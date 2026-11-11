"""discover_graph (오케스트레이터 개발문서 7.2, 구성문서 4.0). 단계별 기업 수와 제외 사유를 모두 남긴다. 순위를 매기지 않는다."""
import json
import operator
from collections import Counter
from datetime import date
from typing import Annotated, TypedDict

from dateutil.relativedelta import relativedelta
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents.overseas_funding.batch import screen_universe
from core.clients import dart
from core.config import settings
from core.clients.dart import DartQuotaError
from core.llm import LLMError, call_llm
from core.schemas import RouteDecision
from orchestrator import common, fill, store
from orchestrator.config import D4_ACTIONS, REGION_LABELS, REGION_MAP
from orchestrator.rules import apply_criteria, apply_rules, region_of
from orchestrator.schemas import CriteriaLLM, DiscoveryCriteria, FollowupOutput

RULE_IDS = ["R1-KS", "R1b-KS", "R2-KS", "R3-KS", "R1-KQ", "R2-KQ", "R3-KQ"]


def default_criteria(as_of: date) -> DiscoveryCriteria:
    """6장 STRIDE 기본 탐색 (2026-11-10 방향 수정): G1~G4 통과 + 대표 프로젝트에 S4 또는 S5. 자금 공백·상장 규정 기준으로 거르지 않고 표에 보여 준다."""
    return DiscoveryCriteria(markets=["KOSPI", "KOSDAQ"], stages=[1, 2, 3, 4, 5], signal_types=["S4_confirmed", "S5_funding"], lookback_months=12, as_of=as_of)


def parse_criteria(text: str, as_of: date, run_id: str) -> DiscoveryCriteria:
    """자연어 → DiscoveryCriteria (LLM 1회). 허용 값 밖은 버리고 unparsed에 둔다."""
    out = call_llm("orchestrator/prompts/parse_criteria.md", {"text": text, "regions": ", ".join(f"{k}({v})" for k, v in REGION_LABELS.items())}, CriteriaLLM, run_id=run_id, as_of=as_of)
    bad = [r for r in out.target_regions if r not in REGION_MAP]
    return DiscoveryCriteria(**{**out.model_dump(), "target_regions": [r for r in out.target_regions if r in REGION_MAP], "stages": [s for s in out.stages if 1 <= s <= 5], "exclude_rule_ids": [r for r in out.exclude_rule_ids if r in RULE_IDS],
                                "unparsed": out.unparsed + [f"지역 {r}" for r in bad]}, as_of=as_of)


class DiscoverState(TypedDict, total=False):
    search_id: str
    run_id: str
    criteria: DiscoveryCriteria
    db_path: str
    progress: object                  # 콜백 (job 진행 표시)
    funnel: list[dict]
    candidates: list[dict]
    targets: list[dict]
    pending: list[dict]
    excluded: Annotated[list[dict], operator.add]
    analyzed: Annotated[list[dict], operator.add]
    rows: list
    summary_md: str
    suggestions: list
    llm_calls: int


def _con(state):
    return store.connect(state.get("db_path"))


def _tick(state, step, **k):
    if state.get("progress"):
        state["progress"](step, **k)


def confirm_criteria(state) -> dict:
    """화면에서 조건 칩을 확인한 뒤 실행하므로 여기서는 그대로 통과한다 (자체 결정: job discover stage=parse_only가 확인 단계다)."""
    return {}


def build_universe(state) -> dict:
    """상장사 수 (시장·업종 필터는 공시가 있는 후보에만 기업개황으로 적용한다. 2,600곳 기업개황 조회를 피하기 위함)."""
    n = sum(1 for c in dart.get_client().corp_codes() if c.get("stock_code"))
    _tick(state, "universe", count=n)
    return {"funnel": [{"step": "universe", "count": n}]}


def scan_events(state) -> dict:
    c = state["criteria"]
    con = _con(state)
    try:
        tracked = {}      # 재사용은 load_cached가 한다
    finally:
        con.close()
    cands = screen_universe(c.as_of - relativedelta(months=c.lookback_months), c.as_of, c.as_of, tracked=tracked)
    cands = [x for x in cands if x["market"] in c.markets]
    _tick(state, "events", count=len(cands))
    return {"candidates": cands, "funnel": state["funnel"] + [{"step": "events", "count": len(cands)}]}


