"""review_graph (오케스트레이터 개발문서 7.3, 구성문서 4.1): 기업 1곳 사전검토서. 검증 실패 문장은 1회 재작성 뒤 '검증 실패'로 표시한다."""
from datetime import date
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from core.clients import dart
from core.company import resolve
from core.config import settings
from orchestrator import common, fill, store
from orchestrator.rules import apply_rules
from orchestrator.schemas import FinalReport, ReportSectionsOutput, Sentence

SECTIONS = ("summary", "project", "funding_gap", "financial", "rules", "verification", "opinion")
TITLES = {"summary": "1. 요약", "project": "2. 해외 진출 프로젝트", "funding_gap": "3. 자금 공백", "financial": "4. 재무 건전성", "rules": "5. 결격·주의 규칙 결과", "verification": "6. 검증 결과와 실사 확인 목록", "opinion": "7. 검토 의견", "appendix": "부록"}


class ReviewState(TypedDict, total=False):
    query: str | None
    corp_code: str | None
    as_of: date
    run_id: str
    db_path: str
    company: dict | None
    candidates: list[str]
    ovs: object
    fin: object
    ver: object
    rules: list
    decision: object
    report: FinalReport | None
    clarification: str | None
    llm_calls: int


def resolve_company(state) -> dict:
    co, err, names = resolve(dart.get_client(), state.get("query"), state.get("corp_code"))
    if not co:
        return {"company": None, "candidates": names, "clarification": f"기업을 하나로 특정하지 못했습니다 ({err}). 후보: {', '.join(names[:10]) or '없음'}"}
    return {"company": co}


def ask_clarification(state) -> dict:
    return {}


def plan_and_dispatch(state) -> dict:
    """plan(ovs, fin 항상) → load_cached → dispatch → verifier_results → check_sufficiency → replan(D1, 1회) → apply_rules."""
    con = store.connect(state.get("db_path"))
    try:
        cc = state["company"]["corp_code"]
        info = common.company_info(con, cc)
        ovs, fin, cached = common.run_agents(con, cc, state["as_of"], state.get("db_path") or settings.path(settings.stride_db_path), run_id=state["run_id"])
        ver = common.verify(ovs, fin, state["as_of"], state["run_id"], cc)
        missing = common.missing_required(ver)
        decision = None
        if missing and not cached:      # D1 = 조사 루프로 빈 값 찾기 (2026-11-10, fill.py)
            ovs, fin, decision, filled = fill.fill_missing(con, state["run_id"], ovs, fin, state["as_of"])
            if filled.get("applied"):
                ver = common.verify(ovs, fin, state["as_of"], state["run_id"], cc)
        store.save_result(con, ovs, ver)
        store.save_result(con, fin, ver)
        rules = apply_rules(fin, ver, info.get("market"), state["as_of"])
        return {"ovs": ovs, "fin": fin, "ver": ver, "rules": rules, "decision": decision, "company": {**state["company"], **info}}
    finally:
        con.close()


def due_diligence(ovs, fin, ver, rules) -> list[str]:
    out = [f"{m.name}: 실사 필요" for m in (fin.metrics if fin else []) if m.data_status == "needs_due_diligence"]
    out += [f"{r.rule_id} {r.label}" for r in rules if r.hit is None]
    out += [f"검증 확인 불가: {c.target} ({c.note or c.kind})" for c in (ver.unverifiable if ver else [])[:10]]
    out += [f"검증 불일치: {c.target} ({c.kind})" for c in (ver.failed if ver else [])]
    out += list(dict.fromkeys((ovs.open_questions if ovs else [])))[:10]
    return out


