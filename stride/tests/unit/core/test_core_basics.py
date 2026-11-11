from datetime import date

from core import catalog, db, evidence
import pytest

from core.asof import CoverageError, FilingList, filter_asof, resolve_version, to_date
from core.schemas import Evidence, Finding
from tests.unit.test_contract import sample_result


def test_filter_asof_drops_future_and_unparseable():
    rows = [{"d": "20250630"}, {"d": "2025-07-01"}, {"d": "bad"}, {"d": date(2025, 1, 1)}]
    assert filter_asof(rows, "d", date(2025, 6, 30)) == [{"d": "20250630"}, {"d": date(2025, 1, 1)}]


def _filings():
    return FilingList([{"rcept_no": "20250617000513", "rcept_dt": "20250618"}],   # rcept_no 앞 8자리 ≠ rcept_dt
                      date(2025, 1, 1), date(2025, 9, 15))


def test_resolve_version():
    assert resolve_version("20250617000513", _filings(), "20250618") == "ok"
    assert resolve_version("20250922000245", _filings(), "20250618") == "unknown"     # as_of 이후 정정본


def test_resolve_version_raises_when_list_period_misses_target():
    with pytest.raises(CoverageError):
        resolve_version("20241028000347", _filings(), "20241028")          # 목록 기간(2025-01-01~) 이전 보고서
    with pytest.raises(CoverageError):
        resolve_version("20250930000001", _filings(), "20250930")          # 목록 기간 끝(as_of) 이후


def test_resolve_version_requires_filing_list_with_period():
    with pytest.raises(CoverageError):
        resolve_version("20250617000513", [{"rcept_no": "20250617000513", "rcept_dt": "20250618"}], "20250618")


def test_to_date_formats():
    assert to_date("2025.03.31") == date(2025, 3, 31)
    assert to_date("20251399") is None


def test_validate_evidence_drops_future_and_dangling():
    r = sample_result()
    future = Evidence(evidence_id="DART:20250701000001:x", source_grade="A", source_type="dart",
                      corp_code=None, published_at=date(2025, 7, 1), title="t")
    f = Finding(finding_id="f1", kind="fact", text="t", evidence_ids=["DART:20250701000001:x"])
    out = evidence.validate_evidence(r.model_copy(update={"evidence": r.evidence + [future], "findings": [f]}))
    assert out.findings == [] and len(out.evidence) == 1 and out.metrics
    assert any("as_of 이후" in e for e in out.errors)


def test_validate_evidence_calc_recompute():
    r = sample_result()
    ok = Evidence(evidence_id="CALC:r1:x", source_grade="D", source_type="calc", corp_code=None,
                  published_at=r.as_of, title="c", meta={"impl": "operator.add", "args": {}, "value": 0})
    # operator.add는 키워드 인자를 받지 않으므로 재계산 실패 → 제거
    out = evidence.validate_evidence(r.model_copy(update={"evidence": r.evidence + [ok]}))
    assert "CALC:r1:x" not in {e.evidence_id for e in out.evidence}
    good = ok.model_copy(update={"meta": {"impl": "math.hypot", "args": {}, "value": 0.0}})
    out = evidence.validate_evidence(r.model_copy(update={"evidence": r.evidence + [good]}))
    assert "CALC:r1:x" in {e.evidence_id for e in out.evidence}


def test_news_id_format():
    assert evidence.news("https://a.b/c").startswith("NEWS:") and len(evidence.news("x")) == 17


def test_catalog_loads_all_entries():
    assert len(catalog.load()) == 45


def test_db_creates_common_tables():
    con = db.connect(":memory:")
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"runs", "evidence", "alerts", "processed_filings", "decisions"} <= names
