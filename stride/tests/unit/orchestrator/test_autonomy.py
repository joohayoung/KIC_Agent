"""자율성 지시 (2026-11-10): 조사 도구 as_of 차단, 루프 예산, 채택 게이트, 빈 값 채우기 반영, 새 공시 조사. claude·DART를 부르지 않는다."""
from datetime import date

import pytest

from agents.common import gate, tools
from core import agent_loop, llm
from core.agent_loop import Finding, LoopSentence, LoopStep
from core.calc.fin_items import maturing_debt_1y
from orchestrator import fill, investigate, store
from tests.unit.orchestrator.test_orchestrator import AS, M, ovs, result

NO = "20260814000001"
XML = """<TITLE>2. 연결재무제표</TITLE><TITLE>2-1. 연결 재무상태표</TITLE><P>(단위 : 천원)</P>
<TABLE><TR><TD>과목</TD><TD>당기말</TD><TD>전기말</TD></TR><TR><TD>현금및현금성자산</TD><TD>1,234</TD><TD>999</TD></TR><TR><TD>단기금융상품</TD><TD>500</TD><TD>400</TD></TR></TABLE>
<TITLE>4. 재무제표</TITLE><TITLE>4-1. 재무상태표</TITLE><P>(단위 : 천원)</P>
<TABLE><TR><TD>과목</TD><TD>당기말</TD><TD>전기말</TD></TR><TR><TD>현금및현금성자산</TD><TD>700</TD><TD>600</TD></TR></TABLE>"""
FILES = {"main.xml": XML.encode("utf-8")}


@pytest.fixture(autouse=True)
def fake_dart(monkeypatch):
    monkeypatch.setattr(gate, "body_xml", lambda files: XML)
    monkeypatch.setattr(gate, "consolidated_audit_statements", lambda files: "")


# ---- 도구 ----
def test_tools_reject_after_as_of():
    assert "as_of 이후" in tools.run_tool("read_document_section", {"rcept_no": "20261201000001", "section": "x"}, AS)["error"]
    assert "없는 도구" in tools.run_tool("delete", {}, AS)["error"]
    assert "인자 오류" in tools.run_tool("read_note_table", {"wrong": 1}, AS)["error"]


def test_search_news_drops_after_as_of(monkeypatch):
    import core.clients.news as news
    monkeypatch.setattr(news.NaverNewsSource, "__init__", lambda self, client=None: None)
    monkeypatch.setattr(news.NaverNewsSource, "search", lambda self, q, s, e: [{"title": "a", "pubDate": date(2026, 11, 4), "url": "u1"}, {"title": "b", "pubDate": date(2026, 11, 9), "url": "u2"}])
    assert [x["url"] for x in tools.search_news(AS, "q", "2026-10-01", "2026-12-31")] == ["u1"]


# ---- 루프 예산 ----
FAKE = {"list_filings": (lambda as_of, **k: [{"rcept_no": "20261001000001", "rcept_dt": "20261001", "report_nm": "x"}], "언제 / 입력 / 출력"),
        "search_news": (lambda as_of, **k: (_ for _ in ()).throw(RuntimeError("네이버 429")), "언제 / 입력 / 출력"),
        "read_note_table": (lambda as_of, **k: (_ for _ in ()).throw(ValueError("표 없음")), "언제 / 입력 / 출력")}


def steps_llm(monkeypatch, seq):
    """LLM이 seq 순서대로 고른다. 소진되면 stop."""
    it = iter(seq)
    calls = []
    monkeypatch.setattr(llm, "call_llm", lambda *a, **k: calls.append(a[1]["tools"]) or next(it, LoopStep(action="stop", reason="끝")))
    return calls


def test_tools_have_when_input_output_and_no_xbrl():
    assert "read_xbrl" not in tools.TOOLS and len(tools.TOOLS) == 7
    assert all(d.startswith("언제: ") and " / 입력: " in d and " / 출력: " in d for _, d in tools.TOOLS.values())


