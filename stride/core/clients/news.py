"""뉴스 출처 (해외진출 개발문서 8.2). 키는 .env에서만 읽고 출력하지 않는다."""
import html
import re
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Protocol

import httpx

from core.config import ROOT, settings

MAX_PAGES = 3       # 보정 전: 검색어당 최신 300건. 부족하면 측정으로 늘린다
PAGE_SIZE = 100


class NewsSource(Protocol):
    def search(self, query: str, start: date, end: date) -> list[dict]: ...


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


def normalize_item(it: dict) -> dict | None:
    try:
        pub = parsedate_to_datetime(it["pubDate"]).date()
    except (KeyError, TypeError, ValueError):
        return None
    return {"title": _clean(it.get("title")), "url": it.get("originallink") or it.get("link"), "pubDate": pub, "description": _clean(it.get("description"))}


class NaverNewsSource:
    """기간 지정이 안 되므로 최신순으로 받다가 start 이전이 나오면 멈춘다."""

    def __init__(self, client: httpx.Client | None = None):
        self._http = client or httpx.Client(timeout=20)
        if settings.naver_news_provider == "developers":
            self._url, self._headers = "https://openapi.naver.com/v1/search/news.json", {"X-Naver-Client-Id": settings.naver_client_id, "X-Naver-Client-Secret": settings.naver_client_secret}
        else:
            self._url, self._headers = settings.naver_news_url, {"X-NCP-APIGW-API-KEY-ID": settings.naver_client_id, "X-NCP-APIGW-API-KEY": settings.naver_client_secret}

    def search(self, query: str, start: date, end: date) -> list[dict]:
        out = []
        for page in range(MAX_PAGES):
            r = self._http.get(self._url, params={"query": query, "display": PAGE_SIZE, "start": page * PAGE_SIZE + 1, "sort": "date"}, headers=self._headers)
            r.raise_for_status()
            items = [x for x in (normalize_item(i) for i in r.json().get("items", [])) if x]
            out += [x for x in items if start <= x["pubDate"] <= end]
            if len(items) < PAGE_SIZE or any(x["pubDate"] < start for x in items):
                break
        return out


class FileNewsSource:
    """BIG KINDS 내보내기 파일 (과거 시점). 컬럼 매핑은 첫 파일을 받아 확정한다 (개발문서 8.2 ※확인)."""

    def __init__(self, corp_code: str):
        self.dir = ROOT / "data/news" / corp_code

    def search(self, query: str, start: date, end: date) -> list[dict]:
        if list(Path(self.dir).glob("*.xlsx")):
            raise NotImplementedError("BIG KINDS 파일 컬럼 매핑 미확인 (개발문서 8.2 ※확인)")
        return []
