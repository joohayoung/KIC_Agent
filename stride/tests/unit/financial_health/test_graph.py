"""재무 건전성 그래프 (LLM 없음): 13.1의 정정 규칙, 공통 계약, collect_financials 시점, 합계 검증, 감사의견. 외부 호출 없이 가짜 클라이언트로 돌린다."""
from datetime import date

import pytest

from agents.financial_health.graph import run
from agents.financial_health.nodes.collect_audit_info import classify_audit, current_rows, normalize_opinion, scope_limitation
from agents.financial_health.nodes.collect_restructuring import match_events, status_of
from core.asof import UNKNOWN_NOTE, FilingList, filter_asof
from core.clients import dart
from core.clients.dart import DartClient
from core.filings import select_reports
from core.report_guard import forbidden_terms
from core.schemas import Request
from tests.unit.test_contract import check_contract

ID = {"cash": "ifrs-full_CashAndCashEquivalents", "st": "ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents", "assets": "ifrs-full_Assets", "liab": "ifrs-full_Liabilities", "equity": "ifrs-full_Equity",
      "parent": "ifrs-full_EquityAttributableToOwnersOfParent", "capital": "ifrs-full_IssuedCapital", "ca": "ifrs-full_CurrentAssets", "cl": "ifrs-full_CurrentLiabilities", "rev": "ifrs-full_Revenue", "oi": "dart_OperatingIncomeLoss",
      "ocf": "ifrs-full_CashFlowsFromUsedInOperatingActivities", "debt": "ifrs-full_ShorttermBorrowings", "int": "dart_AdjustmentsForInterestExpenses"}
SJ = {"rev": "CIS", "oi": "CIS", "ocf": "CF", "int": "CF"}


def fin_rows(no, *, assets=1000, liab=400, equity=600, oi=100, ocf=80, ocf_prev=None):
    vals = {"cash": 50, "st": 10, "assets": assets, "liab": liab, "equity": equity, "parent": equity, "capital": 100, "ca": 300, "cl": 150, "rev": 500, "oi": oi, "ocf": ocf, "debt": 200, "int": 20}
    return [{"rcept_no": no, "sj_div": SJ.get(k, "BS"), "account_id": ID[k], "account_nm": k, "thstrm_amount": str(v), "frmtrm_amount": "" if k != "ocf" or ocf_prev is None else str(ocf_prev), "currency": "KRW"} for k, v in vals.items()]


def doc_body(kind="사업보고서"):
    table = "<TABLE><TR><TD>구분</TD><TD>당기</TD><TD>전기</TD></TR><TR><TD>감가상각비</TD><TD>30</TD><TD>9</TD></TR><TR><TD>무형자산상각비</TD><TD>5</TD><TD>9</TD></TR></TABLE>"
    return f"<DOCUMENT><DOCUMENT-NAME ACODE='1'>{kind}</DOCUMENT-NAME><TITLE>3. 연결재무제표 주석</TITLE><TITLE>20. 비용의 성격별 분류</TITLE>(단위 : 원){table}<TITLE>4. 재무제표</TITLE></DOCUMENT>".encode()


class Fake:
    """list_filings는 실제 클라이언트와 같이 as_of로 거른다."""

    def __init__(self, filings, responses, audit=None, others=()):
        self._f, self._r, self._audit, self._others = filings, responses, audit or {}, list(others)

    def corp_codes(self):
        return [{"corp_code": "00000001", "corp_name": "테스트", "stock_code": "000001"}]

    def get_json(self, endpoint, **k):
        assert endpoint == "company.json"
        return {"corp_cls": "Y"}

    def list_filings(self, as_of, bgn, end, corp_code=None, pblntf_ty=None):
        rows = self._f if pblntf_ty == "A" else self._f + self._others
        return FilingList(filter_asof(rows, "rcept_dt", as_of), date(2000, 1, 1), as_of)

    def financials(self, cc, year, code, fs, filings, dt):
        rows = self._r.get((year, code, fs), [])
        return DartClient._versioned(rows, filings, dt)

    def audit_opinion(self, cc, year, code, filings, dt):
        return DartClient._versioned(self._audit.get(year, []), filings, dt)

    def document(self, no):
        return {"a": doc_body()}


