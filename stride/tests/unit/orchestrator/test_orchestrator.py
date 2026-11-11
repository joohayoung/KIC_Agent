"""오케스트레이터 단위·통합 테스트 (오케스트레이터 개발문서 12장). 에이전트·DART·claude는 가짜로 바꾼다."""
import json
from datetime import date
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

from agents.verifier.schemas import CheckItem, ClaimCheckOutput, VerificationReport
from core import catalog
from core.schemas import AgentResult, Alert, Classification, Evidence, Metric
from orchestrator import common, store
from orchestrator.discover import default_criteria, run_discover
from orchestrator.rules import apply_criteria, apply_rules
from orchestrator.schemas import DiscoveryCriteria, FollowupOutput, ReportSectionsOutput, RouteOutput, Sentence, SentencesOutput

AS = date(2026, 11, 5)
disc = import_module("orchestrator.discover")
rev = import_module("orchestrator.review")
mon = import_module("orchestrator.monitor")
vnodes = import_module("agents.verifier.nodes")


def M(mid, value, period="2025FY", status="ok", eid=None):
    c = catalog.get(mid)
    return Metric(metric_id=mid, name=c["name"], value=value, unit=str(c["unit"]), period=period, methodology=c["methodology"], data_status=status, evidence_ids=[eid or f"DART:{mid}:document"])


def C(key, value, rule="r"):
    return Classification(key=key, value=value, rule=rule, evidence_ids=[f"DART:{key}:document"])


def E(eid):
    return Evidence(evidence_id=eid, source_grade="A", source_type="dart_document", corp_code="c", published_at=date(2026, 1, 1), title="반기보고서 (2026.06)", quote="q")


def result(agent, cc, metrics, classes=(), extra=None):
    ids = {i for x in list(metrics) + list(classes) for i in x.evidence_ids}
    return AgentResult(request_id=f"{cc}:{agent}", agent=agent, agent_version="0", corp_code=cc, corp_name=f"회사{cc}", as_of=AS, status="complete", metrics=list(metrics), classifications=list(classes), evidence=[E(i) for i in ids], extra=extra or {})


def fin(cc, *, impair=10.0, equity=5_000_000_000, audit="적정"):
    return result("financial_health", cc, [M("fin.capital_impairment_ratio", impair), M("fin.equity_ex_nci", equity), M("fin.debt_ratio", 80.0, "2026H1말"), M("fin.ttm_operating_cash_flow", 100, "TTM 2026H1")],
                  [C("fin.audit_opinion", f"{audit}의견", f"bsns_year=2025; 정규화={audit}"), C("fin.audit_scope_limitation", "false")])


def ovs(cc, *, in_scope=True, ratio=0.2, stage=4, country="미국", method="new_plant", invest=10_000_000_000):
    proj = {"project_key": "p", "name": "X", "target_country": country, "method": method, "stage": stage, "gate_pass": in_scope, "amount_krw": invest, "latest_event_date": "2026-09-01"}
    return result("overseas_funding", cc, [M("ovs.overseas_investment_amount", invest, "기준"), M("ovs.funding_gap", int(invest * ratio) if ratio is not None else None, "기준"), M("ovs.funding_gap_ratio", ratio, "기준", "ok" if ratio is not None else "missing"), M("ovs.unconfirmed_overseas_funding", 0, "기준")],
                  [C("ovs.in_scope", "true" if in_scope else "false"), C("ovs.project_stage", str(stage)), C("ovs.investment_amount_source", "major_event")], {"projects": [proj], "signals": [{"signal_type": "S4_confirmed"}]})


def ver(failed=()):
    f = [CheckItem(code="R-02", outcome="fail", kind="value_mismatch", target=t, evidence_ids=["DART:x:document"]) for t in failed]
    return VerificationReport(request_id="v", mode="results", as_of=AS.isoformat(), corp_code="c", checks=f, failed=f, unverifiable=[], failed_targets=list(failed))


# ---- apply_rules (12장) ----
@pytest.mark.parametrize("market,impair,equity,want", [
    ("KOSPI", 49.9, 5e9, {"R3-KS": False, "R2-KS": False}), ("KOSPI", 50, 5e9, {"R3-KS": True}), ("KOSPI", 99.9, 5e9, {"R3-KS": True, "R2-KS": False}), ("KOSPI", 100, 5e9, {"R2-KS": True, "R3-KS": False}),
    ("KOSDAQ", 50, 5e9, {"R3-KQ": True}), ("KOSDAQ", 10, 990_000_000, {"R3-KQ": True}), ("KOSDAQ", 10, 1_000_000_000, {"R3-KQ": False}), ("KOSDAQ", 100, 5e9, {"R2-KQ": True})])
