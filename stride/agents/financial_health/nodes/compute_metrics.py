from agents.financial_health.config import DUE_DILIGENCE, MARKET_METRICS
from agents.financial_health.nodes.collect_restructuring import status_of
from core import catalog
from core import evidence as ev
from core.asof import UNKNOWN_NOTE, to_date
from core.calc import cashflow, fin_items, ratios
from core.nodeguard import guarded
from core.schemas import Classification, Evidence, Metric

SEPARATE = "별도 기준"


class Builder:
    """Metric·CALC 근거를 만든다. CALC meta는 core.evidence가 재계산으로 검사한다."""

    def __init__(self, run_id, corp_code, as_of):
        self.run_id, self.corp_code, self.as_of = run_id, corp_code, as_of
        self.metrics, self.evidence = [], []

    def metric(self, mid, value, period, ids, *, status=None, note=None, separate=False):
        c = catalog.get(mid)
        if status is None:
            status = "ok" if value is not None else "missing"
        if separate:
            note = f"{SEPARATE}. {note}" if note else SEPARATE
        self.metrics.append(Metric(metric_id=mid, name=c["name"], value=value, unit=str(c["unit"]), period=period, methodology=c["methodology"], data_status=status, evidence_ids=list(dict.fromkeys(ids)), note=note))

    def calc(self, mid, period, impl, args, value, inputs, published, title) -> list[str]:
        """계산 근거. 값이 없으면 입력 근거만 돌려준다."""
        if value is None:
            return inputs
        eid = f"{ev.calc(self.run_id, mid)}:{period}"
        self.evidence.append(Evidence(evidence_id=eid, source_grade="A", source_type="calc", corp_code=self.corp_code, published_at=to_date(published), title=title, meta={"impl": impl, "args": args, "value": value, "inputs": inputs}))
        return [eid]


def amount(accounts, key):
    a = (accounts or {}).get(key)
    return a.amount if a else None


def ids_of(accounts, *keys):
    return [accounts[k].evidence_ids[0] for k in keys if accounts and k in accounts]


def debt_ids(src):
    no, fs = src["rcept_no"], src["fs"]
    known = fin_items.BORROW_IDS | set(fin_items.LEASE_IDS.values())
    return [ev.fin(no, fs, r["account_id"]) for r in src["rows"] if r.get("sj_div") == "BS" and r["account_id"] in known]


def debt_evidence(src, corp_code) -> list[Evidence]:
    return [Evidence(evidence_id=i, source_grade="A", source_type="dart_fin", corp_code=corp_code, published_at=to_date(src["rcept_dt"]), title=src["report_nm"]) for i in debt_ids(src)]