def filing(no, dt, nm):
    return {"rcept_no": no, "rcept_dt": dt, "report_nm": nm}


def audit_rows(no, opinion="적정의견"):
    return [{"rcept_no": no, "bsns_year": "제10기\n(당기)", "adt_opinion": opinion}, {"rcept_no": no, "bsns_year": "제10기\n(당기)", "adt_opinion": opinion}, {"rcept_no": no, "bsns_year": "제9기\n(전기)", "adt_opinion": "거절"}]


BASE = [filing("20250301000001", "20250301", "사업보고서 (2024.12)"), filing("20260301000001", "20260301", "사업보고서 (2025.12)"), filing("20260814000001", "20260814", "반기보고서 (2026.06)")]
RESP = {(2024, "11011", "CFS"): fin_rows("20250301000001"), (2025, "11011", "CFS"): fin_rows("20260301000001", ocf=110), (2026, "11012", "CFS"): fin_rows("20260814000001", ocf=60, ocf_prev=50)}


def execute(monkeypatch, tmp_path, fake, as_of):
    monkeypatch.setattr(dart, "get_client", lambda: fake)
    return run(Request(request_id="q", agent="financial_health", mode="single", company="00000001", as_of=as_of, context={"db_path": str(tmp_path / "t.db")}))


def metric(result, mid, period):
    return next(m for m in result.metrics if m.metric_id == mid and m.period == period)


@pytest.fixture
def fake():
    return Fake(BASE, RESP, {2025: audit_rows("20260301000001"), 2024: audit_rows("20250301000001")})


# ---- 공통 계약 ----
def contract_sample():
    """tests/unit/test_contract.py AGENT_SAMPLES용."""
    import tempfile
    keep = dart.get_client
    dart.get_client = lambda: Fake(BASE, RESP, {2025: audit_rows("20260301000001"), 2024: audit_rows("20250301000001")})
    try:
        return run(Request(request_id="q", agent="financial_health", mode="single", company="00000001", as_of=date(2026, 8, 15), context={"db_path": tempfile.mkdtemp() + "/t.db"}))
    finally:
        dart.get_client = keep


def fixture_result(monkeypatch, tmp_path, fake):
    return execute(monkeypatch, tmp_path, fake, date(2026, 8, 15))


def test_agent_contract(monkeypatch, tmp_path, fake):
    r = fixture_result(monkeypatch, tmp_path, fake)
    assert check_contract(r) == [] and r.status == "complete", r.errors
    assert all(m.band is None for m in r.metrics) and not forbidden_terms(r.report_markdown)
    assert {"fin.debt_maturity_profile", "fin.going_concern_note", "fin.credit_rating"} <= {m.metric_id for m in r.metrics if m.data_status == "needs_due_diligence"}


def test_values_and_periods(monkeypatch, tmp_path, fake):
    r = fixture_result(monkeypatch, tmp_path, fake)
    assert metric(r, "fin.ebitda", "2025FY").value == 135                       # 100 + 30 + 5
    assert metric(r, "fin.net_debt", "2025FY").value == 140                     # 200 − 50 − 10
    assert metric(r, "fin.net_debt_to_ebitda", "2025FY").value == pytest.approx(140 / 135)
    assert metric(r, "fin.ebitda_interest_coverage", "2025FY").value == pytest.approx(135 / 20)
    assert metric(r, "fin.ttm_operating_cash_flow", "TTM 2026H1").value == 120   # 60 + 110 − 50
    assert metric(r, "fin.cash_and_equivalents", "2026H1말").value == 50          # 재무 기본 항목은 반기 기준
    assert metric(r, "fin.capital_impairment_ratio", "2025FY").value == -500     # 핵심·상장 입력은 사업보고서 기준
    assert metric(r, "fin.market_cap", "2026-08-15 기준").data_status == "missing"


