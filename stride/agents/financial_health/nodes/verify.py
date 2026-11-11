from agents.financial_health.config import BS_TOLERANCE_KRW
from core.nodeguard import guarded
from core.schemas import Finding


def balance_ok(accounts) -> bool | None:
    """자산총계 = 부채총계 + 자본총계. 계정이 없으면 None (판정 불가)."""
    vals = [accounts[k].amount if k in accounts else None for k in ("total_assets", "total_liabilities", "total_equity")]
    if None in vals:
        return None
    return abs(vals[0] - vals[1] - vals[2]) <= BS_TOLERANCE_KRW


@guarded
def verify(state) -> dict:
    """합계 검증. 실패 연도의 지표는 missing으로 바꾸고 errors에 남긴다. 근거·재계산 검사는 to_result의 validate_evidence가 한다."""
    metrics = list(state.get("metrics") or [])
    errors = []
    failed = set()
    for y in state.get("years") or []:
        if balance_ok(y.accounts) is False:
            failed.add(f"{y.bsns_year}FY")
            errors.append(f"verify: {y.bsns_year} 자산 ≠ 부채+자본")
    latest = (state.get("sources") or {}).get("latest")
    if latest and state.get("latest_periodic") and balance_ok(state["latest_periodic"]) is False:
        failed |= {f"{latest['label']}말", f"TTM {latest['label']}"}
        errors.append(f"verify: {latest['label']} 자산 ≠ 부채+자본")
    out = []
    for m in metrics:
        if m.period in failed and m.data_status == "ok":
            m = m.model_copy(update={"value": None, "data_status": "missing", "note": "자산 ≠ 부채+자본"})
        out.append(m)
    findings = [Finding(finding_id=f"f{i}", kind="calc", text=f"{m.name} {m.period}: {m.value}", evidence_ids=m.evidence_ids, verified=True)
                for i, m in enumerate(x for x in out if x.metric_id in ("fin.net_debt_to_ebitda", "fin.ebitda_interest_coverage", "fin.ebitda_margin") and x.data_status == "ok")]
    return {"metrics": out, "findings": findings, "errors": errors}