def test_apply_rules_thresholds(market, impair, equity, want):
    got = {r.rule_id: r.hit for r in apply_rules(fin("c", impair=impair, equity=equity), ver(), market, AS)}
    assert all(got[k] == v for k, v in want.items()), got
    assert all(r.market == market for r in apply_rules(fin("c"), ver(), market, AS))


def test_scope_limited_qualified_by_market():
    f = fin("c", audit="한정")
    f = f.model_copy(update={"classifications": [c if c.key != "fin.audit_scope_limitation" else c.model_copy(update={"value": "true"}) for c in f.classifications]})
    ks = {r.rule_id: r for r in apply_rules(f, ver(), "KOSPI", AS)}
    kq = {r.rule_id: r for r in apply_rules(f, ver(), "KOSDAQ", AS)}
    assert ks["R1b-KS"].hit and ks["R1b-KS"].label == "관리종목 지정 사유 해당" and kq["R1-KQ"].hit and kq["R1-KQ"].label == "상장폐지 사유 해당"
    unknown = f.model_copy(update={"classifications": [c if c.key != "fin.audit_scope_limitation" else c.model_copy(update={"value": "unknown"}) for c in f.classifications]})
    assert {r.rule_id: r.hit for r in apply_rules(unknown, ver(), "KOSPI", AS)}["R1b-KS"] is None


def test_rule_not_applied_before_source_date_and_r5():
    assert [r.rule_id for r in apply_rules(fin("c"), ver(), "KOSPI", date(2026, 1, 1))] == ["R5"]
    r5 = next(r for r in apply_rules(fin("c"), ver(["fin:fin.debt_ratio"]), "KOSPI", AS) if r.rule_id == "R5")
    assert r5.hit and r5.inputs["failed_targets"] == ["fin:fin.debt_ratio"]


def test_missing_metric_gives_none():
    f = fin("c")
    f = f.model_copy(update={"metrics": [m if m.metric_id != "fin.capital_impairment_ratio" else m.model_copy(update={"value": None, "data_status": "missing"}) for m in f.metrics]})
    r = {x.rule_id: x for x in apply_rules(f, ver(), "KOSPI", AS)}["R3-KS"]
    assert r.hit is None and r.label == "확인 불가(데이터 없음)"


# ---- apply_criteria ----
ROW = {"market": "KOSDAQ", "industry_code": "C29", "in_scope": True, "stage": 4, "country": "미국", "method": "new_plant", "investment": 5e10, "gap_ratio": 0.3, "market_cap": None, "signal_types": ["S4_confirmed"]}


@pytest.mark.parametrize("change,crit,cond", [
    ({"market": "KOSPI"}, {"markets": ["KOSDAQ"]}, "시장"), ({"industry_code": "C10"}, {"industries": ["C29"]}, "업종"), ({"in_scope": False}, {"stages": [4]}, "해외투자 계획 확인 (G1~G4)"),
    ({"stage": 2}, {"stages": [4, 5]}, "진행 단계"), ({"country": "베트남"}, {"target_regions": ["US"]}, "투자 지역"), ({"method": "acquisition"}, {"investment_types": ["신설"]}, "투자 방식"),
    ({"investment": 1e10}, {"min_investment_amount": 5e10}, "최소 투자액"), ({"gap_ratio": -0.1}, {"min_funding_gap_ratio": 0.0}, "자금 공백 비율"),
])
def test_criteria_single_failure(change, crit, cond):
    ok, why, _ = apply_criteria({**ROW, **change}, DiscoveryCriteria(as_of=AS, **crit), [])
    assert not ok and why["condition"] == cond


def test_criteria_missing_keeps_row_as_needs_check():
    ok, why, needs = apply_criteria({**ROW, "country": None, "market_cap": None}, DiscoveryCriteria(as_of=AS, target_regions=["US"], market_cap_range=(1, None)), [])
    assert ok and why is None and needs