# ---- collect_financials 시점 ----
def test_report_filed_day_before_as_of_is_included(monkeypatch, tmp_path, fake):
    r = execute(monkeypatch, tmp_path, fake, date(2026, 8, 14))
    assert any(m.period == "2026H1말" for m in r.metrics)


def test_report_filed_after_as_of_is_excluded(monkeypatch, tmp_path, fake):
    r = execute(monkeypatch, tmp_path, fake, date(2026, 8, 13))
    assert not any("2026H1" in m.period for m in r.metrics) and any(m.period == "2025FY말" for m in r.metrics)
    assert all(e.published_at <= date(2026, 8, 13) for e in r.evidence)


def test_correction_filed_after_as_of_uses_original_as_unknown(monkeypatch, tmp_path):
    # 원본 접수 ≤ as_of < 정정 접수: API는 정정본만 준다
    filings = BASE[:2]
    f = Fake(filings, {(2024, "11011", "CFS"): fin_rows("20250301000001"), (2025, "11011", "CFS"): fin_rows("20260901000001")}, {2025: audit_rows("20260901000001"), 2024: audit_rows("20250301000001")})
    r = execute(monkeypatch, tmp_path, f, date(2026, 4, 8))
    ebitda = metric(r, "fin.ebitda", "2025FY")
    assert ebitda.data_status == "unknown" and ebitda.note == UNKNOWN_NOTE and ebitda.value is None
    assert metric(r, "fin.ebitda", "2024FY").data_status == "ok"                # 다른 연도는 그대로
    assert [c.value for c in r.classifications if c.key == "fin.audit_opinion"] == ["unknown"]
    assert "20260901000001" not in str(r.model_dump(mode="json"))              # 정정 후 값·접수번호 미출력
    assert r.extra["unknown_years"] == [2025]


def test_correction_filed_before_as_of_is_used(monkeypatch, tmp_path):
    filings = BASE[:2] + [filing("20260901000001", "20260901", "[기재정정]사업보고서 (2025.12)")]
    f = Fake(filings, {(2024, "11011", "CFS"): fin_rows("20250301000001"), (2025, "11011", "CFS"): fin_rows("20260901000001")}, {2025: audit_rows("20260901000001")})
    r = execute(monkeypatch, tmp_path, f, date(2026, 9, 2))
    assert metric(r, "fin.ebitda", "2025FY").value == 135


def test_select_reports_groups_corrections_and_quarters():
    rows = [filing("A", "20260301", "사업보고서 (2025.12)"), filing("B", "20260901", "[기재정정]사업보고서 (2025.12)"), filing("C", "20260515", "분기보고서 (2026.03)"), filing("D", "20261114", "분기보고서 (2026.09)"), filing("E", "20260320", "사업보고서제출기한연장신고서 (2025.12)")]
    g = select_reports(rows)
    assert [(x["kind"], x["year"], x["latest"]["rcept_no"], x["first_dt"]) for x in g] == [("q3", 2026, "D", "20261114"), ("annual", 2025, "B", "20260301"), ("q1", 2026, "C", "20260515")]


def test_select_reports_non_december_year():
    rows = [filing("A", "20251020", "사업보고서 (2025.06)"), filing("B", "20260601", "분기보고서 (2026.03)"), filing("C", "20251201", "분기보고서 (2025.09)"), filing("D", "20260301", "반기보고서 (2025.12)")]
    got = {x["latest"]["rcept_no"]: (x["kind"], x["year"]) for x in select_reports(rows)}
    assert got == {"A": ("annual", 2025), "B": ("q3", 2026), "C": ("q1", 2026), "D": ("half", 2026)}


# ---- 합계 검증 ----
def test_balance_check_marks_that_year_missing(monkeypatch, tmp_path):
    resp = {**RESP, (2025, "11011", "CFS"): fin_rows("20260301000001", assets=999_999)}
    f = Fake(BASE, resp, {2025: audit_rows("20260301000001")})
    r = execute(monkeypatch, tmp_path, f, date(2026, 8, 15))
    assert metric(r, "fin.ebitda", "2025FY").data_status == "missing" and metric(r, "fin.ebitda", "2025FY").note == "자산 ≠ 부채+자본"
    assert metric(r, "fin.ebitda", "2024FY").data_status == "ok" and any("자산 ≠ 부채+자본" in e for e in r.errors) and r.status == "partial"


