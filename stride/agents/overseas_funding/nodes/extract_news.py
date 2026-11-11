from agents.overseas_funding.calc.funding import canon_country, is_foreign
from agents.overseas_funding.schemas import NewsExtractionOutput, Signal, SignalType, Stage
from core.llm import call_llm
from core.nodeguard import guarded
from core.units import parse_krw

PROMPT = "agents/overseas_funding/prompts/extract_news.md"


@guarded
def extract_news(state) -> dict:
    """기사에서 해외 확장 진행 신호(S2)를 추출하고 사건으로 묶는다 (7.7). 입력 기사 ID가 아닌 근거는 폐기한다."""
    items, company, req = state.get("news_items") or [], state["company"], state["request"]
    if not items or req.context.get("no_llm"):
        return {}
    text = "\n".join(f"[{x['evidence_id']}] {x['pubDate']} | {x['title']} | {x['description']}" for x in items)
    out = call_llm(PROMPT, {"corp_name": company.corp_name, "as_of": req.as_of, "news_list": text}, NewsExtractionOutput, run_id=state["run_id"], as_of=req.as_of)
    by_id = {x["evidence_id"]: x for x in items}
    signals, questions = [], []
    for i, e in enumerate(out.events):
        ids = [x for x in e.evidence_ids if x in by_id]
        if not ids:
            questions.append(f"기사 사건 폐기(근거 없음): {e.summary}")
            continue
        signals.append(Signal(signal_id=f"{company.corp_code}:S2:{i}", corp_code=company.corp_code, signal_type=SignalType.PROGRESS, event_date=min(by_id[x]["pubDate"] for x in ids), is_overseas=is_foreign(canon_country(e.target_country)), target_country=canon_country(e.target_country), method=e.method, purpose_category="growth_investment",
                              amount_krw=parse_krw(e.amount_original), amount_original=e.amount_original, stage=Stage(e.stage), summary=e.summary, evidence_ids=ids))
    return {"signals": signals, "open_questions": questions, "llm_calls": state.get("llm_calls", 0) + 1}
