"""해외진출 7단계: merge_signals, resolve_conflicts(D3), scope_gate, verify. claude를 호출하지 않는다."""
from datetime import date
from types import SimpleNamespace as NS

import pytest

from agents.overseas_funding.graph import route_after_merge, route_after_verify, run_company
from agents.overseas_funding.nodes.merge_signals import build_projects, finish_project, link_s6, structured_direction
from agents.overseas_funding.nodes.resolve_conflicts import check_decision
from agents.overseas_funding.nodes.scope_gate import judge
from agents.overseas_funding.nodes.verify import amounts_in, code_check
from agents.overseas_funding.schemas import ReportOutput, MajorEventBatchOutput, NewsExtractionOutput, PeriodicPlanOutput, RouteOutput, Signal, SignalStatus, SignalType, Stage, VerifyOutput
from core.calc import cashflow  # noqa: F401
from core.schemas import Evidence, Finding, Request
from tests.unit.overseas_funding import test_llm_nodes as t
from tests.unit.overseas_funding.test_graph import ACQ, FIN, REPORTS, Fake, f
from tests.unit.test_contract import check_contract


def sig(sid, kind=SignalType.CONFIRMED, *, country="미국", dt=date(2026, 4, 1), purpose="growth_investment", amount=100, overseas=True, method="acquisition", stage=Stage.DECIDED, is_new=None, direction=None):
    return Signal(signal_id=sid, corp_code="c", signal_type=kind, event_date=dt, is_overseas=overseas, target_country=country, method=method, purpose_category=purpose, amount_krw=amount, amount_original=None, stage=stage, is_new=is_new, summary="요약", change_direction=direction, evidence_ids=["e"])


def item(no, name="테스트 LLC", dt="2026-04-01", board="2026-04-01", amount=100, part="unknown", **k):
    return {"rcept_no": no, "name": name, "rcept_dt": dt, "board": board, "amount": amount, "part_of_earlier": part, "form_amount": amount, "corrections": [], **k}


def projects_of(signals, items):
    raw, _ = build_projects(signals, {x["rcept_no"]: x for x in items})
    return [finish_project(p) for p in raw]


# ---- 프로젝트 묶기와 금액 (12.1) ----
def test_same_name_groups_whatever_the_llm_method():
    ps = projects_of([sig("c:S4:A", method="acquisition"), sig("c:S4:B", method="equity_investment", dt=date(2026, 9, 1))], [item("A", shares_after=10), item("B", dt="2026-09-01", board="2026-09-01", amount=70, shares_acquired=5, shares_after=15)])
    assert len(ps) == 1 and ps[0]["mergeable"] and ps[0]["amount_krw"] == 170


@pytest.mark.parametrize("second", [{"shares_after": 99}, {"shares_acquired": None}, {"board": "2026-04-01"}])
def test_unclear_merge_uses_latest(second):
    a = {"dt": "2026-09-01", "board": "2026-09-01", "amount": 70, "shares_acquired": 5, "shares_after": 15, **second}
    p = projects_of([sig("c:S4:A"), sig("c:S4:B", dt=date(2026, 9, 1))], [item("A", shares_after=10), item("B", **a)])[0]
    assert not p["mergeable"] and p["amount_krw"] == 70


def test_different_name_is_separate_project():
    assert len(projects_of([sig("c:S4:A"), sig("c:S4:B")], [item("A"), item("B", name="다른 INC")])) == 2


def test_execution_not_added_when_parent_exists():
    ex = item("X", amount=500, execution=True)
    ex.pop("form_amount")
    p = projects_of([sig("c:S4:A"), sig("c:S4:X", dt=date(2026, 5, 1))], [item("A"), ex])
    assert len(p) == 1 and p[0]["amount_krw"] == 100 and p[0]["rcept_nos"] == ["A"] and p[0]["execution_rcept_nos"] == ["X"]


