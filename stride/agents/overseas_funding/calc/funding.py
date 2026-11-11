"""자금 공백 계산 (해외진출 개발문서 7.10 4a, 11.2, 지표 ovs.*). 금액 단위는 원(int). 계산은 전부 코드로 한다."""
import re
from datetime import date

from agents.overseas_funding.config import COUNTRY_ALIASES
from core.asof import to_date

NOTE_INTERNAL = "연결 내부 출자, 집행 시점 확인 불가"
NOTE_ALL_EXCLUDED = "확정 집행 완료분 제외"
_norm = lambda s: re.sub(r"\s", "", s or "")
_num = lambda s: int(s.replace(",", "")) if re.fullmatch(r"-?[\d,]+", (s or "").strip()) else None
FDPP = ("fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc")


def canon_country(name: str | None) -> str | None:
    """국적 칸 표기 통일 (8.1.4 COUNTRY_ALIASES). 표에 없으면 그대로."""
    if not name:
        return None
    n = re.sub(r"\s+", " ", name).strip()
    return COUNTRY_ALIASES.get(n, n)


def is_foreign(country: str | None) -> bool:
    """S1·S2의 해외 여부 (v0.21): 국가가 적혀 있고 대한민국이 아닐 때만. 국가 미상은 해외로 보지 않는다."""
    from agents.overseas_funding.config import KOREA_NAMES
    return bool(country) and not any(k in country for k in KOREA_NAMES)


# ---- 투자액 (7.10 4a) ----
_DATE_PATTERNS = (
    r"\d+차 출자.{0,80}?(\d{4})년 (\d{1,2})월 (\d{1,2})일에 진행",
    r"(\d{4})년 (\d{1,2})월 (\d{1,2})일부로 납입을 완료",
    r"(\d{4})\.\s?(\d{1,2})\.\s?(\d{1,2})\.?\s?일?자로 취득\s?완료",
)


def find_completion_date(text: str) -> tuple[date | None, str | None]:
    """문장에서 납입·출자·취득 완료일을 찾는다. 반환 (날짜, quote). 못 찾으면 (None, None)이고 호출자는 예정일로 처리한다."""
    # ponytail: 차수가 여러 개면 첫 일치만 쓴다. 차수별 금액 대응이 필요하면 공시별 차수 번호까지 읽는다.
    for pat in _DATE_PATTERNS:
        if m := re.search(pat, text or ""):
            y, mo, d = (int(x) for x in m.groups())
            return date(y, mo, d), m.group(0)
    return None, None


def investment_amount(s4: list[dict], base_date: date, as_of: date, *, mergeable: bool = False, fallback: int | None = None) -> dict:
    """프로젝트 대표 투자액. S4 건별로 제외 판정 후 합산한다.

    s4 항목: rcept_no, rcept_dt, amount, relation(회사와 관계 칸), scheduled_date, confirmed_date, confirmed_rcept_dt(확정 날짜 근거 문서 접수일).
    mergeable: 7.8 합산 조건 통과 여부(merge_signals가 판정). False면 남은 건 중 최신 1건.
    fallback: S4가 없을 때의 다음 순위 금액(S5·S1·S2). S4가 있었는데 전부 제외되면 쓰지 않는다.
    반환 {"amount", "note", "items": [{rcept_no, excluded, note}]}.
    """
    if not s4:
        return {"amount": fallback, "note": None, "items": []}
    items, kept = [], []
    for x in s4:
        confirmed = to_date(x.get("confirmed_date"))
        src = to_date(x.get("confirmed_rcept_dt"))
        if confirmed and (src is None or src > as_of):     # 근거 문서가 as_of 뒤면 없는 것으로 본다
            confirmed = None
        excluded = False
        if re.search(r"종속|자회사", x.get("relation") or ""):
            note = NOTE_INTERNAL
        elif confirmed and confirmed <= base_date:
            excluded, note = True, f"재무 기준일 이전 집행 {confirmed}"
        elif confirmed:
            note = f"재무 기준일 이후 집행 {confirmed}"
        else:
            note = f"집행 예정일 {to_date(x.get('scheduled_date'))}, 완료 미확인"
        when = confirmed or to_date(x.get("scheduled_date"))
        items.append({"rcept_no": x["rcept_no"], "excluded": excluded, "note": note, "date": str(when) if when else None})
        if not excluded:
            kept.append(x)
    if not kept:
        return {"amount": 0, "note": NOTE_ALL_EXCLUDED, "items": items}
    if mergeable:
        return {"amount": sum(x["amount"] or 0 for x in kept), "note": None, "items": items}
    return {"amount": max(kept, key=lambda x: x["rcept_dt"])["amount"], "note": None, "items": items}


