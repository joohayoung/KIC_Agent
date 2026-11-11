from datetime import date

from agents.financial_health.config import ACCOUNTS, ANNUAL_YEARS, LOOKBACK_YEARS
from agents.financial_health.schemas import AccountValue, FinancialYear, PeriodicReport
from core import evidence as ev
from core.asof import to_date
from core.calc import fin_items
from core.clients import dart
from core.clients.dart import VIEWER_URL, DartError
from core.clients.dart_notes import lease_input, read_lease_note
from core.filings import select_reports
from core.nodeguard import guarded
from core.schemas import Evidence
from core.clients.dart import DartQuotaError

PERIOD_LABEL = {"annual": "FY", "half": "H1", "q1": "Q1", "q3": "Q3"}
REPRT = {"annual": "11011", "half": "11012", "q1": "11013", "q3": "11014"}


def doc_evidence(company, rcept_no, rcept_dt, title) -> Evidence:
    return Evidence(evidence_id=ev.dart_section(rcept_no, "document"), source_grade="A", source_type="dart_document", corp_code=company["corp_code"], published_at=to_date(rcept_dt), title=title, url=VIEWER_URL.format(rcept_no=rcept_no))


def note_evidence(company, ids, rcept_dt, title, rcept_no) -> list[Evidence]:
    return [Evidence(evidence_id=i, source_grade="A", source_type="dart_document", corp_code=company["corp_code"], published_at=to_date(rcept_dt), title=title, url=VIEWER_URL.format(rcept_no=rcept_no)) for i in ids]


def load_report(client, company, g, filings, *, zero_lease_ok: bool, read_notes: bool) -> dict:
    """보고서 1건의 재무 행과 주석 판독 결과. status: ok | unknown | none."""
    cc, r = company["corp_code"], g["latest"]
    label = f"{g['year']}{PERIOD_LABEL[g['kind']]}"
    base = {"kind": g["kind"], "year": g["year"], "label": label, "rcept_no": r["rcept_no"], "rcept_dt": r["rcept_dt"], "report_nm": r["report_nm"], "is_correction": g["is_correction"]}
    for fs in ("CFS", "OFS"):
        rows = client.financials(cc, g["year"], REPRT[g["kind"]], fs, filings, g["first_dt"])
        if rows:
            break
    if not rows:
        return {**base, "status": "none", "fs": None, "rows": []}
    if any(x.get("_version") == "unknown" for x in rows):
        return {**base, "status": "unknown", "fs": fs, "rows": []}
    no = rows[0]["rcept_no"]
    dt = next((x["rcept_dt"] for x in filings if x["rcept_no"] == no), r["rcept_dt"])
    out = {**base, "status": "ok", "fs": fs, "rows": rows, "rcept_no": no, "rcept_dt": dt, "krw": all(x.get("currency", "KRW") == "KRW" for x in rows)}
    bs = [x for x in rows if x.get("sj_div") == "BS"]
    try:
        files = client.document(no)
    except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
        raise
    except DartError as e:
        return {**out, "doc_error": str(e)[:100], "lease": None, "amort": None, "interest": (None, "이자비용 확인 불가: 원문 조회 실패"), "tb": (None, "리스 주석 대조 불가", None)}
    lease = lease_input(read_lease_note(files))
    out["lease"] = lease
    out["tb"] = fin_items.total_borrowings(bs, lease, zero_lease_ok=zero_lease_ok)
    if read_notes and out["krw"]:
        out["amort"] = fin_items.amortization_sources(no, files, bs)
        out["interest"] = fin_items.interest_expense([x for x in rows if x.get("sj_div") == "CF"], files)
    elif read_notes:
        out["amort"], out["interest"] = None, (None, "이자비용 확인 불가: 비원화")
    return out


def accounts_of(src: dict, company) -> tuple[dict, list[Evidence]]:
    accounts, evidence = {}, []
    fs, no = src["fs"], src["rcept_no"]
    for key, (sjs, ids) in ACCOUNTS.items():
        row = next((x for x in src["rows"] if x.get("sj_div") in sjs and x.get("account_id") in ids), None)
        if row is None:
            continue
        eid = ev.fin(no, fs, row["account_id"])
        evidence.append(Evidence(evidence_id=eid, source_grade="A", source_type="dart_fin", corp_code=company["corp_code"], published_at=to_date(src["rcept_dt"]), title=src["report_nm"], url=VIEWER_URL.format(rcept_no=no)))
        amount = fin_items._amt(row) if src.get("krw", True) else None
        accounts[key] = AccountValue(key=key, account_id=row["account_id"], account_nm=row.get("account_nm", ""), fs_div=fs, sj_div=row["sj_div"], period_label=src["label"], amount=amount, rcept_no=no, evidence_ids=[eid])
    return accounts, evidence