def test_execution_only_uses_merge_rule():
    a, b = item("X", execution=True, dt="2026-01-01", board="2026-01-01"), item("Y", execution=True, amount=50, dt="2026-02-01", board="2026-02-01")
    a.pop("form_amount"), b.pop("form_amount")
    p = projects_of([sig("c:S4:X", dt=date(2026, 1, 1)), sig("c:S4:Y", dt=date(2026, 2, 1))], [a, b])
    assert len(p) == 1 and p[0]["amount_krw"] == 50 and not p[0]["mergeable"]      # 유형자산 공시에는 주식수 칸이 없어 합산을 확인할 수 없다


def test_amount_priority_without_s4():
    p = projects_of([sig("s1", SignalType.PLAN, amount=300, stage=Stage.PLANNED), sig("s2", SignalType.PROGRESS, amount=900, stage=Stage.NEGOTIATING)], [])[0]
    assert (p["amount_krw"], p["amount_source"], p["stage"]) == (300, "periodic", 3)


def test_news_stage_does_not_raise_project_with_s4():
    p = projects_of([sig("c:S4:A"), sig("s2", SignalType.PROGRESS, amount=None, stage=Stage.EXECUTING)], [item("A")])[0]
    assert p["stage"] == 4 and "s2" in p["signal_ids"]


@pytest.mark.parametrize("country,want", [("미국", True), (None, False), ("대한민국", False)])
def test_news_event_without_country_is_not_overseas(monkeypatch, country, want):
    news = NewsExtractionOutput(events=[{"evidence_ids": ["NEWS:x"], "target_country": country, "method": "jv", "stage": 4, "amount_original": None, "is_rumor": False, "summary": "지분 확보"}])
    from importlib import import_module
    node = import_module("agents.overseas_funding.nodes.extract_news")
    monkeypatch.setattr(node, "call_llm", lambda *a, **k: news)
    out = node.extract_news.__wrapped__({"news_items": [{"evidence_id": "NEWS:x", "pubDate": date(2026, 1, 1), "title": "t", "description": "d"}], "company": NS(corp_code="c", corp_name="테스트"), "request": Request(request_id="q", agent="overseas_funding", mode="single", corp_code="c", as_of=date(2026, 11, 5)), "run_id": "r"})
    assert out["signals"][0].is_overseas is want


def test_split_slot_signal_is_not_project_amount():
    ps = projects_of([sig("c:S4:A", amount=148)], [item("A", amount=148)])
    assert ps[0]["amount_krw"] == 148 and ps[0]["signal_ids"] == ["c:S4:A"]


# ---- S6 연결 (7.9, 7.12) ----
P = {"project_key": "미국:x", "name": "테스트 LLC", "corrections": ["C1"], "rcept_nos": ["A"]}


@pytest.mark.parametrize("no,text,want", [
    ("C1", "아무 내용", True),                                   # 원공시의 정정 접수번호
    ("Z", "(1) 출자회사명 : 테스트 LLC(미국)", True),               # 회사명 칸
    ("Z", "1. 발행회사 회사명(국적) 테스트 LLC (USA)", True),
    ("Z", "담보 계약 해지. 테스트 LLC 관련 내용이 문장에 나온다", False),      # 문장 언급만으로는 연결하지 않는다
    ("Z", "주식 담보 제공 계약 해지 회사명 다른회사", False),
])
def test_link_s6(no, text, want):
    assert (link_s6(no, text, [P]) is not None) == want