def prefilter(state) -> dict:
    """정형 칸으로 바로 확인되는 조건(지역·금액)만 적용. K개 초과분은 최근 공시일 순으로 대기."""
    c = state["criteria"]
    kept, excluded = [], []
    for x in state["candidates"]:
        forms = [f for f in x["forms"] if f["country"]]
        if c.target_regions and forms and not any(set(region_of(f["country"])) & set(c.target_regions) for f in forms) and x["strength"] == 2:
            excluded.append({"corp_code": x["corp_code"], "corp_name": x["corp_name"], "step": "prefilter", "condition": "투자 지역 (취득 공시 국적 칸)", "value": ", ".join(sorted({f["country"] for f in forms})), "evidence_ids": [f"DART:{f['rcept_no']}:정형" for f in forms]})
            continue
        amounts = [f["amount"] for f in forms if f["amount"]]
        if c.min_investment_amount and amounts and max(amounts) < c.min_investment_amount and x["strength"] == 2:
            excluded.append({"corp_code": x["corp_code"], "corp_name": x["corp_name"], "step": "prefilter", "condition": "최소 투자액 (취득금액 칸)", "value": max(amounts), "evidence_ids": [f"DART:{f['rcept_no']}:정형" for f in forms]})
            continue
        kept.append(x)
    kept.sort(key=lambda x: x["latest"], reverse=True)
    con = _con(state)
    try:
        # 완료된 실행 = 기업 분석이 1곳 이상 성공한 실행 (자체 결정: 분석이 전부 실패한 실행은 첫 실행 상한을 풀지 않는다)
        first = con.execute("SELECT COUNT(*) FROM orc_search_matches WHERE status='matched' OR (status='excluded' AND excluded_step<>'deep')").fetchone()[0] == 0
    finally:
        con.close()
    k = min(c.max_deep_analysis, settings.first_run_max_deep_analysis) if first else c.max_deep_analysis      # 첫 실제 실행 5곳 (4장)
    _tick(state, "prefilter", count=len(kept))
    return {"targets": kept[:k], "pending": [{"corp_code": x["corp_code"], "corp_name": x["corp_name"], "latest_filing_date": x["latest"]} for x in kept[k:]], "excluded": excluded, "funnel": state["funnel"] + [{"step": "prefilter", "count": len(kept)}]}


def dispatch_batch(state):
    return [Send("analyze_company", {"criteria": state["criteria"], "run_id": state["run_id"], "db_path": state.get("db_path"), "target": x, "search_id": state["search_id"], "progress": state.get("progress")}) for x in state["targets"]] or ["build_board"]


def analyze_company(payload) -> dict:
    """기업 1곳: load_cached/dispatch → verifier_results → check_sufficiency → replan(D1, 1회) → apply_rules. 한 기업 실패가 탐색을 멈추지 않는다."""
    c, run_id, x = payload["criteria"], payload["run_id"], payload["target"]
    con = store.connect(payload.get("db_path"))
    try:
        info = common.company_info(con, x["corp_code"])
        ovs, fin, cached = common.run_agents(con, x["corp_code"], c.as_of, payload.get("db_path") or settings.path(settings.stride_db_path), run_id=run_id)
        ver = common.verify(ovs, fin, c.as_of, run_id, x["corp_code"])
        decision = None
        missing = common.missing_required(ver)
        if missing and not cached:      # 기업당 1회 (7.6). D1 = 조사 루프로 빈 값 찾기 (2026-11-10, fill.py)
            ovs, fin, decision, filled = fill.fill_missing(con, run_id, ovs, fin, c.as_of)
            if filled.get("applied"):
                ver = common.verify(ovs, fin, c.as_of, run_id, x["corp_code"])
        store.save_result(con, ovs, ver)
        store.save_result(con, fin, ver)
        rules = apply_rules(fin, ver, info.get("market") or x["market"], c.as_of)
        if payload.get("progress"):
            payload["progress"]("deep_done", corp_code=x["corp_code"])
        return {"analyzed": [{"corp_code": x["corp_code"], "info": info, "ovs": ovs, "fin": fin, "ver": ver, "rules": rules, "decision": decision, "error": None}]}
    except Exception as e:
        return {"analyzed": [{"corp_code": x["corp_code"], "info": {"corp_code": x["corp_code"], "corp_name": x["corp_name"], "market": x["market"]}, "error": f"{type(e).__name__}: {e}"[:300], "llm_failed": isinstance(e, (LLMError, DartQuotaError)), "latest": x["latest"]}]}
    finally:
        con.close()


