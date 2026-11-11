"""재무 항목 계산 (재무 건전성 개발문서 9.1·9.1a·12장). 금액 단위는 원(int)."""
import re

from core.clients.dart_docs import intangible_from_sources, note_sources
from core.clients.dart_notes import read_amortization, read_interest_note

BORROW_IDS = {   # 9.1 차입금·사채 허용목록 (리스부채 제외)
    "ifrs-full_ShorttermBorrowings", "ifrs-full_CurrentPortionOfLongtermBorrowings",
    "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings", "dart_CurrentPortionOfNoncurrentBondsIssued",
    "dart_ConvertibleBonds", "dart_ConvertibleBondsNet", "dart_CurrentPortionOfConvertibleBonds", "ifrs-full_Borrowings",
    "ifrs-full_LongtermBorrowings", "dart_LongTermBorrowingsGross", "ifrs-full_NoncurrentPortionOfNoncurrentBondsIssued",
    "ifrs-full_NoncurrentPortionOfOtherNoncurrentBorrowings",
}
LEASE_IDS = {"current": "ifrs-full_CurrentLeaseLiabilities", "noncurrent": "ifrs-full_NoncurrentLeaseLiabilities"}
DETECT = ("차입", "사채", "유동성장기부채", "리스부채")
ROU_ID = "ifrs-full_RightofuseAssets"
PPE_ROU_ID = "ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets"   # 사용권자산 포함 유형자산 → 사용권자산 신호


def _norm(s) -> str:
    return re.sub(r"\s", "", s or "")


def _amt(r) -> int | None:
    v = (r.get("thstrm_amount") or "").replace(",", "")
    return int(v) if v.lstrip("-").isdigit() else None


def total_borrowings(bs: list[dict], lease_note: dict | None, *, zero_lease_ok: bool) -> tuple[int | None, str | None, str | None]:
    """총차입금 = 차입금·사채 허용목록 행 + 유동·비유동 리스부채 (STRIDE 정의, 9.1 리스부채 채택 규칙).

    bs: fnlttSinglAcntAll 재무상태표 행. lease_note: 같은 보고서 연결 주석에서 읽은 리스부채
    {"has_section": 제목에 '리스'가 있는 절 존재, "current", "noncurrent", "total": 원 또는 None,
     "currency", "unit": 표 단위(대조 허용오차), "context": 표 앞 문장}. 주석을 읽지 못했으면 None.
    zero_lease_ok: 사업보고서는 True. 반기·분기보고서는 직전 사업보고서의 리스부채 출처가 "리스 없음"일 때만 True.
      직전 사업보고서 리스부채 금액을 가져와 더하지 않는다 (판정에만 쓴다).
    반환: (값, note, 리스부채 출처 "재무상태표"|"리스 주석"|"리스 없음").
    """
    det = [r for r in bs if r["account_id"] in BORROW_IDS or r["account_id"] in LEASE_IDS.values()
           or any(k in _norm(r["account_nm"]) for k in DETECT)]
    known = BORROW_IDS | set(LEASE_IDS.values())
    if bad := [r["account_nm"].strip() for r in det if r["account_id"] not in known]:
        return None, f"미분류 차입 계정: {', '.join(bad)}", None
    if blank := [r["account_nm"].strip() for r in det if _amt(r) is None]:
        return None, f"금액 빈 값: {', '.join(blank)}", None
    debt_rows = [r for r in det if r["account_id"] in BORROW_IDS]
    lease_rows = [r for r in det if r["account_id"] in LEASE_IDS.values()]
    debt = sum(_amt(r) for r in debt_rows)
    # 이중 합산 방지: 리스부채가 이미 총차입금 포함 행 안에 있으면 주석 값을 더하지 않는다
    if mixed := [r["account_nm"].strip() for r in debt_rows if "리스" in _norm(r["account_nm"])]:
        return None, f"리스부채가 차입금 행에 포함: {', '.join(mixed)}", None
    note = lease_note if lease_note and lease_note.get("currency") == "KRW" else None
    if lease_rows:
        if note is None:
            return None, "리스 주석 대조 불가", None
        if note.get("current") is None and note.get("noncurrent") is None and note.get("total") is not None:   # 주석에 합계만 있으면 BS 합과 원 단위 일치만 인정
            lease = sum(_amt(r) for r in lease_rows)
            return (debt + lease, None, "재무상태표") if lease == note["total"] else (None, "리스부채 재무상태표·주석 불일치 (합계)", None)
        for side, aid in LEASE_IDS.items():
            vals = [_amt(r) for r in lease_rows if r["account_id"] == aid]
            bv, nv = (sum(vals) if vals else None), note.get(side)
            if (bv, nv) != (None, None) and (bv is None or nv is None or abs(bv - nv) > (note.get("unit") or 1)):
                return None, f"리스부채 재무상태표·주석 불일치 ({side})", None
        return debt + sum(_amt(r) for r in lease_rows), None, "재무상태표"
    if note:
        if host := [r["account_nm"].strip() for r in debt_rows if _norm(r["account_nm"]) in _norm(note.get("context"))]:
            return None, f"리스부채가 총차입금 포함 행에 들어 있음: {', '.join(host)}", None
        if note.get("current") is not None and note.get("noncurrent") is not None:
            return debt + note["current"] + note["noncurrent"], "리스부채 출처: 리스 주석", "리스 주석"
        if note.get("total") is not None:
            return debt + note["total"], "리스부채 출처: 리스 주석 (합계)", "리스 주석"
    if lease_note is not None and not lease_note.get("has_section"):
        if not zero_lease_ok:
            return None, "최신 보고서 리스부채 미공시", None
        rou = next((_amt(r) for r in bs if r["account_id"] == ROU_ID), None)
        if not rou and not any(r["account_id"] == PPE_ROU_ID for r in bs):
            return debt, None if det else "차입금 계정 없음", "리스 없음"
    return None, "리스부채 확인 불가", None


