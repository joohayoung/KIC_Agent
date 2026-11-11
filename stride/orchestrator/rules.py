"""결격·주의 규칙과 조건 대조 (오케스트레이터 개발문서 5장, 11장). 출처 있는 규칙만, 결과는 사실이다."""
import re
from datetime import date
from pathlib import Path

import yaml

from orchestrator.config import INVESTMENT_TYPE_MAP, REGION_MAP
from orchestrator.schemas import DiscoveryCriteria, RuleResult

RULES_PATH = Path(__file__).with_name("rules.yaml")


def load_rules() -> list[dict]:
    return yaml.safe_load(RULES_PATH.read_text(encoding="utf-8"))


def latest_annual(fin, metric_id):
    """최근 사업연도말 값 (period 'YYYYFY' 중 최신)."""
    rows = [m for m in fin.metrics if m.metric_id == metric_id and re.fullmatch(r"\d{4}FY", m.period or "")]
    return max(rows, key=lambda m: m.period, default=None)


def audit(fin) -> tuple[list[str], list[str], str | None]:
    """감사의견 정규화 값 목록(재무 classification rule의 '정규화=' 값), 근거, 감사범위 제한."""
    rows = [c for c in fin.classifications if c.key == "fin.audit_opinion"]
    norms = [m.group(1) for c in rows if (m := re.search(r"정규화=(\S+)", c.rule))] or [c.value for c in rows]
    scope = next((c.value for c in fin.classifications if c.key == "fin.audit_scope_limitation"), None)
    return norms, [i for c in rows for i in c.evidence_ids], scope


def _metric_cond(m, cond) -> bool:
    return all(not (op == "gte" and not m.value >= v) and not (op == "lt" and not m.value < v) for op, v in cond.items() if op in ("gte", "lt"))


def evaluate(rule: dict, fin) -> tuple[bool | None, dict, list[str], str]:
    """반환 (hit, inputs, evidence_ids, 표시 문구). 입력이 없거나 ok가 아니면 hit=None."""
    c, label = rule["condition"], rule["label"]
    inputs, ids, hits, unknown = {}, [], [], []
    if "audit_in" in c or "scope_limited_qualified" in c:
        norms, aid, scope = audit(fin)
        ids += aid
        inputs.update({"fin.audit_opinion": norms, "fin.audit_scope_limitation": scope})
        if not norms or "미매핑" in norms:
            unknown.append("감사의견")
        if "audit_in" in c and any(n in c["audit_in"] for n in norms):
            hits.append(True)
        if c.get("scope_limited_qualified"):
            if "한정" in norms and scope in (None, "unknown", "missing"):
                unknown.append("감사범위 제한")
            elif "한정" in norms and scope == "true":
                hits.append(True)
    for cond in c.get("any", []):
        m = latest_annual(fin, cond["metric"])
        if m is None or m.data_status != "ok" or m.value is None:
            unknown.append(cond["metric"])
            inputs[cond["metric"]] = None if m is None else m.data_status
            continue
        inputs[cond["metric"]] = m.value
        ids += m.evidence_ids
        if _metric_cond(m, cond):
            hits.append(True)
    if hits:
        return True, inputs, ids, label
    if unknown:
        status = next((x.data_status for x in fin.metrics if x.metric_id in unknown and x.data_status == "unknown"), None)
        return None, inputs, ids, "확인 불가(정정 전 원본 값 확인 불가)" if status == "unknown" else "확인 불가(데이터 없음)"
    return False, inputs, ids, "해당 없음"