def test_default_search_shows_rule_hits_and_missing_values():
    """2026-11-10 방향 수정: 기본 탐색은 G1~G4 + S4·S5만 본다. 상장 규정 해당·자금 공백 음수·값 없음은 제외하지 않는다."""
    rules = apply_rules(fin("c", impair=60), ver(), "KOSDAQ", AS)
    for row in (ROW, {**ROW, "gap_ratio": -0.5}, {**ROW, "gap_ratio": None, "investment": None}):
        ok, why, _ = apply_criteria(row, default_criteria(AS), rules)
        assert ok and why is None, why
    ok, why, needs = apply_criteria({**ROW, "gap_ratio": None}, DiscoveryCriteria(as_of=AS, min_funding_gap_ratio=0.0), [])
    assert ok and needs      # 사용자가 고른 자금 공백 조건도 값이 없으면 확인 필요로 남긴다


@pytest.mark.parametrize("change,cond", [({"signal_types": ["S1_plan", "S2_progress"]}, "신호 종류"), ({"gates_g1_g4": False}, "해외투자 계획 확인 (G1~G4)")])
def test_default_search_requires_gates_and_s4_or_s5(change, cond):
    ok, why, _ = apply_criteria({**ROW, **change}, default_criteria(AS), [])
    assert not ok and why["condition"] == cond


def test_default_search_g5_failure_still_passes():
    """G5(새 신호)만 실패한 기업은 기본 탐색에 남는다."""
    from core.schemas import Classification
    o = ovs("c")
    o = o.model_copy(update={"classifications": [c for c in o.classifications if c.key != "ovs.in_scope"] + [Classification(key="ovs.in_scope", value="false", rule="통과: G1,G2,G3,G4 / 실패: G5", evidence_ids=["CALC:x:ovs.in_scope"])]})
    assert common.row_inputs(o, fin("c"), {"market": "KOSDAQ"})["gates_g1_g4"] is True


# ---- 판단 지점 ----
@pytest.mark.parametrize("action,accepted", [("mark_missing", True), ("follow_correction", True), ("delete_everything", False)])
def test_d1_validator_and_decisions(monkeypatch, tmp_path, action, accepted):
    monkeypatch.setattr(common, "call_llm", lambda *a, **k: RouteOutput(action=action, reason="r"))
    con = store.connect(str(tmp_path / "o.db"))
    d = common.replan(con, "run1", "c", ["fin.debt_ratio"], ovs("c"), fin("c"))
    row = con.execute("SELECT * FROM decisions WHERE run_id='run1'").fetchone()
    assert d.accepted == accepted and row["point"] == "D1" and bool(row["accepted"]) == accepted
    assert (d.action if accepted else d.fallback_action) in ("mark_missing", action)


# ---- discover 통합 ----
def fake_world(monkeypatch, n=30):
    cands = [{"corp_code": f"{i:08d}", "corp_name": f"회사{i}", "market": "KOSDAQ" if i % 3 else "KOSPI", "strength": 2 if i % 2 else 1, "latest": f"202609{i % 28 + 1:02d}",
              "forms": [{"rcept_no": f"R{i}", "sub_kind": "acquisition_stock", "country": "베트남" if i % 5 == 0 else "미국", "amount": 10**10}], "rcept_nos": [f"R{i}"]} for i in range(n)]
    monkeypatch.setattr(disc, "screen_universe", lambda *a, **k: cands)
    monkeypatch.setattr(disc.dart, "get_client", lambda: NS(corp_codes=lambda: [{"stock_code": "1"}] * 2600))
    monkeypatch.setattr(common, "company_info", lambda con, cc: {"corp_code": cc, "corp_name": f"회사{int(cc)}", "market": "KOSDAQ" if int(cc) % 3 else "KOSPI", "induty_code": "C29"})

    def agents(con, cc, as_of, db, *, run_id):
        i = int(cc)
        return ovs(cc, ratio=-0.1 if i % 4 == 0 else 0.2, in_scope=i % 7 != 0), fin(cc, impair=60 if i % 11 == 0 else 10), False
    monkeypatch.setattr(common, "run_agents", agents)
    monkeypatch.setattr(common, "verify", lambda o, f, as_of, run_id, cc: ver())
    monkeypatch.setattr(common, "call_llm", lambda p, v, model, **k: SentencesOutput(sentences=[Sentence(text="보드에 오른 기업이 있다", evidence_ids=[])]) if model is SentencesOutput else RouteOutput(action="mark_missing", reason="r"))
    monkeypatch.setattr(disc, "call_llm", lambda *a, **k: FollowupOutput(suggestions=[RouteOutput(action="suggest_extend_lookback", reason="기간")]))
    return cands


