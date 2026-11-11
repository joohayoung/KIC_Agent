import calendar
import re
from datetime import date

from agents.overseas_funding.calc.funding import NOTE_NO_DATE, available_funds, confirmed_funding, find_completion_date, funding_gap, funding_gap_ratio, investment_amount, investment_beyond_24m, investment_dates, investment_within_24m, is_result, judge_funding, liquidity_ratio, liquidity_surplus, liquidity_uses, parse_result, unconfirmed_funding
from agents.overseas_funding.schemas import FinancialSnapshot, FundingGap
from core import catalog
from core import evidence as ev
from core.asof import UNKNOWN_NOTE, to_date
from core.calc import cashflow, fin_items
from core.clients import dart
from core.clients.dart import REPRT_CODES, VIEWER_URL
from core.clients.dart_docs import plain_text
from core.filings import select_reports
from core.nodeguard import guarded
from core.schemas import Evidence, Metric

OCF_ID = "ifrs-full_CashFlowsFromUsedInOperatingActivities"
KIND_CODE = {"annual": "FY", "half": "H1", "q1": "1Q", "q3": "3Q"}


def base_date_of(group) -> date:
    m = re.search(r"\((\d{4})\.(\d{2})\)", re.sub(r"\s", "", group["latest"]["report_nm"]))
    y, mo = int(m.group(1)), int(m.group(2))
    return date(y, mo, calendar.monthrange(y, mo)[1])


def load_rows(client, cc, year, kind, raw, first_dt):
    for fs in ("CFS", "OFS"):
        rows = client.financials(cc, year, REPRT_CODES[KIND_CODE[kind]], fs, raw, first_dt)
        if rows:
            return fs, rows
    return None, []


def amount_of(rows, account_id, field="thstrm_amount"):
    r = next((x for x in rows if x.get("account_id") == account_id and x.get("sj_div") == "CF"), None)
    return fin_items._amount(r, field) if r else None


def confirmed_date_of(item: dict, filings_by_no: dict, client, periodic_no: str | None, as_of) -> dict:
    """확정 날짜 (7.10 4a): 후속 보고서 주석 문장 → 정정 공시 `취득완료` 사유·문장 순서. 근거 문서 접수일을 함께 돌려준다."""
    key = re.split(r"[,(]", item.get("name") or "")[0].strip()
    if periodic_no and key:
        text = plain_text(client.document(periodic_no))
        for m in re.finditer(re.escape(key), text):
            found, quote = find_completion_date(text[m.start(): m.start() + 200])
            if found:
                return {"confirmed_date": found, "confirmed_rcept_dt": filings_by_no[periodic_no].rcept_dt, "confirmed_rcept_no": periodic_no, "quote": quote}
    for no in reversed(item.get("corrections") or []):
        text = plain_text(client.document(no))
        if re.search(r"정정사유\s*취득\s*완료", text[:600]):
            table = re.search(r"취득예정일자\s*\d{4}-\d{2}-\d{2}\s*(\d{4}-\d{2}-\d{2})", text[:1000])      # 정정 표: 정정 전 정정 후
            done = table.group(1) if table else item.get("scheduled_date")
            if done:
                return {"confirmed_date": to_date(done), "confirmed_rcept_dt": filings_by_no[no].rcept_dt, "confirmed_rcept_no": no, "quote": "취득완료에 따른 정정"}
        found, quote = find_completion_date(text)
        if found:
            return {"confirmed_date": found, "confirmed_rcept_dt": filings_by_no[no].rcept_dt, "confirmed_rcept_no": no, "quote": quote}
    return {}


def metric(mid, value, period, ids, *, status=None, note=None) -> Metric:
    c = catalog.get(mid)
    return Metric(metric_id=mid, name=c["name"], value=value, unit=str(c["unit"]), period=period, methodology=c["methodology"], data_status=status or ("ok" if value is not None else "missing"), evidence_ids=list(dict.fromkeys(ids)), note=note)


