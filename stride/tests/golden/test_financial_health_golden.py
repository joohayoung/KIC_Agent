"""재무 건전성 골든 실행 (14장 4단계: F-NORMAL·F-QUARTER, 5단계: 나머지). 캐시된 DART 응답과 .env 키를 쓴다. 실행: pytest -m golden."""
import json
from pathlib import Path

import pytest

from agents.financial_health.graph import run
from core.schemas import Request
from tests.unit.test_contract import check_contract

G = Path(__file__).parent / "financial_health"
pytestmark = pytest.mark.golden


def load(name):
    return json.loads((G / f"{name}.json").read_text(encoding="utf-8"))


def execute(doc, tmp_path):
    q = doc["request"]
    return run(Request(request_id="g", agent="financial_health", mode="single", corp_code=q["company"], as_of=q["as_of"], context={"db_path": str(tmp_path / "g.db")}))


def metric(r, mid, period):
    return next((m for m in r.metrics if m.metric_id == mid and m.period == period), None)


def near(m, want, tol=0.01):
    assert m is not None and m.value is not None and abs(m.value - want) <= tol, (m, want)


def exact(m, want):
    if want is None:
        assert m is None or m.value is None, m
    else:
        assert m is not None and m.value == want, (m, want)


def opinions(r):
    return sorted(c.value for c in r.classifications if c.key == "fin.audit_opinion")


@pytest.mark.parametrize("name", ["F-NORMAL_G", "F-NORMAL_F"])
def test_normal(name, tmp_path):
    doc = load(name)
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e = doc["expect"]
    assert [c.value for c in r.classifications if c.key == "fin.fs_basis"] == [e["fs_basis"]]
    for period, y in e["years"].items():
        for mid, key in (("fin.total_borrowings", "total_borrowings_krw"), ("fin.net_debt", "net_debt_krw"), ("fin.ebitda", "ebitda_krw")):
            exact(metric(r, mid, period), y[key])
        for mid, key in (("fin.net_debt_to_ebitda", "net_debt_to_ebitda"), ("fin.ebitda_interest_coverage", "ebitda_interest_coverage"), ("fin.ebitda_margin", "ebitda_margin_pct"), ("fin.debt_ratio", "debt_ratio_pct")):
            if y[key] is None:
                assert metric(r, mid, period).value is None
            else:
                near(metric(r, mid, period), y[key])
        if y["net_debt_missing_reason"]:
            assert metric(r, "fin.net_debt", period).note == y["net_debt_missing_reason"]
        if y["coverage_missing_reason"] and y["ebitda_krw"] is not None:
            assert metric(r, "fin.ebitda_interest_coverage", period).note == y["coverage_missing_reason"]
    newest = max(e["years"])
    assert opinions(r) == e["years"][newest]["audit_opinion_raw"]
    assert e["latest_year_all_core_computed"] and all(metric(r, m, newest).data_status == "ok" for m in ("fin.ebitda_interest_coverage", "fin.ebitda_margin"))
    assert r.report_markdown


def test_quarter(tmp_path):
    doc = load("F-QUARTER_F")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e = doc["expect"]
    b = e["latest_basis"]
    p = b["period"]
    exact(metric(r, "fin.cash_and_equivalents", p), b["cash_krw"])
    exact(metric(r, "fin.short_term_financial_assets", p), b["short_term_krw"])
    exact(metric(r, "fin.total_borrowings", p), b["fin.total_borrowings_krw"])
    exact(metric(r, "fin.net_debt", p), b["fin.net_debt_krw"])
    near(metric(r, "fin.debt_ratio", p), b["fin.debt_ratio_pct"])
    exact(metric(r, "fin.ttm_operating_cash_flow", "TTM 2026H1"), b["fin.ttm_operating_cash_flow_krw"])
    a = e["annual_basis"]
    exact(metric(r, "fin.ebitda", "2025FY"), a["fin.ebitda_krw"])
    exact(metric(r, "fin.net_debt", "2025FY"), a["fin.net_debt_krw"])
    near(metric(r, "fin.net_debt_to_ebitda", "2025FY"), a["fin.net_debt_to_ebitda"])
    near(metric(r, "fin.ebitda_interest_coverage", "2025FY"), a["fin.ebitda_interest_coverage"])
    near(metric(r, "fin.ebitda_margin", "2025FY"), a["fin.ebitda_margin_pct"])
    exact(metric(r, "fin.ttm_operating_cash_flow", "2025FY"), a["fin.ttm_operating_cash_flow_2025FY_krw"])
    assert not any(m.period.startswith("2026") and "H1" not in m.period for m in r.metrics if "기준" not in m.period)
    assert all(ev.published_at.isoformat() <= e["must_not_have_after"] for ev in r.evidence)


