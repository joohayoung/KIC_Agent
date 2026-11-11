"""해외진출 9단계: write_report 출력 검사 4종(7.13 3), 재생성·템플릿 대체, to_result 공통 계약. claude를 호출하지 않는다."""
from datetime import date
from importlib import import_module

import pytest

from agents.overseas_funding.graph import run_company
from agents.overseas_funding.nodes.write_report import allowed_numbers, check_report
from agents.overseas_funding.schemas import ReportOutput
from core.schemas import Request
from tests.unit.overseas_funding import test_llm_nodes as t
from tests.unit.overseas_funding.test_step7 import BASE, DOC, graph_run
from tests.unit.test_contract import check_contract

node = import_module("agents.overseas_funding.nodes.write_report")
DATA = "- (fact) 2026-04-13 취득결정, 금액 50,000,000,000원 [1]\n[출처]\n[1] DART 공시, 취득결정, 2026-04-13, A"
OK = "### 테스트 — 사실 요약 (기준일 2026-11-05)\n\n**신호 상태**: 해외 투자 확정\n2026-04-13 이사회에서 500억원 취득을 결정했다 [1]."


@pytest.mark.parametrize("text,kind", [
    (OK, None),
    (OK.replace("[1]", "[2]"), "각주"),
    (OK.replace("[1]", ""), "각주"),
    (OK.replace("500억원", "700억원"), "숫자"),
    (OK + " merge_signals 결과", "내부 이름"),
    (OK + " S4 신호", "내부 이름"),
    (OK + " 투자 적합", "판단 표현"),
    (OK + " 매력이 있다", "판단 표현"),
])
def test_four_checks(text, kind):
    errs = check_report(text, 1, allowed_numbers(DATA) | allowed_numbers("2026-11-05"))
    assert (errs == []) if kind is None else any(e.startswith(kind) or kind in e for e in errs), errs


def run(monkeypatch, outputs):
    calls = []

    def fake(prompt_path, variables, model, *, run_id, as_of=None):
        calls.append(variables)
        return ReportOutput(markdown=outputs[min(len(calls), len(outputs)) - 1](variables))
    monkeypatch.setattr(node, "call_llm", fake)
    from tests.unit.overseas_funding import test_step7
    keep = test_step7.graph_run.__globals__["t"]
    r, _ = graph_run(monkeypatch, {"A1": DOC}, BASE, [t.label("DART:A1:정형")], report=fake)
    assert keep
    return r, calls


def good(v):
    return "### 테스트 — 해외진출·자금수요 사실 요약 (기준일 2026-11-05)\n\n**신호 상태**: " + v["signal_status"] + "\n미국 투자가 이사회 결의 단계다 [1]."


def test_llm_report_used_when_checks_pass(monkeypatch):
    r, calls = run(monkeypatch, [good])
    assert check_contract(r) == [] and not r.errors, r.errors
    assert len(calls) == 1 and r.report_markdown.startswith("### 테스트") and r.extra["report_source"] == "llm"
    assert "[사실]" in calls[0]["findings_and_evidence"] and "[출처]" in calls[0]["findings_and_evidence"]


def test_regenerates_once_then_template(monkeypatch):
    bad = lambda v: good(v) + " 유망하다"
    r, calls = run(monkeypatch, [bad, bad])
    assert len(calls) == 2 and "판단 표현" in calls[1]["재생성_피드백"]
    assert r.extra["report_source"] == "template" and any(e.startswith("write_report: 템플릿 대체") for e in r.errors)
    assert check_report(r.report_markdown, 99, allowed_numbers(r.report_markdown)) == [] or "유망" not in r.report_markdown
    assert "**자금 공백**" in r.report_markdown and "**출처**" in r.report_markdown


def test_second_try_can_pass(monkeypatch):
    r, calls = run(monkeypatch, [lambda v: good(v) + " S4", good])
    assert len(calls) == 2 and r.extra["report_source"] == "llm" and not r.errors


def test_out_of_scope_uses_template_without_llm(monkeypatch):
    called = []
    r, _ = graph_run(monkeypatch, {"A1": DOC}, BASE, [t.label("DART:A1:정형", purpose_category="governance_restructuring")], report=lambda *a, **k: called.append(1))
    assert not called and r.extra["report_source"] == "template" and "범위 밖" in r.report_markdown and check_contract(r) == []
    assert not any(w in r.report_markdown for w in ("유망", "추천", "S4"))


def test_unknown_company_report(monkeypatch):
    from core.clients import dart
    from tests.unit.overseas_funding.test_graph import Fake
    monkeypatch.setattr(dart, "get_client", lambda: Fake([], {}))
    r = run_company(Request(request_id="q", agent="overseas_funding", mode="single", company="없는회사", as_of=date(2026, 11, 5), context={"db_path": ":memory:"}))
    assert r.status == "failed" and "기업을 특정하지 못했습니다" in r.report_markdown


def test_press_fact_marked_in_material():
    from types import SimpleNamespace as NS
    from core.schemas import Evidence, Finding
    ev = Evidence(evidence_id="NEWS:x", source_grade="C", source_type="news", corp_code="c", published_at=date(2026, 1, 1), title="기사")
    f = Finding(finding_id="F1", kind="fact", text="MOU 체결", evidence_ids=["NEWS:x"], verified=True)
    assert node.press(f, {"evidence": [ev]}) and not node.press(f.model_copy(update={"kind": "calc"}), {"evidence": [ev]})
    assert NS


def test_slot_amount_without_won_is_allowed_in_eok():
    assert {'200', '120'} <= allowed_numbers('fdpp_op 20,000,000,000 / 해외 용도 11,999,903,912')

