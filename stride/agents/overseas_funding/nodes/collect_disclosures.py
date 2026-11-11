from dateutil.relativedelta import relativedelta

from agents.overseas_funding.schemas import Filing
from agents.overseas_funding.text.dart_sections import extract_business_section, filter_overseas_paragraphs
from agents.overseas_funding.text.diff import mark_new_paragraphs
from core.asof import FilingList, to_date
from core.clients import dart
from core.clients.dart_docs import body_xml
from core.filings import classify_filing
from core.nodeguard import guarded
from core.clients.dart import DartQuotaError

PUBLICATION_TYPES = ("A", "B", "I", "C")    # 7.3: 정기, 주요사항, 거래소, 발행공시


def to_filing(r: dict) -> Filing:
    c = classify_filing(r["report_nm"])
    return Filing(rcept_no=r["rcept_no"], rcept_dt=to_date(r["rcept_dt"]), report_nm=r["report_nm"], kind=c["kind"], sub_kind=c["sub_kind"], is_correction=c["is_correction"], report_nm_norm=c["norm"], prefixes=c["prefixes"], suffixes=c["suffixes"], filer_scope=c["filer_scope"])


def pick_latest_previous(filings: list[Filing]) -> tuple[Filing | None, Filing | None]:
    """7.3: latest가 사업보고서면 직전 사업보고서, 분기·반기면 직전 정기보고서(종류 무관). 정정은 원 보고서와 같은 기간이라 정정본 최신을 쓴다."""
    latest_per_period: dict = {}
    for f in sorted((x for x in filings if x.kind == "periodic"), key=lambda x: (x.rcept_dt, x.rcept_no)):
        if f.report_nm_norm in ("사업보고서", "반기보고서", "분기보고서"):
            latest_per_period[(f.report_nm_norm, tuple(f.suffixes))] = f
    rows = sorted(latest_per_period.values(), key=lambda x: (x.rcept_dt, x.rcept_no), reverse=True)
    if not rows:
        return None, None
    latest = rows[0]
    rest = rows[1:]
    if latest.sub_kind == "annual":
        rest = [x for x in rest if x.sub_kind == "annual"]
    return latest, rest[0] if rest else None


def report_section(client, no: str):
    return extract_business_section(body_xml(client.document(no)).encode("utf-8"))


def periodic_sections(client, latest: Filing | None, previous: Filing | None) -> tuple[dict, list[str]]:
    """latest의 해외 키워드 문단과 신규 문단 ID. previous가 없으면 신규 판정 불가."""
    if latest is None:
        return {}, []
    paragraphs = report_section(client, latest.rcept_no)
    picked = filter_overseas_paragraphs(paragraphs)
    questions = []
    if previous is None:
        new_ids, status = None, "unknown"
        questions.append("직전 보고서 없음: 신규 문단 판정 불가")
    else:
        new_ids, status = sorted(mark_new_paragraphs(picked, report_section(client, previous.rcept_no))), "ok"
    return {latest.rcept_no: {"paragraphs": [p.__dict__ for p in picked], "new_paragraph_ids": new_ids, "status": status, "previous_rcept_no": previous.rcept_no if previous else None}}, questions


@guarded
def collect_disclosures(state) -> dict:
    """as_of 이전 lookback 기간의 공시 목록을 수집하고 종류별로 분류한다 (7.3). rcept_dt > as_of는 코드로 한 번 더 거른다."""
    req, company = state["request"], state["company"]
    client = dart.get_client()
    bgn = req.as_of - relativedelta(months=req.lookback_months)
    rows = {}
    for ty in PUBLICATION_TYPES:
        for r in client.list_filings(req.as_of, bgn, req.as_of, corp_code=company.corp_code, pblntf_ty=ty):
            rows[r["rcept_no"]] = r
    raw = FilingList(sorted(rows.values(), key=lambda r: (r["rcept_dt"], r["rcept_no"])), bgn, req.as_of)
    filings = [to_filing(r) for r in raw]
    errors, questions, sections = [], [], {}
    try:
        sections, questions = periodic_sections(client, *pick_latest_previous(filings))
    except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
        raise
    except Exception as e:      # 7.3: 원문 다운로드 실패 시 periodic_sections={}
        errors.append(f"collect_disclosures: 원문 {type(e).__name__}")
    return {"filings": filings, "raw_filings": raw, "periodic_sections": sections, "errors": errors, "open_questions": questions}
