"""해외진출 5단계 실행 확인 (13장): G-POS 케이스. LLM 없는 경로라 분할되지 않은 라벨은 unknown이다. 실행: pytest -m golden."""
import json
from pathlib import Path

import pytest

from agents.overseas_funding.graph import run_nollm
from core.schemas import Request
from tests.unit.test_contract import check_contract

G = Path(__file__).parent / "overseas_funding"
pytestmark = pytest.mark.golden


def execute(doc):
    q = doc["request"]
    return run_nollm(Request(request_id="g", agent="overseas_funding", mode="single", corp_code=q["company"], as_of=q["as_of"]))


def load(name):
    return json.loads((G / f"{name}.json").read_text(encoding="utf-8"))


def metric(r, mid):
    return next(m for m in r.metrics if m.metric_id == mid)


@pytest.mark.parametrize("name", ["G-POS_주", "G-POS_MIXED"])
def test_g_pos(name):
    doc = load(name)
    e = doc["expect"]
    r = execute(doc)
    assert check_contract(r) == [] and not r.errors, r.errors
    for want in e["must_have_signals"]:
        sig = next(s for s in r.extra["signals"] if s["signal_id"].endswith(want["rcept_no"] + want.get("signal_suffix", "")))
        assert sig["signal_type"] == want["signal_type"] and sig["is_overseas"] is True and sig["amount_krw"] == want["overseas_amount_krw"]
    for w in e["no_signal"]:
        assert not any(w["rcept_no"] in s["signal_id"] for s in r.extra["signals"])
    for w in e.get("funding_notes", []):
        d = next(x for x in r.extra["funding_decisions"] if x["rcept_no"] == w["rcept_no"])
        assert d["final"] == w["final"] and d["amount"] == w["amount_krw"] and d["overseas_amount"] is None
    assert r.extra["financial_snapshot"]["source_rcept_no"] == e["financial_base"]["rcept_no"]
    assert metric(r, "fin.cash_and_equivalents").value == e["cash_krw"]
    assert metric(r, "fin.short_term_financial_assets").value == e["short_term_krw"]
    assert metric(r, "fin.ttm_operating_cash_flow").value == e["ttm_ocf_krw"]
    assert metric(r, "ovs.confirmed_overseas_funding").value == e["confirmed_funding_krw"]
    assert metric(r, "ovs.unconfirmed_overseas_funding").value == e["unconfirmed_funding_krw"]
    assert metric(r, "ovs.available_internal_funds").value == e["available_funds_krw"]
    assert metric(r, "ovs.overseas_investment_amount").value == e["overseas_investment_krw"]
    assert metric(r, "ovs.funding_gap").value == e["funding_gap_krw"]
    assert metric(r, "ovs.funding_gap_ratio").value == pytest.approx(e["funding_gap_ratio"], abs=1e-4)
    items = {x["rcept_no"]: x for x in r.extra["s4_items"]}
    for n in e["investment_notes"]:
        x = items[n["rcept_no"]]
        assert x["excluded"] == n["excluded"]
        if n.get("confirmed_execution_date"):
            assert x["confirmed_date"] == n["confirmed_execution_date"] and x["confirmed_rcept_no"] == n["date_source_rcept_no"]
            assert x["amount"] == n["amount_krw"] and x["latest_rcept_no"] == n["latest_version"]
        else:
            assert x["note"] == n["note"]
    for q in e["open_questions"]:
        assert q in r.open_questions
    assert all(ev.published_at.isoformat() <= e["must_not_have_after"] for ev in r.evidence)
    assert r.extra["periodic_sections"]


def test_g_pos_sub_merges_by_share_fields_without_llm():
    """합산은 소유주식수 누적으로 판정하므로 LLM 없는 경로에서도 같다 (2026-11-07 결정). 추가 출자는 시설 칸만 투자액이다."""
    doc = load("G-POS_보조")
    e = doc["expect"]
    r = execute(doc)
    assert check_contract(r) == [] and not r.errors, r.errors
    assert metric(r, "ovs.available_internal_funds").value == e["available_funds_krw"]
    assert metric(r, "ovs.overseas_investment_amount").value == e["overseas_investment_krw"] and metric(r, "ovs.funding_gap").value == e["funding_gap_krw"]
    assert not any(q.startswith("취득 공시 합산 불명확") for q in r.open_questions)
    assert r.extra["funding_gap"]["overseas_subsidiary_working_capital_krw"] == e["overseas_subsidiary_working_capital_krw"]