def test_loop_budget_and_stop(monkeypatch):
    monkeypatch.setattr(tools, "TOOLS", FAKE)
    calls = steps_llm(monkeypatch, [LoopStep(action="call", tool="list_filings", args={"corp_code": str(i), "bgn": "2026-01-01"}, reason="r") for i in range(10)])
    out = agent_loop.run_loop("g", "c", "o", FAKE, as_of=AS, run_id="t")
    assert len(calls) == agent_loop.MAX_STEPS and out["final"] is None and out["steps"][-1]["outcome"] == "budget"
    calls = steps_llm(monkeypatch, [])
    out = agent_loop.run_loop("g", "c", "o", FAKE, as_of=AS, run_id="t")
    assert len(calls) == 1 and out["final"].action == "stop"


def test_loop_blocks_repeated_call(monkeypatch):
    """같은 도구·같은 인자는 다시 실행하지 않고 '이미 확인함'을 돌려준다. 스텝 수에는 들어간다."""
    ran = []
    fake = {**FAKE, "list_filings": (lambda as_of, **k: ran.append(k) or [{"rcept_no": "20261001000001"}], "d")}
    monkeypatch.setattr(tools, "TOOLS", fake)
    same = LoopStep(action="call", tool="list_filings", args={"corp_code": "c", "bgn": "2026-01-01"}, reason="r")
    steps_llm(monkeypatch, [same, LoopStep(action="call", tool="list_filings", args={"bgn": "2026-01-01", "corp_code": "c"}, reason="순서만 다름"), same])
    out = agent_loop.run_loop("g", "c", "o", fake, as_of=AS, run_id="t")
    assert len(ran) == 1 and out["repeats"] == 2 and [s["outcome"] for s in out["steps"]] == ["call", "repeat", "repeat", "stop"]
    assert out["steps"][1]["result"].startswith("이미 확인함: ") and out["tool_calls"] == {"list_filings": 1}


def test_news_failure_removes_tool_for_this_run(monkeypatch):
    monkeypatch.setattr(tools, "TOOLS", FAKE)
    calls = steps_llm(monkeypatch, [LoopStep(action="call", tool="search_news", args={"query": "q", "bgn": "2026-01-01"}, reason="맥락"),
                                    LoopStep(action="call", tool="search_news", args={"query": "q2", "bgn": "2026-01-01"}, reason="다시")])
    out = agent_loop.run_loop("g", "c", "o", FAKE, as_of=AS, run_id="t")
    assert out["steps"][0]["outcome"] == "news_unavailable" and out["steps"][0]["result"].startswith("뉴스 사용 불가, 공시 근거로 진행")
    assert "search_news" in calls[0] and "search_news" not in calls[1]      # 다음 선택부터 도구 목록에서 빠진다
    assert out["steps"][1]["outcome"] == "error" and "허용되지 않은 도구" in out["steps"][1]["result"]


def test_other_tool_error_returns_string(monkeypatch):
    monkeypatch.setattr(tools, "TOOLS", FAKE)
    steps_llm(monkeypatch, [LoopStep(action="call", tool="read_note_table", args={"rcept_no": NO, "kind": "x"}, reason="r")])
    out = agent_loop.run_loop("g", "c", "o", FAKE, as_of=AS, run_id="t")
    assert out["steps"][0]["outcome"] == "error" and "ValueError: 표 없음" in out["steps"][0]["result"]


def test_dart_quota_stops_loop(monkeypatch):
    """DART 020은 오류 문자열로 삼키지 않고 루프 밖으로 올린다."""
    from core.clients.dart import DartQuotaError

    def quota(as_of, **k):
        raise DartQuotaError("list.json: status 020")
    fake = {**FAKE, "list_filings": (quota, "d")}
    monkeypatch.setattr(tools, "TOOLS", fake)
    steps_llm(monkeypatch, [LoopStep(action="call", tool="list_filings", args={"corp_code": "c", "bgn": "2026-01-01"}, reason="r")])
    with pytest.raises(DartQuotaError):
        agent_loop.run_loop("g", "c", "o", fake, as_of=AS, run_id="t")


