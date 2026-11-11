from pathlib import Path

from jinja2 import Environment

from core.nodeguard import guarded
from core.report_guard import forbidden_terms

TEMPLATE = Path(__file__).resolve().parents[1] / "templates" / "report.md.j2"
CORE = ("fin.net_debt_to_ebitda", "fin.ebitda_interest_coverage", "fin.ebitda_margin")
LISTING = ("fin.capital_impairment_ratio", "fin.equity_ex_nci")
AUX = ("fin.ebitda", "fin.total_borrowings", "fin.net_debt", "fin.debt_ratio", "fin.current_ratio", "fin.borrowing_dependency", "fin.cash_and_equivalents", "fin.short_term_financial_assets", "fin.ttm_operating_cash_flow", "fin.market_cap", "fin.net_debt_to_ev", "fin.per", "fin.pbr", "fin.ev_to_ebitda")


def show(m) -> str:
    if m.data_status == "unknown":
        return "확인 불가"
    if m.value is None:
        return "산출 불가"
    if m.unit == "원":
        return f"{m.value / 1e8:,.1f}억 원"
    return f"{m.value:,.2f}{m.unit}"


def row(m) -> dict:
    return {"name": m.name, "period": m.period, "text": show(m), "note": m.note, "methodology": m.methodology}


@guarded
def write_report(state) -> dict:
    """템플릿으로 사실 요약을 만든다. LLM 없음. 판단 표현이 있으면 비우고 errors에 남긴다."""
    req, company = state["request"], state.get("company")
    metrics = state.get("metrics") or []
    label = {"annual": "사업보고서", "half": "반기보고서", "q1": "1분기보고서", "q3": "3분기보고서"}
    text = Environment(autoescape=False, trim_blocks=True, lstrip_blocks=True).from_string(TEMPLATE.read_text(encoding="utf-8")).render(
        has_company=bool(company), corp_name=(company or {}).get("corp_name") or req.company or req.corp_code, as_of=req.as_of, errors=state.get("errors") or [],
        reports=[{"label": f"{r.bsns_year} {label[r.report_kind]}", "rcept_dt": r.rcept_dt, "rcept_no": r.rcept_no, "is_correction": r.is_correction} for r in state.get("reports") or []],
        core=[row(m) for m in metrics if m.metric_id in CORE], listing=[row(m) for m in metrics if m.metric_id in LISTING], aux=[row(m) for m in metrics if m.metric_id in AUX],
        dd=[row(m) for m in metrics if m.data_status == "needs_due_diligence"], classes=state.get("classifications") or [], questions=state.get("open_questions") or [])
    hits = forbidden_terms(text)
    if hits:
        return {"report_markdown": None, "errors": [f"write_report: 판단 표현 {hits}"]}
    return {"report_markdown": text}