# ---- 해외 용도 금액 (7.5 6단계) ----
def overseas_amount(slots: dict[str, int | None], scopes: dict[str, str], quotes: dict[str, str] | None = None) -> tuple[int | None, list[str]]:
    """overseas 칸만 합산. mixed·unknown 칸은 제외하고 open_question. overseas 칸이 없으면 None. 세부 내역 문장은 합산하지 않고 원문만 남긴다."""
    total, questions = None, []
    for slot, amount in slots.items():
        if not amount:
            continue
        scope = scopes.get(slot, "unknown")
        if scope == "overseas":
            total = (total or 0) + amount
        elif scope != "domestic":
            questions.append(f"해외 용도 불명 칸: {slot} {amount:,}")
            if quotes and quotes.get(slot):
                questions.append(f"칸 안 세부 내역 (합산 안 함): {quotes[slot]}")
    return total, questions


# ---- 결정 ↔ 결과 공시 (11.2) ----
def strip_nm(nm: str | None) -> str:
    return re.sub(r"^(\[[^\]]*\])+", "", _norm(nm))


def is_result(nm: str | None) -> bool:
    """결과 공시 여부. `(합병등)`과 종속회사 결과는 제외한다."""
    n = strip_nm(nm)
    if re.search(r"종속회사|자회사", n):
        return False
    return n == "증권발행실적보고서" or bool(re.match(r"(증권발행결과|유상증자또는주식관련사채등의발행결과)(\(자율공시\))?", n))


def sec_type(s: str | None) -> tuple[str, str | None]:
    """결과 공시 증권 종류 → (rights|cb|bw|other, 보통|기타|None)."""
    t = _norm(s)
    if re.search(r"파생결합|주가연계|교환사채", t):
        return ("other", None)
    if "신주인수권부사채" in t:
        return ("bw", None)
    if "전환사채" in t:
        return ("cb", None)
    if re.search(r"우선주|종류주|상환전환", t):
        return ("rights", "기타")
    if "보통주" in t or "기명식" in t:
        return ("rights", "보통")
    return ("other", None)


def parse_result(text: str, nm: str) -> dict:
    """결과 공시 원문 → sec, sec_text, planned, actual, pay(YYYYMMDD), board(YYYYMMDD)."""
    t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text))
    if strip_nm(nm) == "증권발행실적보고서":
        amt = re.search(r"구분 발행총액 비고 \S+ ([\d,]+)", t)
        sec = re.search(r"(?:모집|매출) (보통주|우선주|종류주\S*|기타주\S*) [\d,]+", t)
        pays = re.findall(r"(\d{4})년 (\d{2})월 (\d{2})일", t[t.find("납입"):t.find("납입") + 600]) if "납입" in t else []
        kind = sec_type(sec.group(1)) if sec else sec_type(t[:1500])
        return {"sec_text": sec.group(1) if sec else None, "sec": kind, "planned": None, "actual": _num(amt.group(1)) if amt else None,
                "pay": max("".join(p) for p in pays) if pays else None, "board": None}
    g = lambda p: (m.group(1).strip() if (m := re.search(p, t)) else None)
    sec = g(r"증권의 종류 (.*?) 2\. 발행방법")
    return {"sec_text": sec, "sec": sec_type(sec or ""), "planned": _num(g(r"발행예정금액\(원\) ([\d,]+)")), "actual": _num(g(r"실제발행금액\(원\) ([\d,]+)")),
            "pay": (g(r"납입일 (\d{4}-\d{2}-\d{2})") or "").replace("-", "") or None, "board": (g(r"최초 이사회결의일 (\d{4}-\d{2}-\d{2})") or "").replace("-", "") or None}