@pytest.mark.parametrize("nm,text,orig,want", [
    ("기타주요경영사항(타법인주식및출자증권취득결정철회)", "철회내용", None, "cancelled"),
    ("타법인주식및출자증권취득결정", "3. 정정사유 투자구조 변경에 따른 취득결정 철회", ACQ.format(rel="-", amt="1", sch="2027-01-01"), "cancelled"),
    ("타법인주식및출자증권취득결정", "3. 정정사유 취득완료에 따른 정정 " + ACQ.format(rel="-", amt="9", sch="2027-01-01"), ACQ.format(rel="-", amt="1", sch="2027-01-01"), "none"),
    ("타법인주식및출자증권취득결정", "3. 정정사유 금액 변경 " + ACQ.format(rel="-", amt="9", sch="2027-01-01"), ACQ.format(rel="-", amt="10", sch="2027-01-01"), "reduced"),
    ("타법인주식및출자증권취득결정", "3. 정정사유 금액 변경 " + ACQ.format(rel="-", amt="11", sch="2027-01-01"), ACQ.format(rel="-", amt="10", sch="2027-01-01"), "expanded"),
    ("타법인주식및출자증권취득결정", "3. 정정사유 일정 변경 " + ACQ.format(rel="-", amt="10", sch="2027-06-01"), ACQ.format(rel="-", amt="10", sch="2027-01-01"), "postponed"),
    ("기타공시", "변경 사항", None, None),                              # 정형으로 못 읽으면 None → LLM 라벨
])
def test_structured_direction(nm, text, orig, want):
    assert structured_direction(NS(report_nm_norm=nm), text, orig) == want


def graph_run(monkeypatch, docs, filings, major, *, plan=None, news=None, verify=None, as_of=date(2026, 11, 5), db=None, report=None):
    def fake(prompt_path, variables, model, *, run_id, as_of=None):
        fake.calls.append(model.__name__)
        if model is PeriodicPlanOutput:
            return plan or PeriodicPlanOutput(items=[], no_plan_found=True)
        if model is MajorEventBatchOutput:
            return MajorEventBatchOutput(items=major)
        if model is VerifyOutput:
            return verify or VerifyOutput(results=[{"finding_id": f"F{i}", "verdict": "supported", "reason": "일치"} for i in range(1, 9)])
        if model is RouteOutput:
            fake.route = variables
            return RouteOutput(action="record_conflict", reason="기사 금액", evidence_ids=[])
        if model is NewsExtractionOutput:
            return news or NewsExtractionOutput(events=[])
        if model is ReportOutput:
            return ReportOutput(markdown=f"### 테스트 — 해외진출·자금수요 사실 요약 (기준일 {as_of})\n\n**신호 상태**: {variables['signal_status']}\n이사회 결의 단계다 [1].")
        return model.model_validate({"queries": []})
    fake.calls = []
    fake.route = None
    from importlib import import_module
    t.wire(monkeypatch, Fake(filings, docs, fin=FIN), fake, news if False else ())
    for m in ("verify", "resolve_conflicts", "write_report"):
        monkeypatch.setattr(import_module(f"agents.overseas_funding.nodes.{m}"), "call_llm", fake)
    if report:
        monkeypatch.setattr(import_module("agents.overseas_funding.nodes.write_report"), "call_llm", report)
    r = run_company(Request(request_id="q", agent="overseas_funding", mode="single", corp_code="00000001", as_of=as_of, context={"db_path": db or ":memory:"}))
    return r, fake


DOC = ACQ.format(rel="-", amt="500", sch="2027-01-01")
BASE = REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")]


def status(r):
    return next(c.value for c in r.classifications if c.key == "ovs.signal_status")


def test_unlinked_s6_never_touches_stage_or_gate(monkeypatch):
    """주식 담보 해지처럼 프로젝트와 무관한 변경 공시: LLM이 cancelled라 해도 기록만 남는다."""
    r, _ = graph_run(monkeypatch, {"A1": DOC, "H1": "주식 담보 제공 계약 해지 해소사유 당사자들의 합의에 따라 담보계약 해지"}, BASE + [f("H1", "20260901", "최대주주변경을수반하는주식담보제공계약해제ㆍ취소등")], [t.label("DART:A1:정형"), t.label("DART:H1:정형", change_direction="cancelled", is_overseas=False, quote="담보계약 해지")])
    assert check_contract(r) == [] and not r.errors, r.errors
    assert next(c.value for c in r.classifications if c.key == "ovs.in_scope") == "true" and status(r) == SignalStatus.CONFIRMED.value
    assert [x["signal_id"] for x in r.extra["unlinked_s6"]] == ["00000001:S6:H1"] and not [x for x in r.extra["signals"] if x["signal_type"] == "S6_alert"]
    assert r.extra["projects"][0]["stage"] == 4 and r.extra["projects"][0]["change_direction"] == "none"