def test_discover_funnel_and_exclusions(monkeypatch, tmp_path):
    cands = fake_world(monkeypatch)
    db = str(tmp_path / "d.db")
    crit = default_criteria(AS).model_copy(update={"target_regions": ["US"], "max_deep_analysis": 20})
    out = run_discover("default", crit, db_path=db)
    steps = {f["step"]: f["count"] for f in out["funnel"]}
    region_out = [x for x in cands if x["strength"] == 2 and x["forms"][0]["country"] == "베트남"]
    assert steps["universe"] == 2600 and steps["events"] == 30 and steps["prefilter"] == 30 - len(region_out)
    assert steps["deep"] == 5 and len(out["pending"]) == steps["prefilter"] - 5      # 첫 실행 5곳
    assert steps["final"] == len(out["rows"]) and len(out["rows"]) + len([x for x in out["excluded"] if x["step"] == "apply_criteria"]) == 5
    assert all(x["condition"] and x["step"] for x in out["excluded"])      # 제외 사유 100% 기록
    con = store.connect(db)
    statuses = {r["status"] for r in con.execute("SELECT status FROM orc_search_matches")}
    assert statuses <= {"matched", "excluded", "pending"} and con.execute("SELECT COUNT(*) FROM orc_search_runs").fetchone()[0] == 1
    second = run_discover("default", crit, db_path=db)
    assert {f["step"]: f["count"] for f in second["funnel"]}["deep"] == 20      # 완료된 실행이 있으면 K=20
    assert not any(w in json.dumps([r.model_dump() for r in second["rows"]], ensure_ascii=False) for w in ("추천", "유망", "score", "rank"))


# ---- review 통합: 검증 실패 주입 ----
def test_review_rewrites_once_then_marks(monkeypatch, tmp_path):
    monkeypatch.setattr(rev, "resolve", lambda client, q, cc: ({"corp_code": "00000007", "corp_name": "회사7"}, None, []))
    monkeypatch.setattr(rev.dart, "get_client", lambda: None)
    monkeypatch.setattr(common, "company_info", lambda con, cc: {"corp_code": cc, "corp_name": "회사7", "market": "KOSDAQ", "induty_code": "C29"})
    monkeypatch.setattr(common, "run_agents", lambda con, cc, as_of, db, *, run_id: (ovs(cc), fin(cc), True))
    monkeypatch.setattr(common, "verify", lambda o, f, as_of, run_id, cc: ver())
    calls = []
    bad = Sentence(text="해외 투자액은 999억 원이다", evidence_ids=["DART:ovs.overseas_investment_amount:document"])
    good = Sentence(text="해외 투자액은 100억 원이다", evidence_ids=["DART:ovs.overseas_investment_amount:document"])

    def llm(path, variables, model, **k):
        calls.append(path)
        return ReportSectionsOutput(summary=[bad, good], project=[good], funding_gap=[], financial=[], rules=[], verification=[], opinion=[])
    monkeypatch.setattr("core.llm.call_llm", llm)
    monkeypatch.setattr(vnodes, "call_llm", lambda *a, **k: ClaimCheckOutput(verdict="supported", reason="r"))
    out = rev.run_review(query="회사7", as_of=AS, db_path=str(tmp_path / "r.db"))
    rep = out["report"]
    assert len(calls) == 2 and "(검증 실패)" in rep.sections["summary"] and rep.verification_status == "partially_failed"
    assert "100억 원이다 [1]" in rep.sections["summary"] and rep.sections["appendix"].startswith("[1]")


