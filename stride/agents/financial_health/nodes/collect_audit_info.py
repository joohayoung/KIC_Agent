import re

from agents.financial_health.config import AUDIT_OPINION_MAP
from core import evidence as ev
from core.asof import UNKNOWN_NOTE, to_date
from core.clients import dart
from core.clients.dart import VIEWER_URL
from core.nodeguard import guarded
from core.schemas import Classification, Evidence

SCOPE_WORDS = ("범위제한", "감사범위")


def normalize_opinion(raw: str) -> str | None:
    """공백을 지운 값으로 매핑한다. 없으면 None (미매핑)."""
    s = re.sub(r"\s", "", raw or "")
    return next((k for k, vs in AUDIT_OPINION_MAP.items() if s in vs), None)


def scope_limitation(rows: list[dict]) -> str:
    """true / false / unknown (3.3). 문구가 있으면 true, 적정 계열이면 false, 그 외 unknown."""
    text = re.sub(r"\s", "", " ".join((r.get("adt_opinion") or "") + (r.get("adt_reprt_spcmnt_matter") or "") for r in rows))
    if any(w in text for w in SCOPE_WORDS):
        return "true"
    ops = [normalize_opinion(r.get("adt_opinion")) for r in rows if (r.get("adt_opinion") or "").strip()]
    return "false" if ops and all(o == "적정" for o in ops) else "unknown"


def current_rows(rows: list[dict]) -> list[dict]:
    """당기 행 = 응답 첫 행의 기수와 같은 행들. `(당기)` 대신 `(주1)`로 오는 경우가 있어 문자열 "당기"로 거르지 않는다."""
    if not rows:
        return []
    first = re.sub(r"\s", "", rows[0].get("bsns_year") or "").split("기")[0]
    return [r for r in rows if re.sub(r"\s", "", r.get("bsns_year") or "").split("기")[0] == first]


def classify_audit(rows: list[dict], year: int, report_no: str, version_ok: bool) -> tuple[list[Classification], list[str]]:
    """Classification 목록과 쓸 근거 ID. report_no는 값이 없을 때의 근거 (보고서 원문)."""
    rule = f"bsns_year={year}, reprt_code=11011"
    fallback = [ev.dart_section(report_no, "document")]
    if not version_ok:
        return [Classification(key=k, value="unknown", rule=f"{rule}; {UNKNOWN_NOTE}", evidence_ids=fallback) for k in ("fin.audit_opinion", "fin.audit_scope_limitation")], []
    cur = [r for r in current_rows(rows) if (r.get("adt_opinion") or "").strip()]
    if not cur:
        return [Classification(key="fin.audit_opinion", value="missing", rule=rule, evidence_ids=fallback), Classification(key="fin.audit_scope_limitation", value="unknown", rule=rule, evidence_ids=fallback)], []
    out, ids = [], []
    for raw in sorted({r["adt_opinion"].strip() for r in cur}):
        no = next(r["rcept_no"] for r in cur if r["adt_opinion"].strip() == raw)
        eid = ev.dart_api(no, "accnutAdtorNmNdAdtOpinion", "adt_opinion")
        ids.append(eid)
        out.append(Classification(key="fin.audit_opinion", value=raw, rule=f"{rule}; 정규화={normalize_opinion(raw) or '미매핑'}", evidence_ids=[eid]))
    out.append(Classification(key="fin.audit_scope_limitation", value=scope_limitation(cur), rule=rule, evidence_ids=ids[:1]))
    return out, ids


@guarded
def collect_audit_info(state) -> dict:
    """최근 사업보고서의 감사의견을 가져와 분류한다 (9.2, 3.3)."""
    years = state["sources"]["years"]
    if not years:
        return {"audit": []}
    client = dart.get_client()
    year = max(years)
    src = years[year]
    company = state["company"]
    rows = client.audit_opinion(company["corp_code"], year, "11011", state["sources"]["filings"], src["rcept_dt"])
    ok = not any(r.get("_version") == "unknown" for r in rows)
    out, ids = classify_audit(rows, year, src["rcept_no"], ok)
    evidence = [Evidence(evidence_id=i, source_grade="A", source_type="dart_api", corp_code=company["corp_code"], published_at=to_date(src["rcept_dt"]), title=src["report_nm"], url=VIEWER_URL.format(rcept_no=src["rcept_no"])) for i in ids]
    return {"audit": out, "evidence": evidence}