def cls(r, key):
    return sorted(c.value for c in r.classifications if c.key == key)


def rejects_future(r, as_of):
    assert all(ev.published_at.isoformat() <= as_of for ev in r.evidence)


@pytest.mark.parametrize("name", ["F-IMPAIR50_KOSPI", "F-IMPAIR50_KOSDAQ", "F-FULLIMPAIR_KOSPI", "F-FULLIMPAIR_KOSDAQ", "F-KOSDAQ-EQ_KOSDAQ"])
def test_listing_inputs(name, tmp_path):
    doc = load(name)
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e = doc["expect"]
    p = f"{e['bsns_year']}FY"
    near(metric(r, "fin.capital_impairment_ratio", p), e["fin.capital_impairment_ratio_pct"])
    exact(metric(r, "fin.equity_ex_nci", p), e["fin.equity_ex_nci_krw"])
    assert opinions(r) == sorted(e["fin.audit_opinion"]) and cls(r, "fin.fs_basis") == [e["fs_basis"]]
    rejects_future(r, e["must_not_have_after"])


@pytest.mark.parametrize("name", ["F-AUDIT_의견거절", "F-AUDIT_한정"])
def test_audit(name, tmp_path):
    doc = load(name)
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e = doc["expect"]
    assert opinions(r) == [e["fin.audit_opinion"]] and cls(r, "fin.audit_scope_limitation") == [e["fin.audit_scope_limitation"]]
    assert e["audit_opinion_map"] in next(c.rule for c in r.classifications if c.key == "fin.audit_opinion")
    p = f"{e['bsns_year']}FY"
    near(metric(r, "fin.capital_impairment_ratio", p), e["capital_impairment_ratio_pct"])
    exact(metric(r, "fin.equity_ex_nci", p), e["equity_ex_nci_krw"])
    rejects_future(r, e["must_not_have_after"])


def test_netcash(tmp_path):
    doc = load("F-NETCASH_1")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e, p = doc["expect"], doc["expect"]["period"]
    exact(metric(r, "fin.total_borrowings", p), e["total_borrowings_krw"])
    assert metric(r, "fin.total_borrowings", p).note == e["total_borrowings_note"]
    exact(metric(r, "fin.net_debt", p), e["fin.net_debt_krw"])
    assert e["fin.net_debt_krw"] < 0
    exact(metric(r, "fin.ebitda", p), e["fin.ebitda_krw"])
    near(metric(r, "fin.net_debt_to_ebitda", p), e["fin.net_debt_to_ebitda"])
    near(metric(r, "fin.ebitda_interest_coverage", p), e["fin.ebitda_interest_coverage"])
    assert metric(r, "fin.ebitda_interest_coverage", p).note == e["interest_note"]
    near(metric(r, "fin.ebitda_margin", p), e["fin.ebitda_margin_pct"])


def test_netcash_without_ebitda(tmp_path):
    doc = load("F-NETCASH-NOEBITDA_A")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e, p = doc["expect"], doc["expect"]["period"]
    exact(metric(r, "fin.net_debt", p), e["fin.net_debt_krw"])
    assert e["fin.net_debt_krw"] < 0
    for mid in ("fin.ebitda", "fin.net_debt_to_ebitda", "fin.ebitda_margin", "fin.ebitda_interest_coverage"):
        assert metric(r, mid, p).data_status == "missing" and metric(r, mid, p).value is None
    assert e["ebitda_note"] in metric(r, "fin.ebitda", p).note and metric(r, "fin.ebitda_interest_coverage", p).note == e["interest_note"]