@pytest.mark.parametrize("llm_direction", ["cancelled", "none"])
def test_linked_cancel_is_same_whatever_the_label(monkeypatch, llm_direction):
    """회사명 칸으로 연결되면 공시 이름으로 방향을 읽는다. LLM 라벨이 흔들려도 결과가 같다."""
    name = "기타주요경영사항(타법인주식및출자증권취득결정철회)"
    r, _ = graph_run(monkeypatch, {"A1": DOC, "C1": "철회내용 (1) 출자회사명 : 테스트 LLC(USA)"}, BASE + [f("C1", "20260901", name)], [t.label("DART:A1:정형"), t.label("DART:C1:정형", change_direction=llm_direction, quote="철회내용")])
    assert next(c.value for c in r.classifications if c.key == "ovs.in_scope") == "false" and status(r) == SignalStatus.CANCELLED.value
    assert "G4" in next(c.rule for c in r.classifications if c.key == "ovs.in_scope")
    assert r.extra["projects"][0]["stage"] == 1 and [x["change_direction"] for x in r.extra["signals"] if x["signal_type"] == "S6_alert"] == ["cancelled"]


def test_old_s6_before_new_decision_does_not_lower_stage(monkeypatch):
    a2 = ACQ.format(rel="-", amt="70", sch="2027-02-01").replace("2026-04-13", "2026-09-01")
    corr = "2. 정정관련 공시서류제출일 2026-04-13 3. 정정사유 금액 축소 " + ACQ.format(rel="-", amt="300", sch="2027-01-01")
    r, _ = graph_run(monkeypatch, {"A1": DOC, "A9": corr, "A2": a2}, BASE + [f("A9", "20260501", "[기재정정]타법인주식및출자증권취득결정"), f("A2", "20260901", "타법인주식및출자증권취득결정")], [t.label("DART:A9:정형", change_direction="reduced", quote="금액 축소"), t.label("DART:A2:정형")])
    p = r.extra["projects"][0]
    assert p["stage"] == 4 and p["change_direction"] == "none" and status(r) == SignalStatus.CONFIRMED.value
    assert [x["change_direction"] for x in r.extra["signals"] if x["signal_type"] == "S6_alert"] == ["reduced"]


# ---- 게이트 (7.9) ----
def proj(**k):
    return {"project_key": "p", "is_overseas": True, "purpose_category": "growth_investment", "latest_event_date": "2026-04-01", "change_direction": "none", "has_new_signal": True, **k}


AS = date(2026, 11, 5)


@pytest.mark.parametrize("market,projects,signals,in_scope,status_,code", [
    ("KOSDAQ", [proj()], [], True, None, None),
    ("UNLISTED", [proj()], [], False, SignalStatus.OUT_OF_SCOPE, "G1"),
    ("KOSPI", [proj(purpose_category="governance_restructuring")], [sig("x")], False, SignalStatus.OUT_OF_SCOPE, "G2"),
    ("KOSPI", [], [sig("x", SignalType.FUNDING, overseas=False)], False, SignalStatus.OUT_OF_SCOPE, "G2"),      # 국내 용도 조달
    ("KOSPI", [], [], False, SignalStatus.NO_SIGNAL, "G2"),
    ("KOSPI", [], [sig("a", SignalType.ALERT, overseas=False)], False, SignalStatus.NO_SIGNAL, "G2"),
    ("KOSPI", [proj(latest_event_date="2020-01-01")], [sig("x")], False, SignalStatus.OUT_OF_SCOPE, "G3"),
    ("KOSPI", [proj(change_direction="cancelled")], [sig("x")], False, SignalStatus.CANCELLED, "G4"),
    ("KOSPI", [proj(has_new_signal=False)], [sig("x", SignalType.PLAN)], False, SignalStatus.OUT_OF_SCOPE, "G5"),
])
def test_gate(market, projects, signals, in_scope, status_, code):
    r = judge(market, projects, signals, AS, 24)
    assert r["in_scope"] == in_scope and r.get("signal_status") == status_
    assert (f"실패: {code}" in r["scope_reason"]) if code else "실패" not in r["scope_reason"]


