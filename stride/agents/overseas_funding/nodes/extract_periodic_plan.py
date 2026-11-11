import re

from agents.overseas_funding.calc.funding import canon_country, is_foreign
from agents.overseas_funding.schemas import PeriodicPlanOutput, Signal, SignalType, Stage
from core import evidence as ev
from core.clients.dart import VIEWER_URL
from core.llm import call_llm
from core.nodeguard import guarded
from core.schemas import Evidence
from core.units import parse_krw

PROMPT = "agents/overseas_funding/prompts/extract_periodic_plan.md"
_ws = lambda s: re.sub(r"\s+", "", s or "")


def build_material(sec: dict) -> str:
    new = sec.get("new_paragraph_ids")
    lines = []
    for p in sec["paragraphs"]:
        tag = "UNKNOWN" if new is None else "NEW" if p["paragraph_id"] in new else "EXISTING"
        lines.append(f"[{p['paragraph_id']}][{tag}] {p['text']}")
    return "\n".join(lines)


def validate_items(output: PeriodicPlanOutput, sec: dict) -> tuple[list, list[str]]:
    """paragraph_id가 입력에 있고 quote가 그 문단에 있는 항목만 남긴다."""
    by_id = {p["paragraph_id"]: p["text"] for p in sec["paragraphs"]}
    good, dropped = [], []
    for it in output.items:
        if it.paragraph_id not in by_id:
            dropped.append(f"계획 항목 폐기(문단 없음): {it.paragraph_id}")
        elif _ws(it.quote) not in _ws(by_id[it.paragraph_id]):
            dropped.append(f"계획 항목 폐기(인용 불일치): {it.paragraph_id}")
        else:
            good.append(it)
    return good, dropped


@guarded
def extract_periodic_plan(state) -> dict:
    """정기보고서 '사업의 내용'에서 해외 확장 계획 신호(S1)를 추출한다 (7.4). 금액은 원문 표기를 코드로 변환한다."""
    sections, company, req = state.get("periodic_sections") or {}, state["company"], state["request"]
    if not sections or req.context.get("no_llm"):
        return {}
    no, sec = next(iter(sections.items()))
    if not sec["paragraphs"]:
        return {}
    f = next(x for x in state["filings"] if x.rcept_no == no)
    out = call_llm(PROMPT, {"corp_name": company.corp_name, "report_nm": f.report_nm, "rcept_dt": f.rcept_dt, "재추출_피드백": "", "paragraphs": build_material(sec)}, PeriodicPlanOutput, run_id=state["run_id"], as_of=req.as_of)
    good, dropped = validate_items(out, sec)
    new = sec.get("new_paragraph_ids")
    signals, evidence = [], []
    for i, it in enumerate(good):
        eid = ev.dart_section(no, f"II.사업의내용#{it.paragraph_id}")
        evidence.append(Evidence(evidence_id=eid, source_grade="A", source_type="dart_document", corp_code=company.corp_code, published_at=f.rcept_dt, title=f.report_nm, url=VIEWER_URL.format(rcept_no=no), quote=it.quote))
        signals.append(Signal(signal_id=f"{company.corp_code}:S1:{no}:{it.paragraph_id}:{i}", corp_code=company.corp_code, signal_type=SignalType.PLAN, event_date=f.rcept_dt, is_overseas=is_foreign(canon_country(it.target_country)), target_country=canon_country(it.target_country), method=it.method, purpose_category="growth_investment",
                              amount_krw=parse_krw(it.amount_original), amount_original=it.amount_original, stage=Stage(it.stage), is_new=None if new is None else it.paragraph_id in new, summary=it.summary, evidence_ids=[eid]))
    return {"signals": signals, "evidence": evidence, "open_questions": dropped, "llm_calls": state.get("llm_calls", 0) + 1}