# ---- 1년 안 만기 차입금 · 직전 사업연도 배당금 (유동성 원천·소요, STRIDE 정의) ----
# 유동 차입 표준 계정 (DART 응답 확인, api_fields.md 35장). 리스부채는 넣지 않는다.
CURRENT_DEBT_IDS = {
    "ifrs-full_ShorttermBorrowings", "ifrs-full_CurrentPortionOfLongtermBorrowings", "ifrs-full_CurrentBorrowingsAndCurrentPortionOfNoncurrentBorrowings",
    "dart_CurrentPortionOfNoncurrentBondsIssued", "dart_CurrentPortionOfBonds", "dart_CurrentPortionOfConvertibleBonds", "dart_CurrentPortionOfBondWithWarrant",
    "dart_CurrentPortionOfExchangeableBond", "dart_CurrentLoansReceived", "ifrs-full_CurrentLoansReceivedAndCurrentPortionOfNoncurrentLoansReceived",
    "ifrs-full_CurrentBondsIssuedAndCurrentPortionOfNoncurrentBondsIssued",
}
# 유동·비유동 어느 쪽에도 쓰이는 계정과 표준계정코드 미사용 행은 재무상태표 안 위치(유동부채 절)로 나눈다
SECTION_DEBT_NAME = re.compile(r"^(단기|유동성장기|유동성|유동)?(차입금|차입부채|장기부채|장기차입금|사채|전환사채|신주인수권부사채|교환사채)(및사채)?$")
CURRENT_HEAD, SECTION_END = "ifrs-full_CurrentLiabilities", {"ifrs-full_NoncurrentLiabilities", "ifrs-full_Liabilities", "ifrs-full_Equity", "ifrs-full_EquityAndLiabilities"}