def build_board(state) -> dict:
    """apply_criteria → BoardRow, funnel(deep, final), 제외 목록."""
    c, con = state["criteria"], _con(state)
    try:
        watched = {r["corp_code"] for r in con.execute("SELECT corp_code FROM orc_watchlist")}
        prev_rows = {r["corp_code"]: json.loads(r["row_json"]) for r in con.execute("SELECT corp_code, row_json FROM orc_search_matches WHERE search_id=? AND status='matched' AND run_id=(SELECT run_id FROM orc_search_runs WHERE search_id=? ORDER BY created_at DESC LIMIT 1)", (state["search_id"], state["search_id"]))}
        others = {}
        for r in con.execute("SELECT search_id, corp_code FROM orc_search_matches WHERE status='matched' AND search_id<>?", (state["search_id"],)):
            others.setdefault(r["corp_code"], set()).add(r["search_id"])
    finally:
        con.close()
    rows, excluded, retry = [], [], []
    for a in state.get("analyzed") or []:
        if a.get("llm_failed"):      # 한도 등으로 분석하지 못함: 제외가 아니라 분석 대기 (원칙 3)
            retry.append({"corp_code": a["corp_code"], "corp_name": a["info"].get("corp_name"), "latest_filing_date": a.get("latest"), "note": "DART 일일 요청 한도 초과로 분석 대기" if "DartQuotaError" in (a.get("error") or "") else "LLM 호출 실패로 분석 대기"})
            continue
        if a["error"]:
            excluded.append({"corp_code": a["corp_code"], "corp_name": a["info"].get("corp_name"), "step": "deep", "condition": "분석 실패", "value": a["error"], "evidence_ids": []})
            continue
        ok, why, needs = apply_criteria(common.row_inputs(a["ovs"], a["fin"], a["info"]), c, a["rules"])
        if not ok:
            ids = [i for m in a["ovs"].metrics[:1] for i in m.evidence_ids]
            excluded.append({"corp_code": a["corp_code"], "corp_name": a["ovs"].corp_name or a["info"].get("corp_name"), "step": "apply_criteria", **why, "evidence_ids": ids})
            continue
        badges = [x.alert_type for x in a["ovs"].alerts if x.alert_type in ("stage_up", "stage_down", "plan_changed", "cancelled")]
        prev = prev_rows.get(a["corp_code"])
        if prev is None and prev_rows:
            badges.insert(0, "new_match")
        elif prev and prev["investment_amount"]["value"] != (common.metric(a["ovs"], "ovs.overseas_investment_amount").value if common.metric(a["ovs"], "ovs.overseas_investment_amount") else None):
            badges.append("amount_changed")
        row = common.board_row(a["ovs"], a["fin"], a["info"], a["rules"], a["ver"], matched_search_ids=sorted(others.get(a["corp_code"], [])), is_watched=a["corp_code"] in watched, change_badges=badges)
        if needs and row.verification == "verified":
            row = row.model_copy(update={"verification": "needs_check"})
        rows.append(row)
    rows.sort(key=common.default_sort_key)      # common.DEFAULT_SORT_TEXT
    funnel = state["funnel"] + [{"step": "deep", "count": len(state.get("analyzed") or []) - len(retry)}, {"step": "final", "count": len(rows)}]
    _tick(state, "final", count=len(rows))
    return {"rows": rows, "excluded": excluded, "funnel": funnel, "pending": retry + (state.get("pending") or [])}


def plan_followup(state) -> dict:
    """D4 (7.6). 결과 0건이거나 확인 필요가 절반 이상일 때만. 제안만 하고 실행하지 않는다."""
    rows = state.get("rows") or []
    if rows and sum(r.verification != "verified" for r in rows) * 2 < len(rows):
        return {"suggestions": []}
    reasons = Counter(x.get("condition") for x in state.get("excluded") or [])
    con = _con(state)
    out = []
    try:
        try:
            got = call_llm("orchestrator/prompts/plan_followup.md", {"funnel": common.dumps(state["funnel"]), "reasons": common.dumps(reasons)}, FollowupOutput, run_id=state["run_id"], as_of=state["criteria"].as_of)
            for s in got.suggestions[:2]:
                ok = s.action in D4_ACTIONS
                out.append(RouteDecision(point="D4", action=f"{s.action}({s.field})" if s.field and ok else (s.action if ok else "none"), reason=s.reason[:300], evidence_ids=s.evidence_ids, accepted=ok, fallback_action=None if ok else "none"))
        except Exception as e:
            out.append(RouteDecision(point="D4", action="none", reason=f"LLM 실패: {type(e).__name__}", accepted=False, fallback_action="none"))
        for d in out:
            store.save_decision(con, state["run_id"], "orchestrator.plan_followup", None, d)
    finally:
        con.close()
    return {"suggestions": out, "llm_calls": (state.get("llm_calls") or 0) + 1}