# ---- 채택 게이트 ----
def G(**k):
    f = {"rcept_no": NO, "table_hint": "연결재무상태표", "row_label": "현금및현금성자산", "claimed_raw": 1234} | k
    return gate.check(f, expected_rcept_nos=[NO], expected_scope="CFS", allowed_rows=("현금및현금성자산", "단기금융상품"), files=FILES)


def test_gate_adopts_code_read_value_in_won():
    g = G()
    assert g["adopted"] and g["value"] == 1_234_000      # 천원 표 → 원. 값은 코드가 읽은 것


@pytest.mark.parametrize("change,why", [({"claimed_raw": 1235}, "값 불일치"), ({"rcept_no": "20250814000001"}, "기간 불일치"), ({"row_label": "정기예금"}, "규칙 목록 밖"),
                                         ({"table_hint": "없는표"}, "다시 찾지 못함"), ({"claimed_raw": None}, "적지 않음")])
def test_gate_rejects(change, why):
    g = G(**change)
    assert not g["adopted"] and why in g["reason"], g


def test_gate_rejects_wrong_scope():
    g = gate.check({"rcept_no": NO, "table_hint": "재무상태표", "row_label": "현금및현금성자산", "claimed_raw": 700}, expected_rcept_nos=[NO], expected_scope="CFS", files=FILES)
    assert not g["adopted"] or g["value"] != 700_000      # 별도 표 값은 연결 기대에서 채택되지 않는다


def test_maturing_overrides_fill_blank_rows_only():
    bs = [{"account_id": "ifrs-full_CurrentLiabilities", "account_nm": "유동부채", "thstrm_amount": "9"}, {"account_id": "ifrs-full_ShorttermBorrowings", "account_nm": "단기차입금", "thstrm_amount": ""},
          {"account_id": "-표준계정코드 미사용-", "account_nm": "유동성 기타 차입금(사채 제외)", "thstrm_amount": "5"}, {"account_id": "ifrs-full_NoncurrentLiabilities", "account_nm": "비유동부채", "thstrm_amount": "1"}]
    assert maturing_debt_1y(bs[:2] + bs[3:], {"단기차입금": 70}) == (70, None)
    assert maturing_debt_1y(bs, {"단기차입금": 70, "유동성 기타 차입금(사채 제외)": 5})[0] is None      # 미분류는 덮어쓰지 않는다


# ---- 빈 값 채우기 ----
def liquidity_ovs():
    base = ovs("c")
    ms = [m for m in base.metrics] + [M("fin.cash_and_equivalents", 1_000, "2026H1말", eid=f"DART:{NO}:document"), M("fin.short_term_financial_assets", None, "2026H1말", "missing", eid=f"DART:{NO}:document"),
                                       M("fin.ttm_operating_cash_flow", 300, "TTM 2026H1", eid=f"DART:{NO}:document"), M("ovs.confirmed_overseas_funding", 0, "기준"), M("ovs.overseas_investment_within_24m", 10_000_000_000, "기준"),
                                       M("fin.maturing_debt_1y", 200, "2026H1말"), M("fin.dividends_paid_last_fy", 0, "직전 사업연도"), M("ovs.liquidity_uses", 10_000_000_200, "기준"),
                                       M("ovs.available_internal_funds", None, "기준", "missing"), M("ovs.liquidity_surplus", None, "기준", "missing"),
                                       M("ovs.liquidity_sources_to_uses", None, "기준", "missing").model_copy(update={"note": "원천 산출 불가(단기금융상품 — 단기금융상품 행 없음, 기타유동금융자산 행 있음)"})]
    r = result("overseas_funding", "c", ms, base.classifications, {**base.extra, "financial_snapshot": {"source_rcept_no": NO, "fs_div": "CFS", "base_period": "2026H1"}})
    return r.model_copy(update={"evidence": [e.model_copy(update={"published_at": date(2026, 8, 14)}) for e in r.evidence]})


