"""화면 시험 (화면_데이터_연결명세 5장): fixture DB로 queries 함수가 빈 값 없이 반환하는지, 3페이지가 예외 없이 그려지는지. claude·DART를 부르지 않는다."""
import json
from datetime import date
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from orchestrator import store
from tests.unit.orchestrator.test_orchestrator import AS, fin, ovs, ver
from orchestrator import common
from orchestrator.rules import apply_rules
from orchestrator.schemas import FinalReport, FeedItem
from ui import format as f
from ui import queries

UI = Path(__file__).resolve().parents[2] / "ui"
CC = "00000001"


def build_fixture(path: Path) -> None:
    """기본 탐색 실행 1건(matched 1, pending 1, excluded 1), 관심 기업 1, 검토서 1, 변경 내역 1, 신호 1."""
    con = store.connect(str(path))
    info = {"corp_code": CC, "corp_name": "회사00000001", "market": "KOSDAQ", "induty_code": "C29", "stock_code": "000001", "updated_at": "x"}
    con.execute("INSERT OR REPLACE INTO orc_companies VALUES (?,?,?,?,?,?)", tuple(info.values()))
    o, fn = ovs(CC), fin(CC)
    o = o.model_copy(update={"extra": {**o.extra, "signals": [{"signal_id": "s1", "signal_type": "S4_confirmed", "event_date": "2026-09-01", "summary": "취득결정", "stage": 4, "project_key": "p", "evidence_ids": ["DART:20260901000001:정형"]}]}})
    store.save_result(con, o, ver())
    store.save_result(con, fn, ver())
    rules = apply_rules(fn, ver(), "KOSDAQ", AS)
    row = common.board_row(o, fn, info, rules, ver(), matched_search_ids=[], is_watched=True, change_badges=["new_match"])
    con.execute("INSERT INTO orc_search_runs VALUES ('default','r1',?,?,?,?,?)", (AS.isoformat(), json.dumps([{"step": "universe", "count": 2600}, {"step": "final", "count": 1}]), "요약 문장이다 [1].", "[]", store.now()))
    con.execute("INSERT INTO orc_search_matches VALUES ('default',?,'r1',?,'matched',NULL,NULL,NULL,?,'[]')", (CC, AS.isoformat(), row.model_dump_json()))
    con.execute("INSERT INTO orc_search_matches VALUES ('default','00000002','r1',?,'pending',NULL,NULL,NULL,?,'[]')", (AS.isoformat(), json.dumps({"corp_code": "00000002", "corp_name": "대기회사", "latest_filing_date": "20261001"})))
    con.execute("INSERT INTO orc_search_matches VALUES ('default','00000003','r1',?,'excluded','apply_criteria','자금 공백 비율','-0.1',?,?)", (AS.isoformat(), json.dumps({"corp_name": "제외회사"}), json.dumps(["DART:20261001000003:정형"])))
    con.execute("INSERT INTO orc_watchlist VALUES (?,?,?,?)", (CC, info["corp_name"], store.now(), "test"))
    rep = FinalReport(report_id="rep_1", corp_code=CC, as_of=AS, is_partial=False, sections={k: f"{k} 문장 [1]." for k in ("summary", "project", "funding_gap", "financial", "rules", "verification", "opinion")} | {"appendix": "[1] 근거"}, rule_results=rules, due_diligence=["실사 항목"], verification_status="passed", evidence=o.evidence)
    con.execute("INSERT INTO orc_reports VALUES (?,?,?,?,?,?,?)", ("rep_1", CC, AS.isoformat(), "r1", rep.model_dump_json(), "passed", store.now()))
    store.add_feed(con, FeedItem(item_id="w1", kind="watch_change", search_id=None, corp_code=CC, alert_type="stage_up", before=None, after=None, reason="단계 2 → 4", event_date=AS, evidence_ids=["DART:20261101000001:정형"]))
    store.add_feed(con, FeedItem(item_id="n1", kind="new_match", search_id="default", corp_code=CC, alert_type="new_match", before="미충족", after="충족", reason="조건 충족", event_date=date.today(), evidence_ids=["DART:x:정형"]))
    con.execute("INSERT OR REPLACE INTO orc_monitor_cursor VALUES (1,'20261105000001','20261105',?)", (store.now(),))
    store.save_trace(con, "fill_1", "r1", CC, AS.isoformat(), "fill", "fin.short_term_financial_assets", [{"step": 1, "tool": "read_note_table", "args": {"rcept_no": "20260814000001", "kind": "단기금융상품"}, "reason": "주석에서 내역 확인", "result": "표", "outcome": "call", "seconds": 1.0, "tokens": 10},
                                                                                       {"step": 2, "tool": "gate", "reason": "단기금융상품: 원문 일치", "result": "채택 500,000원", "outcome": "adopted", "source": {"rcept_no": "20260814000001"}}])
    store.save_trace(con, "inv_1", "r1", CC, AS.isoformat(), "investigate", "20261101000001 유상증자결정", [{"step": 1, "tool": "find_related_filings", "args": {"rcept_no": "20261101000001"}, "reason": "발행결과 확인", "result": "[]", "outcome": "call"}])
    con.execute("INSERT INTO orc_investigations VALUES ('inv_1','inv_1','r1',?,'20261101000001',?,'immediate','요약 문장 [1].','{}','passed','[]',?)", (CC, AS.isoformat(), store.now()))
    con.executescript("CREATE TABLE IF NOT EXISTS overseas_funding_signals (signal_id TEXT, run_id TEXT, as_of TEXT, corp_code TEXT, signal_type TEXT, event_date TEXT, is_overseas INTEGER, target_country TEXT, method TEXT, purpose_category TEXT, amount_krw INTEGER, amount_original TEXT, stage INTEGER, is_new INTEGER, project_key TEXT, summary TEXT, evidence_ids_json TEXT, PRIMARY KEY (signal_id, run_id))")
    con.execute("INSERT INTO overseas_funding_signals VALUES ('s1','r','2026-11-05',?, 'S4_confirmed','2026-10-20',1,'미국','new_plant','growth_investment',1,NULL,4,1,'p','x','[]')", (CC,))
    con.commit()
    con.close()


