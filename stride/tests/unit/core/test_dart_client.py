import json
from datetime import date

import httpx
import pytest

from core.asof import CoverageError, FilingList
from core.clients.dart import DartClient, DartError


def client(tmp_path, handler) -> DartClient:
    c = DartClient(api_key="TESTKEY", cache_dir=tmp_path)
    c._http = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_list_filings_pages_and_drops_future_rows(tmp_path):
    pages = {
        "1": [{"rcept_no": "20250630000001", "rcept_dt": "20250630"}, {"rcept_no": "20250701000001", "rcept_dt": "20250701"}],
        "2": [{"rcept_no": "20250617000513", "rcept_dt": "20250618"}],
    }

    def handler(req):
        p = req.url.params
        assert p["end_de"] == "20250630"          # end_de가 as_of를 넘지 않게 잘림
        return httpx.Response(200, json={"status": "000", "total_page": 2, "list": pages[p["page_no"]]})

    rows = client(tmp_path, handler).list_filings(date(2025, 6, 30), "20250101", "20251231", corp_code="00000000")
    assert [r["rcept_no"] for r in rows] == ["20250630000001", "20250617000513"]


def test_status_013_is_empty_and_error_hides_key(tmp_path):
    c = client(tmp_path, lambda req: httpx.Response(200, json={"status": "013", "message": "조회된 데이타가 없습니다."}))
    assert c.list_filings(date(2025, 6, 30), "20250101", "20250630") == []
    c = client(tmp_path / "x", lambda req: httpx.Response(200, json={"status": "020", "message": "요청 제한"}))
    with pytest.raises(DartError) as e:
        c.get_json("list.json", bgn_de="20250101")
    assert "TESTKEY" not in str(e.value)


def test_cache_reused_and_key_not_in_cache_name(tmp_path):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"status": "000", "list": []})

    c = client(tmp_path, handler)
    c.get_json("piicDecsn.json", corp_code="1")
    c.get_json("piicDecsn.json", corp_code="1")
    assert len(calls) == 1
    assert all("TESTKEY" not in p.read_text(encoding="utf-8") for p in (tmp_path / "dart").iterdir())


def test_major_event_marks_post_asof_correction_unknown_and_strips_values(tmp_path):
    body = {"status": "000", "list": [{"rcept_no": "20250922000245", "fdpp_ocsa": "1,000"},
                                      {"rcept_no": "20250630000001", "fdpp_ocsa": "2,000"}]}
    filings_asof = FilingList([{"rcept_no": "20250910000580", "rcept_dt": "20250910"},     # 원공시만 as_of 이하
                               {"rcept_no": "20250630000001", "rcept_dt": "20250630"}], date(2025, 1, 1), date(2025, 9, 15))
    c = client(tmp_path, lambda req: httpx.Response(200, json=body))
    rows = c.major_event("rights_issue", "1", "20250101", "20250915", filings_asof)
    assert rows[0] == {"rcept_no": "20250922000245", "_version": "unknown", "_note": "정정 전 원본 값 확인 불가"}
    assert rows[1]["_version"] == "ok" and rows[1]["fdpp_ocsa"] == "2,000"


def test_list_filings_returns_period_and_financials_refuse_uncovered_report(tmp_path):
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"status": "000", "total_page": 1, "list": []})

    c = client(tmp_path, handler)
    fl = c.list_filings(date(2025, 6, 30), "20250101", "20251231", corp_code="1")
    assert (fl.bgn_de, fl.end_de) == (date(2025, 1, 1), date(2025, 6, 30))
    n = len(calls)
    with pytest.raises(CoverageError):
        c.financials("1", 2024, "11014", "CFS", fl, "20241114")             # 목록 기간 밖 보고서
    with pytest.raises(CoverageError):
        c.audit_opinion("1", 2024, "11011", fl, "20240320")
    with pytest.raises(CoverageError):
        c.major_event("cb", "1", "20240101", "20250630", fl)                 # 조회 시작일이 목록 기간 밖
    with pytest.raises(CoverageError):
        c.financials("1", 2025, "11011", "CFS", [], "20250320")              # 기간 정보 없는 목록
    assert len(calls) == n                                                  # 검사 실패 시 API를 부르지 않음


@pytest.mark.live
def test_live_list_json_fields():
    rows = DartClient(use_cache=False).list_filings(date(2026, 3, 31), "20260325", "20260331", pblntf_ty="B")
    assert rows and {"rcept_no", "rcept_dt", "report_nm", "corp_code", "corp_cls", "rm"} <= set(rows[0])
    assert json.dumps(rows[0], ensure_ascii=False)


def test_status_020_quota_no_retry_same_day(tmp_path):
    """020은 DartQuotaError, 캐시하지 않고, 같은 날 캐시에 없는 다음 호출은 HTTP를 보내지 않는다. 429·5xx는 3회 재시도."""
    from core.clients.dart import DartQuotaError
    calls = []

    def handler(req):
        calls.append(req.url.path)
        return httpx.Response(200, json={"status": "020", "message": "요청 제한"})
    c = client(tmp_path, handler)
    with pytest.raises(DartQuotaError):
        c.get_json("list.json", bgn_de="20250101")
    with pytest.raises(DartQuotaError):
        c.get_json("list.json", bgn_de="20250102")
    assert len(calls) == 1      # 두 번째는 HTTP 없이 바로 중단
    assert not any((tmp_path / "dart").glob("*")) if (tmp_path / "dart").exists() else True      # 020 응답은 캐시하지 않는다
    z = client(tmp_path / "z", lambda req: httpx.Response(200, content=b'{"status":"020","message":"x"}'))
    import core.clients.dart as d
    d.QUOTA_DAY["day"] = None
    with pytest.raises(DartQuotaError):
        z.document("20250101000001")


def test_429_5xx_retried_three_times(tmp_path, monkeypatch):
    import tenacity
    monkeypatch.setattr(tenacity.nap, "sleep", lambda s: None)
    calls = []
    c = client(tmp_path, lambda req: calls.append(1) or httpx.Response(503))
    with pytest.raises(DartError):
        c.get_json("list.json", bgn_de="20250101")
    assert len(calls) == 3
