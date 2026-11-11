"""monitor_graph (구성문서 4.2, 오케스트레이터 7.7). 누락분 처리, 같은 공시 중복 경보 0건. 커서는 끝까지 성공했을 때만 저장한다."""
import json
import re
from datetime import date, timedelta

from core.clients import dart
from core.config import settings
from core.clients.dart import DartQuotaError
from core.llm import LLMError
from core.filings import classify_filing
from orchestrator import common, store
from orchestrator.investigate import investigate_filing
from orchestrator.config import CORRECTION_AGENTS, MONITOR_MAX_COMPANIES, ROUTE_BY_EVENT
from orchestrator.rules import apply_criteria, apply_rules
from orchestrator.schemas import DiscoveryCriteria, FeedItem

PBLNTF = ("A", "B", "I")
FIRST_LOOKBACK_DAYS = 7      # 커서가 없을 때 처음 조회 기간 (자체 결정 2026-11-09: 문서에 없음. 첫 실행 시 과거 전체를 다시 분석하지 않기 위함)


def route_by_event(report_nm: str) -> tuple[str, ...]:
    c = classify_filing(report_nm)
    name = c["norm"]
    if c["is_correction"] or re.search(r"연기|철회|해제|해지|취소", name):
        return CORRECTION_AGENTS
    for prefixes, agents in ROUTE_BY_EVENT:
        if name.startswith(prefixes):
            return agents
    return ()


def tracked_targets(con, as_of: str) -> dict:
    """추적 대상 = 관심 기업 + 추적 중인 탐색의 최신 실행 matched 기업.
    자체 결정 (2026-11-09): '시장·업종 후보군' 전체는 상장사 대부분이다. 분석 대기(pending)도 넣었더니 첫 감시에서 76곳을 분석해 첫 실행 5곳 원칙을 넘었다. 분석 대기는 [추가 분석]으로만 분석한다."""
    out = {r["corp_code"]: {"watch"} for r in con.execute("SELECT corp_code FROM orc_watchlist")}
    for s in con.execute("SELECT search_id FROM orc_searches WHERE tracking=1"):
        run = con.execute("SELECT run_id FROM orc_search_runs WHERE search_id=? ORDER BY created_at DESC LIMIT 1", (s["search_id"],)).fetchone()
        if run:
            for r in con.execute("SELECT corp_code FROM orc_search_matches WHERE search_id=? AND run_id=? AND status='matched'", (s["search_id"], run["run_id"])):
                out.setdefault(r["corp_code"], set()).add(s["search_id"])
    return out


def poll(client, since: date, until: date) -> list[dict]:
    """커서 이후 공시 전부. 3개월 단위로 나눠 조회하고 total_page까지 순회한다 (client.list_filings)."""
    rows, a = [], since
    while a <= until:
        b = min(a + timedelta(days=88), until)
        for ty in PBLNTF:
            rows += client.list_filings(until, a, b, pblntf_ty=ty)
        a = b + timedelta(days=1)
    return sorted({r["rcept_no"]: r for r in rows}.values(), key=lambda r: (r["rcept_dt"], r["rcept_no"]))


def run_monitor(as_of: date, *, db_path=None, run_id=None, client=None) -> dict:
    run_id = run_id or store.new_id("mon")
    client = client or dart.get_client()
    con = store.connect(db_path)
    stats = {"run_id": run_id, "polled": 0, "relevant": 0, "companies": 0, "feed": 0}
    try:
        cur = con.execute("SELECT * FROM orc_monitor_cursor WHERE id=1").fetchone()
        since = date.fromisoformat(f"{cur['last_rcept_dt'][:4]}-{cur['last_rcept_dt'][4:6]}-{cur['last_rcept_dt'][6:]}") if cur else as_of - timedelta(days=FIRST_LOOKBACK_DAYS)
        rows = poll(client, since, as_of)
        stats["polled"] = len(rows)
        targets = tracked_targets(con, as_of.isoformat())
        done = {r["rcept_no"] for r in con.execute("SELECT rcept_no FROM processed_filings WHERE agent='orchestrator.monitor'")}
        relevant = [r for r in rows if r["corp_code"] in targets and r["rcept_no"] not in done and route_by_event(r["report_nm"])]
        stats["relevant"] = len(relevant)
        by_corp = {}
        for r in relevant:
            by_corp.setdefault(r["corp_code"], []).append(r)
        first = con.execute("SELECT COUNT(*) FROM runs WHERE agent='orchestrator.monitor' AND status='complete'").fetchone()[0] == 0
        cap = settings.first_run_max_deep_analysis if first else MONITOR_MAX_COMPANIES      # 한 번에 다시 분석하는 기업 수 상한
        order = sorted(by_corp, key=lambda cc: ("watch" not in targets[cc], by_corp[cc][0]["rcept_dt"]))      # 관심 기업 먼저, 오래된 공시 먼저
        deferred = order[cap:]
        stats["deferred"] = len(deferred)
        stats.update(inv_cap=cap, investigations=0, inv_calls=0, inv_late=0)      # 새 공시 조사: 공시 1건당 루프 1회, 감시 1회 상한 = 재분석 상한 (2026-11-10)
        for i, cc in enumerate(order[:cap]):
            filings = by_corp[cc]
            try:
                _process_company(con, cc, filings, targets[cc], as_of, run_id, db_path, stats)
            except (LLMError, DartQuotaError) as e:      # 한도: 이 기업부터 다음 실행으로 미룬다. 커서는 미룬 첫 공시 앞 (아래)
                deferred = order[i:]
                stats["deferred"] = len(deferred)
                stats["stopped"] = "DART 일일 요청 한도 초과" if isinstance(e, DartQuotaError) else "LLM 호출 실패"
                break
            for r in filings:
                con.execute("INSERT OR REPLACE INTO processed_filings VALUES (?,?,?,?)", (r["rcept_no"], "orchestrator.monitor", run_id, store.now()))
            con.commit()
        last = rows[-1] if rows else None
        if deferred:      # 다음 실행이 미룬 공시부터 다시 읽게 한다. 처리한 공시는 processed_filings로 건너뛴다
            first_deferred = min(r["rcept_dt"] for cc in deferred for r in by_corp[cc])
            last = {"rcept_no": None, "rcept_dt": first_deferred}
        con.execute("INSERT OR REPLACE INTO orc_monitor_cursor VALUES (1,?,?,?)", (last["rcept_no"] if last else (cur["last_rcept_no"] if cur else None), last["rcept_dt"] if last else as_of.strftime("%Y%m%d"), store.now()))      # 끝까지 성공했을 때만
        con.execute("INSERT OR REPLACE INTO runs (run_id, agent, corp_code, as_of, mode, status, started_at, finished_at, llm_calls, errors_json) VALUES (?,?,?,?,?,?,?,?,?,?)", (run_id, "orchestrator.monitor", None, as_of.isoformat(), "monitor", "complete", store.now(), store.now(), 0, json.dumps(stats)))
        con.commit()
        return stats
    finally:
        con.close()


