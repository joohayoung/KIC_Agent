import re

from dateutil.relativedelta import relativedelta

from agents.overseas_funding.config import TRADING_PATTERNS, TRADING_TECHNICAL

from agents.overseas_funding.schemas import SignalStatus, SignalType
from core import catalog, evidence as ev
from core.asof import to_date
from core.nodeguard import guarded
from core.schemas import Evidence, Metric

LISTED = ("KOSPI", "KOSDAQ")


def project_count(keys: list[str]) -> int:
    """ovs.overseas_project_count: G1~G5 통과 프로젝트 수."""
    return len(keys)


def judge(market: str | None, projects: list[dict], signals: list, as_of, lookback_months: int) -> dict:
    """7.9 G1~G5. 반환 in_scope, scope_reason, signal_status(범위 밖일 때), passed(통과 프로젝트 키)."""
    start = as_of - relativedelta(months=lookback_months)
    g2 = [p for p in projects if p["is_overseas"] and p["purpose_category"] == "growth_investment"]
    g3 = [p for p in g2 if to_date(p["latest_event_date"]) >= start]
    g4 = [p for p in g3 if p["change_direction"] != "cancelled"]
    g5 = [p for p in g4 if p["has_new_signal"]]
    results = {"G1": market in LISTED, "G2": bool(g2), "G3": bool(g3), "G4": bool(g4), "G5": bool(g5)}
    first_fail = next((k for k, v in results.items() if not v), None)
    reason = "통과: " + ",".join(k for k, v in results.items() if v) + (f" / 실패: {first_fail}" if first_fail else "")
    if first_fail is None:
        return {"in_scope": True, "scope_reason": reason, "passed": [p["project_key"] for p in g5]}
    material = any(s.signal_type in (SignalType.CONFIRMED, SignalType.FUNDING) for s in signals)
    overseas = any(s.is_overseas for s in signals if s.signal_type != SignalType.ALERT)
    if first_fail == "G4":
        status = SignalStatus.CANCELLED
    elif first_fail == "G2" and not overseas and not material:
        status = SignalStatus.NO_SIGNAL      # 해외 신호도 국내 결정도 없음. 국내 용도 조달·취득이 있으면 G2 실패로 범위 밖이다
    else:
        status = SignalStatus.OUT_OF_SCOPE
    return {"in_scope": False, "scope_reason": reason, "signal_status": status, "passed": []}


def trading_warnings(filings: list) -> list[dict]:
    """7.9 거래 상태 경고 (v0.21 채택). as_of 이하 공시 이름에서 아직 끝나지 않은 거래정지·관리종목·상장폐지 심사를 사실로만 적는다. 범위 판정에 쓰지 않는다."""
    out = []
    rows = sorted(filings, key=lambda f: (f.rcept_dt, f.rcept_no))
    for kind, (start, end) in TRADING_PATTERNS.items():
        last = None
        for f in rows:
            name = re.sub(r"\s", "", f.report_nm)
            if re.search(end, name):
                last = None
            elif re.search(start, name) and not (kind == "halted" and re.search(TRADING_TECHNICAL, name)):
                last = last or f      # 정지 기간 변경은 같은 정지의 연장이다. 시작 공시를 남긴다
        if last:
            out.append({"type": kind, "since": last.rcept_dt.isoformat(), "rcept_no": last.rcept_no, "report_nm": re.sub(r"\s+", " ", last.report_nm).strip()})
    return out


@guarded
def scope_gate(state) -> dict:
    """신규 해외 성장투자 신호가 있는지 규칙으로 분류한다 (7.9). 사실 분류이고 판단이 아니다. LLM 없음."""
    req, company = state["request"], state["company"]
    projects = state.get("projects") or []
    r = judge(company.market, projects, state.get("signals_merged") or [], req.as_of, req.lookback_months)
    passed = set(r.pop("passed"))
    projects = [{**p, "gate_pass": p["project_key"] in passed} for p in projects]
    mid = "ovs.overseas_project_count"
    c = catalog.get(mid)
    eid = ev.calc(state["run_id"], mid)
    proof = Evidence(evidence_id=eid, source_grade="A", source_type="calc", corp_code=company.corp_code, published_at=req.as_of, title=mid, meta={"impl": "agents.overseas_funding.nodes.scope_gate.project_count", "args": {"keys": sorted(passed)}, "value": len(passed), "inputs": []})
    metric = Metric(metric_id=mid, name=c["name"], value=len(passed), unit=str(c["unit"]), period=f"{req.as_of} 기준", methodology=c["methodology"], data_status="ok", evidence_ids=[eid])
    return {**r, "projects": projects, "metrics": [metric], "evidence": [proof], "trading_status_warnings": trading_warnings(state.get("filings") or [])}
