"""공시명 정규화·분류 (해외진출 개발문서 8.1.3). 재무 건전성 9.3도 이 정규화 이름을 쓴다."""
import re

CORRECTION_PREFIXES = {"기재정정", "첨부정정", "첨부추가"}
SUBSIDIARY_SUFFIXES = {"종속회사의주요경영사항", "자회사의주요경영사항"}
_SUFFIX = re.compile(r"\((자율공시|종속회사의주요경영사항|자회사의주요경영사항|\d{4}\.\d{2})\)$")


def normalize_report_nm(report_nm: str | None) -> dict:
    """반환 {"norm", "prefixes", "suffixes", "wrapper", "is_correction", "filer_scope"}."""
    s = re.sub(r"\s", "", report_nm or "")
    prefixes = []
    while m := re.match(r"\[([^\]]*)\]", s):
        prefixes.append(m.group(1))
        s = s[m.end():]
    wrapper = None
    if m := re.fullmatch(r"주요사항보고서\((.*)\)", s):
        s, wrapper = m.group(1), "주요사항보고서"
    suffixes = []
    while m := _SUFFIX.search(s):
        suffixes.insert(0, m.group(1))
        s = s[:m.start()]
    s = s.replace("양수결정", "취득결정")
    return {"norm": s, "prefixes": prefixes, "suffixes": suffixes, "wrapper": wrapper, "is_correction": bool(CORRECTION_PREFIXES & set(prefixes)),
            "filer_scope": "subsidiary" if SUBSIDIARY_SUFFIXES & set(suffixes) else "self"}


def classify_filing(report_nm: str | None) -> dict:
    """정규화 + kind·sub_kind. 위에서부터 첫 일치 (8.1.3 표)."""
    n = normalize_report_nm(report_nm)
    s = n["norm"]
    for test, kind, sub in (
        (lambda: "처분결정" in s or "양도결정" in s, "other", "disposal"),
        (lambda: s.startswith("사업보고서"), "periodic", "annual"),
        (lambda: s.startswith("반기보고서"), "periodic", "half"),
        (lambda: s.startswith("분기보고서"), "periodic", "quarter"),
        (lambda: s.startswith("타법인주식및출자증권취득결정"), "major_event", "acquisition_stock"),      # 시작 일치: '기타주요경영사항(…취득결정철회)'는 경보다
        (lambda: s.startswith("유형자산취득결정"), "major_event", "acquisition_asset"),
        (lambda: s.startswith("영업취득결정"), "major_event", "business_transfer"),
        (lambda: s.startswith("신규시설투자등"), "major_event", "new_facility"),
        (lambda: s.startswith("유상증자결정"), "major_event", "rights_issue"),
        (lambda: s.startswith("전환사채권발행결정"), "major_event", "cb"),
        (lambda: s.startswith("신주인수권부사채권발행결정"), "major_event", "bw"),
        (lambda: s == "증권발행실적보고서" or s.startswith(("증권발행결과", "유상증자또는주식관련사채등의발행결과")), "other", "issue_result"),
        (lambda: re.search("연기|철회|해제|해지|취소|변경", s) is not None, "alert", "change"),
        (lambda: s.startswith("자본으로인정되는채무증권발행결정"), "other", "hybrid_capital"),
    ):
        if test():
            return {**n, "kind": kind, "sub_kind": sub}
    return {**n, "kind": "other", "sub_kind": None}


def select_reports(filings) -> list[dict]:
    """목록 → 기간별 보고서 묶음 (접수일 내림차순). 정정은 같은 기간으로 묶어 최신 접수와 원본 접수일을 함께 둔다."""
    rows = []
    for r in filings:
        c = classify_filing(r["report_nm"])
        m = re.search(r"\((\d{4})\.(\d{2})\)$", re.sub(r"\s", "", r["report_nm"]))
        if c["kind"] == "periodic" and m and c["norm"] in ("사업보고서", "반기보고서", "분기보고서"):
            rows.append({**r, "_sub": c["sub_kind"], "_y": int(m.group(1)), "_m": int(m.group(2)), "_corr": c["is_correction"]})
    annual_months = [x["_m"] for x in sorted(rows, key=lambda x: x["rcept_dt"]) if x["_sub"] == "annual"]
    fy_month = annual_months[-1] if annual_months else 12
    groups: dict = {}
    for x in rows:
        offset = (x["_m"] - fy_month) % 12
        kind = "annual" if x["_sub"] == "annual" else "half" if x["_sub"] == "half" else "q1" if offset == 3 else "q3"
        year = x["_y"] if x["_m"] <= fy_month else x["_y"] + 1
        groups.setdefault((kind, year), []).append(x)
    out = []
    for (kind, year), xs in groups.items():
        xs.sort(key=lambda x: (x["rcept_dt"], x["rcept_no"]))
        out.append({"kind": kind, "year": year, "latest": xs[-1], "first_dt": xs[0]["rcept_dt"], "is_correction": xs[-1]["_corr"]})
    return sorted(out, key=lambda g: (g["latest"]["rcept_dt"], g["latest"]["rcept_no"]), reverse=True)