def summarize_board(state) -> dict:
    """3~5문장 사실 요약 → 검증 answer 모드 → 실패 시 1회 재작성 → 그래도 실패한 문장은 제거."""
    rows = state.get("rows") or []
    analyzed = {a["corp_code"]: a for a in state.get("analyzed") or [] if not a["error"]}
    funnel_line = "단계별 기업 수: " + ", ".join(f"{f['step']} {f['count']}" for f in state["funnel"])
    results = [x for r in rows for x in (analyzed[r.corp_code]["ovs"], analyzed[r.corp_code]["fin"])]
    facts, cited = common.facts_and_cited(results, [funnel_line] + [f"- 보드 기업: {r.corp_name} ({r.market}), 진행 단계 {r.project.get('stage_label')}" for r in rows])
    if not rows:
        return {"summary_md": f"조건을 충족한 기업이 없습니다. {funnel_line}."}
    try:
        text, foot, rep, _, calls = common.verified_sentences("summarize_board.md", {"facts": facts}, cited, state["criteria"].as_of, run_id=state["run_id"], on_fail="drop")
    except Exception as e:      # 요약 실패는 보드를 막지 않는다
        return {"summary_md": f"요약을 만들지 못했습니다 ({type(e).__name__}). {funnel_line}."}
    ev = common.all_evidence(*results)
    return {"summary_md": text + "\n\n" + common.footnote_block(foot, ev), "llm_calls": (state.get("llm_calls") or 0) + calls}


def save_board(state) -> dict:
    con = _con(state)
    c, sid, rid = state["criteria"], state["search_id"], state["run_id"]
    try:
        con.execute("INSERT OR REPLACE INTO orc_search_runs VALUES (?,?,?,?,?,?,?)", (sid, rid, c.as_of.isoformat(), common.dumps(state["funnel"]), state.get("summary_md") or "", common.dumps([d.model_dump() for d in state.get("suggestions") or []]), store.now()))
        for r in state.get("rows") or []:
            con.execute("INSERT OR REPLACE INTO orc_search_matches VALUES (?,?,?,?,?,?,?,?,?,?)", (sid, r.corp_code, rid, c.as_of.isoformat(), "matched", None, None, None, r.model_dump_json(), common.dumps(r.investment_amount["evidence_ids"])))
        for p in state.get("pending") or []:
            con.execute("INSERT OR REPLACE INTO orc_search_matches VALUES (?,?,?,?,?,?,?,?,?,?)", (sid, p["corp_code"], rid, c.as_of.isoformat(), "pending", None, None, None, common.dumps(p), "[]"))
        for x in state.get("excluded") or []:
            con.execute("INSERT OR REPLACE INTO orc_search_matches VALUES (?,?,?,?,?,?,?,?,?,?)", (sid, x["corp_code"], rid, c.as_of.isoformat(), "excluded", x["step"], x["condition"], str(x["value"]), common.dumps({"corp_name": x.get("corp_name")}), common.dumps(x.get("evidence_ids") or [])))
        con.commit()
    finally:
        con.close()
    return {}


def build_graph():
    g = StateGraph(DiscoverState)
    for name, fn in (("confirm_criteria", confirm_criteria), ("build_universe", build_universe), ("scan_events", scan_events), ("prefilter", prefilter), ("analyze_company", analyze_company), ("build_board", build_board), ("plan_followup", plan_followup), ("summarize_board", summarize_board), ("save_board", save_board)):
        g.add_node(name, fn)
    g.add_edge(START, "confirm_criteria")
    for a, b in (("confirm_criteria", "build_universe"), ("build_universe", "scan_events"), ("scan_events", "prefilter"), ("analyze_company", "build_board"), ("build_board", "plan_followup"), ("plan_followup", "summarize_board"), ("summarize_board", "save_board"), ("save_board", END)):
        g.add_edge(a, b)
    g.add_conditional_edges("prefilter", dispatch_batch, ["analyze_company", "build_board"])
    return g.compile()


def run_discover(search_id: str, criteria: DiscoveryCriteria, *, db_path=None, progress=None, run_id=None) -> dict:
    """반환 DiscoveryBoard 필드 dict. 동시 실행은 1 (구독 처리량 실측 전)."""
    run_id = run_id or store.new_id("disc")
    out = build_graph().invoke({"search_id": search_id, "run_id": run_id, "criteria": criteria, "db_path": db_path, "progress": progress, "excluded": [], "analyzed": []}, {"max_concurrency": 1, "recursion_limit": 200})
    return {"search_id": search_id, "run_id": run_id, "funnel": out["funnel"], "rows": out.get("rows") or [], "pending": out.get("pending") or [], "excluded": out.get("excluded") or [], "summary_md": out.get("summary_md"), "suggestions": out.get("suggestions") or []}