def test_negative_ebitda(tmp_path):
    doc = load("F-NEGEBITDA_E")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e, p = doc["expect"], doc["expect"]["period"]
    exact(metric(r, "fin.ebitda", p), e["fin.ebitda_krw"])
    assert e["fin.ebitda_krw"] < 0
    m = metric(r, "fin.net_debt_to_ebitda", p)
    assert m.value is None and m.note == e["net_debt_to_ebitda_note"]
    c = metric(r, "fin.ebitda_interest_coverage", p)
    near(c, e["fin.ebitda_interest_coverage"])
    assert c.note == e["coverage_note"]
    near(metric(r, "fin.ebitda_margin", p), e["fin.ebitda_margin_pct"])


def test_separate_only(tmp_path):
    doc = load("F-OFS_1")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e, p = doc["expect"], doc["expect"]["period"]
    assert cls(r, "fin.fs_basis") == ["OFS"] and opinions(r) == e["fin.audit_opinion"]
    m = metric(r, "fin.ebitda", p)
    assert m.value == e["fin.ebitda_krw"] and m.note.startswith(e["basis_note"])
    exact(metric(r, "fin.total_borrowings", p), e["total_borrowings_krw"])
    assert metric(r, "fin.net_debt", p).data_status == "missing"
    assert e["interest_note"] in metric(r, "fin.ebitda_interest_coverage", p).note
    near(metric(r, "fin.debt_ratio", p), e["fin.debt_ratio_pct"])


def test_no_interest(tmp_path):
    doc = load("F-NOINTEREST_1")
    r = execute(doc, tmp_path)
    e, p = doc["expect"], doc["expect"]["period"]
    c = metric(r, "fin.ebitda_interest_coverage", p)
    assert c.value is None and c.data_status == "missing" and e["interest_note"] in c.note
    exact(metric(r, "fin.ebitda", p), e["fin.ebitda_krw"])
    exact(metric(r, "fin.total_borrowings", p), e["total_borrowings_krw"])


def test_correction_before_filing(tmp_path):
    doc = load("F-CORRECTED_KOSPI")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e = doc["expect"]
    assert opinions(r) == [e["fin.audit_opinion"]] and cls(r, "fin.audit_scope_limitation") == ["unknown"]
    for mid in ("fin.ebitda", "fin.net_debt", "fin.debt_ratio"):
        m = metric(r, mid, "2025FY")
        assert m.data_status == e["metrics_2025FY_data_status"] and m.note == e["metrics_note"] and m.value is None
    dump = str(r.model_dump(mode="json"))
    assert e["api_response_rcept_no"] not in dump and all(v not in opinions(r) for v in e["must_not_output_values"])
    rejects_future(r, e["must_not_have_after"])


def test_no_market_data(tmp_path):
    doc = load("F-NOMARKET_F")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and r.status == doc["expect"]["result_status"], r.errors
    e = doc["expect"]
    assert cls(r, "fin.market_data_source") == [e["fin.market_data_source"]]
    for mid in e["missing_metrics"]:
        assert next(m for m in r.metrics if m.metric_id == mid).data_status == "missing"
    near(metric(r, "fin.net_debt_to_ebitda", "2025FY"), e["fin.net_debt_to_ebitda_2025FY"])
    near(metric(r, "fin.ebitda_interest_coverage", "2025FY"), e["fin.ebitda_interest_coverage_2025FY"])


def test_restructuring(tmp_path):
    doc = load("F-RESTRUCT_KOSPI")
    r = execute(doc, tmp_path)
    assert check_contract(r) == [] and not r.errors, r.errors
    e = doc["expect"]
    assert cls(r, "fin.restructuring_status") == [e["fin.restructuring_status"]]
    got = {x["rcept_no"]: x["kind"] for x in r.extra["restructuring_events"]}
    assert got == {x["rcept_no"]: x["kind"] for x in e["events"]}
    assert not set(got) & set(e["corrected_same_event"]) and not set(got) & set(e["excluded_subsidiary"])
    rejects_future(r, e["must_not_have_after"])

