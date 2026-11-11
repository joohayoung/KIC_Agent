"""answer_graph, route_intent, board_filter (오케스트레이터 개발문서 7.1, 7.4, 7.5). 새로 수집하지 않는다."""
from datetime import date

from core.clients import dart
from core.company import resolve
from core.llm import call_llm
from orchestrator import common, store
from orchestrator.config import INSTANT_FILTER_FIELDS
from orchestrator.schemas import Answer, BoardFilterOutput, IntentResult

NO_DATA = "아직 분석한 결과가 없습니다. [기업 상세 열기]로 분석할 수 있어요."


def parse_intent(text: str, as_of: date, run_id: str) -> IntentResult:
    return call_llm("orchestrator/prompts/parse_intent.md", {"text": text}, IntentResult, run_id=run_id, as_of=as_of)


def run_answer(question: str, company: str | None, as_of: date, *, db_path=None, run_id=None) -> Answer:
    """resolve_company → load_context → answer_question → verifier_answer (실패 1회 재작성) → save_answer."""
    run_id = run_id or store.new_id("ans")
    con = store.connect(db_path)
    try:
        co, err, names = resolve(dart.get_client(), company, None) if company else (None, "기업 표현 없음", [])
        ovs = store.latest_result(con, co["corp_code"], "overseas_funding", as_of.isoformat()) if co else None
        fin = store.latest_result(con, co["corp_code"], "financial_health", as_of.isoformat()) if co else None
        if not (ovs or fin):
            ans = Answer(question=question, answer_md=NO_DATA if co else f"기업을 특정하지 못했습니다. 후보: {', '.join(names[:10]) or '없음'}", evidence_ids=[], links=[{"label": "기업 상세 열기", "page": "company", "corp_code": co["corp_code"]}] if co else [], verification_status="no_data")
        else:
            facts, cited = common.facts_and_cited([ovs, fin])
            text, foot, rep, out, _ = common.verified_sentences("answer_question.md", {"question": question, "facts": facts}, cited, as_of, run_id=run_id, corp_code=co["corp_code"], on_fail="drop")
            ev = common.all_evidence(ovs, fin)
            ids = [i for v in foot.values() for i in v]
            ans = Answer(question=question, answer_md=text + "\n\n" + common.footnote_block(foot, ev), evidence_ids=ids, links=[{"label": f"{co['corp_name']} 상세 보기", "page": "company", "corp_code": co["corp_code"]}],
                         verification_status="partially_failed" if rep.failed else "passed")
        con.execute("INSERT OR REPLACE INTO orc_answers VALUES (?,?,?,?,?,?)", (store.new_id("ans"), question, co["corp_code"] if co else None, as_of.isoformat(), ans.model_dump_json(), store.now()))
        con.commit()
        return ans
    finally:
        con.close()


def run_board_filter(text: str, as_of: date, run_id: str) -> dict:
    """7.5. 허용 필드만 적용하고 나머지는 '다시 탐색 필요' 안내."""
    out = call_llm("orchestrator/prompts/parse_board_filter.md", {"text": text, "fields": "\n".join(f"- {k}: {v}" for k, v in INSTANT_FILTER_FIELDS.items())}, BoardFilterOutput, run_id=run_id, as_of=as_of)
    good = [f.model_dump() for f in out.filters if f.field in INSTANT_FILTER_FIELDS]
    bad = [f.field for f in out.filters if f.field not in INSTANT_FILTER_FIELDS]
    return {"filters": good, "message": "조건을 바꾸려면 다시 탐색이 필요해요" if bad or not good else None, "rejected": bad}


def apply_board_filters(rows: list[dict], filters: list[dict]) -> list[dict]:
    """화면 표에 필터 적용 (재실행 없음). 값이 없는 행은 필터를 통과하지 못한다."""
    def get(r, field):
        liq = r.get("liquidity") or {}
        return {"liquidity_ratio": (liq.get("ratio") or {}).get("value"), "liquidity_surplus": (liq.get("surplus") or {}).get("value"), "debt_ratio": r["debt_ratio"]["value"], "investment_amount": r["investment_amount"]["value"], "funding_gap": r["funding_gap"]["value"], "funding_gap_ratio": r["funding_gap"]["ratio"], "stage": r["project"]["stage"], "rule_hit": bool(r["rule_hits"]), "verification": r["verification"]}[field]
    ops = {">=": lambda a, b: a >= b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, "<": lambda a, b: a < b, "==": lambda a, b: a == b, "!=": lambda a, b: a != b}
    out = []
    for r in rows:
        try:
            if all(get(r, f["field"]) is not None and ops[f["op"]](get(r, f["field"]), type(get(r, f["field"]))(f["value"]) if not isinstance(get(r, f["field"]), bool) else str(f["value"]).lower() in ("true", "1", "예")) for f in filters):
                out.append(r)
        except (TypeError, ValueError):
            continue
    return out