def balance_basics(b: Builder, src, accounts, period, fallback):
    """총차입금·순차입금·부채비율·유동비율·차입금의존도. 사업연도와 최신 보고서가 같은 산식을 쓴다. 순차입금 재료를 돌려준다."""
    sep = src["fs"] == "OFS"
    bs = [r for r in src["rows"] if r.get("sj_div") == "BS"]
    krw = src.get("krw", True)
    tb, tb_note, _ = src.get("tb") or (None, "리스 주석 대조 불가", None)
    if not krw:
        tb, tb_note = None, "비원화"
    b.evidence += debt_evidence(src, b.corp_code)
    d_ids = debt_ids(src) or fallback
    t_ids = b.calc("fin.total_borrowings", period, "core.calc.fin_items.add_amounts", {"amounts": [tb]}, tb, d_ids, src["rcept_dt"], src["report_nm"])
    b.metric("fin.total_borrowings", tb, period, t_ids, note=tb_note, separate=sep)
    cash, cash_note = fin_items.cash_and_equivalents(bs) if krw else (None, "비원화")
    st, st_note = fin_items.short_term_financial_assets(bs) if krw else (None, "비원화")
    nd = fin_items.net_debt(tb, cash, st)
    nd_note = None if nd is not None else tb_note if tb is None else st_note if st is None else cash_note
    nd_ids = b.calc("fin.net_debt", period, "core.calc.fin_items.net_debt", {"total_borrowings_value": tb, "cash": cash, "short_term": st}, nd, t_ids + ids_of(accounts, "cash", "st_fin_assets"), src["rcept_dt"], src["report_nm"])
    b.metric("fin.net_debt", nd, period, nd_ids or fallback, note=nd_note, separate=sep)
    for mid, impl, fn, args, keys in (
        ("fin.debt_ratio", "core.calc.ratios.debt_ratio", ratios.debt_ratio, {"liabilities": amount(accounts, "total_liabilities"), "equity": amount(accounts, "total_equity")}, ("total_liabilities", "total_equity")),
        ("fin.current_ratio", "core.calc.ratios.current_ratio", ratios.current_ratio, {"current_assets": amount(accounts, "current_assets"), "current_liabilities": amount(accounts, "current_liabilities")}, ("current_assets", "current_liabilities")),
        ("fin.borrowing_dependency", "core.calc.ratios.borrowing_dependency", ratios.borrowing_dependency, {"total_borrowings": tb, "total_assets": amount(accounts, "total_assets")}, ("total_assets",)),
    ):
        v = fn(**args)
        note = "자본총계 ≤ 0" if mid == "fin.debt_ratio" and v is None and (args["equity"] or 0) <= 0 and args["equity"] is not None else None
        b.metric(mid, v, period, b.calc(mid, period, impl, args, v, ids_of(accounts, *keys) or fallback, src["rcept_dt"], src["report_nm"]), note=note, separate=sep)
    return nd, cash, st, cash_note, st_note


def year_metrics(b: Builder, year: int, src, accounts):
    period = f"{year}FY"
    sep = src["fs"] == "OFS"
    fallback = [ev.dart_section(src["rcept_no"], "document")]
    nd, *_ = balance_basics(b, src, accounts, period, fallback)
    oi = amount(accounts, "operating_income")
    am = src.get("amort") or {"depreciation": None, "amortization": None, "combined": None, "note": "비원화" if not src.get("krw", True) else "상각비 미발견", "evidence_ids": []}
    eb = None
    note = am["note"]
    if oi is None:
        note = "계정 없음: 영업이익"
    elif am["combined"] is not None:
        eb = fin_items.ebitda_total(oi, None, None, am["combined"])
    elif am["depreciation"] is not None and am["amortization"] is not None:
        eb = fin_items.ebitda_total(oi, am["depreciation"], am["amortization"])
    inputs = ids_of(accounts, "operating_income") + list(am["evidence_ids"])
    e_ids = b.calc("fin.ebitda", period, "core.calc.fin_items.ebitda_total", {"operating_income": oi, "depreciation": am["depreciation"], "amortization": am["amortization"], "combined": am["combined"]}, eb, inputs or fallback, src["rcept_dt"], src["report_nm"])
    b.metric("fin.ebitda", eb, period, e_ids or fallback, note=note, separate=sep)
    nde = ratios.net_debt_to_ebitda(nd, eb)
    nde_note = "EBITDA 산출 불가" if eb is None else "EBITDA ≤ 0으로 계산 안 함" if eb <= 0 else None
    b.metric("fin.net_debt_to_ebitda", nde, period, b.calc("fin.net_debt_to_ebitda", period, "core.calc.ratios.net_debt_to_ebitda", {"net_debt": nd, "ebitda": eb}, nde, e_ids or fallback, src["rcept_dt"], src["report_nm"]) or fallback, status=("ok" if nde is not None else "missing"), note=nde_note, separate=sep)
    interest, int_note = src.get("interest") or (None, "이자비용 확인 불가: 원문 조회 실패")
    cov, cov_note = ratios.ebitda_interest_coverage(eb, interest, int_note)
    b.metric("fin.ebitda_interest_coverage", cov, period, b.calc("fin.ebitda_interest_coverage", period, "core.calc.ratios.ebitda_interest_coverage", {"ebitda": eb, "interest": interest}, cov, e_ids or fallback, src["rcept_dt"], src["report_nm"]) or fallback, note=cov_note, separate=sep)
    rev = amount(accounts, "revenue")
    mg = ratios.ebitda_margin(eb, rev)
    b.metric("fin.ebitda_margin", mg, period, b.calc("fin.ebitda_margin", period, "core.calc.ratios.ebitda_margin", {"ebitda": eb, "revenue": rev}, mg, e_ids + ids_of(accounts, "revenue") or fallback, src["rcept_dt"], src["report_nm"]) or fallback, separate=sep)
    ocf = amount(accounts, "op_cash_flow")
    b.metric("fin.ttm_operating_cash_flow", ocf, period, ids_of(accounts, "op_cash_flow") or fallback, separate=sep)


