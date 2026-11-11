from dateutil.relativedelta import relativedelta

from agents.financial_health.config import RESTRUCTURING_MONTHS, RESTRUCTURING_PATTERNS
from agents.financial_health.schemas import RestructuringEvent
from core import evidence as ev
from core.asof import to_date
from core.clients import dart
from core.clients.dart import VIEWER_URL
from core.filings import normalize_report_nm
from core.nodeguard import guarded
from core.schemas import Evidence

_KIND = {nm: k for k, names in RESTRUCTURING_PATTERNS.items() for nm in names}


def match_events(filings: list[dict]) -> list[dict]:
    """9.3 정규화 이름 완전 일치. 종속회사 공시는 이 기업의 상태에 넣지 않는다."""
    out = []
    for r in filings:
        n = normalize_report_nm(r["report_nm"])
        if n["filer_scope"] == "self" and n["norm"] in _KIND and not n["is_correction"]:      # 정정은 같은 사건 1건으로 본다
            out.append({**r, "kind": _KIND[n["norm"]]})
    return sorted(out, key=lambda r: (r["rcept_dt"], r["rcept_no"]))


def status_of(events: list[dict]) -> tuple[str, str | None]:
    """가장 최근 개시 계열 공시의 종류. 종결 공시가 있어도 '없음'으로 되돌리지 않고 문구만 남긴다."""
    opened = [e for e in events if e["kind"] != "종결"]
    closed = [e for e in events if e["kind"] == "종결"]
    note = f"종결 공시 있음({to_date(closed[-1]['rcept_dt'])})" if closed else None
    return (opened[-1]["kind"] if opened else "없음"), note


@guarded
def collect_restructuring(state) -> dict:
    """as_of 이전 24개월 공시 목록에서 회생·워크아웃·파산 관련 공시를 찾는다."""
    req, company = state["request"], state["company"]
    filings = dart.get_client().list_filings(req.as_of, req.as_of - relativedelta(months=RESTRUCTURING_MONTHS), req.as_of, corp_code=company["corp_code"])
    events, evidence = [], []
    for e in match_events(filings):
        eid = ev.dart_section(e["rcept_no"], "list")
        evidence.append(Evidence(evidence_id=eid, source_grade="A", source_type="dart_list", corp_code=company["corp_code"], published_at=to_date(e["rcept_dt"]), title=e["report_nm"], url=VIEWER_URL.format(rcept_no=e["rcept_no"])))
        events.append(RestructuringEvent(rcept_no=e["rcept_no"], rcept_dt=to_date(e["rcept_dt"]), report_nm=e["report_nm"], kind=e["kind"], evidence_ids=[eid]))
    return {"restructuring": events, "evidence": evidence}