# ---- monitor 재생 ----
def test_monitor_catches_up_and_no_duplicate_feed(monkeypatch, tmp_path):
    monkeypatch.setattr(mon, "investigate_filing", lambda con, run_id, ovs, f, as_of: {"calls": 0, "late": 0})      # 새 공시 조사는 test_investigate에서 본다
    db = str(tmp_path / "m.db")
    con = store.connect(db)
    con.execute("INSERT INTO orc_watchlist VALUES ('00000001','회사1','x','test')")
    con.commit()
    rows = [{"rcept_no": "20261101000001", "rcept_dt": "20261101", "corp_code": "00000001", "report_nm": "타법인주식및출자증권취득결정"}, {"rcept_no": "20261103000001", "rcept_dt": "20261103", "corp_code": "00000002", "report_nm": "타법인주식및출자증권취득결정"}]
    client = NS(list_filings=lambda as_of, a, b, pblntf_ty=None: [r for r in rows if pblntf_ty == "I" and r["rcept_dt"] <= as_of.strftime("%Y%m%d")])
    monkeypatch.setattr(common, "company_info", lambda con, cc: {"corp_code": cc, "corp_name": "회사", "market": "KOSDAQ", "induty_code": "C29"})
    o = ovs("00000001")
    o = o.model_copy(update={"alerts": [Alert(agent="overseas_funding", corp_code="00000001", alert_type="stage_up", message="단계 2 → 4", evidence_ids=["DART:x:document"])]})
    monkeypatch.setattr(common, "run_agents", lambda con, cc, as_of, db, *, run_id: (o, fin(cc), False))
    monkeypatch.setattr(common, "verify", lambda *a: ver())
    first = mon.run_monitor(date(2026, 11, 1), db_path=db, client=client)      # 11-02 실행은 누락됐다고 본다
    later = mon.run_monitor(date(2026, 11, 5), db_path=db, client=client)
    again = mon.run_monitor(date(2026, 11, 5), db_path=db, client=client)
    con = store.connect(db)
    feed = con.execute("SELECT * FROM orc_feed").fetchall()
    assert first["relevant"] == 1 and later["relevant"] == 0 and again["relevant"] == 0      # 처리한 공시는 다시 하지 않는다
    assert len(feed) == len({r["item_id"] for r in feed}) and any(r["alert_type"] == "stage_up" for r in feed)
    assert con.execute("SELECT last_rcept_dt FROM orc_monitor_cursor").fetchone()[0] == "20261103"


def test_route_by_event():
    assert mon.route_by_event("유상증자결정") == ("overseas_funding", "financial_health")
    assert mon.route_by_event("[기재정정]타법인주식및출자증권취득결정") == ("overseas_funding",)
    assert mon.route_by_event("감사보고서제출") == ("financial_health",) and mon.route_by_event("임원ㆍ주요주주특정증권등소유상황보고서") == ()


def test_worker_progress_from_other_thread(monkeypatch, tmp_path):
    """병렬 노드 스레드에서 진행 표시를 기록해도 SQLite 스레드 오류가 나지 않는다 (2026-11-09 실제 실행에서 5곳 전부 실패한 원인)."""
    import threading
    from orchestrator import worker
    db = str(tmp_path / "w.db")
    con = store.connect(db)
    job = worker.enqueue(con, "discover", {"search_id": "default", "as_of": AS.isoformat()})
    errors = []

    def fake_discover(sid, crit, *, db_path=None, progress=None, run_id=None):
        t = threading.Thread(target=lambda: errors.append(None) if progress("deep_done") is None else None)
        t.start()
        t.join()
        return {"run_id": "r1"}
    monkeypatch.setattr(worker, "run_discover", fake_discover)
    assert worker.run_worker(db_path=db, once=True) == 1
    row = store.connect(db).execute("SELECT status, progress_json FROM orc_jobs WHERE job_id=?", (job,)).fetchone()
    assert row["status"] == "done" and json.loads(row["progress_json"])["deep_done"] == 1


