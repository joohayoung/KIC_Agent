"""시점 필터 (공통 양식 6장). API 파라미터를 믿지 않고 반환 직전에 한 번 더 거른다.

DART 시점 판정은 list.json `rcept_dt`로만 한다. rcept_no 앞 8자리는 실제 접수일보다 하루 빠른 경우가 있다.
"""
from datetime import date, datetime
from typing import Literal

UNKNOWN_NOTE = "정정 전 원본 값 확인 불가"


def to_date(v) -> date | None:
    """date / datetime / 'YYYYMMDD' / 'YYYY-MM-DD' / 'YYYY.MM.DD' → date. 해석 불가면 None."""
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, str):
        s = v.strip().replace("-", "").replace(".", "")[:8]
        if len(s) == 8 and s.isdigit():
            try:
                return date(int(s[:4]), int(s[4:6]), int(s[6:]))
            except ValueError:
                return None
    return None


def filter_asof(rows: list, date_field: str, as_of: date) -> list:
    """date_field 값이 as_of 이하인 행만 남긴다. 날짜를 해석할 수 없는 행은 버린다(누수 방지 우선)."""
    out = []
    for r in rows:
        d = to_date(r.get(date_field) if isinstance(r, dict) else getattr(r, date_field, None))
        if d is not None and d <= as_of:
            out.append(r)
    return out


class CoverageError(ValueError):
    """정정 판정용 공시 목록의 기간이 대상 보고서 접수일을 포함하지 않음. unknown으로 덮지 않고 중단한다."""


class FilingList(list):
    """list.json 조회 결과 + 조회 기간(bgn_de~end_de). 정정 판정은 이 기간 안의 보고서에만 할 수 있다."""

    def __init__(self, rows, bgn_de: date, end_de: date):
        super().__init__(rows)
        self.bgn_de, self.end_de = bgn_de, end_de


def ensure_covers(filings: list, target_rcept_dt) -> None:
    d = to_date(target_rcept_dt)
    if not isinstance(filings, FilingList):
        raise CoverageError("조회 기간 정보가 없는 공시 목록 (list_filings 결과를 넘겨야 함)")
    if d is None or not (filings.bgn_de <= d <= filings.end_de):
        raise CoverageError(f"공시 목록 기간 {filings.bgn_de}~{filings.end_de}이 대상 보고서 접수일 {target_rcept_dt}을 포함하지 않음")


def resolve_version(rcept_no: str, filings_asof: list[dict], target_rcept_dt) -> Literal["ok", "unknown"]:
    """정정 후 최신본만 주는 API(DS005·재무·감사의견) 응답 행을 쓸 수 있는지 판정한다 (해외진출 개발문서 6.1).

    filings_asof: list_filings(as_of, ...) 결과 (rcept_dt <= as_of, 조회 기간 포함).
    target_rcept_dt: 판정 대상 원공시·보고서의 list.json 접수일. 목록 기간 밖이면 CoverageError.
    응답 rcept_no가 목록에 있으면 ok, 없으면(정정 접수가 as_of 이후) unknown.
    원공시와 1:1 대응이 안 되는 경우는 호출자가 unknown으로 둔다.
    """
    ensure_covers(filings_asof, target_rcept_dt)
    return "ok" if any(f.get("rcept_no") == rcept_no for f in filings_asof) else "unknown"