def test_one_cancelled_project_does_not_fail_gate_when_other_alive():
    r = judge("KOSPI", [proj(project_key="a", change_direction="cancelled"), proj(project_key="b")], [], AS, 24)
    assert r["in_scope"] and r["passed"] == ["b"]


# ---- 충돌 D3 (7.8a) ----
def conflict_run(monkeypatch, action="record_conflict"):
    plan = PeriodicPlanOutput(no_plan_found=False, items=[{"paragraph_id": "p1", "quote": "미국 공장", "target_country": "미국", "method": "new_plant", "stage": 2, "amount_original": "1,000원", "timeline": None, "summary": "미국 공장"}])
    sec = "<TITLE>II. 사업의 내용</TITLE><P>미국 공장을 신설할 계획이며 투자 규모는 1,000원입니다.</P><TITLE>III. 재무</TITLE>"
    return graph_run(monkeypatch, {"A1": DOC, "20260814000001": sec, "20260301000001": "<TITLE>II. 사업의 내용</TITLE><P>x 미국</P><TITLE>III. 재무</TITLE>"}, BASE, [t.label("DART:A1:정형")], plan=plan)


def test_conflict_is_recorded_as_d3_decision(monkeypatch):
    r, fake = conflict_run(monkeypatch)
    assert "RouteOutput" in fake.calls and any(d.get("point") == "D3" and d["action"] == "record_conflict" for d in r.extra["decisions"])
    assert any(q.startswith("금액 충돌:") for q in r.open_questions)
    assert r.extra["conflicts"][0]["resolved"] and next(m for m in r.metrics if m.metric_id == "ovs.overseas_investment_amount").value == 500      # S4 우선


@pytest.mark.parametrize("action,ids,want", [("fetch_original_text", ["e"], "fetch_original_text"), ("record_conflict", ["e"], "record_conflict"), ("delete", ["e"], "record_conflict"), ("fetch_original_text", ["밖"], "record_conflict")])
def test_d3_validator(action, ids, want):
    assert check_decision(NS(action=action, evidence_ids=ids), {"e"})[0] == want


def test_route_after_merge():
    assert route_after_merge({"conflicts": [{"resolved": False}], "conflict_round": 0}) == "resolve_conflicts"
    assert route_after_merge({"conflicts": [{"resolved": False}], "conflict_round": 2}) == "scope_gate"
    assert route_after_merge({"conflicts": [{"resolved": True}]}) == "scope_gate"


# ---- 검증 (7.11, 12.1) ----
E = {"e": Evidence(evidence_id="e", source_grade="A", source_type="dart_document", corp_code="c", published_at=date(2026, 1, 1), title="공시", quote="취득금액 500", meta={"value": 500})}


@pytest.mark.parametrize("text,ids,code", [
    ("취득 500원", ["e"], None),
    ("취득 501원", ["e"], None),                   # 허용오차 0.5%
    ("취득 600원", ["e"], "C3"),
    ("취득 500원", ["없음"], "C1"),
])
def test_code_check(text, ids, code):
    why = code_check(Finding(finding_id="F", kind="fact", text=text, evidence_ids=ids), E, date(2026, 2, 1))
    assert (why is None) if code is None else why.startswith(code)


def test_code_check_rejects_future_evidence():
    assert code_check(Finding(finding_id="F", kind="fact", text="x", evidence_ids=["e"]), E, date(2025, 1, 1)).startswith("C2")


def calc_evidence(value):
    return {"k": Evidence(evidence_id="k", source_grade="A", source_type="calc", corp_code="c", published_at=date(2026, 1, 1), title="g", meta={"impl": "agents.overseas_funding.calc.funding.funding_gap", "args": {"investment": 100, "available": 30}, "value": value})}


def test_c4_recalculates():
    f = Finding(finding_id="F", kind="calc", text="자금 공백 70원", evidence_ids=["k"])
    assert code_check(f, calc_evidence(70), date(2026, 2, 1)) is None
    assert code_check(f, calc_evidence(71), date(2026, 2, 1)).startswith("C4")