def test_fill_adopts_gate_value_and_recomputes(monkeypatch, tmp_path):
    o = liquidity_ovs()
    targets, skipped = fill.collect_targets(o, None, AS)
    assert [t["key"] for t in targets] == ["fin.short_term_financial_assets"] and targets[0]["expected"] == [NO]
    monkeypatch.setattr(fill, "run_loop", lambda *a, **k: {"steps": [{"step": 1, "tool": "read_note_table", "args": {}, "reason": "r", "result": "x", "outcome": "call"}], "calls": 2, "tokens": 10, "seconds": 1.0, "seen": [],
                                                           "final": LoopStep(action="stop", reason="찾음", findings=[Finding(target="fin.short_term_financial_assets", rcept_no=NO, table_hint="연결재무상태표", row_label="단기금융상품", claimed_raw=500)])})
    monkeypatch.setattr(gate, "read_row", lambda no, hint, row, files=None: _read(no, hint, row))
    con = store.connect(str(tmp_path / "f.db"))
    o2, _, d, s = fill.fill_missing(con, "run", o, None, AS)
    m = {x.metric_id: x for x in o2.metrics}
    assert d.action == "agent_search" and len(s["adopted"]) == 1 and s["applied"] == ["fin.short_term_financial_assets"]
    assert m["fin.short_term_financial_assets"].value == 500_000 and "에이전트 탐색으로 확보" in m["fin.short_term_financial_assets"].note
    assert m["ovs.available_internal_funds"].value == 1_000 + 500_000 + 300 + 0
    assert m["ovs.liquidity_sources_to_uses"].value == pytest.approx(501_300 / 10_000_000_200)
    assert not [e for e in o2.errors if "validate_evidence" in e], o2.errors      # 새 근거 형식·재계산 통과
    rows = store.traces(con, "c")
    assert [r["outcome"] for r in rows] == ["call", "adopted"] and rows[-1]["purpose"] == "fill"


_orig_read_row = gate.read_row


def _read(no, hint, row):
    return _orig_read_row(no, hint, row, files=FILES)


def test_fill_rejects_mismatch_keeps_missing(monkeypatch, tmp_path):
    o = liquidity_ovs()
    monkeypatch.setattr(fill, "run_loop", lambda *a, **k: {"steps": [], "calls": 1, "tokens": 1, "seconds": 0.1, "seen": [],
                                                           "final": LoopStep(action="stop", reason="r", findings=[Finding(target="fin.short_term_financial_assets", rcept_no=NO, table_hint="연결재무상태표", row_label="단기금융상품", claimed_raw=501)])})
    monkeypatch.setattr(gate, "read_row", lambda no, hint, row, files=None: _read(no, hint, row))
    con = store.connect(str(tmp_path / "f.db"))
    o2, _, d, s = fill.fill_missing(con, "run", o, None, AS)
    assert s["rejected"] and not s["adopted"] and next(m for m in o2.metrics if m.metric_id == "fin.short_term_financial_assets").value is None


def test_fill_skips_unfillable_without_llm(monkeypatch, tmp_path):
    o = liquidity_ovs()
    o = o.model_copy(update={"metrics": [m.model_copy(update={"note": "비원화"}) if m.metric_id == "fin.short_term_financial_assets" else m for m in o.metrics]})
    monkeypatch.setattr(fill, "run_loop", lambda *a, **k: pytest.fail("LLM을 부르면 안 된다"))
    _, _, d, s = fill.fill_missing(store.connect(str(tmp_path / "f.db")), "run", o, None, AS)
    assert d.action == "mark_missing" and s["skipped"]