def _process_company(con, cc, filings, reasons, as_of, run_id, db_path, stats) -> None:
    """dispatch → verifier_results → match_saved_criteria → diff_and_alert → notify."""
    info = common.company_info(con, cc)
    ovs, fin, _ = common.run_agents(con, cc, as_of, db_path or settings.path(settings.stride_db_path), run_id=run_id)
    ver = common.verify(ovs, fin, as_of, run_id, cc)
    store.save_result(con, ovs, ver)
    store.save_result(con, fin, ver)
    stats["companies"] += 1
    rules = apply_rules(fin, ver, info.get("market"), as_of)
    for f in filings:      # 새 공시 조사 (자율: 조사 경로·알림 시점·요약. 상태·경보는 위 에이전트 규칙 결과 그대로)
        if stats["investigations"] >= stats["inv_cap"]:
            stats["inv_skipped"] = stats.get("inv_skipped", 0) + 1
            continue
        got = investigate_filing(con, run_id, ovs, f, as_of)
        stats["investigations"] += 1
        stats["inv_calls"] += got["calls"]
        stats["inv_late"] += got["late"]
    inputs = common.row_inputs(ovs, fin, info)
    ids = [i for m in ovs.metrics[:1] for i in m.evidence_ids] or [f"DART:{filings[-1]['rcept_no']}:list"]
    for s in con.execute("SELECT * FROM orc_searches WHERE tracking=1"):
        crit = DiscoveryCriteria(**{**json.loads(s["criteria_json"]), "as_of": as_of})
        ok, why, _ = apply_criteria(inputs, crit, rules)
        run = con.execute("SELECT run_id FROM orc_search_runs WHERE search_id=? ORDER BY created_at DESC LIMIT 1", (s["search_id"],)).fetchone()
        was = con.execute("SELECT status FROM orc_search_matches WHERE search_id=? AND corp_code=? AND run_id=?", (s["search_id"], cc, run["run_id"])).fetchone() if run else None
        was_match = bool(was and was["status"] == "matched")
        if ok != was_match:
            gap = inputs.get("gap_ratio")
            reason = f"조건 충족: 자금 공백 비율 {gap * 100:.1f}%" if ok and gap is not None else (f"조건 이탈: {why['condition']} {why['value']}" if why else "조건 충족")
            if store.add_feed(con, FeedItem(item_id=f"{s['search_id']}:{cc}:{'new' if ok else 'left'}:{filings[-1]['rcept_no']}", kind="new_match" if ok else "left_match", search_id=s["search_id"], corp_code=cc, alert_type="new_match" if ok else "left_match", before="충족" if was_match else "미충족", after="충족" if ok else "미충족", reason=reason, event_date=as_of, evidence_ids=ids)):
                stats["feed"] += 1
            if run:
                con.execute("INSERT OR REPLACE INTO orc_search_matches VALUES (?,?,?,?,?,?,?,?,?,?)", (s["search_id"], cc, run["run_id"], as_of.isoformat(), "matched" if ok else "excluded", None if ok else "monitor", None if ok else why["condition"], None if ok else str(why["value"]),
                                                                                                      common.board_row(ovs, fin, info, rules, ver, matched_search_ids=[], is_watched="watch" in reasons, change_badges=["new_match"]).model_dump_json() if ok else common.dumps({"corp_name": ovs.corp_name}), common.dumps(ids)))
                con.commit()
    if "watch" in reasons:      # 관심 기업: 에이전트 경보를 그대로 변경 내역으로
        for a in ovs.alerts + fin.alerts:
            if store.add_feed(con, FeedItem(item_id=f"watch:{cc}:{a.alert_type}:{filings[-1]['rcept_no']}", kind="watch_change", search_id=None, corp_code=cc, alert_type=a.alert_type, before=None, after=None, reason=a.message[:300], event_date=as_of, evidence_ids=a.evidence_ids)):
                stats["feed"] += 1