@guarded
def collect_financials(state) -> dict:
    """as_of 이전 접수 정기보고서를 고르고 재무 계정을 가져온다 (개발문서 8장, 7장 정정 규칙)."""
    req, company = state["request"], state["company"]
    client = dart.get_client()
    bgn = date(req.as_of.year - LOOKBACK_YEARS, 1, 1)
    filings = client.list_filings(req.as_of, bgn, req.as_of, corp_code=company["corp_code"], pblntf_ty="A")
    groups = select_reports(filings)
    if not groups:
        return {"reports": [], "years": [], "latest_periodic": None, "sources": {"years": {}, "latest": None, "unknown_years": [], "filings": filings}, "errors": ["collect_financials: 정기보고서 없음"]}
    annual = [g for g in groups if g["kind"] == "annual"]
    annual.sort(key=lambda g: g["year"], reverse=True)
    annual = annual[:ANNUAL_YEARS]
    reports, years, evidence, questions, by_year, unknown = [], [], [], [], {}, []
    for g in annual:
        src = load_report(client, company, g, filings, zero_lease_ok=True, read_notes=True)
        by_year[g["year"]] = src
        evidence.append(doc_evidence(company, src["rcept_no"] if src["status"] == "ok" else g["latest"]["rcept_no"], src["rcept_dt"], src["report_nm"]))
        if src["status"] != "ok":
            if src["status"] == "unknown":
                unknown.append(g["year"])
            continue
        if src.get("amort"):
            evidence += note_evidence(company, src["amort"]["evidence_ids"], src["rcept_dt"], src["report_nm"], src["rcept_no"])
        accounts, evs = accounts_of(src, company)
        evidence += evs
        ids = [ev.dart_section(src["rcept_no"], "document")]
        years.append(FinancialYear(bsns_year=g["year"], fs_div=src["fs"], accounts=accounts, rcept_no=src["rcept_no"], evidence_ids=ids))
    if len({y.fs_div for y in years}) > 1:
        questions.append("연결·별도 혼재")
    latest_g = groups[0]
    if latest_g["kind"] == "annual" and latest_g["year"] in by_year:
        latest = by_year[latest_g["year"]]
    else:
        prior = next((by_year[g["year"]] for g in annual), None)      # 직전 사업보고서. 금액은 가져오지 않고 판정에만 쓴다 (9.1 3-1)
        zero_ok = bool(prior and prior.get("tb") and prior["tb"][2] == "리스 없음")
        latest = load_report(client, company, latest_g, filings, zero_lease_ok=zero_ok, read_notes=False)
        evidence.append(doc_evidence(company, latest["rcept_no"], latest["rcept_dt"], latest["report_nm"]))
    latest_accounts = None
    if latest["status"] == "ok":
        latest_accounts, evs = accounts_of(latest, company)
        evidence += evs
        row = next((x for x in latest["rows"] if x.get("sj_div") == "CF" and x.get("account_id") == "ifrs-full_CashFlowsFromUsedInOperatingActivities"), None)
        latest["op_cf_prev_same"] = fin_items._amount(row, "frmtrm_amount") if row and latest.get("krw", True) else None
    for g in groups:
        if g in annual or g is latest_g:
            src = by_year.get(g["year"]) if g["kind"] == "annual" else latest
            eid = ev.dart_section(src["rcept_no"], "document")
            reports.append(PeriodicReport(rcept_no=src["rcept_no"], rcept_dt=to_date(src["rcept_dt"]), report_kind=g["kind"], bsns_year=g["year"], reprt_code=REPRT[g["kind"]], is_correction=g["is_correction"], evidence_ids=[eid]))
    return {"reports": reports, "years": years, "latest_periodic": latest_accounts, "sources": {"years": by_year, "latest": latest, "unknown_years": unknown, "filings": filings}, "evidence": evidence, "open_questions": questions}
