"""해외진출 10단계 BatchGraph: 화면 거르기, 첫 실행 상한, 순위 없는 목록. claude를 호출하지 않는다."""
from datetime import date

from agents.overseas_funding import batch
from core.asof import FilingList
from core.schemas import Request
from tests.unit.overseas_funding.test_graph import ACQ

KR = ACQ.replace("테스트 LLC(USA)", "테스트(대한민국)")


class Market:
    def __init__(self, rows, docs):
        self.rows, self.docs = rows, docs

    def list_filings(self, as_of, bgn, end, corp_code=None, pblntf_ty=None):
        return FilingList([r for r in self.rows if r.get("ty", "I") == pblntf_ty], bgn, as_of)

    def document(self, no):
        return {"a": ("<DOCUMENT-NAME>x</DOCUMENT-NAME>" + self.docs.get(no, "")).encode()}


def row(no, cc, dt, nm, cls="K", ty="I"):
    return {"rcept_no": no, "corp_code": cc, "corp_name": f"회사{cc}", "rcept_dt": dt, "report_nm": nm, "corp_cls": cls, "ty": ty}


ROWS = [row("1", "A", "20240805", "타법인주식및출자증권취득결정"), row("2", "B", "20240806", "타법인주식및출자증권취득결정"), row("3", "C", "20240807", "신규시설투자등"),
        row("4", "D", "20240808", "유상증자결정", ty="B"), row("5", "E", "20240809", "타법인주식및출자증권취득결정", cls="E"), row("6", "F", "20240810", "[기재정정]타법인주식및출자증권취득결정")]
DOCS = {"1": ACQ.format(rel="-", amt="1", sch="2025-01-01"), "2": KR.format(rel="-", amt="1", sch="2025-01-01")}


def test_screen_universe():
    got = batch.screen_universe(date(2024, 8, 1), date(2024, 8, 31), date(2024, 8, 31), client=Market(ROWS, DOCS))
    assert [(x["corp_code"], x["strength"]) for x in got] == [("A", 2), ("C", 1)]      # 국내 취득·조달·비상장·정정 제외, 해외 국적 칸 우선


def test_screen_skips_closed_without_new_filing():
    m = Market(ROWS, DOCS)
    assert [x["corp_code"] for x in batch.screen_universe(date(2024, 8, 1), date(2024, 8, 31), date(2024, 8, 31), client=m, tracked={"A": ("신호 없음", "2024-08-20")})] == ["C"]
    assert "A" in [x["corp_code"] for x in batch.screen_universe(date(2024, 8, 1), date(2024, 8, 31), date(2024, 8, 31), client=m, tracked={"A": ("신호 없음", "2024-08-01")})]


def test_first_run_limit_and_table_without_rank(monkeypatch, tmp_path):
    cands = [{"corp_code": f"{i:08d}", "corp_name": f"회사{i}", "strength": 2, "latest": "20240801", "rcept_nos": []} for i in range(8)]
    monkeypatch.setattr(batch, "screen_universe", lambda *a, **k: cands)
    seen = []

    def fake(payload):
        seen.append(payload["request"].corp_code)
        return {"results": [{"result": None, "seconds": 0, "llm_calls": 0, "screen": payload["screen"], "error": "x"}]}
    monkeypatch.setattr(batch, "company_graph", fake)
    req = Request(request_id="b1", agent="overseas_funding", mode="batch", as_of=date(2024, 8, 31), period_start=date(2024, 8, 1), context={"db_path": str(tmp_path / "b.db")})
    out = batch.run_batch(req)
    assert len(seen) == 5 and len(out["pending"]) == 3      # 첫 실행 5곳
    assert "순위" not in out["table_markdown"] and out["table_markdown"].count("실행 실패") == 5
    seen.clear()
    batch.run_batch(req.model_copy(update={"request_id": "b2"}))
    assert len(seen) == 8      # 완료된 실행이 있으면 상한이 BATCH_MAX_COMPANIES
