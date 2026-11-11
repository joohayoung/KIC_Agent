"""해외진출 7단계 완료 기준: 12.2 유형별 골든 (13장). 실제 claude -p를 호출한다. 실행: pytest -m llm tests/golden/test_overseas_step7.py
STRIDE_LLM_REPLAY=1이면 같은 입력의 호출 기록을 재사용한다. 경보는 8단계 update_state라 여기서 보지 않는다."""
import json
import os
import re
from datetime import date
from functools import lru_cache
from pathlib import Path

import pytest

from agents.overseas_funding.graph import run_company
from core.schemas import Request
from tests.unit.test_contract import check_contract

G = Path(__file__).parent / "overseas_funding"
pytestmark = pytest.mark.llm
if os.environ.get("STRIDE_LLM_REPLAY"):
    from tests.golden import llm_replay
    llm_replay.install()


@lru_cache(maxsize=None)
def result(company: str, as_of: str):
    r = run_company(Request(request_id="g", agent="overseas_funding", mode="single", corp_code=company, as_of=date.fromisoformat(as_of), context={"db_path": ":memory:"}))      # 경보는 재생 테스트(tests/replay)에서 본다
    out = Path(os.environ.get("STRIDE_STEP7_DUMP", "")) if os.environ.get("STRIDE_STEP7_DUMP") else None
    if out:
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{company}_{as_of}.json").write_text(r.model_dump_json(indent=1), encoding="utf-8")
    return r


def load(name):
    return json.loads((G / f"{name}.json").read_text(encoding="utf-8"))


def metric(r, mid):
    return next((m for m in r.metrics if m.metric_id == mid), None)


def cls(r, key):
    return next((c for c in r.classifications if c.key == key), None)


def check(r, e, as_of):
    assert check_contract(r) == [] and not r.errors, r.errors
    if "in_scope" in e:
        assert cls(r, "ovs.in_scope").value == str(e["in_scope"]).lower(), cls(r, "ovs.in_scope").rule
    if "signal_status" in e:
        assert cls(r, "ovs.signal_status").value == e["signal_status"]
    if "scope_reason_has" in e:
        assert e["scope_reason_has"] in cls(r, "ovs.in_scope").rule
    signals = r.extra["signals"]
    for t in e.get("must_not_have_signal_types", []):
        assert not [s for s in signals if s["signal_type"] == t], t
    for w in e.get("must_have_signals", []):
        no = (w.get("original_rcept_no") or w["rcept_no"]) + w.get("signal_suffix", "")
        if w["signal_type"] == "S5_funding":      # S5 id는 최신 정정본 접수번호다
            s = next(x for x in signals if x["signal_type"] == "S5_funding" and w["rcept_no"] in x["signal_id"])
        else:
            s = next(x for x in signals if x["signal_type"] == w["signal_type"] and x["signal_id"].endswith(no))
        for key, field in (("is_overseas", "is_overseas"), ("purpose_category", "purpose_category"), ("target_country", "target_country"), ("overseas_amount_krw", "amount_krw")):
            if key in w:
                assert s[field] == w[key], (no, key, s)
        if w.get("change_direction") == "취소/해제":
            assert s["change_direction"] == "cancelled"
        if w.get("fund_use_scopes"):
            filing = next(d["filing_rcept_no"] for d in r.extra["funding_decisions"] if d["rcept_no"] == w["rcept_no"])
            scopes = {x["slot"]: x["scope"] for x in r.extra["major_labels"][filing]["fund_use_scopes"]}
            for slot, scope in w["fund_use_scopes"].items():      # 국내 칸은 근거가 다른 공시에 있어 unknown도 허용한다 (G-DOM 정답지 메모). in_scope 결과는 같다
                assert scopes.get(slot) == scope or (scope == "domestic" and scopes.get(slot) == "unknown"), (no, slot, scopes)
        if w.get("open_question"):
            assert w["open_question"] in r.open_questions
        for q in w.get("open_questions", []):
            assert any(x.startswith(q[:12]) for x in r.open_questions), q
    for w in e.get("no_signal", []):
        assert not any(w["rcept_no"] in x["signal_id"] for x in signals), w
    ids = " ".join(x.evidence_id for x in r.evidence) + " ".join(x["signal_id"] for x in signals)
    for no in e.get("must_not_have_rcept_no", []):
        assert no not in ids, no
    for no in e.get("evidence_has", []):
        assert no in ids, no
    for w in e.get("must_not_be_overseas", []):
        assert not any(w["rcept_no"] in x["signal_id"] and x["is_overseas"] for x in signals), w
    assert all(x.published_at <= date.fromisoformat(as_of) for x in r.evidence)
    if "stage" in e:
        assert r.extra["projects"][0]["stage"] == 1
    for key, mid in (("cash_krw", "fin.cash_and_equivalents"), ("short_term_krw", "fin.short_term_financial_assets"), ("ttm_ocf_krw", "fin.ttm_operating_cash_flow"), ("confirmed_funding_krw", "ovs.confirmed_overseas_funding"), ("unconfirmed_funding_krw", "ovs.unconfirmed_overseas_funding"), ("available_funds_krw", "ovs.available_internal_funds"), ("overseas_investment_krw", "ovs.overseas_investment_amount"), ("funding_gap_krw", "ovs.funding_gap")):
        if key in e:
            assert metric(r, mid).value == e[key], (mid, metric(r, mid))
    if "funding_gap_ratio" in e and isinstance(e["funding_gap_ratio"], float):
        assert metric(r, "ovs.funding_gap_ratio").value == pytest.approx(e["funding_gap_ratio"], abs=1e-4)
    if str(e.get("funding_gap", "")).startswith("missing"):
        assert metric(r, "ovs.funding_gap").value is None
    lq = e.get("liquidity_draft") or {}      # 2026-11-10 방향 수정 지표 (draft: 만기 차입금·배당금 원문 대조 전)
    for key, mid in (("investment_within_24m_krw", "ovs.overseas_investment_within_24m"), ("investment_beyond_24m_krw", "ovs.overseas_investment_beyond_24m"), ("maturing_debt_1y_krw", "fin.maturing_debt_1y"),
                     ("dividends_paid_last_fy_krw", "fin.dividends_paid_last_fy"), ("liquidity_uses_krw", "ovs.liquidity_uses"), ("liquidity_surplus_krw", "ovs.liquidity_surplus")):
        if key in lq:
            assert metric(r, mid).value == lq[key], (mid, metric(r, mid))
    if lq.get("liquidity_sources_to_uses") is not None:
        assert metric(r, "ovs.liquidity_sources_to_uses").value == pytest.approx(lq["liquidity_sources_to_uses"], abs=1e-6)
    if "overseas_subsidiary_working_capital_krw" in e:
        assert r.extra["funding_gap"]["overseas_subsidiary_working_capital_krw"] == e["overseas_subsidiary_working_capital_krw"]
    finals = {d["rcept_no"]: d for d in r.extra["funding_decisions"]}
    for w in e.get("funding_status", []):
        d = finals[w["rcept_no"]]
        if "final" in w:
            assert d["final"] == w["final"], (w["rcept_no"], d)
        if "s5_amount_krw" in w:
            assert d["overseas_amount"] == w["s5_amount_krw"]
    for q in e.get("open_questions", []) if isinstance(e.get("open_questions"), list) else []:
        assert q in r.open_questions
    if "max_unverified_findings" in e:
        assert len([f for f in r.findings if f.kind == "unverified"]) <= e["max_unverified_findings"], r.findings
    assert all(f.verified is not None for f in r.findings)