def decision_amount(kind: str, row: dict) -> int | None:
    """결정 금액: 유상증자 fdpp_* 합, CB·BW bd_fta."""
    if kind == "rights":
        return sum(_num(row.get(f)) or 0 for f in FDPP) or None
    return _num(row.get("bd_fta"))


def decision_sub(kind: str, row: dict) -> str | None:
    if kind != "rights":
        return None
    o, e = _num(row.get("nstk_ostk_cnt")), _num(row.get("nstk_estk_cnt"))
    return "혼합" if o and e else "보통" if o else "기타" if e else None


def link(dec: dict, results: list[dict]) -> tuple[str, dict | None]:
    """결정에 연결할 결과 공시 → (linked | none | amount_mismatch | ambiguous, 결과). 금액은 원 단위 완전 일치만."""
    same = [r for r in results if r["rcept_dt"] >= dec["rcept_dt"] and r["sec"][0] == dec["kind"] and (dec.get("sub") is None or r["sec"][1] == dec["sub"])]
    hit = [r for r in same if r["actual"] == dec["amount"]]
    if len(hit) > 1:
        narrowed = [r for r in hit if r["board"] and r["board"] == dec.get("board")]
        hit = narrowed if len(narrowed) == 1 else hit
    if len(hit) == 1:
        return "linked", hit[0]
    if len(hit) > 1:
        return "ambiguous", None
    near = [r for r in same if r["planned"] == dec["amount"] or (r["board"] and r["board"] == dec.get("board"))]
    return ("amount_mismatch", near[0]) if near else ("none", None)


def _select_results(results: list[dict], as_of: date) -> list[dict]:
    """as_of 이하의 결과 공시만. 정정 공시는 같은 증권·납입일의 앞 공시를 대체한다."""
    keep: list[dict] = []
    for r in sorted((r for r in results if is_result(r["nm"]) and to_date(r["rcept_dt"]) <= as_of), key=lambda x: x["rcept_dt"]):
        if _norm(r["nm"]).startswith("["):
            keep = [k for k in keep if (k["sec"], k["pay"]) != (r["sec"], r["pay"])]
        keep.append(r)
    return keep


def judge_funding(decisions: list[dict], results: list[dict], as_of: date, base_date: date) -> list[dict]:
    """결정 공시별 11.2 판정. decisions 항목: rcept_no, rcept_dt, kind, sub, amount, board, overseas_amount, version(ok|unknown).
    반환 각 항목에 final(확정·합산|확정·현금 반영|미확정|open_question), result, open_question 추가."""
    pool = _select_results(results, as_of)
    out = [dict(d) for d in decisions]
    used: dict[str, list[dict]] = {}
    for d in out:
        d["status"], d["result"] = link(d, pool)
        if d["status"] == "linked":
            used.setdefault(d["result"]["rcept_no"], []).append(d)
    for ds in used.values():
        if len(ds) > 1:      # 결과 1건을 결정 2건이 가리키면 모호
            for d in ds:
                d["status"], d["result"] = "ambiguous", None
    for d in out:
        d["open_question"] = None
        if d["status"] == "linked":
            pay = to_date(d["result"]["pay"])
            if pay is None:
                d["final"], d["open_question"] = "open_question", f"결과 공시 납입일 확인 불가: {d['result']['rcept_no']}"
            else:
                d["final"] = "확정·합산" if pay > base_date else "확정·현금 반영"
        elif d["status"] == "none":
            d["final"] = "미확정"
        elif d["status"] == "ambiguous":
            d["final"], d["open_question"] = "open_question", f"조달 결과 공시 연결 모호: {d['rcept_no']}"
        else:
            r = d["result"]
            d["final"], d["open_question"] = "open_question", f"조달 금액 불일치: 결정 {d['amount']:,} / 결과 {r['actual'] or 0:,}: {r['rcept_no']}"
    return out


def confirmed_funding(judged: list[dict]) -> tuple[int, str]:
    """ovs.confirmed_overseas_funding. 반환 (금액, "ok"|"unknown"). 6.1 unknown 공시는 금액에 넣지 않고 상태를 unknown으로 둔다."""
    unknown = any(d.get("version") == "unknown" for d in judged)
    return sum(d.get("overseas_amount") or 0 for d in judged if d["final"] == "확정·합산" and d.get("version") != "unknown"), "unknown" if unknown else "ok"