def synthesize_report(state) -> dict:
    """7.2 섹션 순서. 모든 문장 각주. 검증 실패 문장은 1회 재작성 뒤 '(검증 실패)' 표시."""
    ovs, fin, ver, rules, co = state["ovs"], state["fin"], state["ver"], state["rules"], state["company"]
    rule_lines = [f"- 규칙 {r.rule_id} ({r.market}, {r.source} {r.source_date}): {r.label} 근거 {r.evidence_ids}" for r in rules]
    ver_lines = [f"- 검증: 확인 {len(ver.checks)}건, 불일치 {len(ver.failed)}건, 확인 불가 {len(ver.unverifiable)}건"]
    facts, cited = common.facts_and_cited([ovs, fin], [f"- 기업: {co.get('corp_name')} ({co.get('market')}, 업종 {co.get('induty_code')})"] + rule_lines + ver_lines)
    for r in rules:
        for i in r.evidence_ids:
            cited.setdefault(i, {"values": [], "quote": f"{r.rule_id} {r.label}"})
    flat = []
    try:
        out = None
        # 섹션 문장을 한 번에 받아 한 문서로 검증한다 (문장 번호 = 섹션 순서대로 이어 붙인 순서)
        from core.llm import call_llm
        feedback, calls = "", 0
        for attempt in range(2):
            out = call_llm("orchestrator/prompts/synthesize_report.md", {"corp_name": co.get("corp_name"), "as_of": state["as_of"], "facts": facts, "재작성_피드백": feedback}, ReportSectionsOutput, run_id=state["run_id"], as_of=state["as_of"])
            calls += 1
            flat = [(k, s) for k in SECTIONS for s in getattr(out, k)]
            text, foot = common.render([s for _, s in flat], cited)
            from agents.verifier.graph import verify_answer
            rep = verify_answer(text, foot, cited, state["as_of"], request_id=f"{state['run_id']}:report", corp_code=co["corp_code"])
            calls += rep.llm_calls
            if not rep.failed:
                break
            feedback = "## 이전 출력의 검증 실패\n" + "\n".join(f"- {c.target} {c.kind}: {c.actual or ''} {c.note or ''}" for c in rep.failed[:10]) + "\n실패한 문장을 자료에 맞게 고치거나 빼세요."
        bad = {int(t.split()[1]) for t in rep.failed_targets if t.startswith("문장 ")}
    except Exception as e:      # 작성 실패 → 부분 검토서
        return {"report": _template(state, f"검토서 문장 생성 실패 ({type(e).__name__})"), "llm_calls": 0}
    marked = [(k, s.model_copy(update={"text": s.text.rstrip(". ") + " (검증 실패)"}) if i in bad else s) for i, (k, s) in enumerate(flat, 1)]
    sections, all_foot, order = {}, {}, {}
    for k in SECTIONS:
        sents = [s for kk, s in marked if kk == k]
        parts = []
        for s in sents:
            ids = tuple(i for i in s.evidence_ids if i in cited)
            if ids and ids not in order:
                order[ids] = len(order) + 1
                all_foot[order[ids]] = list(ids)
            parts.append(s.text.rstrip(". ") + (f" [{order[ids]}]" if ids else "") + ".")
        sections[k] = " ".join(parts) or "자료 없음."
    ev = common.all_evidence(ovs, fin)
    sections["appendix"] = common.footnote_block(all_foot, ev) + f"\n\n실행: as_of {state['as_of']}, run_id {state['run_id']}, 규칙 기준일 " + ", ".join(sorted({r.source_date for r in rules if r.rule_id != 'R5'}))
    if state.get("decision"):
        d = state["decision"]
        sections["verification"] += f" 필수 지표 부족으로 재확인 판단(D1) '{d.action}' 기록, 실행 경로는 '{d.fallback_action or d.action}'."
    is_partial = ovs.status != "complete" or fin.status != "complete"
    report = FinalReport(report_id=store.new_id("rep"), corp_code=co["corp_code"], as_of=state["as_of"], is_partial=is_partial, sections=sections, rule_results=rules, due_diligence=due_diligence(ovs, fin, ver, rules),
                         verification_status="partially_failed" if (bad or ver.failed) else "passed", evidence=[ev[i] for ids in all_foot.values() for i in ids if i in ev])
    return {"report": report, "llm_calls": calls}


def _template(state, why) -> FinalReport:
    ovs, fin, ver, rules, co = state.get("ovs"), state.get("fin"), state.get("ver"), state.get("rules") or [], state["company"]
    secs = {k: "자료 없음." for k in SECTIONS}
    secs["summary"] = f"{why}. 아래 값은 에이전트 결과 그대로다."
    secs["rules"] = " ".join(f"{r.rule_id}: {r.label}." for r in rules)
    secs["appendix"] = f"실행: as_of {state['as_of']}, run_id {state['run_id']}"
    return FinalReport(report_id=store.new_id("rep"), corp_code=co["corp_code"], as_of=state["as_of"], is_partial=True, sections=secs, rule_results=rules, due_diligence=due_diligence(ovs, fin, ver, rules), verification_status="partially_failed", evidence=[])


def save_report(state) -> dict:
    con = store.connect(state.get("db_path"))
    try:
        r = state["report"]
        con.execute("INSERT OR REPLACE INTO orc_reports VALUES (?,?,?,?,?,?,?)", (r.report_id, r.corp_code, r.as_of.isoformat(), state["run_id"], r.model_dump_json(), r.verification_status, store.now()))
        con.commit()
    finally:
        con.close()
    return {}


def build_graph():
    g = StateGraph(ReviewState)
    for name, fn in (("resolve_company", resolve_company), ("ask_clarification", ask_clarification), ("plan_and_dispatch", plan_and_dispatch), ("synthesize_report", synthesize_report), ("save_report", save_report)):
        g.add_node(name, fn)
    g.add_edge(START, "resolve_company")
    g.add_conditional_edges("resolve_company", lambda s: "plan_and_dispatch" if s.get("company") else "ask_clarification", ["plan_and_dispatch", "ask_clarification"])
    g.add_edge("ask_clarification", END)
    g.add_edge("plan_and_dispatch", "synthesize_report")
    g.add_edge("synthesize_report", "save_report")
    g.add_edge("save_report", END)
    return g.compile()


def run_review(*, query=None, corp_code=None, as_of: date, db_path=None, run_id=None) -> dict:
    run_id = run_id or store.new_id("rev")
    out = build_graph().invoke({"query": query, "corp_code": corp_code, "as_of": as_of, "run_id": run_id, "db_path": db_path})
    return {"run_id": run_id, "report": out.get("report"), "clarification": out.get("clarification"), "candidates": out.get("candidates") or [], "corp_code": (out.get("company") or {}).get("corp_code")}


__all__ = ["run_review", "TITLES", "Sentence"]