SINGLE = ["G-POS_주", "G-POS_보조", "G-POS_MIXED", "G-POS_HALTED", "G-GOV_I", "G-MIX_1", "G-MIX_D", "G-RICH_F", "G-DOM_주", "G-DOM_EDGE", "G-NONE_H"]


@pytest.mark.parametrize("name", [n for n in SINGLE if (G / f"{n}.json").exists()])
def test_single(name):
    doc = load(name)
    q = doc["request"]
    as_of = q["as_of"]
    r = result(q["company"], as_of)
    check(r, doc["expect"], as_of)
    if name == "G-POS_HALTED":      # 7.9 거래 상태 경고 (v0.21): 범위 판정은 그대로, 사실만 표시
        assert {w["type"] for w in r.extra["trading_status_warnings"]} >= {"halted"} and cls(r, "ovs.in_scope").value == "true"
    elif name.startswith("G-POS"):
        assert not r.extra["trading_status_warnings"], r.extra["trading_status_warnings"]


@pytest.mark.parametrize("name", ["G-TRACK_D", "G-CHANGE_1"])
def test_sequence(name):
    doc = load(name)
    company = doc["request"].get("company") or doc["corp_code"]
    for step in doc["expect"]["steps"]:
        check(result(company, step["as_of"]), step, step["as_of"])


def test_g_track_same_project_when_new_filing_arrives():
    doc = load("G-TRACK_D")
    a, b = (result(doc["corp_code"], s) for s in ("2026-08-22", "2026-09-20"))
    assert len(a.extra["projects"]) == len(b.extra["projects"])


def test_g_change_singapore_is_separate_project():
    r = result(load("G-CHANGE_1")["corp_code"], "2025-10-28")
    keys = {p["target_country"] for p in r.extra["projects"]}
    assert {"베트남", "싱가포르"} <= keys and len([p for p in r.extra["projects"] if p["target_country"] == "베트남"]) == 1


def test_g_mix_d3_decision_with_injected_news_amount(monkeypatch):
    """13장 7단계: G-MIX 충돌 처리 결정이 decisions에 기록된다. 실제 실행에는 금액 충돌이 없어 기사 사건 금액만 주입한다. 공시·D3 판단은 실제 값이다."""
    from importlib import import_module

    from agents.overseas_funding.schemas import NewsExtractionOutput
    from core import evidence as ev
    node = import_module("agents.overseas_funding.nodes.extract_news")
    original = node.call_llm

    def fake(prompt_path, variables, model, *, run_id, as_of=None):
        first = re.search(r"\[(NEWS:[^\]]+)\]", variables["news_list"]).group(1)
        return NewsExtractionOutput(events=[{"evidence_ids": [first], "target_country": "폴란드", "method": "new_plant", "stage": 3, "amount_original": "1,000억원", "is_rumor": False, "summary": "폴란드 공장 투자 기사"}])
    monkeypatch.setattr(node, "call_llm", fake)
    assert ev and original
    r = run_company(Request(request_id="g", agent="overseas_funding", mode="single", corp_code="00495633", as_of=date(2026, 11, 5), context={"db_path": ":memory:"}))
    assert r.extra["conflicts"], "주입한 금액이 충돌을 만들어야 한다"
    d3 = [d for d in r.extra["decisions"] if d.get("point") == "D3"]
    assert d3 and d3[0]["action"] in ("fetch_original_text", "record_conflict")
    assert any(q.startswith("금액 충돌:") for q in r.open_questions) and all(c["resolved"] for c in r.extra["conflicts"])
    assert next(m for m in r.metrics if m.metric_id == "ovs.overseas_investment_amount").value != 100_000_000_000      # 공시 금액 우선