def total(amounts: list[int]) -> int:
    """합계. 미확정 조달 calc 근거의 재계산용."""
    return sum(amounts)


def unconfirmed_funding(judged: list[dict]) -> int:
    """ovs.unconfirmed_overseas_funding. 자금 공백에 넣지 않는다."""
    return sum(d.get("overseas_amount") or 0 for d in judged if d["final"] in ("미확정", "open_question"))


# ---- 자금 공백 (11.2) ----
def available_funds(cash: int | None, short_term: int | None, ttm_ocf: int | None, confirmed: int | None) -> int | None:
    """현금 + 단기금융상품 + TTM 영업현금흐름(음수 그대로) + 확정 조달액. 입력 중 하나라도 없으면 None."""
    return None if None in (cash, short_term, ttm_ocf, confirmed) else cash + short_term + ttm_ocf + confirmed


def funding_gap(investment: int | None, available: int | None) -> int | None:
    """해외 투자액 − 가용 자금 (양수 = 부족). 투자액이 없으면 None."""
    return None if investment is None or available is None else investment - available


def funding_gap_ratio(gap: int | None, investment: int | None) -> float | None:
    """공백 / 투자액. 투자액 0·없음이면 None."""
    return None if gap is None or not investment else gap / investment


# ---- 유동성 원천·소요 (S&P Liquidity Descriptors 준용, STRIDE 정의, 개발문서 11.3) ----
HORIZON_MONTHS = 24
NOTE_NO_DATE = "예정일 없음"


def horizon_end(as_of) -> date:
    """as_of + 24개월 (2월 29일은 28일로)."""
    d = to_date(as_of)
    try:
        return d.replace(year=d.year + HORIZON_MONTHS // 12)
    except ValueError:
        return d.replace(year=d.year + HORIZON_MONTHS // 12, day=28)


def investment_dates(s4: list[dict], inv: dict, *, mergeable: bool, fallback: int | None) -> list[list]:
    """투자액에 들어간 건별 [금액, 집행일(YYYY-MM-DD)|None]. 집행일 = 확정일(재무 기준일 이후) → 예정일 순.
    S4가 없으면 [[fallback, None]]. 투자액이 없으면 []."""
    if not s4:
        return [] if fallback is None else [[fallback, None]]
    kept = [(x, r) for x, r in zip(s4, inv["items"]) if not r["excluded"]]
    if not kept:
        return [[0, None]]
    if not mergeable:
        kept = [max(kept, key=lambda xr: xr[0]["rcept_dt"])]
    return [[x["amount"] or 0, r["date"]] for x, r in kept]


def investment_within_24m(parts: list[list], as_of: str) -> int | None:
    """24개월 안 해외 투자액. 집행일 ≤ as_of+24개월이거나 날짜가 없는 건의 합. parts가 비면 None."""
    end = horizon_end(as_of)
    return sum(a for a, d in parts if d is None or to_date(d) <= end) if parts else None


def investment_beyond_24m(parts: list[list], as_of: str) -> int | None:
    """24개월 밖 해외 투자액 (소요에 넣지 않는다)."""
    end = horizon_end(as_of)
    return sum(a for a, d in parts if d is not None and to_date(d) > end) if parts else None


def liquidity_uses(investment_24m: int | None, maturing_debt: int | None, dividends: int | None) -> int | None:
    """소요 = 24개월 안 해외 투자액 + 1년 안 만기 차입금 + 직전 사업연도 배당금 지급액. 하나라도 없으면 None."""
    return None if None in (investment_24m, maturing_debt, dividends) else investment_24m + maturing_debt + dividends


def liquidity_surplus(sources: int | None, uses: int | None) -> int | None:
    """원천 − 소요."""
    return None if sources is None or uses is None else sources - uses


def liquidity_ratio(sources: int | None, uses: int | None) -> float | None:
    """원천 ÷ 소요. 소요 0이면 None (호출자가 note '소요 0'). 원천 음수면 음수 그대로."""
    return None if sources is None or not uses else sources / uses