def apply_rules(fin, ver, market: str, as_of: date) -> list[RuleResult]:
    """rules.yaml을 시장·source_date로 거른 뒤 평가한다 (11장). R5는 검증 실패 항목이 있으면 hit=True."""
    out = []
    fallback = [e.evidence_id for e in (fin.evidence if fin else [])][:1] or ["CALC:rules:none"]
    for rule in load_rules():
        if rule["market"] != market or rule["source_date"] > as_of.isoformat() or fin is None:
            continue
        hit, inputs, ids, label = evaluate(rule, fin)
        out.append(RuleResult(rule_id=rule["rule_id"], hit=hit, label=rule["label"] if hit else label, source=rule["source"], source_date=rule["source_date"], market=market, inputs=inputs, evidence_ids=list(dict.fromkeys(ids)) or fallback))
    failed = list(ver.failed_targets) if ver else []
    out.append(RuleResult(rule_id="R5", hit=bool(failed), label="해당 수치 '검증 실패', 결론에 사용 금지" if failed else "해당 없음", source="STRIDE 내부 원칙", source_date=as_of.isoformat(), market=market, inputs={"failed_targets": failed},
                          evidence_ids=list(dict.fromkeys(i for c in (ver.failed if ver else []) for i in c.evidence_ids)) or fallback))
    return out


def region_of(country: str | None) -> list[str]:
    return [k for k, v in REGION_MAP.items() if country in v]


def apply_criteria(row: dict, criteria: DiscoveryCriteria, rule_results: list[RuleResult]) -> tuple[bool, dict | None, bool]:
    """조건을 순서대로 확인하고 처음 실패한 조건을 제외 사유로 돌려준다 (11장). 반환 (충족, 제외 사유, 확인 필요).
    값이 missing이면 제외하지 않고 확인 필요로 남긴다. 단 자금 공백 비율 조건은 그 값이 조건이라 missing이면 제외한다."""
    needs = False

    def fail(cond, value):
        return False, {"condition": cond, "value": value}, needs
    if row.get("market") not in criteria.markets:
        return fail("시장", row.get("market"))
    if criteria.industries and not any((row.get("industry_code") or "").startswith(p) for p in criteria.industries):
        if row.get("industry_code"):
            return fail("업종", row.get("industry_code"))
        needs = True
    if criteria.stages and row.get("gates_g1_g4", row.get("in_scope")) is not True:
        return fail("해외투자 계획 확인 (G1~G4)", row.get("gates_g1_g4", row.get("in_scope")))
    if criteria.stages and row.get("stage") not in criteria.stages:
        return fail("진행 단계", row.get("stage"))
    if criteria.target_regions:
        if row.get("country") is None:
            needs = True
        elif not set(region_of(row["country"])) & set(criteria.target_regions):
            return fail("투자 지역", row["country"])
    if criteria.investment_types:
        allowed = {m for t in criteria.investment_types for m in INVESTMENT_TYPE_MAP[t]}
        if row.get("method") is None:
            needs = True
        elif row["method"] not in allowed:
            return fail("투자 방식", row["method"])
    if criteria.min_investment_amount is not None:
        if row.get("investment") is None:
            needs = True
        elif row["investment"] < criteria.min_investment_amount:
            return fail("최소 투자액", row["investment"])
    if criteria.min_funding_gap_ratio is not None:
        if row.get("gap_ratio") is None:
            needs = True      # 값이 없으면 제외하지 않는다 (2026-11-10 방향 수정)
        elif not row["gap_ratio"] > criteria.min_funding_gap_ratio:
            return fail("자금 공백 비율", round(row["gap_ratio"], 4))
    if criteria.market_cap_range:
        lo, hi = criteria.market_cap_range
        cap = row.get("market_cap")
        if cap is None:
            needs = True
        elif (lo is not None and cap < lo) or (hi is not None and cap > hi):
            return fail("시가총액", cap)
    if criteria.signal_types and not set(criteria.signal_types) & set(row.get("signal_types") or []):
        return fail("신호 종류", sorted(row.get("signal_types") or []))
    for r in rule_results:
        if r.rule_id in criteria.exclude_rule_ids:
            if r.hit is True:
                return fail(f"상장 규정 기준 ({r.rule_id})", r.label)
            if r.hit is None:
                needs = True
    return True, None, needs