def listing_metrics(b: Builder, year: int, src, accounts):
    """상장 규정 입력: 최근 사업연도말."""
    period = f"{year}FY"
    sep = src["fs"] == "OFS"
    fallback = [ev.dart_section(src["rcept_no"], "document")]
    bs = [r for r in src["rows"] if r.get("sj_div") == "BS"]
    eq = fin_items.equity_ex_nci(bs, src["fs"]) if src.get("krw", True) else None
    b.metric("fin.equity_ex_nci", eq, period, ids_of(accounts, "equity_parent" if src["fs"] == "CFS" else "total_equity") or fallback, separate=sep)
    cap = amount(accounts, "capital_stock")
    ratio = ratios.capital_impairment_ratio(cap, eq)
    b.metric("fin.capital_impairment_ratio", ratio, period, b.calc("fin.capital_impairment_ratio", period, "core.calc.ratios.capital_impairment_ratio", {"capital_stock": cap, "equity": eq}, ratio, ids_of(accounts, "capital_stock") or fallback, src["rcept_dt"], src["report_nm"]), separate=sep)


def latest_metrics(b: Builder, latest, accounts, by_year):
    """재무 기본 항목·순차입금은 최신 정기보고서 기준."""
    period = f"{latest['label']}말"
    sep = latest["fs"] == "OFS"
    fallback = [ev.dart_section(latest["rcept_no"], "document")]
    nd, cash, st, cash_note, st_note = balance_basics(b, latest, accounts, period, fallback)
    b.metric("fin.cash_and_equivalents", cash, period, ids_of(accounts, "cash") or fallback, note=cash_note, separate=sep)
    b.metric("fin.short_term_financial_assets", st, period, ids_of(accounts, "st_fin_assets") or fallback, note=st_note, separate=sep)
    is_fy = latest["kind"] == "annual"
    prior = by_year.get(latest["year"] - 1)
    fy_prev = None
    if prior and prior["status"] == "ok" and prior.get("krw", True):
        row = next((x for x in prior["rows"] if x.get("sj_div") == "CF" and x.get("account_id") == "ifrs-full_CashFlowsFromUsedInOperatingActivities"), None)
        fy_prev = fin_items._amt(row) if row else None
    cum = amount(accounts, "op_cash_flow")
    prev_same = latest.get("op_cf_prev_same")
    code = "FY" if is_fy else {"half": "H1", "q1": "1Q", "q3": "3Q"}[latest["kind"]]
    ttm = cashflow.ttm_operating_cash_flow(cum, prev_same, fy_prev, code)
    p = f"TTM {latest['label']}"
    ids = b.calc("fin.ttm_operating_cash_flow", p, "core.calc.cashflow.ttm_operating_cash_flow", {"cum_current": cum, "cum_prev_same": prev_same, "fy_prev": fy_prev, "period": code}, ttm, ids_of(accounts, "op_cash_flow") or fallback, latest["rcept_dt"], latest["report_nm"])
    b.metric("fin.ttm_operating_cash_flow", ttm, p, ids or fallback, separate=sep)


