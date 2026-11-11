"""해외진출 8단계: update_state 경보 규칙(7.12)과 거래 상태 경고(7.9). claude를 호출하지 않는다."""
from datetime import date
from types import SimpleNamespace as NS

import pytest

from agents.overseas_funding.nodes.scope_gate import trading_warnings
from agents.overseas_funding.nodes.update_state import changes, decide_status
from agents.overseas_funding.schemas import SignalStatus, SignalType, Stage
from tests.unit.overseas_funding import test_llm_nodes as t
from tests.unit.overseas_funding.test_step7 import BASE, DOC, graph_run, sig
from tests.unit.overseas_funding.test_graph import f


def cur(status, projects=(), signals=(), gap=None):
    return {"status": status.value, "projects": list(projects), "signals": list(signals), "gap": gap, "main_ids": ["m"], "cancel_ids": ["c"]}


def prev(status, projects=(), gap=None, as_of="2026-06-01"):
    return {"status": status.value, "projects": list(projects), "gap": gap, "as_of": as_of}


P = {"project_key": "k", "stage": 4, "signal_ids": ["s"]}


@pytest.mark.parametrize("before,now,want", [
    (None, SignalStatus.CONFIRMED, {"new_signal"}),
    (SignalStatus.OUT_OF_SCOPE, SignalStatus.DETECTED, {"new_signal"}),
    (SignalStatus.CONFIRMED, SignalStatus.CONFIRMED, set()),
    (None, SignalStatus.NO_SIGNAL, set()),
    (SignalStatus.CONFIRMED, SignalStatus.CANCELLED, {"cancelled"}),
    (SignalStatus.CANCELLED, SignalStatus.CANCELLED, set()),      # 같은 취소를 반복해 알리지 않는다
])
def test_status_alerts(before, now, want):
    assert {k for k, _, _ in changes(prev(before) if before else None, cur(now))} == want


def test_stage_alerts():
    got = changes(prev(SignalStatus.CONFIRMED, [P]), cur(SignalStatus.CANCELLED, [{**P, "stage": 1}]))
    assert {k for k, _, _ in got} == {"stage_down", "cancelled"}
    assert {k for k, _, _ in changes(prev(SignalStatus.DETECTED, [{**P, "stage": 2}]), cur(SignalStatus.CONFIRMED, [P]))} == {"stage_up"}


def test_new_funding_only_after_previous_as_of():
    s5 = [sig("old", SignalType.FUNDING, dt=date(2026, 5, 1)), sig("new", SignalType.FUNDING, dt=date(2026, 7, 1))]
    got = changes(prev(SignalStatus.CONFIRMED), cur(SignalStatus.CONFIRMED, signals=s5))
    assert [(k, ids) for k, _, ids in got] == [("new_funding", ["new"])]
    assert not changes(None, cur(SignalStatus.CONFIRMED, signals=s5))[1:]      # 첫 실행은 new_signal만


def test_plan_changed_needs_linked_s6():
    linked = sig("a", SignalType.ALERT, dt=date(2026, 7, 1), direction="postponed").model_copy(update={"project_key": "k"})
    loose = sig("b", SignalType.ALERT, dt=date(2026, 7, 1), direction="postponed")
    assert [k for k, _, _ in changes(prev(SignalStatus.CONFIRMED), cur(SignalStatus.CHANGED, signals=[linked, loose]))] == ["plan_changed"]
    assert not changes(prev(SignalStatus.CONFIRMED), cur(SignalStatus.CONFIRMED, signals=[loose]))


def test_gap_sign_change_only():
    assert [k for k, _, _ in changes(prev(SignalStatus.CONFIRMED, gap=-10), cur(SignalStatus.CONFIRMED, gap=5))] == ["gap_changed"]
    assert not changes(prev(SignalStatus.CONFIRMED, gap=10), cur(SignalStatus.CONFIRMED, gap=50))      # 변화율 기준은 문서에 값이 없어 끈다


@pytest.mark.parametrize("project,want", [({"change_direction": "postponed", "stage": 3}, SignalStatus.CHANGED), ({"change_direction": "none", "stage": 4}, SignalStatus.CONFIRMED), ({"change_direction": "none", "stage": 2}, SignalStatus.DETECTED)])
def test_decide_status(project, want):
    assert decide_status({"in_scope": True, "projects": [{"gate_pass": True, "amount_krw": 1, **project}]}) == want
    assert decide_status({"in_scope": False, "signal_status": SignalStatus.CANCELLED}) == SignalStatus.CANCELLED


def F(no, dt, nm):
    return NS(rcept_no=no, rcept_dt=date.fromisoformat(dt), report_nm=nm)


def test_trading_warnings():
    rows = [F("1", "2024-03-21", "주권매매거래정지"), F("2", "2025-04-15", "주권매매거래정지기간변경 (상장적격성 실질심사 대상 결정)"), F("3", "2026-04-09", "주권매매거래정지 (주식의 병합, 분할 등 전자등록 변경, 말소)")]
    got = {w["type"]: w for w in trading_warnings(rows)}
    assert got["halted"]["since"] == "2024-03-21" and got["delisting_review"]["rcept_no"] == "2"
    assert not trading_warnings([F("1", "2026-04-09", "주권매매거래정지 (주식의 병합, 분할 등 전자등록 변경, 말소)"), F("2", "2026-05-06", "주권매매거래정지해제 (액면병합 주권 변경상장)")])
    assert not trading_warnings([F("1", "2026-01-01", "주권매매거래정지"), F("2", "2026-01-05", "주권매매거래정지해제")])
    assert not trading_warnings([F("1", "2026-01-01", "기타시장안내(관리종목지정우려종목)")])


def test_replay_in_one_db(monkeypatch, tmp_path):
    """같은 DB로 시점 순서 실행: 첫 실행 new_signal, 철회 뒤 cancelled·stage_down, 미래 상태를 읽지 않는다."""
    db = str(tmp_path / "r.db")
    name = "기타주요경영사항(타법인주식및출자증권취득결정철회)"
    docs = {"A1": DOC, "C1": "철회내용 (1) 출자회사명 : 테스트 LLC(USA)"}
    filings = BASE + [f("C1", "20260901", name)]
    labels = [t.label("DART:A1:정형"), t.label("DART:C1:정형", change_direction="cancelled", quote="철회내용")]
    later, _ = graph_run(monkeypatch, docs, filings, labels, as_of=date(2026, 11, 5), db=db)      # 미래 시점을 먼저 저장해도
    first, _ = graph_run(monkeypatch, docs, filings, labels, as_of=date(2026, 8, 20), db=db)
    assert [a.alert_type for a in first.alerts] == ["new_signal"]      # 앞선 기록이 없으므로 새 신호
    again, _ = graph_run(monkeypatch, docs, filings, labels, as_of=date(2026, 11, 5), db=db)
    assert {a.alert_type for a in again.alerts} == {"cancelled", "stage_down"} and next(c.value for c in again.classifications if c.key == "ovs.signal_status") == SignalStatus.CANCELLED.value
    assert Stage.MENTIONED == 1 and later.alerts