def maturing_debt_1y(bs: list[dict], overrides: dict[str, int] | None = None) -> tuple[int | None, str | None]:
    """fin.maturing_debt_1y = 유동부채 절의 단기차입금 + 유동성장기부채(차입금) + 유동성사채 (리스부채 제외).
    유동 표준 계정은 위치와 관계없이 넣고, 그 밖의 차입·사채 행은 유동부채 절 안에 있을 때 이름 규칙으로 분류한다.
    분류 안 되는 차입 행(리스 포함 행, 이름 규칙 밖, 절을 못 찾음)이나 빈 금액이 있으면 None. 행이 없으면 0.
    overrides: {행 이름: 원} — 빈 금액 행만 채운다 (조사 루프가 찾고 채택 게이트가 원문에서 다시 읽은 값). 분류는 바꾸지 않는다."""
    ov = {_norm(k): v for k, v in (overrides or {}).items()}
    amt = lambda r: _amt(r) if _amt(r) is not None else ov.get(_norm(r["account_nm"]))
    ids = [r["account_id"] for r in bs]
    start = ids.index(CURRENT_HEAD) if CURRENT_HEAD in ids else None
    end = next((i for i in range(start + 1, len(ids)) if ids[i] in SECTION_END), len(ids)) if start is not None else None
    picked, bad = [], []
    for i, r in enumerate(bs):
        nm = _norm(r["account_nm"])
        if r["account_id"] in CURRENT_DEBT_IDS:
            picked.append(r)
            continue
        if r["account_id"] in LEASE_IDS.values() or not any(k in nm for k in ("차입", "사채", "유동성장기부채")):
            continue
        if start is None:
            bad.append(r["account_nm"].strip())
        elif start < i < end:
            if SECTION_DEBT_NAME.match(re.sub(r"\(.*?\)|,.*$", "", nm)) and "리스" not in nm:
                picked.append(r)
            else:
                bad.append(r["account_nm"].strip())
    if bad:
        return None, f"미분류 차입 행: {', '.join(bad)}"
    if blank := [r["account_nm"].strip() for r in picked if amt(r) is None]:
        return None, f"금액 빈 값: {', '.join(blank)}"
    return (sum(amt(r) for r in picked), None) if picked else (0, "유동 차입 행 없음")


DIVIDEND_PAID_IDS = {"ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "ifrs-full_DividendsPaidToEquityHoldersOfParentClassifiedAsFinancingActivities",
                     "ifrs-full_DividendsPaidClassifiedAsOperatingActivities"}
HYBRID_ID = "dart_DividendsPaidToHybridBond"


def dividends_paid_last_fy(cf: list[dict]) -> tuple[int | None, str | None]:
    """fin.dividends_paid_last_fy = 직전 사업보고서 현금흐름표 배당금 지급 행 (지급액은 부호와 관계없이 절댓값).
    표준 계정 행이 없으면 표준계정코드 미사용 '배당금(의) 지급' 행. 수취 행·신종자본증권 배당은 넣지 않는다.
    지급 행이 여럿이면 None, 없으면 0 (note '배당 지급 행 없음')."""
    rows = [r for r in cf if r["account_id"] in DIVIDEND_PAID_IDS]
    if not rows:
        rows = [r for r in cf if r["account_id"] not in DIVIDEND_PAID_IDS | {HYBRID_ID} and re.fullmatch(r"(배당금?의?지급|배당금지급액?)", _norm(r["account_nm"]))]
    if not rows:
        return 0, "배당 지급 행 없음"
    if len(rows) > 1:
        return None, "배당 지급 행 여러 개: " + ", ".join(r["account_nm"].strip() for r in rows)
    v = _amt(rows[0])
    return (abs(v), None) if v is not None else (None, "배당 지급 금액 빈 값")


# ---- 재무 기본 항목 (9.1, 3.2) ----
CASH_ID = "ifrs-full_CashAndCashEquivalents"
ST_ID = "ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents"
OTHER_CURRENT_ID = "ifrs-full_OtherCurrentFinancialAssets"
INTANGIBLE_IDS = ("ifrs-full_IntangibleAssetsOtherThanGoodwill", "ifrs-full_IntangibleAssetsAndGoodwill")


def _bs_amount(bs: list[dict], account_id: str) -> tuple[bool, int | None]:
    r = next((x for x in bs if x["account_id"] == account_id), None)
    return (False, None) if r is None else (True, _amt(r))


def cash_and_equivalents(bs: list[dict]) -> tuple[int | None, str | None]:
    found, v = _bs_amount(bs, CASH_ID)
    return (v, None) if found and v is not None else (None, "계정 없음: 현금및현금성자산")