# ---- 새 공시 조사 ----
def test_investigate_keeps_only_verified_sentences_and_counts_late(monkeypatch, tmp_path):
    o = ovs("c")
    seen = [{"tool": "list_filings", "args": {}, "result": [{"rcept_no": "20261020000001", "rcept_dt": "20261020", "report_nm": "증권발행실적보고서"}]}]
    final = LoopStep(action="stop", reason="r", timing="immediate", related=["20261020000001"],
                     sentences=[LoopSentence(text="2026-10-20에 증권발행실적보고서가 접수되었다.", evidence_ids=["DART:20261020000001:목록"]), LoopSentence(text="근거 없는 문장.", evidence_ids=["DART:99999999999999:목록"])])
    monkeypatch.setattr(investigate, "run_loop", lambda *a, **k: {"steps": [], "calls": 3, "tokens": 5, "seconds": 1.0, "seen": seen, "final": final})
    from types import SimpleNamespace as NS
    monkeypatch.setattr(investigate, "verify_answer", lambda text, foot, cited, as_of, **k: NS(failed_targets=[], llm_calls=0))
    con = store.connect(str(tmp_path / "i.db"))
    got = investigate.investigate_filing(con, "run", o, {"rcept_no": "20261101000001", "rcept_dt": "20261101", "report_nm": "유상증자결정"}, AS)
    assert got["timing"] == "immediate" and got["late"] == 0 and "증권발행실적보고서" in got["summary_md"] and "근거 없는" not in got["summary_md"]
    assert con.execute("SELECT timing, verification_status FROM orc_investigations").fetchone()[:] == ("immediate", "passed")
    late = investigate._cited_from_seen([{"result": [{"rcept_no": "20261201000001"}]}], {}, AS)
    assert late == 1


def test_fill_ttm_from_three_reports(monkeypatch, tmp_path):
    """TTM 구성 3개를 각 보고서 당기 열에서 채택하고 기존 함수로 TTM을 계산한다. 하나라도 없으면 반영하지 않는다."""
    o = liquidity_ovs()
    o = o.model_copy(update={"metrics": [m.model_copy(update={"value": 0, "data_status": "ok"}) if m.metric_id == "fin.short_term_financial_assets" else m.model_copy(update={"value": None, "data_status": "missing"}) if m.metric_id == "fin.ttm_operating_cash_flow" else m for m in o.metrics]})
    reports = {"사업보고서": ["20260310000001"], "반기보고서": ["20250814000001"]}
    monkeypatch.setattr(fill, "_reports", lambda as_of, cc, pat, bgn: next((v for k, v in reports.items() if k in pat), []))
    targets, _ = fill.collect_targets(o, None, AS)
    assert sorted(t["key"] for t in targets) == ["fin.ttm_operating_cash_flow:cum", "fin.ttm_operating_cash_flow:fy_prev", "fin.ttm_operating_cash_flow:prev_same"]
    F_ = lambda part, no, raw: Finding(target=f"fin.ttm_operating_cash_flow:{part}", rcept_no=no, table_hint="연결현금흐름표", row_label="영업활동현금흐름", claimed_raw=raw)
    vals = {NO: 100, "20260310000001": 250, "20250814000001": 80}
    monkeypatch.setattr(gate, "check", lambda f, **k: {"adopted": True, "value": vals[f["rcept_no"]] * 1000, "reason": "원문 일치", "read": []})
    for findings, want in (([F_("cum", NO, 100), F_("fy_prev", "20260310000001", 250), F_("prev_same", "20250814000001", 80)], (100 + 250 - 80) * 1000), ([F_("cum", NO, 100)], None)):
        monkeypatch.setattr(fill, "run_loop", lambda *a, **k: {"steps": [], "calls": 1, "tokens": 1, "seconds": 0.1, "seen": [], "final": LoopStep(action="stop", reason="r", findings=findings)})
        o2, _, _, s = fill.fill_missing(store.connect(str(tmp_path / "t.db")), "run", o, None, AS)
        assert next(m for m in o2.metrics if m.metric_id == "fin.ttm_operating_cash_flow").value == want
    assert not [e for e in o2.errors if "validate_evidence" in e]


def test_node_guard_raises_quota_but_records_other_errors():
    """노드 가드는 보통 예외를 errors로 남기지만 DART 020은 올려 그래프·배치를 멈춘다."""
    from core.clients.dart import DartQuotaError
    from core.nodeguard import guarded

    @guarded
    def node(state):
        raise state["exc"]
    assert node({"exc": ValueError("x")})["errors"][0].startswith("node: ValueError")
    with pytest.raises(DartQuotaError):
        node({"exc": DartQuotaError("020")})
