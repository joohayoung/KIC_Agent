"""OpenDART 공통 클라이언트 (해외진출 개발문서 8.1, 필드 확정 기록: core/docs/api_fields.md).

- status "000" 정상, "013" 데이터 없음 → 빈 결과, "020" 일일 한도 초과 → DartQuotaError(같은 날 재시도 안 함), 그 외 DartError
- 호출 간 0.2초, 429/5xx·연결 오류는 지수 백오프 3회
- 원본 응답은 STRIDE_CACHE_DIR/dart/{sha1(요청)} 에 캐시 (키는 캐시 키에 넣지 않음)
- 시점 판정은 list.json rcept_dt만 쓴다 (list_filings가 as_of로 거름)
- DS005·재무·감사의견은 정정 후 최신본만 준다 → as_of 이하 공시 목록(filings_asof)으로 행마다 ok/unknown 판정,
  unknown 행은 값을 지운다 (개발문서 6.1, api_fields.md 1.2)
- 예외 메시지에 API 키(URL 쿼리)를 남기지 않는다
"""
import hashlib
import io
import json
import time
import zipfile
from datetime import date
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from core.asof import UNKNOWN_NOTE, FilingList, ensure_covers, filter_asof, resolve_version, to_date
from core.config import settings

BASE = "https://opendart.fss.or.kr/api/"
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

# 8.1.4 DS005 주요사항보고서 (api_fields.md 4장에서 실제 응답으로 확인)
MAJOR_EVENT_APIS = {
    "acquisition_stock": "otcprStkInvscrInhDecsn",   # 타법인 주식 및 출자증권 양수결정
    "acquisition_asset": "tgastInhDecsn",            # 유형자산 양수 결정
    "business_transfer": "bsnInhDecsn",              # 영업양수 결정
    "rights_issue": "piicDecsn",                     # 유상증자 결정
    "cb": "cvbdIsDecsn",                             # 전환사채권 발행결정
    "bw": "bdwtIsDecsn",                             # 신주인수권부사채권 발행결정
}
REPRT_CODES = {"1Q": "11013", "H1": "11012", "3Q": "11014", "FY": "11011"}
CORPCODE_TTL_SEC = 7 * 24 * 3600
MIN_INTERVAL_SEC = 0.2


class DartError(Exception):
    pass


class DartQuotaError(DartError):
    """OpenDART status 020 (일일 요청 한도 초과, 개인 키 20,000회/일). 같은 날 다시 부르지 않는다.
    노드 가드·조사 도구가 삼키지 않고 위로 올린다: 조사 루프·배치 중단, 기업은 분석 대기, 감시 커서는 그 공시 앞."""


QUOTA_DAY: dict = {"day": None}      # 020을 받은 날. 같은 날은 캐시에 없는 호출을 보내지 않는다


def _quota(endpoint: str, message: str = "") -> "DartQuotaError":
    QUOTA_DAY["day"] = date.today()
    return DartQuotaError(f"{endpoint}: status 020 일일 요청 한도 초과 {message}".strip())


@lru_cache(maxsize=1)
def get_client() -> "DartClient":
    """노드가 쓰는 공용 클라이언트. 테스트는 이 함수를 바꿔 끼운다."""
    return DartClient()


class _Retryable(Exception):
    pass


def _ymd(d: date | str) -> str:
    return d.strftime("%Y%m%d") if isinstance(d, date) else d


