"""document.xml ZIP 안에서 연결 주석 구간을 고른다 (재무 건전성 개발문서 9.1a).

ZIP에는 본문(사업·반기·분기보고서)과 첨부 감사보고서가 함께 있을 수 있다. 파일 종류는 파일 이름이 아니라 <DOCUMENT-NAME>으로 판별한다.
연결감사보고서는 쓰고 별도 감사보고서(DOCUMENT-NAME `감사보고서`)는 쓰지 않는다. 정정본 ZIP에는 본문만 있는 경우가 있다.
예외는 별도재무제표만 있음이 확인된 기업이다 (`separate_only`, `note_sources`).
"""
import re

BODY_KINDS = ("사업보고서", "반기보고서", "분기보고서")
CONSOLIDATED_AUDIT = "연결감사보고서"
SEPARATE_AUDIT = "감사보고서"


def doc_kind(xml: str) -> str:
    """<DOCUMENT-NAME> 값(공백 제거). 없으면 빈 문자열."""
    m = re.search(r"<DOCUMENT-NAME[^>]*>(.*?)</DOCUMENT-NAME>", xml, re.S)
    return re.sub(r"\s", "", m.group(1)) if m else ""


def _titles(xml: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), re.sub(r"\s", "", m.group(1))) for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S)]


def body_consolidated_notes(xml: str) -> str:
    """본문의 'N. 연결재무제표 주석' ~ 'N. 재무제표' 구간."""
    t = _titles(xml)
    start = next((s for s, _, x in t if re.fullmatch(r"\d+\.연결재무제표주석", x)), None)
    if start is None:
        return ""
    return xml[start: next((s for s, _, x in t if s > start and re.fullmatch(r"\d+\.재무제표", x)), len(xml))]


def audit_statements(xml: str) -> str:
    """감사보고서의 첨부 재무제표 구간 (TITLE '(첨부)…재무제표' ~ TITLE '주석'). 현금흐름표 조정 행이 본문보다 자세한 경우가 있다."""
    t = _titles(xml)
    i = next((k for k, (_, _, x) in enumerate(t) if x.startswith("(첨부)") and x.endswith("재무제표")), None)
    if i is None:
        return ""
    return xml[t[i][1]: t[i + 1][0] if i + 1 < len(t) else len(xml)]


def audit_notes(xml: str) -> str:
    """감사보고서의 TITLE '주석' ~ 다음 TITLE 구간."""
    t = _titles(xml)
    i = next((k for k, (_, _, x) in enumerate(t) if x == "주석"), None)
    if i is None:
        return ""
    return xml[t[i][1]: t[i + 1][0] if i + 1 < len(t) else len(xml)]


def consolidated_audit_statements(files: dict[str, bytes]) -> str:
    """연결감사보고서의 첨부 연결재무제표 구간. 없으면 빈 문자열."""
    for b in files.values():
        x = b.decode("utf-8", "replace")
        if doc_kind(x) == CONSOLIDATED_AUDIT:
            return audit_statements(x)
    return ""


def consolidated_sources(files: dict[str, bytes], mode: str = "all") -> list[tuple[str, str]]:
    """[(출처 이름, 연결 주석 구간)]. 본문 → 연결감사보고서(첨부 연결재무제표 + 주석) 순서. mode="main"이면 본문만 (수정 전 비교용)."""
    docs = [(doc_kind(b.decode("utf-8", "replace")), b.decode("utf-8", "replace")) for b in files.values()]
    out = [(k, seg) for k, x in docs if k in BODY_KINDS and (seg := body_consolidated_notes(x))]
    if mode == "all":
        out += [(k, audit_statements(x) + seg) for k, x in docs if k == CONSOLIDATED_AUDIT and (seg := audit_notes(x))]
    return out


# ---- 별도재무제표만 있는 기업 (재무 건전성 9.1a, 2026-11-05 결정) ----
_NO_SUBSIDIARY = re.compile(r"연결대상\s*종속회사[^.]{0,40}?해당\s*사항\s*(이\s*)?없")