def test_monitor_first_run_cap_and_pending_not_tracked(monkeypatch, tmp_path):
    monkeypatch.setattr(mon, "investigate_filing", lambda con, run_id, ovs, f, as_of: {"calls": 0, "late": 0})      # 새 공시 조사는 test_investigate에서 본다
    db = str(tmp_path / "m2.db")
    con = store.connect(db)
    con.execute("INSERT INTO orc_search_runs VALUES ('default','r0','2026-11-01','[]','','[]','2026-11-01')")
    for i in range(8):
        con.execute("INSERT INTO orc_search_matches VALUES ('default',?,'r0','2026-11-01','matched',NULL,NULL,NULL,'{}','[]')", (f"{i:08d}",))
    con.execute("INSERT INTO orc_search_matches VALUES ('default','99999999','r0','2026-11-01','pending',NULL,NULL,NULL,'{}','[]')")
    con.commit()
    rows = [{"rcept_no": f"2026110{i % 3 + 1}00000{i}", "rcept_dt": f"2026110{i % 3 + 1}", "corp_code": f"{i:08d}", "report_nm": "유상증자결정"} for i in range(8)] + [{"rcept_no": "20261102999999", "rcept_dt": "20261102", "corp_code": "99999999", "report_nm": "유상증자결정"}]
    client = NS(list_filings=lambda as_of, a, b, pblntf_ty=None: [r for r in rows if pblntf_ty == "B"])
    seen = []
    monkeypatch.setattr(common, "company_info", lambda con, cc: {"corp_code": cc, "corp_name": "회사", "market": "KOSDAQ", "induty_code": "C29"})
    monkeypatch.setattr(common, "run_agents", lambda con, cc, as_of, db, *, run_id: (seen.append(cc), ovs(cc), fin(cc), False)[1:])
    monkeypatch.setattr(common, "verify", lambda *a: ver())
    first = mon.run_monitor(date(2026, 11, 5), db_path=db, client=client)
    assert first["relevant"] == 8 and len(seen) == 5 and first["deferred"] == 3 and "99999999" not in seen      # 첫 감시 5곳, 분석 대기 기업은 추적 대상 아님
    second = mon.run_monitor(date(2026, 11, 5), db_path=db, client=client)
    assert len(seen) == 8 and second["deferred"] == 0      # 미룬 공시를 다음 실행에서 처리


def test_llm_failed_results_are_not_reused_and_go_pending(monkeypatch, tmp_path):
    """한도로 LLM이 실패한 해외진출 결과는 저장·재사용하지 않고, 탐색에서는 분석 대기로 둔다 (2026-11-09 실제 실행)."""
    db = str(tmp_path / "f.db")
    con = store.connect(db)
    bad = ovs("00000001").model_copy(update={"errors": ["extract_periodic_plan: LLMRateLimitError: 사용량 한도"], "status": "partial"})
    store.save_result(con, bad)
    assert store.load_result(con, "00000001", "overseas_funding", AS.isoformat()) is None
    monkeypatch.setattr(common, "run_company", lambda req: bad)
    with pytest.raises(Exception, match="LLMRateLimit|사용량"):
        common.run_agents(con, "00000001", AS, db, run_id="r")
    fake_world(monkeypatch, n=3)

    def failing(con, cc, as_of, dbp, *, run_id):
        from core.llm import LLMRateLimitError
        raise LLMRateLimitError("사용량 한도")
    monkeypatch.setattr(common, "run_agents", failing)
    out = run_discover("default", default_criteria(AS), db_path=db)
    assert not out["excluded"] and len(out["pending"]) == 3 and all(p.get("note") for p in out["pending"])


def test_dart_quota_goes_pending_and_monitor_defers(monkeypatch, tmp_path):
    """DART 020: 탐색은 분석 대기(사유 표시), 감시는 그 기업부터 미루고 커서를 미룬 첫 공시 날짜에 둔다."""
    from core.clients.dart import DartQuotaError
    db = str(tmp_path / "q.db")
    fake_world(monkeypatch, n=2)

    def quota(con, cc, as_of, dbp, *, run_id):
        raise DartQuotaError("document.xml: status 020 일일 요청 한도 초과")
    monkeypatch.setattr(common, "run_agents", quota)
    out = run_discover("default", default_criteria(AS), db_path=db)
    assert not out["excluded"] and len(out["pending"]) == 2 and all("DART 일일 요청 한도" in p["note"] for p in out["pending"])
    con = store.connect(db)
    con.execute("INSERT INTO orc_watchlist VALUES ('00000001','회사1','x','test')")
    con.commit()
    rows = [{"rcept_no": "20261103000001", "rcept_dt": "20261103", "corp_code": "00000001", "report_nm": "유상증자결정"}]
    client = NS(list_filings=lambda as_of, a, b, pblntf_ty=None: [r for r in rows if pblntf_ty == "B"])
    monkeypatch.setattr(common, "company_info", lambda con, cc: {"corp_code": cc, "corp_name": "회사", "market": "KOSDAQ", "induty_code": "C29"})
    st = mon.run_monitor(date(2026, 11, 5), db_path=db, client=client)
    assert st["stopped"] == "DART 일일 요청 한도 초과" and st["deferred"] == 1
    assert con.execute("SELECT last_rcept_dt FROM orc_monitor_cursor").fetchone()[0] == "20261103"
    assert not con.execute("SELECT 1 FROM processed_filings WHERE rcept_no='20261103000001'").fetchone()