def test_amounts_in_units():
    assert amounts_in("투자 1,000억원과 20원") == [100_000_000_000, 20]
    assert amounts_in("유상증자에 106억5400만원 출자") == [10_654_000_000]


def test_route_after_verify():
    assert route_after_verify({"reextract_targets": ["news", "periodic"], "verify_round": 1}) == "extract_periodic_plan"
    assert route_after_verify({"reextract_targets": ["news", "major_event"], "verify_round": 1}) == "parse_major_events"
    assert route_after_verify({"reextract_targets": ["news"], "verify_round": 2}) == "update_state"
    assert route_after_verify({"reextract_targets": []}) == "update_state"


PLAN = PeriodicPlanOutput(no_plan_found=False, items=[{"paragraph_id": "p1", "quote": "미국 공장", "target_country": "미국", "method": "new_plant", "stage": 2, "amount_original": None, "timeline": None, "summary": "미국 공장"}])
SEC = {"20260814000001": "<TITLE>II. 사업의 내용</TITLE><P>미국 공장을 신설할 계획입니다.</P><TITLE>III. 재무</TITLE>", "20260301000001": "<TITLE>II. 사업의 내용</TITLE><P>x 미국</P><TITLE>III. 재무</TITLE>"}


def plan_finding(r):
    return next(q for q in r.findings if q.text.endswith("미국 공장 (미국)"))


def test_contradicted_llm_text_reextracts_once_then_unverified(monkeypatch):
    def bad(i):
        return {"finding_id": f"F{i}", "verdict": "contradicted", "reason": "다름"}
    r, fake = graph_run(monkeypatch, {"A1": DOC, **SEC}, BASE, [t.label("DART:A1:정형")], plan=PLAN, verify=VerifyOutput(results=[bad(i) for i in range(1, 5)]))
    assert fake.calls.count("VerifyOutput") == 2 and fake.calls.count("PeriodicPlanOutput") == 2
    assert plan_finding(r).kind == "unverified" and plan_finding(r).verified is False


def test_not_enough_does_not_reextract(monkeypatch):
    v = VerifyOutput(results=[{"finding_id": f"F{i}", "verdict": "not_enough", "reason": "근거 짧음"} for i in range(1, 5)])
    r, fake = graph_run(monkeypatch, {"A1": DOC, **SEC}, BASE, [t.label("DART:A1:정형")], plan=PLAN, verify=v)
    assert fake.calls.count("VerifyOutput") == 1 and fake.calls.count("PeriodicPlanOutput") == 1 and plan_finding(r).kind == "unverified"


def test_structured_signal_needs_no_llm_check(monkeypatch):
    r, fake = graph_run(monkeypatch, {"A1": DOC}, BASE, [t.label("DART:A1:정형")])
    assert "VerifyOutput" not in fake.calls and all(q.verified for q in r.findings)


def test_full_graph_contract_and_findings(monkeypatch):
    r, _ = graph_run(monkeypatch, {"A1": DOC}, BASE, [t.label("DART:A1:정형")])
    assert check_contract(r) == [] and not r.errors, r.errors
    assert any(x.kind == "calc" and x.verified for x in r.findings) and any(x.kind == "fact" and x.verified for x in r.findings)
    assert {c.key for c in r.classifications} == {"ovs.signal_status", "ovs.in_scope", "ovs.project_stage", "ovs.investment_amount_source"}
    assert next(m for m in r.metrics if m.metric_id == "ovs.overseas_project_count").value == 1


def test_out_of_scope_stops_before_gap(monkeypatch):
    r, fake = graph_run(monkeypatch, {"A1": DOC}, BASE, [t.label("DART:A1:정형", purpose_category="governance_restructuring")])
    assert status(r) == SignalStatus.OUT_OF_SCOPE.value and "VerifyOutput" not in fake.calls and [m.metric_id for m in r.metrics] == ["ovs.overseas_project_count"]