@pytest.fixture
def fixture_db(tmp_path, monkeypatch):
    path = tmp_path / "fixture.db"
    build_fixture(path)
    monkeypatch.setattr(queries, "DB_PATH", path)
    return path


def test_queries_return_values(fixture_db):
    assert queries.get_searches()[0]["search_id"] == "default"
    run = queries.latest_run("default")
    board = queries.get_board("default", run["run_id"])
    assert len(board["matched"]) == 1 and len(board["pending"]) == 1 and board["excluded"][0]["excluded_condition"] == "자금 공백 비율"
    r = board["matched"][0]
    for key in ("corp_name", "market", "project", "investment_amount", "funding_gap", "debt_ratio", "ttm_operating_cash_flow", "verification"):
        assert r[key] not in (None, "", {}), key
    wl = queries.get_watchlist_rows(AS.isoformat())
    assert wl[0]["row"]["project"]["stage"] == 4 and wl[0]["latest_change"]["alert_type"] == "stage_up"
    assert queries.tracked_searches()[0]["matched_count"] == 1 and queries.tracked_searches()[0]["feed"]
    assert queries.get_feed()[0]["reason"] == "단계 2 → 4"
    assert queries.get_weekly_signals(AS.isoformat())[0]["region"] == "미국"
    assert queries.get_report(CC, AS.isoformat())["report"]["verification_status"] == "passed"
    assert queries.unread_feed_count() == 2 and queries.last_update()["updated_at"]


def test_format_never_blank():
    assert f.value({"value": None, "data_status": "missing"}) == "산출 불가" and f.value({"value": None, "data_status": "unknown"}) == "확인 불가"
    assert f.value({"value": None, "data_status": "needs_due_diligence"}) == "실사 필요" and f.value(None) == "산출 불가"
    assert f.eok(141_012_345_678) == "1,410억" and f.pct(0.441) == "44.1%" and f.pct(142.0, ratio=False) == "142%"
    assert f.period_label("TTM 2026H1") == "TTM · 반기보고서 기준일 2026-06-30" and f.period_label("2025FY") == "연간 · 사업보고서 기준일 2025-12-31" and f.period_label("2026H1말") == "시점 · 반기보고서 기준일 2026-06-30"
    assert f.evidence_link("DART:20260917900571:정형") == "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260917900571"


@pytest.mark.parametrize("page", [None, "pages/1_기업_발굴.py", "pages/3_기업_상세.py"])
def test_pages_render(fixture_db, page):
    at = AppTest.from_file(str(UI / "app.py"), default_timeout=60)
    at.session_state["as_of"] = AS
    at.session_state["company"] = CC
    at.run()
    if page:
        at.switch_page(str(UI / page))
        at.run()
    assert not at.exception, [e.message for e in at.exception]
    text = " ".join(x.value for x in at.markdown) + " ".join(str(getattr(x, "value", "")) for x in at.metric)
    assert not any(w in text for w in ("추천", "유망", "점수", "순위"))
    if page in (None, "pages/3_기업_상세.py"):
        assert any("조사 과정" in x.label for x in at.expander), [x.label for x in at.expander]


@pytest.mark.parametrize("i", range(4))
def test_usage_chips_fill_query_box(fixture_db, i):
    """사용법 칩을 누르면 입력창에 예시 문장이 채워진다 (2026-11-10 화면에서 StreamlitWidgetAlreadyInstantiatedError)."""
    at = AppTest.from_file(str(UI / "app.py"), default_timeout=60)
    at.session_state["as_of"] = AS
    at.run()
    at.button(key=f"chip_{i}").click().run()
    assert not at.exception, [e.message for e in at.exception]
    assert at.session_state["query_text"] and "OO" not in at.session_state["query_text"]
