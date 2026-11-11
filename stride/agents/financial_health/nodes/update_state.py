import json

from agents.financial_health import store
from agents.financial_health.config import AGENT_KEY, EQUITY_ALERT_KRW, IMPAIRMENT_ALERTS
from core.nodeguard import guarded
from core.schemas import Alert


def changes(prev: dict | None, cur: dict) -> list[tuple[str, str]]:
    """직전 상태와 비교한 사실 변화 (alert_type, 메시지). 좋고 나쁨을 적지 않는다."""
    out = []
    if prev is None:
        return [("market_data_missing", "시장 데이터 없음")] if cur.get("market") == "missing" else []
    if prev.get("audit") != cur.get("audit"):
        out.append(("audit_opinion_changed", f"감사의견 {prev.get('audit')} → {cur.get('audit')}"))
    p, c = prev.get("impairment"), cur.get("impairment")
    for line in IMPAIRMENT_ALERTS:
        if p is not None and c is not None and p < line <= c:
            out.append((f"impairment_crossed_{line}", f"자본잠식률 {p:.2f} → {c:.2f}"))
    p, c = prev.get("equity"), cur.get("equity")
    if p is not None and c is not None and p >= EQUITY_ALERT_KRW > c:
        out.append(("equity_below_1bn", f"자기자본 {p:,} → {c:,}"))
    if prev.get("restructuring") != cur.get("restructuring") and cur.get("restructuring") != "없음":
        out.append(("restructuring_filed", f"구조조정 공시 상태 {prev.get('restructuring')} → {cur.get('restructuring')}"))
    if prev.get("market") != "missing" and cur.get("market") == "missing":
        out.append(("market_data_missing", "시장 데이터 없음"))
    return out


def facts(metrics: list[dict], classes: list[dict]) -> dict:
    def metric(mid):
        return next((m["value"] for m in metrics if m["metric_id"] == mid), None)

    def cls(key):
        vals = [c["value"] for c in classes if c["key"] == key]
        return ", ".join(sorted(vals)) if vals else None
    return {"audit": cls("fin.audit_opinion"), "impairment": metric("fin.capital_impairment_ratio"), "equity": metric("fin.equity_ex_nci"), "restructuring": cls("fin.restructuring_status"), "market": cls("fin.market_data_source")}


@guarded
def update_state(state) -> dict:
    """결과를 저장하고 직전 상태와 비교해 Alert를 만든다 (10장)."""
    company = state.get("company")
    if not company:
        return {"alerts": []}
    req = state["request"]
    metrics = [m.model_dump(mode="json") for m in state.get("metrics") or []]
    classes = [c.model_dump(mode="json") for c in state.get("classifications") or []]
    con = store.connect((req.context or {}).get("db_path"))
    try:
        as_of = req.as_of.isoformat()
        cc = company["corp_code"]
        row = store.previous_snapshot(con, cc, as_of)
        prev = facts(json.loads(row["metrics_json"]), json.loads(row["classifications_json"])) if row else None
        cur = facts(metrics, classes)
        reports = state.get("reports") or []
        annual = next((r.rcept_no for r in reports if r.report_kind == "annual"), None)
        fs = next((c["value"] for c in classes if c["key"] == "fin.fs_basis"), None)
        store.save(con, state["run_id"], cc, as_of, fs, metrics, classes, annual, reports[0].rcept_no if reports else None,
                   {"audit_opinion": cur["audit"], "capital_impairment_ratio": cur["impairment"], "restructuring_status": cur["restructuring"], "equity_ex_nci": cur["equity"]})
    finally:
        con.close()
    ids = next((m.evidence_ids for m in state.get("metrics") or []), [])
    return {"alerts": [Alert(agent=AGENT_KEY, corp_code=cc, alert_type=t, message=msg, evidence_ids=ids) for t, msg in changes(prev, cur)] if ids else []}