@guarded
def compute_funding_gap(state) -> dict:
    """as_of 시점 재무로 자금 공백을 계산한다 (7.10). 계산은 전부 코드로 한다. LLM 없음."""
    req, company = state["request"], state["company"]
    cc = company.corp_code
    client = dart.get_client()
    raw = state["raw_filings"]
    by_no = {f.rcept_no: f for f in state["filings"]}
    groups = select_reports(raw)
    questions, evidence, metrics = [], [], []
    if not groups:
        return {"financials": None, "funding_gap": None, "errors": ["compute_funding_gap: 정기보고서 없음"]}
    g = groups[0]
    base = base_date_of(g)
    label = f"{g['year']}{KIND_CODE[g['kind']]}"
    period = f"{req.as_of} 기준"
    fs, rows = load_rows(client, cc, g["year"], g["kind"], raw, g["first_dt"])
    report = g["latest"]
    doc_id = ev.dart_section(report["rcept_no"], "document")
    evidence.append(Evidence(evidence_id=doc_id, source_grade="A", source_type="dart_document", corp_code=cc, published_at=to_date(report["rcept_dt"]), title=report["report_nm"], url=VIEWER_URL.format(rcept_no=report["rcept_no"])))
    unknown = any(r.get("_version") == "unknown" for r in rows)
    krw = all(r.get("currency", "KRW") == "KRW" for r in rows)
    cash = st = ttm = None
    maturing, maturing_note, prior = None, None, None
    dividends, div_note, div_ids = None, "직전 사업보고서 없음", []
    notes = []
    if unknown:
        notes.append(UNKNOWN_NOTE)
    elif not krw:
        notes.append("비원화")
    elif rows:
        bs = [r for r in rows if r.get("sj_div") == "BS"]
        cash, cash_note = fin_items.cash_and_equivalents(bs)
        st, st_note = fin_items.short_term_financial_assets(bs)
        notes += [n for n in (cash_note, st_note) if n and "금액" not in n and (cash is None or st is None)]
        maturing, maturing_note = fin_items.maturing_debt_1y(bs)
        cum, prev_same = amount_of(rows, OCF_ID), amount_of(rows, OCF_ID, "frmtrm_amount")
        fy_prev = None
        prior, prior_rows = (g, rows) if g["kind"] == "annual" else (next((x for x in groups if x["kind"] == "annual" and x["year"] == g["year"] - 1), None), [])
        if prior and prior is not g:
            _, prior_rows = load_rows(client, cc, prior["year"], "annual", raw, prior["first_dt"])
        if prior and prior_rows and not any(r.get("_version") == "unknown" for r in prior_rows) and all(r.get("currency", "KRW") == "KRW" for r in prior_rows):
            fy_prev = amount_of(prior_rows, OCF_ID) if prior is not g else None
            dividends, div_note = fin_items.dividends_paid_last_fy([r for r in prior_rows if r.get("sj_div") == "CF"])
            div_ids = [ev.dart_section(prior["latest"]["rcept_no"], "document")]
            if prior is not g:
                evidence.append(Evidence(evidence_id=div_ids[0], source_grade="A", source_type="dart_document", corp_code=cc, published_at=to_date(prior["latest"]["rcept_dt"]), title=prior["latest"]["report_nm"], url=VIEWER_URL.format(rcept_no=prior["latest"]["rcept_no"])))
        elif prior:
            div_note = "직전 사업보고서 재무 확인 불가"

        ttm = cashflow.ttm_operating_cash_flow(cum, prev_same, fy_prev, KIND_CODE[g["kind"]])
        if ttm is not None and ttm < 0:
            notes.append("TTM 영업현금흐름 음수")
    status = "unknown" if unknown else None
    snapshot = FinancialSnapshot(corp_code=cc, fs_div=fs or "CFS", base_period=label, source_rcept_no=rows[0]["rcept_no"] if rows and not unknown else report["rcept_no"], cash_and_equivalents=cash, short_term_financial_assets=st, ttm_operating_cash_flow=ttm, total_borrowings=None, evidence_ids=[doc_id])
    # 투자액
    project = state.get("projects") or []
    project = [p for p in project if p.get("gate_pass")] or ([] if any("gate_pass" in p for p in project) else project)      # 게이트를 거치지 않은 경로(5·6단계)는 전체
    project = max(project, key=lambda p: p.get("amount_krw") or 0) if project else None
    items = [x for x in state.get("s4_items") or [] if project and x["rcept_no"] in project["rcept_nos"]]
    for x in items:
        x.update(confirmed_date_of(x, by_no, client, report["rcept_no"], req.as_of))
    inv = investment_amount(items, base, req.as_of, mergeable=bool(project and project.get("mergeable")), fallback=project.get("amount_krw") if project else None)
    kept = [x for x, r in zip(items, inv["items"]) if not r["excluded"]]
    if len(kept) > 1 and not (project and project.get("mergeable")):
        questions.append("취득 공시 합산 불명확: " + ", ".join(x["rcept_no"] for x in kept))
    # 조달
    results = []
    for f in state["filings"]:
        if is_result(f.report_nm):
            results.append({**parse_result(plain_text(client.document(f.rcept_no)), f.report_nm), "rcept_no": f.rcept_no, "rcept_dt": f.rcept_dt.strftime("%Y%m%d"), "nm": f.report_nm})
    judged = judge_funding(state.get("funding_decisions") or [], results, req.as_of, base)
    questions += [d["open_question"] for d in judged if d.get("open_question")]
    confirmed, conf_status = confirmed_funding(judged)
    unconfirmed = unconfirmed_funding(judged)
    avail = available_funds(cash, st, ttm, confirmed)
    gap = funding_gap(inv["amount"], avail)
    ratio = funding_gap_ratio(gap, inv["amount"])
    note = "; ".join(notes + ([inv["note"]] if inv["note"] else [])) or None
    gap_status = "unknown" if unknown else None
    ids = [doc_id]
    s4_ids = [i for s in state.get("signals_merged") or state.get("signals") or [] if project and s.signal_id in project["amount_signal_ids"] for i in s.evidence_ids] or ids
    fg = FundingGap(overseas_investment_krw=inv["amount"], investment_amount_source=project["amount_source"] if project else "missing", available_funds_krw=avail, confirmed_funding_krw=confirmed, unconfirmed_funding_krw=unconfirmed, gap_krw=gap, gap_ratio=ratio, note=note, overseas_subsidiary_working_capital_krw=sum(x.get("subsidiary_working_capital") or 0 for x in kept), evidence_ids=ids)
    def calc_id(mid, impl, args, value):
        if value is None:
            return ids
        eid = ev.calc(state["run_id"], mid)
        evidence.append(Evidence(evidence_id=eid, source_grade="A", source_type="calc", corp_code=cc, published_at=req.as_of, title=mid, meta={"impl": impl, "args": args, "value": value, "inputs": ids}))
        return [eid]
    F = "agents.overseas_funding.calc.funding."
    metrics += [
        metric("fin.cash_and_equivalents", cash, f"{label}말", ids, status=status, note=UNKNOWN_NOTE if unknown else None),
        metric("fin.short_term_financial_assets", st, f"{label}말", ids, status=status, note=UNKNOWN_NOTE if unknown else None),
        metric("fin.ttm_operating_cash_flow", ttm, f"TTM {label}", ids, status=status, note=UNKNOWN_NOTE if unknown else None),
        metric("ovs.overseas_investment_amount", inv["amount"], period, s4_ids, note=inv["note"]),
        metric("ovs.confirmed_overseas_funding", confirmed, period, ids, status="unknown" if conf_status == "unknown" else "ok"),
        metric("ovs.unconfirmed_overseas_funding", unconfirmed, period, calc_id("ovs.unconfirmed_overseas_funding", F + "total", {"amounts": [d.get("overseas_amount") or 0 for d in judged if d["final"] in ("미확정", "open_question")]}, unconfirmed)),
        metric("ovs.available_internal_funds", avail, period, calc_id("ovs.available_internal_funds", F + "available_funds", {"cash": cash, "short_term": st, "ttm_ocf": ttm, "confirmed": confirmed}, avail), status=gap_status, note=UNKNOWN_NOTE if unknown else None),
        metric("ovs.funding_gap", gap, period, calc_id("ovs.funding_gap", F + "funding_gap", {"investment": inv["amount"], "available": avail}, gap), status=gap_status, note=note),
        metric("ovs.funding_gap_ratio", ratio, period, calc_id("ovs.funding_gap_ratio", F + "funding_gap_ratio", {"gap": gap, "investment": inv["amount"]}, ratio), status=gap_status, note="투자액 0" if inv["amount"] == 0 else None),
    ]
    # 유동성 원천·소요 (11.3, S&P Liquidity Descriptors 준용 STRIDE 정의). 원천 = 가용 자금과 같은 구성
    mergeable = bool(project and project.get("mergeable"))
    parts = investment_dates(items, inv, mergeable=mergeable, fallback=project.get("amount_krw") if project else None)
    within, beyond = investment_within_24m(parts, str(req.as_of)), investment_beyond_24m(parts, str(req.as_of))
    within_note = NOTE_NO_DATE if any(d is None and a for a, d in parts) else None
    uses = liquidity_uses(within, maturing, dividends)
    surplus, lratio = liquidity_surplus(avail, uses), liquidity_ratio(avail, uses)
    src_why = ", ".join(k for k, v in (("현금및현금성자산", cash), ("단기금융상품", st), ("TTM 영업현금흐름", ttm), ("확정 해외 조달", confirmed)) if v is None) + (f" — {'; '.join(notes)}" if notes else "")
    parts_why = [(k, v, n) for k, v, n in (("원천", avail, src_why or None), ("24개월 내 해외 투자액", within, inv["note"]), ("1년 내 만기 차입금", maturing, maturing_note), ("배당금 지급액", dividends, div_note)) if v is None]
    why = "; ".join(f"{k} 산출 불가" + (f"({n})" if n else "") for k, v, n in parts_why) or None
    uses_why = "; ".join(f"{k} 산출 불가" + (f"({n})" if n else "") for k, v, n in parts_why if k != "원천") or None
    lnote = why or ("소요 0" if uses == 0 else "원천 음수" if avail is not None and avail < 0 else None)
    fy_label = f"{prior['year']}FY" if prior else None
    metrics += [
        metric("ovs.overseas_investment_within_24m", within, period, calc_id("ovs.overseas_investment_within_24m", F + "investment_within_24m", {"parts": parts, "as_of": str(req.as_of)}, within) if parts else s4_ids, note=within_note),
        metric("ovs.overseas_investment_beyond_24m", beyond, period, calc_id("ovs.overseas_investment_beyond_24m", F + "investment_beyond_24m", {"parts": parts, "as_of": str(req.as_of)}, beyond) if parts else s4_ids),
        metric("fin.maturing_debt_1y", maturing, f"{label}말", ids, status=status, note=UNKNOWN_NOTE if unknown else maturing_note),
        metric("fin.dividends_paid_last_fy", dividends, fy_label or "직전 사업연도", div_ids or ids, note=div_note),
        metric("ovs.liquidity_uses", uses, period, calc_id("ovs.liquidity_uses", F + "liquidity_uses", {"investment_24m": within, "maturing_debt": maturing, "dividends": dividends}, uses), note=uses_why),
        metric("ovs.liquidity_surplus", surplus, period, calc_id("ovs.liquidity_surplus", F + "liquidity_surplus", {"sources": avail, "uses": uses}, surplus), status=gap_status, note=lnote),
        metric("ovs.liquidity_sources_to_uses", lratio, period, calc_id("ovs.liquidity_sources_to_uses", F + "liquidity_ratio", {"sources": avail, "uses": uses}, lratio), status=gap_status, note=lnote),
    ]
    metrics = [m for m in state.get("metrics") or [] if m.metric_id == "ovs.overseas_project_count"] + metrics
    return {"financials": snapshot, "funding_gap": fg, "metrics": metrics, "evidence": evidence, "open_questions": questions, "s4_items": [{**x, **r, "confirmed_date": str(x.get("confirmed_date")) if x.get("confirmed_date") else None, "confirmed_rcept_dt": str(x.get("confirmed_rcept_dt")) if x.get("confirmed_rcept_dt") else None} for x, r in zip(items, inv["items"])], "funding_decisions": judged}