def unknown_year(b: Builder, year: int, src):
    """7장: 그 연도의 모든 지표 unknown."""
    ids = [ev.dart_section(src["rcept_no"], "document")]
    for mid in ("fin.ebitda", "fin.total_borrowings", "fin.net_debt", "fin.net_debt_to_ebitda", "fin.ebitda_interest_coverage", "fin.ebitda_margin", "fin.debt_ratio", "fin.current_ratio", "fin.borrowing_dependency", "fin.ttm_operating_cash_flow"):
        b.metric(mid, None, f"{year}FY", ids, status="unknown", note=UNKNOWN_NOTE)


@guarded
def compute_metrics(state) -> dict:
    """3.2의 Metric을 core.calc 함수로 계산한다 (12장). 근거는 CALC + 입력 근거."""
    src = state.get("sources") or {}
    company, req = state["company"], state["request"]
    by_year = src.get("years") or {}
    if not by_year:
        return {"metrics": [], "classifications": list(state.get("audit") or [])}
    b = Builder(state["run_id"], company["corp_code"], req.as_of)
    years = {y.bsns_year: y for y in state.get("years") or []}
    for year in sorted(by_year, reverse=True):
        s = by_year[year]
        if s["status"] == "unknown":
            unknown_year(b, year, s)
        elif s["status"] == "ok":
            year_metrics(b, year, s, years[year].accounts)
    newest = max(by_year)
    s = by_year[newest]
    ids0 = [ev.dart_section(s["rcept_no"], "document")]
    if s["status"] == "ok":
        listing_metrics(b, newest, s, years[newest].accounts)
    elif s["status"] == "unknown":
        for mid in ("fin.equity_ex_nci", "fin.capital_impairment_ratio"):
            b.metric(mid, None, f"{newest}FY", ids0, status="unknown", note=UNKNOWN_NOTE)
    latest = src.get("latest")
    if latest and latest["status"] == "ok":
        latest_metrics(b, latest, state.get("latest_periodic"), by_year)
    elif latest and latest["status"] == "unknown":
        ids = [ev.dart_section(latest["rcept_no"], "document")]
        for mid, p in (("fin.cash_and_equivalents", f"{latest['label']}말"), ("fin.short_term_financial_assets", f"{latest['label']}말"), ("fin.total_borrowings", f"{latest['label']}말"), ("fin.net_debt", f"{latest['label']}말"), ("fin.debt_ratio", f"{latest['label']}말"), ("fin.ttm_operating_cash_flow", f"TTM {latest['label']}")):
            b.metric(mid, None, p, ids, status="unknown", note=UNKNOWN_NOTE)
    market_period = f"{req.as_of} 기준"
    for mid in MARKET_METRICS:
        b.metric(mid, None, market_period, ids0, note="시장 데이터 없음")
    for mid in DUE_DILIGENCE:
        b.metric(mid, None, f"{newest}FY", ids0, status="needs_due_diligence")
    classes = list(state.get("audit") or [])
    events = state.get("restructuring") or []
    value, note = status_of([{"kind": e.kind, "rcept_dt": e.rcept_dt.isoformat()} for e in events])
    classes.append(Classification(key="fin.restructuring_status", value=value, rule=f"재무 9.3 공시명 완전 일치{'; ' + note if note else ''}", evidence_ids=[e.evidence_ids[0] for e in events] or ids0))
    market = state.get("market")
    classes.append(Classification(key="fin.market_data_source", value=market.source if market else "missing", rule="시장 데이터 경로 (9.4)", evidence_ids=ids0))
    classes.append(Classification(key="fin.fs_basis", value=s.get("fs") or "CFS", rule="연결 우선, 없으면 별도", evidence_ids=ids0))
    return {"metrics": b.metrics, "classifications": classes, "evidence": b.evidence}
