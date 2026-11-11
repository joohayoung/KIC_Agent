"""BatchGraph (5.5, 10.7). screen_universe → 기업별 Send → company_graph → aggregate_list. 순위를 매기지 않는다.

screen_universe는 LLM 없이 기간 내 공시 목록만 본다. 오케스트레이터 scan_events가 재사용한다.
"""
import operator
import time
from datetime import date, datetime, timedelta
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from agents.overseas_funding import store
from agents.overseas_funding.config import BATCH_MAX_COMPANIES, KOREA_NAMES, LLM_CONCURRENCY, SCREEN_SUB_KINDS
from agents.overseas_funding.graph import build_company_graph, _initial, to_result
from agents.overseas_funding.calc.funding import canon_country
from agents.overseas_funding.nodes.parse_major_events import parse_acquisition_form
from core.clients import dart
from core.clients.dart_docs import plain_text
from core.config import settings
from core.filings import classify_filing
from core.schemas import Request
from core.clients.dart import DartQuotaError

SKIP_STATUSES = ("신호 없음", "범위 밖", "취소")
_company_graph = None


def screen_universe(start: date, end: date, as_of: date, *, client=None, tracked: dict | None = None) -> list[dict]:
    """기간 내 거래소·주요사항 공시에서 해외 투자 후보 상장사를 고른다. LLM 없음.
    강도 2: 타법인 취득 양식의 국적 칸이 해외. 강도 1: 국적 칸이 없는 시설·자산·영업 취득 (해외 여부는 기업 실행에서 판단).
    조달 공시와 정기보고서는 공시 이름만으로 해외 여부를 알 수 없어 넣지 않는다 (자체 결정 2026-11-09).
    tracked: {corp_code: (signal_status, last_as_of)}. 직전 상태가 신호 없음·범위 밖·취소이고 그 뒤 새 공시가 없으면 제외."""
    client = client or dart.get_client()
    rows, a = [], start
    while a <= end:      # 달력 월 단위로 조회한다 (3개월 제한 안). 다 지난 달은 조회 기간이 기준일과 무관해 캐시를 다시 쓴다
        month_end = (a.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
        b = min(month_end, end)
        for ty in ("I", "B"):
            rows += client.list_filings(as_of, a, b, pblntf_ty=ty)
        a = b + timedelta(days=1)
    found: dict[str, dict] = {}
    for r in sorted(rows, key=lambda r: (r["rcept_dt"], r["rcept_no"])):
        c = classify_filing(r["report_nm"])
        if r.get("corp_cls") not in ("Y", "K") or c["is_correction"] or c["sub_kind"] not in SCREEN_SUB_KINDS:
            continue
        strength, country, amount = 1, None, None
        if c["sub_kind"] == "acquisition_stock":
            try:
                form = parse_acquisition_form(plain_text(client.document(r["rcept_no"])))
                country, amount = form["country"], form["amount"]
            except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
                raise
            except Exception:      # 원문을 못 읽으면 강도 1로 남긴다
                pass
            if country and any(k in country for k in KOREA_NAMES):
                continue
            strength = 2 if country else 1
        x = found.setdefault(r["corp_code"], {"corp_code": r["corp_code"], "corp_name": r.get("corp_name"), "market": {"Y": "KOSPI", "K": "KOSDAQ"}[r["corp_cls"]], "strength": 0, "latest": "", "rcept_nos": [], "forms": []})
        x["strength"] = max(x["strength"], strength)
        x["latest"] = max(x["latest"], r["rcept_dt"])
        x["rcept_nos"].append(r["rcept_no"])
        x["forms"].append({"rcept_no": r["rcept_no"], "sub_kind": c["sub_kind"], "country": canon_country(country), "amount": amount})
    out = []
    for x in found.values():
        prev = (tracked or {}).get(x["corp_code"])
        if prev and prev[0] in SKIP_STATUSES and x["latest"] <= prev[1].replace("-", ""):
            continue
        out.append(x)
    return sorted(out, key=lambda x: (x["strength"], x["latest"]), reverse=True)


class BatchState(TypedDict, total=False):
    request: Request
    targets: list[dict]
    pending: list[dict]
    results: Annotated[list[dict], operator.add]
    table_markdown: str
    started: float


def _tracked(db_path) -> dict:
    con = store.connect(db_path)
    try:
        return {r["corp_code"]: (r["signal_status"], r["last_as_of"]) for r in con.execute("SELECT * FROM overseas_funding_tracked")}
    finally:
        con.close()


def completed_batch_runs(db_path) -> int:
    con = store.connect(db_path)
    try:
        return con.execute("SELECT COUNT(*) FROM runs WHERE agent='overseas_funding_batch' AND status='complete'").fetchone()[0]
    finally:
        con.close()


def screen(state: BatchState) -> dict:
    req = state["request"]
    db = (req.context or {}).get("db_path")
    cands = screen_universe(req.period_start, req.as_of, req.as_of, tracked=_tracked(db))
    limit = min(BATCH_MAX_COMPANIES, req.context.get("max_companies", BATCH_MAX_COMPANIES))
    if completed_batch_runs(db) == 0:      # 첫 실제 실행은 5곳 (오케스트레이터 4장 prefilter와 같은 설정)
        limit = min(limit, settings.first_run_max_deep_analysis)
    return {"targets": cands[:limit], "pending": cands[limit:], "started": time.monotonic()}


def fan_out(state: BatchState):
    req = state["request"]
    return [Send("company_graph", {"request": req.model_copy(update={"mode": "single", "corp_code": x["corp_code"], "company": None}), "screen": x}) for x in state["targets"]] or ["aggregate_list"]


def company_graph(payload: dict) -> dict:
    """CompanyGraph를 기업 1곳으로 실행한다. 한 기업의 실패가 배치를 멈추지 않는다."""
    global _company_graph
    _company_graph = _company_graph or build_company_graph()
    t0 = time.monotonic()
    try:
        state = _company_graph.invoke(_initial(payload["request"]), {"recursion_limit": 80})
        r = to_result(state)
        row = {"result": r, "seconds": round(time.monotonic() - t0, 1), "llm_calls": r.extra.get("llm_calls", 0), "screen": payload["screen"], "error": None}
    except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
        raise
    except Exception as e:
        row = {"result": None, "seconds": round(time.monotonic() - t0, 1), "llm_calls": 0, "screen": payload["screen"], "error": f"{type(e).__name__}: {e}"[:300]}
    return {"results": [row]}


def eok(v) -> str:
    return "-" if v is None else f"{v / 1e8:,.1f}억"


def table(results: list[dict]) -> str:
    """10.7 목록. 순위 열이 없고 최근 신호일 순이다."""
    lines = ["| 기업 | 신호 상태 | 대표 프로젝트 (국가·방식) | 단계 | 해외 투자액 | 자금 공백 | 최근 신호일 | 이번 경보 |", "|---|---|---|---|---|---|---|---|"]
    rows = []
    for x in results:
        r = x["result"]
        if r is None:
            rows.append(("", f"| {x['screen'].get('corp_name') or x['screen']['corp_code']} | 실행 실패 | - | - | - | - | - | - |"))
            continue
        cls = {c.key: c.value for c in r.classifications}
        p = max((p for p in r.extra.get("projects") or [] if p.get("gate_pass")), key=lambda p: p.get("amount_krw") or 0, default=None)
        m = {k.metric_id: k.value for k in r.metrics}
        latest = max((s["event_date"] for s in r.extra.get("signals") or []), default="")
        proj = f"{p.get('target_country') or '-'}·{p.get('method') or '-'}" if p else "-"
        rows.append((latest, f"| {r.corp_name} | {cls.get('ovs.signal_status', '-')} | {proj} | {cls.get('ovs.project_stage', '-')} | {eok(m.get('ovs.overseas_investment_amount'))} | {eok(m.get('ovs.funding_gap'))} | {latest or '-'} | {', '.join(a.alert_type for a in r.alerts) or '-'} |"))
    return "\n".join(lines + [line for _, line in sorted(rows, key=lambda x: x[0], reverse=True)])


def aggregate_list(state: BatchState) -> dict:
    results = state.get("results") or []
    md = table(results)
    details = "\n\n".join(x["result"].report_markdown or "" for x in results if x["result"])
    req = state["request"]
    db = (req.context or {}).get("db_path")
    con = store.connect(db)
    try:
        now = datetime.now().isoformat(timespec="seconds")
        con.execute("INSERT OR REPLACE INTO runs (run_id, agent, corp_code, as_of, mode, status, started_at, finished_at, llm_calls, errors_json) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (req.request_id, "overseas_funding_batch", None, req.as_of.isoformat(), "batch", "complete", now, now, sum(x["llm_calls"] for x in results), "[]"))
        con.commit()
    finally:
        con.close()
    return {"table_markdown": md + ("\n\n" + details if details else "")}


def build_batch_graph():
    g = StateGraph(BatchState)
    g.add_node("screen_universe", screen)
    g.add_node("company_graph", company_graph)
    g.add_node("aggregate_list", aggregate_list)
    g.add_edge(START, "screen_universe")
    g.add_conditional_edges("screen_universe", fan_out, ["company_graph", "aggregate_list"])
    g.add_edge("company_graph", "aggregate_list")
    g.add_edge("aggregate_list", END)
    return g.compile()


def run_batch(request: Request) -> dict:
    """반환 {"table_markdown", "results", "pending", "seconds"}. 동시 실행은 LLM_CONCURRENCY."""
    t0 = time.monotonic()
    out = build_batch_graph().invoke({"request": request}, {"max_concurrency": LLM_CONCURRENCY, "recursion_limit": 200})
    return {"table_markdown": out.get("table_markdown"), "results": out.get("results") or [], "pending": out.get("pending") or [], "seconds": round(time.monotonic() - t0, 1)}