# ---- 감사의견 ----
def test_audit_opinion_text_as_is_and_dedup():
    out, _ = classify_audit(audit_rows("R", "  적    정 "), 2025, "R", True)
    ops = [c for c in out if c.key == "fin.audit_opinion"]
    assert [c.value for c in ops] == ["적    정"] and "정규화=적정" in ops[0].rule and "bsns_year=2025" in ops[0].rule     # 앞뒤 공백만 제거, 같은 값 1개, 사업연도는 요청 값


def test_audit_unmapped_and_current_row_by_first_period():
    assert normalize_opinion("부적정") is None and normalize_opinion("한정의견") == "한정"
    out, _ = classify_audit([{"rcept_no": "R", "bsns_year": "제10기(주1)", "adt_opinion": "감사인의 긴 문장"}], 2025, "R", True)
    assert "미매핑" in out[0].rule
    rows = [{"bsns_year": "제10기(주1)", "adt_opinion": "한정"}, {"bsns_year": "제9기(전기)", "adt_opinion": "적정"}]
    assert [r["adt_opinion"] for r in current_rows(rows)] == ["한정"]


@pytest.mark.parametrize("rows,want", [
    ([{"adt_opinion": "한정", "adt_reprt_spcmnt_matter": "감사범위 제한으로"}], "true"),
    ([{"adt_opinion": "적정의견"}], "false"),
    ([{"adt_opinion": "한정의견"}], "unknown"),
    ([{"adt_opinion": "의견거절"}], "unknown"),
])
def test_scope_limitation(rows, want):
    assert scope_limitation(rows) == want


def test_audit_missing_and_unknown():
    assert classify_audit([], 2025, "R", True)[0][0].value == "missing"
    assert classify_audit([], 2025, "R", False)[0][0].value == "unknown"


# ---- 구조조정 ----
def test_restructuring_exact_name_only_and_closed_note():
    rows = [filing("A", "20260615", "주요사항보고서(회생절차개시신청)"), filing("B", "20260620", "회생절차개시신청(종속회사의주요경영사항)"), filing("C", "20260625", "출자법인의회생절차및파산절차관련사실등발생"), filing("D", "20260701", "회생절차종결결정")]
    ev = match_events(rows)
    assert [e["rcept_no"] for e in ev] == ["A", "D"]
    assert status_of(ev) == ("회생절차", "종결 공시 있음(2026-07-01)") and status_of([]) == ("없음", None)


# ---- Alert·기업 식별 ----
def test_alert_on_audit_change_only_after_filing(monkeypatch, tmp_path):
    f = Fake(BASE[:2], RESP, {2025: audit_rows("20260301000001"), 2024: audit_rows("20250301000001", "한정의견")})
    first = execute(monkeypatch, tmp_path, f, date(2026, 2, 1))     # 2024 사업보고서 기준
    assert [a.alert_type for a in first.alerts] == ["market_data_missing"]
    second = execute(monkeypatch, tmp_path, f, date(2026, 3, 2))    # 2025 사업보고서 접수 다음 날
    assert [a.alert_type for a in second.alerts] == ["audit_opinion_changed"] and second.alerts[0].message == "감사의견 한정의견 → 적정의견"
    again = execute(monkeypatch, tmp_path, f, date(2026, 2, 1))     # 재생: 미래 이력을 읽지 않는다
    assert "audit_opinion_changed" not in [a.alert_type for a in again.alerts]


def test_company_not_found_goes_to_report(monkeypatch, tmp_path, fake):
    monkeypatch.setattr(dart, "get_client", lambda: fake)
    r = run(Request(request_id="q", agent="financial_health", mode="single", company="없는회사", as_of=date(2026, 8, 15), context={"db_path": str(tmp_path / "t.db")}))
    assert r.status == "failed" and r.corp_code is None and r.report_markdown