def separate_only(files: dict[str, bytes]) -> bool:
    """사업보고서가 '연결대상 종속회사 해당사항 없음'이라 하고, ZIP에 연결재무제표가 없음이 모두 확인될 때만 True."""
    docs = [(doc_kind(b.decode("utf-8", "replace")), b.decode("utf-8", "replace")) for b in files.values()]
    body = next((x for k, x in docs if k in BODY_KINDS), None)
    if body is None or any(k == CONSOLIDATED_AUDIT for k, _ in docs) or not _NO_SUBSIDIARY.search(_plain(body)):
        return False
    t = _titles(body)
    start = next((s for s, _, x in t if re.fullmatch(r"\d+\.연결재무제표", x)), None)
    if start is None:
        return True
    end = next((s for s, _, x in t if s > start and re.fullmatch(r"\d+\.재무제표", x)), len(body))
    return "<TABLE" not in body[start:end]


def body_separate_notes(xml: str) -> str:
    """본문의 'N. 재무제표 주석' 절. 절 안에 번호 제목이 많아 SECTION-2 끝까지 본다."""
    start = next((s for s, _, x in _titles(xml) if re.fullmatch(r"\d+\.재무제표주석", x)), None)
    if start is None:
        return ""
    end = xml.find("</SECTION-2>", start)
    return xml[start: end if end >= 0 else len(xml)]


def note_sources(files: dict[str, bytes], mode: str = "all") -> list[tuple[str, str]]:
    """9.1a 출처. separate_only면 본문 재무제표 주석 → 별도 감사보고서, 그 외에는 연결 출처(별도 감사보고서 제외)."""
    if not separate_only(files):
        return consolidated_sources(files, mode)
    docs = [(doc_kind(b.decode("utf-8", "replace")), b.decode("utf-8", "replace")) for b in files.values()]
    out = [(k, seg) for k, x in docs if k in BODY_KINDS and (seg := body_separate_notes(x))]
    if mode == "all":
        out += [(k, audit_statements(x) + seg) for k, x in docs if k == SEPARATE_AUDIT and (seg := audit_notes(x))]
    return out


def attached_statements(files: dict[str, bytes]) -> str:
    """9.1a 출처의 감사보고서 첨부 재무제표 구간."""
    kind = SEPARATE_AUDIT if separate_only(files) else CONSOLIDATED_AUDIT
    return next((audit_statements(x) for b in files.values() if doc_kind(x := b.decode("utf-8", "replace")) == kind), "")


_LEADING_CSS = re.compile(r"^\s*(?:[.#]?[\w-]+(?:\s*,\s*[.#]?[\w-]+)*\s*\{[^{}]*\}\s*)+")


def plain_text(files: dict[str, bytes]) -> str:
    """ZIP 전체를 공백 정리한 문장으로. 거래소 공시 앞의 양식 스타일 코드는 뺀다."""
    x = _plain(" ".join(b.decode("utf-8", "replace") for b in files.values()))
    i = x.rfind(".xforms_input")
    x = x[x.find("}", i) + 1:].strip() if i >= 0 else x
    return _LEADING_CSS.sub("", x, count=1)     # 정정 양식은 앞에 다른 스타일 표가 있다 (api_fields.md 32장)


def body_xml(files: dict[str, bytes]) -> str:
    """본문 XML. 본문 종류가 없으면 첫 파일."""
    docs = [b.decode("utf-8", "replace") for b in files.values()]
    return next((x for x in docs if doc_kind(x) in BODY_KINDS), docs[0] if docs else "")


# ---- 무형자산 변동표 (재무 건전성 9.1a) ----
UNITS = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "십억원": 1_000_000_000, "억원": 100_000_000}
_UNIT_RE = re.compile(r"단위\s*[:：]?\s*(백만원|십억원|천원|억원|원|[A-Z]{3})")
_AMORT = re.compile(r"^(무형(고정)?자산)?(감가)?상각(비|액)?(\(.*\))?$")
_DECREASE = re.compile(r"처분|감소|손상|폐기|제각|매각|대체출|상각")
_HEADER_SKIP = re.compile(r"합계|총계|^계$|구분|과목|당기|전기|단위|기초|기말|공시금액|장부금액|무형자산및영업권")