def short_term_financial_assets(bs: list[dict]) -> tuple[int | None, str | None]:
    """행이 있으면 그 값(빈 금액은 missing). 행 없고 기타유동금융자산도 없으면 0, 기타유동금융자산 행만 있으면 missing."""
    found, v = _bs_amount(bs, ST_ID)
    if found:
        return v, None if v is not None else "단기금융상품 금액 빈 값"
    if _bs_amount(bs, OTHER_CURRENT_ID)[0]:
        return None, "단기금융상품 행 없음, 기타유동금융자산 행 있음"
    return 0, "단기금융상품 행 없음"


def _amount(row: dict, field: str) -> int | None:
    v = (row.get(field) or "").replace(",", "")
    return int(v) if v.lstrip("-").isdigit() else None


def add_amounts(amounts: list[int | None]) -> int | None:
    """합계 근거 재계산용. 하나라도 없으면 None."""
    return None if None in amounts else sum(amounts)


def ebitda_total(operating_income: int | None, depreciation: int | None, amortization: int | None, combined: int | None = None) -> int | None:
    """영업이익 + 감가상각비(사용권 포함) + 무형자산상각비. 합산 행만 있으면 그 합계. 일부 항목만으로 계산하지 않는다."""
    if operating_income is None:
        return None
    if combined is not None:
        return operating_income + combined
    return None if depreciation is None or amortization is None else operating_income + depreciation + amortization


def net_debt(total_borrowings_value: int | None, cash: int | None, short_term: int | None) -> int | None:
    """총차입금 − (현금 + 단기금융상품). 구성 중 missing이 있으면 None."""
    return None if None in (total_borrowings_value, cash, short_term) else total_borrowings_value - cash - short_term


def equity_ex_nci(bs: list[dict], fs_div: str) -> int | None:
    """연결: 지배기업 소유주지분, 별도: 자본총계. 계정 없으면 None."""
    return _bs_amount(bs, "ifrs-full_EquityAttributableToOwnersOfParent" if fs_div == "CFS" else "ifrs-full_Equity")[1]


# ---- 상각비·EBITDA (9.1a, 12장) ----
def _evidence(rcept_no: str, src: dict, section: str) -> list[str]:
    return [f"DART:{rcept_no}:{section}#{x['label']}" for x in src.get("rows", []) if x.get("value_krw") is not None]


