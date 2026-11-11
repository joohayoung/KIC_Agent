"""해외진출 6단계 완료 기준: G-POS 케이스 must_have_signals. 실제 claude -p를 호출한다. 실행: pytest -m llm. 결과는 호출마다 달라질 수 있다."""
import json
from pathlib import Path

import pytest

from agents.overseas_funding.graph import run_extraction
from core.schemas import Request
from tests.unit.test_contract import check_contract

G = Path(__file__).parent / "overseas_funding"
pytestmark = pytest.mark.llm


@pytest.mark.parametrize("name", ["G-POS_주", "G-POS_보조", "G-POS_MIXED"])
def test_must_have_signals(name):
    doc = json.loads((G / f"{name}.json").read_text(encoding="utf-8"))
    q, e = doc["request"], doc["expect"]
    r = run_extraction(Request(request_id="g", agent="overseas_funding", mode="single", corp_code=q["company"], as_of=q["as_of"]))
    assert check_contract(r) == [] and not r.errors, r.errors
    print(json.dumps({"labels": r.extra["major_labels"], "questions": r.open_questions, "gap": r.extra["funding_gap"], "llm_calls": r.extra["llm_calls"]}, ensure_ascii=False, default=str))
    for want in e["must_have_signals"]:
        no = (want.get("original_rcept_no") or want["rcept_no"]) + want.get("signal_suffix", "")
        s = next(x for x in r.extra["signals"] if x["signal_id"].endswith(no) and x["signal_type"] == want["signal_type"])
        assert s["is_overseas"] == want["is_overseas"], (no, s)
        if "purpose_category" in want:      # 2026-11-09 교체한 G-POS_주 둘째 신호는 이 키가 없다
            assert s["purpose_category"] == want["purpose_category"], (no, s)
        assert s["target_country"] == want["target_country"], (no, s)
        assert s["amount_krw"] == want["overseas_amount_krw"], (no, s)
    assert next(m for m in r.metrics if m.metric_id == "ovs.overseas_investment_amount").value == e["overseas_investment_krw"]
    assert next(m for m in r.metrics if m.metric_id == "ovs.funding_gap").value == e["funding_gap_krw"]
    for w in e["no_signal"]:
        assert not any(w["rcept_no"] in x["signal_id"] for x in r.extra["signals"])
    for question in e.get("open_questions", []):
        assert question in r.open_questions
