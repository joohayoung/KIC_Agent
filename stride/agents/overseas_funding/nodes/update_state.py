import json

from agents.overseas_funding import store
from agents.overseas_funding.config import AGENT_KEY, ALERT_CONFIG
from agents.overseas_funding.schemas import SignalStatus, SignalType
from core.nodeguard import guarded
from core.schemas import Alert

DETECTED_OR_MORE = (SignalStatus.DETECTED.value, SignalStatus.CONFIRMED.value, SignalStatus.CHANGED.value)


def main_project(projects: list[dict]) -> dict | None:
    """대표 프로젝트: 게이트를 통과한 프로젝트 중 대표 금액이 가장 큰 것 (7.10 4, 7.12 2)."""
    return max((p for p in projects if p.get("gate_pass")), key=lambda p: p.get("amount_krw") or 0, default=None)


def decide_status(state) -> SignalStatus:
    """7.12 2. 범위 밖은 scope_gate의 분류를 그대로 쓴다."""
    if not state.get("in_scope"):
        return state.get("signal_status") or SignalStatus.NO_SIGNAL
    p = main_project(state.get("projects") or [])
    if p is None:
        return SignalStatus.DETECTED
    if p["change_direction"] in ("postponed", "reduced"):
        return SignalStatus.CHANGED
    return SignalStatus.CONFIRMED if p["stage"] >= 4 else SignalStatus.DETECTED


def changes(prev: dict | None, cur: dict) -> list[tuple[str, str, list[str]]]:
    """7.12 3 경보 (alert_type, 메시지, 관련 signal_id). 사실 변화만 적는다."""
    out = []
    status = cur["status"]
    if (prev is None or prev["status"] in (SignalStatus.NO_SIGNAL.value, SignalStatus.OUT_OF_SCOPE.value)) and status in DETECTED_OR_MORE:
        out.append(("new_signal", f"신호 상태 {prev['status'] if prev else '기록 없음'} → {status}", cur["main_ids"]))
    if status == SignalStatus.CANCELLED.value and (prev is None or prev["status"] != SignalStatus.CANCELLED.value):
        out.append(("cancelled", f"신호 상태 {prev['status'] if prev else '기록 없음'} → {status}", cur["cancel_ids"]))
    if prev is None:
        return out
    before = {p["project_key"]: p for p in prev["projects"]}
    for p in cur["projects"]:
        old = before.get(p["project_key"])
        if old and old["stage"] != p["stage"]:
            kind = "stage_up" if p["stage"] > old["stage"] else "stage_down"
            out.append((kind, f"{p.get('name') or p.get('target_country') or '프로젝트'} 단계 {old['stage']} → {p['stage']}", p["signal_ids"]))
    after = prev["as_of"]
    funding = [s for s in cur["signals"] if s.signal_type == SignalType.FUNDING and s.event_date.isoformat() > after]
    if funding:
        out.append(("new_funding", "새 조달 결정 " + ", ".join(f"{s.event_date} {s.summary}" for s in funding), [s.signal_id for s in funding]))
    changed = [s for s in cur["signals"] if s.signal_type == SignalType.ALERT and s.project_key and s.change_direction in ("postponed", "reduced") and s.event_date.isoformat() > after]
    if changed:      # 프로젝트에 연결된 S6만 경보를 만든다. unlinked_s6는 기록만 (7.12, v0.20)
        out.append(("plan_changed", "계획 변경 공시 " + ", ".join(f"{s.event_date} {s.change_direction}" for s in changed), [s.signal_id for s in changed]))
    a, b = prev["gap"], cur["gap"]
    if a is not None and b is not None and (a > 0) != (b > 0):
        out.append(("gap_changed", f"자금 공백 {a:,} → {b:,}", cur["main_ids"]))
    elif a and b is not None and ALERT_CONFIG["gap_change_ratio"] is not None and abs(b - a) / abs(a) >= ALERT_CONFIG["gap_change_ratio"]:
        out.append(("gap_changed", f"자금 공백 {a:,} → {b:,}", cur["main_ids"]))
    return out


@guarded
def update_state(state) -> dict:
    """추적 DB를 갱신하고 직전 상태와 비교해 사실 변화 경보를 만든다 (7.12). LLM 없음."""
    company, req = state.get("company"), state["request"]
    if not company:
        return {}
    status = decide_status(state)
    projects = state.get("projects") or []
    signals = state.get("signals_merged") or []
    gap = state.get("funding_gap")
    gap_krw = gap.gap_krw if gap and state.get("in_scope") else None
    main = main_project(projects)
    cancelled = [s.signal_id for s in signals if s.signal_type == SignalType.ALERT and s.change_direction == "cancelled" and s.project_key]
    cur = {"status": status.value, "projects": projects, "signals": signals, "gap": gap_krw, "main_ids": (main or {}).get("amount_signal_ids") or (main or {}).get("signal_ids") or [], "cancel_ids": cancelled}
    as_of = req.as_of.isoformat()
    con = store.connect((req.context or {}).get("db_path"))
    try:
        row = store.previous(con, company.corp_code, as_of)
        prev = {"status": row["signal_status"], "gap": row["gap_krw"], "projects": json.loads(row["projects_json"]), "as_of": row["as_of"]} if row else None
        found = changes(prev, cur)
        paragraphs = [(no, next((f.rcept_dt.isoformat() for f in state.get("filings") or [] if f.rcept_no == no), None), p["paragraph_id"], p["text"]) for no, sec in (state.get("periodic_sections") or {}).items() for p in sec.get("paragraphs") or []]
        store.save(con, run_id=state["run_id"], corp_code=company.corp_code, as_of=as_of, status=status.value, main_key=(main or {}).get("project_key"), gap=gap_krw, projects=projects, signals=signals, paragraphs=paragraphs, filings=[f.rcept_no for f in state.get("filings") or []], agent=AGENT_KEY)
    finally:
        con.close()
    by_id = {s.signal_id: s for s in signals}
    fallback = next((m.evidence_ids for m in state.get("metrics") or [] if m.metric_id == "ovs.overseas_project_count"), [])
    alerts = []
    for kind, message, ids in found:
        evidence = list(dict.fromkeys(e for i in ids if i in by_id for e in by_id[i].evidence_ids)) or fallback
        if evidence:
            alerts.append(Alert(agent=AGENT_KEY, corp_code=company.corp_code, alert_type=kind, message=message[:300], evidence_ids=evidence))
    return {"signal_status": status, "alerts": alerts}