def amortization_sources(rcept_no: str, files: dict[str, bytes], bs: list[dict], *, mode: str = "all") -> dict:
    """9.1a: N(비용의 성격별 분류)·C(창출된 현금 조정 또는 현금흐름표)를 표 단위 1개 허용오차로 대조해 채택한다.

    반환 {"depreciation", "amortization", "combined", "status", "note", "sources": {"N", "C"}, "evidence_ids"}.
    combined는 N 합산 행만 있을 때의 감가+무형 합계. 사용권자산상각비는 감가상각비에 포함한 값이다. 비원화는 값을 쓰지 않는다.
    """
    d = read_amortization(files, mode)
    N, C = d.get("N", {}), d.get("C", {})
    out = {"depreciation": None, "amortization": None, "combined": None, "status": None, "note": None, "sources": {"N": N, "C": C},
           "evidence_ids": _evidence(rcept_no, N, "연결주석.비용의성격별분류") + _evidence(rcept_no, C, "연결주석.영업에서창출된현금")}
    if any(x.get("currency") not in (None, "KRW") for x in (N, C)):
        return {**out, "status": "비원화", "note": "비원화"}
    n, cv = N.get("values", {}), C.get("values", {})
    unit = max(N.get("unit") or 1, C.get("unit") or 1)
    close = lambda a, b: a is not None and b is not None and abs(a - b) <= unit
    cdep = None if cv.get("dep") is None else cv["dep"] + (cv.get("rou") or 0)
    dep, amort, status, note = None, None, None, None
    if n.get("combined") is not None and cdep is not None:
        if close(n["combined"] + (n.get("rou") or 0), cdep + (cv.get("amort") or 0)):      # N에 사용권 행이 따로 있으면 합계에 넣어 비교
            dep, amort, status = cdep, cv.get("amort"), "일치(합계)"
        elif close(n["combined"], cdep):
            dep, status = cdep, "일치(합계, 무형 없음)"
        else:
            status = "불일치"
    elif n.get("dep") is not None and cdep is not None:
        # 감가상각비(사용권 포함) 합계끼리 비교한다. N에 사용권 행이 있으면 감가와 사용권을 출처마다 다르게 나눠도 합계만 본다
        same = close(n["dep"] + n["rou"], cdep) if n.get("rou") is not None else close(n["dep"], cdep) or close(n["dep"], cv["dep"])
        if same:
            dep, status = cdep, "일치"      # 사용권 포함 값 채택
        else:
            status = "불일치"
    elif cdep is not None:
        dep, status, note = cdep, "C에만", "상각비 출처: C"
    elif n.get("dep") is not None:
        dep, status, note = n["dep"], "N에만", "상각비 출처: N"
    elif n.get("combined") is not None:
        return {**out, "combined": n["combined"], "status": "N 합산만", "note": "감가+무형 합산 행만 있음(구성 불명)"}
    else:
        status = "미발견"
    if status == "불일치":
        return {**out, "status": status, "note": f"상각비 출처 불일치: N {n} / C {cv}"}
    if amort is None:
        na, ca = n.get("amort"), cv.get("amort")
        if na is not None and ca is not None and not close(na, ca):
            return {**out, "depreciation": dep, "status": "불일치", "note": f"상각비 출처 불일치: N {n} / C {cv}"}
        amort = ca if ca is not None else na
    if amort is None:
        rows = [r for r in bs if r["account_id"] in INTANGIBLE_IDS]
        vs = [_amt(r) for r in rows]
        if not rows or all(v == 0 for v in vs):
            amort, note = 0, "BS 무형자산 없음/0"
        else:
            rf = intangible_from_sources(note_sources(files, mode), tuple(v for v in vs if v))
            if rf["status"] != "missing":
                amort, note = rf["value"], f"무형자산상각비 출처: 변동표 ({rf['reason']})"
            else:
                note = f"무형자산상각비 미공시: {rf['reason']}" if dep is not None else "상각비 미발견"
    elif dep is None:
        note = "상각비 미발견"
    return {**out, "depreciation": dep, "amortization": amort, "status": status, "note": note}


def ebitda(year, sources: dict) -> tuple[int | None, list[str], str | None]:
    """EBITDA = 영업이익 + 감가상각비(사용권 포함) + 무형자산상각비 (STRIDE 정의). year.accounts["operating_income"].amount, sources = amortization_sources 결과.
    반환 (값, evidence_id, note). 일부 항목만으로 계산하지 않는다."""
    op = year.accounts.get("operating_income")
    if op is None or op.amount is None:
        return None, [], "계정 없음: 영업이익"
    ids = list(op.evidence_ids) + list(sources["evidence_ids"])
    if sources["combined"] is not None:
        return op.amount + sources["combined"], ids, sources["note"]
    if sources["depreciation"] is None or sources["amortization"] is None:
        return None, [], sources["note"]
    return op.amount + sources["depreciation"] + sources["amortization"], ids, sources["note"]


def interest_expense(cf_rows: list[dict], files: dict[str, bytes], *, krw: bool = True, mode: str = "all") -> tuple[int | None, str | None]:
    """이자비용 (9.1a). 현금흐름 조정 행 → 주석 표 일치. 반환 (값, note). 금융비용 합계·이자 지급액으로 대체하지 않는다."""
    r = next((x for x in cf_rows if x["account_id"] == "dart_AdjustmentsForInterestExpenses" and x.get("sj_div", "CF") == "CF"), None)
    if any(x.get("currency", "KRW") != "KRW" for x in cf_rows):
        return None, "이자비용 확인 불가: 비원화"
    if r is not None and _amt(r) is not None:
        return _amt(r), None
    got = read_interest_note(files, krw, mode)
    if got["value"] is not None:
        return got["value"], f"이자비용 출처: {got['route']} 주석"
    return None, f"이자비용 확인 불가: {got['reason']}"
