"""검증 에이전트 단위 테스트 (검증 개발문서 13장). claude를 호출하지 않는다."""
from datetime import date
from importlib import import_module

import pytest

from agents.verifier.graph import verify_answer, verify_results
from agents.verifier.schemas import ClaimCheckOutput
from core.schemas import AgentResult, Classification, Evidence, Metric
from core import catalog

nodes = import_module("agents.verifier.nodes")
AS = date(2026, 6, 30)


def metric(mid, value, ids, status="ok"):
    c = catalog.get(mid)
    return Metric(metric_id=mid, name=c["name"], value=value, unit=str(c["unit"]), period="2026H1", methodology=c["methodology"], data_status=status, evidence_ids=ids)


def ev(eid, day=date(2026, 5, 15), **k):
    return Evidence(evidence_id=eid, source_grade="A", source_type="calc" if eid.startswith("CALC") else "dart_fin", corp_code="00000001", published_at=day, title="반기보고서 (2026.06)", **k)


def result(agent, metrics, evidence, report=None, classes=()):
    return AgentResult(request_id="q", agent=agent, agent_version="0", corp_code="00000001", corp_name=None, as_of=AS, status="complete", metrics=metrics, classifications=list(classes), evidence=evidence, report_markdown=report)


CALC = "CALC:r1:ovs.funding_gap"
GOOD_CALC = {"impl": "agents.overseas_funding.calc.funding.funding_gap", "args": {"investment": 100, "available": 30}, "value": 70, "inputs": []}


def run(results, required=()):
    return verify_results(results, AS, list(required), request_id="v1")


def codes(rep, outcome="fail"):
    return sorted({(c.code, c.kind) for c in rep.checks if c.outcome == outcome})


def test_r01_missing_evidence():
    r = result("ovs", [metric("ovs.funding_gap", 70, ["CALC:없음"])], [ev(CALC, meta=GOOD_CALC)])
    assert ("R-01", "missing_evidence") in codes(run([r]))


def test_r02_calc_recompute():
    ok = run([result("ovs", [metric("ovs.funding_gap", 70, [CALC])], [ev(CALC, meta=GOOD_CALC)])])
    assert not [c for c in ok.failed if c.code == "R-02"]
    bad = run([result("ovs", [metric("ovs.funding_gap", 71, [CALC])], [ev(CALC, meta={**GOOD_CALC, "value": 71})])])
    assert ("R-02", "value_mismatch") in codes(bad)


class Client:
    def __init__(self, rows=None, fail=False):
        self.rows, self.fail = rows or [], fail

    def get_json(self, endpoint, **k):
        if self.fail:
            raise RuntimeError("down")
        return {"status": "000", "list": self.rows}


FIN = "FIN:20260815000001:CFS:ifrs-full_CashAndCashEquivalents"


@pytest.mark.parametrize("rows,fail,want", [
    ([{"account_id": "ifrs-full_CashAndCashEquivalents", "rcept_no": "20260815000001", "thstrm_amount": "100"}], False, "pass"),
    ([{"account_id": "ifrs-full_CashAndCashEquivalents", "rcept_no": "20260815000001", "thstrm_amount": "101"}], False, "fail"),      # 1원 다름
    ([], True, "unverifiable"),
])
def test_r02_fin_recheck(monkeypatch, rows, fail, want):
    monkeypatch.setattr(nodes.dart, "get_client", lambda: Client(rows, fail))
    rep = run([result("fin", [metric("fin.cash_and_equivalents", 100, [FIN])], [ev(FIN)])])
    assert next(c.outcome for c in rep.checks if c.code == "R-02") == want


def test_r03_future_evidence():
    rep = run([result("ovs", [metric("ovs.funding_gap", 70, [CALC])], [ev(CALC, day=date(2026, 7, 1), meta=GOOD_CALC)])])
    assert ("R-03", "future_evidence") in codes(rep)


def test_r04_cross_agent():
    a = result("overseas_funding", [metric("fin.cash_and_equivalents", 100, ["DART:1:document"])], [ev("DART:1:document")])
    b = result("financial_health", [metric("fin.cash_and_equivalents", 120, ["DART:1:document"])], [ev("DART:1:document")])
    assert ("R-04", "cross_agent_mismatch") in codes(run([a, b]))
    b2 = result("financial_health", [metric("fin.cash_and_equivalents", 100, ["DART:1:document"])], [ev("DART:1:document")])
    assert not [c for c in run([a, b2]).failed if c.code == "R-04"]


def test_r05_coverage():
    rep = run([result("fin", [metric("fin.debt_ratio", None, ["DART:1:document"], "missing")], [ev("DART:1:document")])], ["fin.debt_ratio", "fin.equity_ex_nci"])
    assert rep.coverage == {"fin.debt_ratio": "missing", "fin.equity_ex_nci": "absent"}


def test_r06_forbidden_term():
    rep = run([result("ovs", [], [], report="이 기업은 유망하다")])
    assert ("R-06", "forbidden_term") in codes(rep)


# ---- answer 모드 ----
CITED = {"CALC:r:ovs.funding_gap": {"value": 141_012_345_678, "unit": "원", "quote": "자금 공백"}, "CALC:r:ratio": {"value": 0.4, "unit": "비율", "quote": "비율"}}
FOOT = {1: ["CALC:r:ovs.funding_gap"], 2: ["CALC:r:ratio"]}


def answer(text, monkeypatch, verdict="supported"):
    monkeypatch.setattr(nodes, "call_llm", lambda *a, **k: ClaimCheckOutput(verdict=verdict, reason="r"))
    return verify_answer(text, FOOT, CITED, AS, request_id="a1")


@pytest.mark.parametrize("text,want", [("자금 공백은 1,410억 원이다 [1].", "pass"), ("자금 공백은 1,510억 원이다 [1].", "number_mismatch"), ("자금 공백은 1,410억 원이다.", "number_without_source"), ("자금 공백 비율은 40%다 [2].", "pass")])
def test_a01_numbers(monkeypatch, text, want):
    rep = answer(text, monkeypatch)
    got = [c for c in rep.checks if c.code == "A-01"][0]
    assert (got.outcome == "pass") if want == "pass" else got.kind == want


def test_a02_broken_footnote(monkeypatch):
    assert ("A-02", "broken_footnote") in codes(answer("근거가 없는 각주다 [9].", monkeypatch))


@pytest.mark.parametrize("text,want", [("관리종목 지정 사유 해당 [1].", None), ("투자 적합 기업이다 [1].", "judgment_without_source")])
def test_a04_rule_phrase_allowed(monkeypatch, text, want):
    got = [c for c in answer(text, monkeypatch).checks if c.code == "A-04"][0]
    assert got.kind == want


def test_a03_claims_and_limit(monkeypatch):
    rep = answer("자금 공백은 1,410억 원이다 [1].", monkeypatch, "not_supported")
    assert ("A-03", "claim_not_supported") in codes(rep) and rep.llm_calls == 1
    monkeypatch.setattr(nodes, "MAX_CLAIM_CHECKS", 0)
    rep = answer("자금 공백은 1,410억 원이다 [1].", monkeypatch)
    assert any(c.kind == "claim_check_skipped" for c in rep.unverifiable)


def test_report_has_no_score_fields():
    rep = run([])
    assert not {"score", "grade", "rank"} & set(rep.model_dump())
    assert Classification