def _plain(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _table_rows(tbl: str) -> list[list[str]]:
    rows = [[_plain(x) for x in re.findall(r"<T[DEHU][^>]*>(.*?)</T[DEHU]>", tr, re.S)] for tr in re.findall(r"<TR.*?</TR>", tbl, re.S)]
    return [r for r in rows if r]


def _num(s: str) -> int | None:
    """숫자 셀. '-'·빈 칸은 0, 숫자가 아니면 None."""
    x = s.strip().replace(",", "").replace(" ", "")
    if x in ("", "-", "–", "—"):
        return 0
    neg = (x.startswith("(") and x.endswith(")")) or x[0] in "△-"
    x = x.strip("()△-")
    if not re.fullmatch(r"\d+", x):
        return None
    return -int(x) if neg else int(x)


def _norm(s: str) -> str:
    return re.sub(r"\s", "", s)


def _judge(start: int, end: int, moves: list[tuple[str, int]], assets: list[str], unit: int) -> dict:
    """기초·기말·증감(라벨, 값) → 판정. 상각 행이 있으면 그 값, 없으면 영업권만 → 0, 기초 + 증가 − 감소 = 기말이면 0, 아니면 missing."""
    amort = {abs(v) for lab, v in moves if _AMORT.match(lab)}      # 같은 행이 두 번 나오는 표가 있어 값이 같으면 1번만 센다
    if amort:
        return {"status": "amort", "value": sum(amort) * unit, "reason": "변동표 상각 행"}
    if assets and all("영업권" in a for a in assets):
        return {"status": "zero", "value": 0, "reason": "영업권만 있음"}
    total = start + sum(v if v < 0 or not _DECREASE.search(lab) else -v for lab, v in moves)
    if total == end:
        return {"status": "zero", "value": 0, "reason": "변동표에 상각 없음, 기초+증가-감소=기말 일치", "end_krw": end * unit, "unit": unit}
    return {"status": "missing", "value": None, "reason": f"변동표 합계 불일치 (계산 {total:,} / 기말 {end:,})"}


def _rows_mode(rows: list[list[str]], unit: int) -> dict | None:
    """증감이 행에 있는 표: 기초·취득·상각·기말 행, 자산이 열."""
    labs = [next((_norm(c) for c in r if _norm(c)), "") for r in rows]
    s = next((i for i, x in enumerate(labs) if x.startswith("기초")), None)
    if s is None:
        return None
    e = next((i for i in range(s + 1, len(labs)) if labs[i].startswith("기말")), None)
    if e is None:
        return None
    head = [c for r in rows[:s] for c in r]
    hn = [_norm(c) for c in head]
    has_total = any(re.search(r"(합계|총계)$|^계$", x) for x in hn)   # '무형자산 및 영업권 합계' 같은 머리글 포함
    both = any(re.search(r"당기|\(당\)", x) for x in hn) and any(re.search(r"전기|\(전\)", x) for x in hn)
    assets = sorted({c for c in hn if c and not _HEADER_SKIP.search(c)})

    def value(r: list[str]) -> int | None:
        k = next((i for i, c in enumerate(r) if _norm(c)), 0)
        v = [_num(c) for c in r[k + 1:]]
        v = [x for x in v if x is not None]
        if not v:
            return None
        return v[-1] if has_total else v[0] if both or len(v) == 1 else sum(v)

    st, en = value(rows[s]), value(rows[e])
    if st is None or en is None:
        return None
    moves = [(labs[i], value(rows[i])) for i in range(s + 1, e)]
    moves = [(a, b) for a, b in moves if b is not None]
    return _judge(st, en, moves, assets, unit)


def _cols_mode(rows: list[list[str]], unit: int) -> dict | None:
    """증감이 열에 있는 표: 머리글이 기초·취득·기말, 자산이 행."""
    hi = next((i for i, r in enumerate(rows[:4]) if any(_norm(c).startswith("기초") for c in r) and any(_norm(c).startswith("기말") for c in r)), None)
    if hi is None:
        return None
    cols = [_norm(c) for c in rows[hi] if _norm(c) and not re.fullmatch(r"구분|과목|계정과목", _norm(c))]
    body = [r for r in rows[hi + 1:] if len(r) > len(cols)]
    if not body:
        return None
    names = [_norm(r[0]) for r in body]
    total_i = next((i for i, x in enumerate(names) if re.fullmatch(r"합계|총계|계", x)), None)
    vals = [[_num(c) for c in r[-len(cols):]] for r in body]
    if any(x is None for v in vals for x in v):
        return None
    row = vals[total_i] if total_i is not None else [sum(v[i] for v in vals) for i in range(len(cols))]
    si, ei = next(i for i, c in enumerate(cols) if c.startswith("기초")), next(i for i, c in enumerate(cols) if c.startswith("기말"))
    moves = [(c, row[i]) for i, c in enumerate(cols) if i not in (si, ei)]
    return _judge(row[si], row[ei], moves, [x for x in names if not re.fullmatch(r"합계|총계|계", x)], unit)


def intangible_rollforward(seg: str) -> dict:
    """연결 주석 구간에서 무형자산 변동표(당기)를 찾아 상각비를 판정한다.
    반환 {"status": "amort"|"zero"|"missing", "value": 원 또는 None, "reason"}. 표를 못 찾으면 missing."""
    for m in re.finditer(r"<TABLE.*?</TABLE>", seg, re.S):
        ctx = _plain(seg[max(0, m.start() - 320):m.start()])
        rows = _table_rows(m.group(0))
        flat = _norm(" ".join(c for r in rows[:2] for c in r))
        if not (re.search(r"무형자산|영업권", ctx[-160:]) or re.search(r"무형자산|영업권", flat)) or re.search(r"손상|배분|상각방법|내용연수|이연법인세|사용권", ctx[-60:]):
            continue
        if re.search(r"전기\s*(\(단위|$)", ctx[-24:]):
            continue
        um = list(_UNIT_RE.finditer(ctx))
        inner = _UNIT_RE.search(_plain(m.group(0))[:300])
        u = (inner or (um[-1] if um else None))
        u = u.group(1) if u else None
        if u not in UNITS:
            if u:
                return {"status": "missing", "value": None, "reason": f"비원화 변동표 ({u})"}
            continue
        got = _rows_mode(rows, UNITS[u]) or _cols_mode(rows, UNITS[u])
        if got:
            return got
    return {"status": "missing", "value": None, "reason": "변동표 없음"}


def intangible_from_sources(sources: list[tuple[str, str]], bs_values: tuple[int, ...] = ()) -> dict:
    """출처별 변동표 판정을 합친다. 첫 판정을 쓰고, 출처끼리 값이 다르면 missing.
    bs_values: 재무상태표 무형자산 후보 금액. 상각 행 없는 0 판정은 기말이 이 값과 표 단위 안에서 맞을 때만 인정한다(일부 자산만 담은 표를 잡는 것 방지)."""
    got = []
    for name, seg in sources:
        r = intangible_rollforward(seg)
        if r["status"] == "zero" and "end_krw" in r and bs_values and not any(abs(r["end_krw"] - v) <= r["unit"] for v in bs_values):
            r = {"status": "missing", "value": None, "reason": f"변동표 기말과 재무상태표 무형자산이 다름 ({r['end_krw']:,})"}
        if r["status"] != "missing":
            got.append((name, r))
    if not got:
        last = intangible_rollforward(sources[-1][1]) if sources else {"reason": "연결 주석 없음"}
        return {"status": "missing", "value": None, "reason": last["reason"]}
    if len({r["value"] for _, r in got}) > 1:
        return {"status": "missing", "value": None, "reason": "무형자산 변동표 출처끼리 값 다름"}
    return {**got[0][1], "source": got[0][0]}