class DartClient:
    def __init__(self, api_key: str | None = None, cache_dir: Path | None = None, use_cache: bool = True):
        self._key = api_key or settings.dart_api_key
        if not self._key:
            raise DartError("DART_API_KEY가 .env에 없음")
        self.cache_dir = (cache_dir or settings.path(settings.stride_cache_dir)) / "dart"
        self.use_cache = use_cache
        self._last = 0.0
        self._http = httpx.Client(timeout=60)

    # ---- 저수준 ----
    def _cache_path(self, endpoint: str, params: dict) -> Path:
        key = endpoint + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))
        return self.cache_dir / hashlib.sha1(key.encode()).hexdigest()

    @retry(retry=retry_if_exception(lambda e: isinstance(e, _Retryable)),
           wait=wait_exponential(multiplier=1, max=8), stop=stop_after_attempt(3), reraise=True)
    def _fetch(self, endpoint: str, params: dict) -> bytes:
        wait = MIN_INTERVAL_SEC - (time.monotonic() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        try:
            r = self._http.get(BASE + endpoint, params={"crtfc_key": self._key, **params})
        except httpx.TransportError as e:
            raise _Retryable(f"{endpoint}: 연결 오류 {type(e).__name__}") from None
        if r.status_code == 429 or r.status_code >= 500:
            raise _Retryable(f"{endpoint}: HTTP {r.status_code}")
        if r.status_code != 200:
            raise DartError(f"{endpoint}: HTTP {r.status_code}")
        return r.content

    def raw(self, endpoint: str, **params) -> bytes:
        params = {k: v for k, v in params.items() if v is not None}
        path = self._cache_path(endpoint, params)
        if self.use_cache and path.exists():
            return path.read_bytes()
        if QUOTA_DAY["day"] == date.today():
            raise DartQuotaError(f"{endpoint}: 오늘 일일 요청 한도 초과를 이미 받음 (재시도 안 함)")
        try:
            body = self._fetch(endpoint, params)
        except _Retryable as e:
            raise DartError(str(e)) from None
        if self.use_cache:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
        return body

    def get_json(self, endpoint: str, **params) -> dict:
        data = json.loads(self.raw(endpoint, **params))
        st = data.get("status")
        if st == "013":
            return {"status": "013", "list": []}
        if st == "020":
            self._cache_path(endpoint, {k: v for k, v in params.items() if v is not None}).unlink(missing_ok=True)
            raise _quota(endpoint, data.get("message", ""))
        if st != "000":
            self._cache_path(endpoint, {k: v for k, v in params.items() if v is not None}).unlink(missing_ok=True)
            raise DartError(f"{endpoint}: status {st} {data.get('message', '')}")
        return data

    def _zip(self, endpoint: str, **params) -> dict[str, bytes]:
        body = self.raw(endpoint, **params)
        if not body.startswith(b"PK"):
            self._cache_path(endpoint, params).unlink(missing_ok=True)
            if b"020" in body[:300] and (b"status" in body[:300]):      # 원문 ZIP 대신 오류 응답(JSON·XML)
                raise _quota(endpoint)
            raise DartError(f"{endpoint}: ZIP 아님 {body[:200].decode('utf-8', 'replace')}")
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            return {n: z.read(n) for n in z.namelist()}

    # ---- 8.1.1 고유번호 ----
    def corp_codes(self) -> list[dict]:
        """CORPCODE.xml 전체. 로컬 캐시 7일마다 갱신."""
        path = self._cache_path("corpCode.xml", {})
        if path.exists() and time.time() - path.stat().st_mtime > CORPCODE_TTL_SEC:
            path.unlink()
        files = self._zip("corpCode.xml")
        root = ElementTree.fromstring(next(iter(files.values())))
        return [{c.tag: (c.text or "").strip() for c in item} for item in root.iter("list")]

    # ---- 8.1.2 공시검색 ----
    def list_filings(self, as_of: date, bgn_de: date | str, end_de: date | str, corp_code: str | None = None,
                     pblntf_ty: str | None = None, pblntf_detail_ty: str | None = None) -> FilingList:
        """total_page까지 순회. end_de는 as_of를 넘지 않게 자르고, 반환 전 rcept_dt로 한 번 더 거른다.
        반환 FilingList는 조회 기간(bgn_de~end_de)을 함께 가진다 (정정 판정용, 개발문서 6.1)."""
        end = min(_ymd(end_de), _ymd(as_of))
        rows, page = [], 1
        while True:
            d = self.get_json("list.json", corp_code=corp_code, bgn_de=_ymd(bgn_de), end_de=end,
                              pblntf_ty=pblntf_ty, pblntf_detail_ty=pblntf_detail_ty,
                              page_no=page, page_count=100)
            rows += d.get("list", [])
            if page >= int(d.get("total_page", 1) or 1):
                break
            page += 1
        return FilingList(filter_asof(rows, "rcept_dt", as_of), to_date(_ymd(bgn_de)), to_date(end))

    # ---- 8.1.6 공시 원문 ----
    def document(self, rcept_no: str) -> dict[str, bytes]:
        """document.xml ZIP → {파일명: XML bytes}."""
        return self._zip("document.xml", rcept_no=rcept_no)

    # ---- 정정 후 최신본만 주는 API: DS005·재무·감사의견 (개발문서 6.1) ----
    @staticmethod
    def _versioned(rows: list[dict], filings_asof: FilingList, target_rcept_dt) -> list[dict]:
        """각 행에 _version(ok/unknown)을 붙인다. unknown 행은 값을 지우고 rcept_no와 사유만 남긴다(누수 방지).
        목록 기간이 target_rcept_dt를 포함하지 않으면 CoverageError (unknown으로 덮지 않음)."""
        out = []
        for r in rows:
            if resolve_version(r.get("rcept_no", ""), filings_asof, target_rcept_dt) == "ok":
                out.append({**r, "_version": "ok"})
            else:
                out.append({"rcept_no": r.get("rcept_no"), "_version": "unknown", "_note": UNKNOWN_NOTE})
        return out

    # ---- 8.1.4 DS005 ----
    def major_event(self, kind: str, corp_code: str, bgn_de: date | str, end_de: date | str,
                    filings_asof: FilingList) -> list[dict]:
        """kind는 MAJOR_EVENT_APIS 키. 기간 필터는 원공시 접수일 기준, 반환 값은 최신 정정본.
        조회 기간 bgn_de~end_de 전체가 filings_asof 기간 안이어야 한다 (아니면 CoverageError, 호출 전 검사)."""
        ensure_covers(filings_asof, bgn_de)
        ensure_covers(filings_asof, end_de)
        d = self.get_json(MAJOR_EVENT_APIS[kind] + ".json", corp_code=corp_code,
                          bgn_de=_ymd(bgn_de), end_de=_ymd(end_de))
        return self._versioned(d.get("list", []), filings_asof, bgn_de)

    # ---- 8.1.5 재무제표 ----
    def financials(self, corp_code: str, bsns_year: int | str, reprt_code: str, fs_div: str,
                   filings_asof: FilingList, report_rcept_dt) -> list[dict]:
        """fnlttSinglAcntAll. report_rcept_dt = 대상 정기보고서(원본)의 list.json 접수일.
        목록 기간 밖이면 CoverageError(호출 전 검사). 보고서가 as_of 이후 정정본이면 모든 행이 unknown."""
        ensure_covers(filings_asof, report_rcept_dt)
        d = self.get_json("fnlttSinglAcntAll.json", corp_code=corp_code, bsns_year=str(bsns_year),
                          reprt_code=reprt_code, fs_div=fs_div)
        return self._versioned(d.get("list", []), filings_asof, report_rcept_dt)

    # ---- 재무 건전성 9.2 감사의견 ----
    def audit_opinion(self, corp_code: str, bsns_year: int | str, reprt_code: str,
                      filings_asof: FilingList, report_rcept_dt) -> list[dict]:
        ensure_covers(filings_asof, report_rcept_dt)
        d = self.get_json("accnutAdtorNmNdAdtOpinion.json", corp_code=corp_code,
                          bsns_year=str(bsns_year), reprt_code=reprt_code)
        return self._versioned(d.get("list", []), filings_asof, report_rcept_dt)