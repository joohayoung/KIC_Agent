"""사업보고서 주석 판독: 상각비 N·C(재무 건전성 9.1a), 리스부채(9.1), 이자비용(9.1a).

scripts/probe_amortization·probe_lease_note·probe_interest_note에서 옮겼다. 출처는 dart_docs.note_sources. 값 채택 판단은 core/calc/fin_items.py에 있다.
"""
import re
from collections import Counter

from core.clients.dart_docs import UNITS, _UNIT_RE as UNIT_RE, attached_statements, body_xml, note_sources, separate_only


# ---- 공통 ----
def num(s: str) -> int | None:
    s = s.strip().replace(",", "").replace(" ", "")
    if s in ("", "-", "–", "—"):
        return None
    neg = s.startswith("(") and s.endswith(")") or s.startswith("△") or s.startswith("-")
    s = s.strip("()△-")
    if not re.fullmatch(r"\d+(\.\d+)?", s):
        return None
    v = float(s)
    return int(-v if neg else v)


def classify(label: str) -> str | None:
    t = re.sub(r"\s", "", label)
    if "대손" in t or "환입" in t:
        return None
    if "사용권" in t and "상각" in t:
        return "rou"
    if re.match(r"무형(고정)?자산(감가)?상각", t):      # '무형자산감가상각'은 합산 행이 아니라 무형자산상각비다
        return "amort"
    if "감가상각" in t:
        if "무형" in t or "상각" in t.replace("감가상각", ""):
            return "combined"                   # 감가상각비및무형자산상각비, 감가상각비와 기타상각 등: 나눌 수 없음
        return None if "투자부동산" in t else "dep"
    if re.search("무형(고정)?자산", t) and "상각" in t:
        return "amort"
    return None


# ---- 상각비 (9.1a) ----


def section(seg: str, heading: str) -> str:
    """제목(TITLE 태그 또는 본문 'N. 제목')부터 다음 제목 전까지."""
    m = re.search(rf"<TITLE[^>]*>\s*\d+\.\s*[^<]*?{heading}[^<]*</TITLE>", seg) or \
        re.search(rf"(?<![\d.])\d{{1,2}}\.\s*(?:<[^>]+>\s*)*[^<]{{0,20}}?{heading}", seg)
    if not m:
        return ""
    rest = seg[m.end():]
    nxt = re.search(r"<TITLE[^>]*>\s*\d+\.|(?<![\d.(])\b\d{1,2}\.\s+[가-힣]", re.sub(r"<TABLE.*?</TABLE>", lambda x: " " * len(x.group(0)), rest, flags=re.S))
    return rest[: nxt.start()] if nxt else rest[:60000]


def row_label(r: list[str]) -> tuple[str | None, int]:
    """숫자 셀 앞의 텍스트 셀 중 분류되는 것 (첫 칸이 묶음 제목인 표 대응). (라벨, 라벨 칸 위치)."""
    for i, x in enumerate(r):
        if num(x) is not None or x in ("-", ""):
            break
        if classify(x):
            return x, i
    return None, -1


def amounts_after(r: list[str], li: int, header: list[list[str]]) -> list[int]:
    """라벨 뒤 금액들. 머리글에 주석 열이 있으면 주석 번호(값 3개 이상일 때 첫 값이 1,000 미만)를 뺀다."""
    nums = [num(x) for x in r[li + 1:] if num(x) is not None]
    has_note_col = any(re.sub(r"\s", "", x) in ("주석", "주") for h in header for x in h)
    return nums[1:] if has_note_col and len(nums) >= 3 and abs(nums[0]) < 1000 else nums


def pick(tbl) -> dict:
    """상각 행의 당기 값. 앞 3행 머리글에 '합계' 열이 있으면 그 열(기능별 열이 있는 표), 없으면 라벨 뒤 첫 숫자 셀."""
    if not tbl:
        return {"values": {}, "rows": [], "currency": None}
    tot, hdr_len = None, None
    for h in tbl["rows"][:3]:
        idx = [i for i, x in enumerate(h) if re.sub(r"\s", "", x) in ("합계", "계")]
        if idx and len(h) > 2:
            tot, hdr_len = idx[0], len(h)
            break
    got, seen = {}, []
    for r in tbl["rows"]:
        lab, li = row_label(r)
        if not lab:
            continue
        k = classify(lab)
        if tot is not None and len(r) == hdr_len:
            v, col = num(r[tot]), "합계"
        else:
            v, col = next(iter(amounts_after(r, li, tbl["rows"][:3])), None), "첫 숫자"
        val = v * tbl["unit"] if (v is not None and tbl["unit"]) else None
        seen.append({"label": lab, "kind": k, "raw": v, "value_krw": val, "col": col})
        if val is not None and k not in got:
            got[k] = val
    return {"values": got, "rows": seen, "currency": tbl["currency"], "unit": tbl["unit"]}


def first_table(sec: str):
    """구간 안에서 상각 행이 있는 첫 표 (XBRL 렌더링형은 당기 표가 먼저). (단위, 통화, 행[])."""
    for tm in re.finditer(r"<TABLE.*?</TABLE>", sec, re.S):
        tbl = tm.group(0)
        rows = []
        for tr in re.findall(r"<TR.*?</TR>", tbl, re.S):
            cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()
                     for x in re.findall(r"<T[DEHU][^>]*>(.*?)</T[DEHU]>", tr, re.S)]
            if cells:
                rows.append(cells)
        if not any(row_label(r)[0] for r in rows):
            continue
        before = re.sub(r"<[^>]+>", " ", sec[:tm.start()])[-400:] + " " + re.sub(r"<[^>]+>", " ", tbl)[:400]
        um = UNIT_RE.search(before)
        u = um.group(1) if um else None
        return {"unit": UNITS.get(u), "currency": "KRW" if (u in UNITS) else u, "rows": rows}
    return None


def face_cf(xml: str, separate: bool = False) -> str:
    """본문 III장의 현금흐름표 (주석에 조정 내역이 없는 회사용). 별도 기준이 확인된 기업만 별도 현금흐름표."""
    titles = [(m.start(), m.end(), re.sub(r"\s", "", m.group(1))) for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S)]
    i = next((k for k, (_, _, t) in enumerate(titles) if re.fullmatch(r"\d-\d\.현금흐름표" if separate else r"\d-\d\.연결현금흐름표", t)), None)
    if i is None:
        return ""
    return xml[titles[i][1]: titles[i + 1][0] if i + 1 < len(titles) else len(xml)]


N_HEADS = (r"성격별\s*분류", r"성격별\s*비용", r"비용의\s*성격")
C_HEADS = (r"영업(?:활동)?(?:으로부터|에서)\s*창출된\s*현금", r"수익\s*[ㆍ·및]?\s*비용의?\s*조정", r"현금흐름표")


def read_amortization(files: dict[str, bytes], mode: str = "all") -> dict:
    """9.1a. 주석 출처(note_sources)에서 N·C 상각 행을 읽는다. 채택 판단은 fin_items.amortization_sources가 한다."""
    sources = note_sources(files, mode)
    if not sources:
        return {"error": "연결재무제표 주석 구간 없음"}
    N, C, n_found = {"values": {}, "rows": [], "currency": None}, {"values": {}, "rows": [], "currency": None}, False
    for name, seg in sources:
        if not N["values"]:
            n_sec = next((s for h in N_HEADS if (s := section(seg, h))), "")
            n_found = n_found or bool(n_sec)
            cand = pick(first_table(n_sec))
            if cand["values"] or (cand["currency"] not in (None, "KRW") and not N["currency"]):    # 비원화 표는 값 없이 통화만 남겨 채택 단계에서 missing으로 처리한다
                N = {**cand, "where": name}
    for name, seg in sources:
        c_note = next((t for h in C_HEADS if (t := first_table(section(seg, h)))), None)
        cand = pick(c_note)
        if {"dep", "combined"} & set(cand["values"]):
            C = {**cand, "where": f"주석({name})"}
            break
        if (cand["values"] and not C["values"]) or (cand["currency"] not in (None, "KRW") and not C["currency"]):
            C = {**cand, "where": f"주석({name})"}
    if not ({"dep", "combined"} & set(C["values"])):      # 주석에 감가상각 행이 없으면 본문 값만 쓴다 (사용권 행만 있는 주석과 섞지 않음)
        F = pick(first_table(face_cf(body_xml(files), separate_only(files))))
        if F["values"] or not C["values"]:
            C = {**F, "where": "현금흐름표 본문"}
        if mode == "all" and not ({"dep", "combined"} & set(C["values"])):   # 본문 현금흐름표가 요약이면 감사보고서 첨부 현금흐름표
            A = pick(first_table(attached_statements(files)))
            if {"dep", "combined"} & set(A["values"]):
                C = {**A, "where": "감사보고서 첨부 현금흐름표"}
    return {"N": {**N, "found_section": n_found}, "C": C, "notes_chars": sum(len(s) for _, s in sources), "sources": [k for k, _ in sources]}


# ---- 리스부채 (9.1) ----
def lease_kind(label: str) -> str | None:
    t = re.sub(r"\s", "", label)
    if "리스부채" not in t:
        return None
    if any(k in t for k in ("이자", "상환", "지급", "증가", "감소", "변동", "기초", "할인", "현재가치", "만기", "미할인")):
        return None
    if "비유동" in t:
        return "noncurrent"
    if "유동" in t:
        return "current"
    if t in ("리스부채", "리스부채합계", "리스부채계"):
        return "total"
    return None


def _lease_sections(seg: str):
    """제목에 '리스'가 있는 절 후보 (TITLE 태그 또는 본문 'N. …리스…')."""
    heads = [m for m in re.finditer(r"<TITLE[^>]*>\s*\d+\.\s*[^<]*리스[^<]*</TITLE>", seg)]
    heads += [m for m in re.finditer(r"(?<![\d.])\d{1,2}\.\s*(?:<[^>]+>\s*)*[^<\d]{0,15}리스", seg)]
    for m in sorted(heads, key=lambda x: x.start()):
        rest = seg[m.end(): m.end() + 80000]
        nxt = re.search(r"<TITLE[^>]*>\s*\d+\.|(?<![\d.(])\b\d{1,2}\.\s+[가-힣]",
                        re.sub(r"<TABLE.*?</TABLE>", lambda x: " " * len(x.group(0)), rest, flags=re.S))
        yield rest[: nxt.start()] if nxt else rest


SKIP_HDR = ("기초", "증가", "감소", "상환", "1년", "이내", "미할인", "만기", "재무현금흐름", "신규")


def table_rows(tbl: str):
    rows = [[re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", x)).strip()
             for x in re.findall(r"<T[DEHU][^>]*>(.*?)</T[DEHU]>", tr, re.S)]
            for tr in re.findall(r"<TR.*?</TR>", tbl, re.S)]
    return [r for r in rows if r]


def _read_lease_table(rows):
    """한 표에서 당기말 유동·비유동·합계 리스부채. 형태 A(행 라벨), B(유동/비유동 열), C(유동부채/비유동부채 묶음)."""
    hdr = " ".join(" ".join(r) for r in rows[:3])
    if any(k in hdr for k in SKIP_HDR):
        return {}
    got = {}
    # 형태 B: 머리글 행에 유동·비유동 열
    for hi, h in enumerate(rows[:3]):
        hs = [re.sub(r"\s", "", x) for x in h]
        if "유동" in hs and "비유동" in hs:
            ci, cn = hs.index("유동"), hs.index("비유동")
            for r in rows[hi + 1:]:
                if re.sub(r"\s", "", r[0]).startswith("리스부채"):
                    off = len(r) - len(h)
                    if 0 <= off <= 1 and ci + off < len(r) and cn + off < len(r):
                        got = {"current": num(r[ci + off]), "noncurrent": num(r[cn + off]), "form": "B"}
                    break
            if got:
                return got
    # 형태 A·C
    state = None
    for r in rows:
        cells = [re.sub(r"\s", "", x) for x in r]
        if any(x in ("유동부채", "유동") for x in cells):
            state = "current"
        if any(x in ("비유동부채", "비유동") for x in cells):
            state = "noncurrent"
        kinds = [(lease_kind(x), i) for i, x in enumerate(r) if lease_kind(x)]
        if not kinds:
            continue
        spec = [ki for ki in kinds if ki[0] in ("current", "noncurrent")]
        k, i = spec[0] if spec else kinds[0]
        if k == "total" and state and cells[i] == "리스부채":
            k, form = state, "C"
        else:
            form = "A"
        v = next((num(x) for x in r[i + 1:] if num(x) is not None), None)
        if v is not None and k not in got:
            got[k] = v
            got["form"] = form
    return got


def _scan_lease(seg: str):
    """연결 주석의 모든 표를 순서대로 보고 유동·비유동이 둘 다 나온 첫 표, 없으면 값이 나온 첫 표."""
    first = None
    for tm in re.finditer(r"<TABLE.*?</TABLE>", seg, re.S):
        rows = table_rows(tm.group(0))
        if any(re.sub(r"\s", "", x) == "주석" for h in rows[:3] for x in h):      # 첨부 재무제표(주석 번호 열)는 주석 표가 아니다. '14, 39, 42'를 금액으로 읽는다
            continue
        got = _read_lease_table(rows)
        if not any(k in got for k in ("current", "noncurrent", "total")):
            continue
        prev = list(UNIT_RE.finditer(re.sub(r"<[^>]+>", " ", seg[:tm.start()])[-400:]))     # 표에 가장 가까운 단위 표기
        inner = UNIT_RE.search(re.sub(r"<[^>]+>", " ", tm.group(0))[:400])
        u = (inner or (prev[-1] if prev else None))
        u = u.group(1) if u else None
        unit, cur = UNITS.get(u), ("KRW" if u in UNITS else u)
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg[max(0, tm.start() - 300):tm.start()]))[-80:]
        rec = {"values": {k: v * unit for k, v in got.items() if k != "form" and v is not None and unit},
               "raw": {k: v for k, v in got.items() if k != "form"}, "form": got.get("form"),
               "currency": cur, "unit": unit, "context": title}
        if "current" in got and "noncurrent" in got:
            return rec
        first = first or rec
    return first

def lease_input(rep: dict) -> dict | None:
    """read_lease_note 결과 → fin_items.total_borrowings 입력. 주석을 읽지 못했으면 None."""
    if not rep.get("has_notes"):
        return None
    n = rep.get("note") or {}
    v = n.get("values", {})
    return {"has_section": rep["has_section"], "current": v.get("current"), "noncurrent": v.get("noncurrent"), "total": v.get("total"),
            "currency": n.get("currency", "KRW"), "unit": n.get("unit"), "context": n.get("context", "")}


def read_lease_note(files: dict[str, bytes], mode: str = "all") -> dict:
    """한 보고서(사업·반기·분기) 주석에서 리스부채 (9.1). has_section: 제목에 '리스'가 있는 절 존재 여부."""
    sources = note_sources(files, mode)
    has = lambda x: x and ("current" in x["raw"] or "noncurrent" in x["raw"])
    has_section = False
    L = None
    for name, seg in sources:                             # 1순위: 제목에 '리스'가 있는 절
        for sec in _lease_sections(seg):
            has_section = True
            cand = _scan_lease(sec)
            if has(cand):
                cand["where"] = f"리스 절({name})"
                return {"has_notes": True, "has_section": True, "note": cand}
            L = L or cand
    for name, seg in sources:                             # 2순위: 연결 주석 전체 표
        cand = _scan_lease(seg)
        if has(cand) or (cand and not L):
            cand["where"] = f"주석 전체 검색({name})"
            L = cand
            if has(cand):
                break
    return {"has_notes": bool(sources), "has_section": has_section, "note": L}


# ---- 이자비용 (9.1a) ----
LABEL = re.compile(r"^이자비용(\(금융원가\)|에대한조정|조정)?(\(\*?\d+\))?$")
SKIP_CTX = re.compile(r"퇴직|확정급여|리스|특수관계|사채의변동|전환사채")
FIN = re.compile(r"금융(원가|비용)")
CF_ADJ = re.compile(r"현금흐름표|영업활동현금흐름|수익.?비용의?조정|창출된현금|조정내역")


def _pick_interest(r, k, header):
    """이자비용 행의 당기 값. 합계 열이 있으면 합계, 값이 1개면 그 값, 당기·전기 2열이면 첫 값. 그 외(범주별 열만)는 None."""
    h = re.sub(r"\s", "", " ".join(header))
    nums = [num(x) for x in r[k + 1:] if num(x) is not None]
    if "주석" in h and len(nums) >= 3 and abs(nums[0]) < 1000:      # 주석 번호 열
        nums = nums[1:]
    if not nums:
        return None
    if "합계" in h:
        return abs(nums[-1])
    nz = [n for n in nums if n != 0]
    if len(nz) <= 1:
        return abs(nz[0]) if nz else 0
    years = [int(x) for x in header if re.fullmatch(r"\s*20\d\d\s*", x)][:2]   # 머리글이 '2025 2024'인 표
    both = (re.search(r"당기|\(당\)", h) and re.search(r"전기|\(전\)", h)) or (len(years) == 2 and years[0] > years[1])
    return abs(nums[0]) if both and len(nums) == 2 else None


def read_interest_note(files: dict[str, bytes], krw: bool = True, mode: str = "all") -> dict:
    """주석 이자비용 (9.1a). 출처(본문, 감사보고서)마다 따로 표를 센다. 같은 표가 두 출처에 있어도 2표로 세지 않는다.
    반환 {"value", "reason", "fin_values", "counts", "source", "route"}. route = "금융원가" | "현금흐름 조정" | None."""
    sources = note_sources(files, mode)
    results = [(name,) + _one_source(seg, krw) for name, seg in sources]
    hits = sorted((r for r in results if r[1]), key=lambda r: r[5])      # 표 단위가 작은(더 자세한) 출처 값을 쓴다
    if hits and any(abs(r[1] - hits[0][1]) > r[5] for r in hits):         # 본문 원 단위와 감사보고서 천원 단위의 반올림 차이는 같은 값
        return {"value": None, "reason": "출처끼리 값 다름", "fin_values": [], "counts": {}, "source": None, "route": None}
    if hits:
        h = hits[0]
        return {"value": h[1], "reason": "두 표 일치", "fin_values": h[3], "counts": h[4], "source": h[0], "route": "금융원가" if h[3] else "현금흐름 조정"}
    best = next((r for r in results if r[3]), results[0] if results else None)
    if not best:
        return {"value": None, "reason": "표 없음", "fin_values": [], "counts": {}, "source": None, "route": None}
    why = "이자비용 행 없음(차입원가 자본화 있음)" if best[2] == "표 없음" and any(_capitalized(seg) for _, seg in sources) else best[2]
    return {"value": None, "reason": why, "fin_values": best[3], "counts": best[4], "source": None, "route": None}


def _capitalized(seg):
    """주석에 '자본화된 차입원가' 행의 당기 값이 있는가 (재무 9.1a, 2026-11-06 결정). '-'·0은 없음으로 본다."""
    m = re.search(r"자본화(?:된|한)\s*차입원가\s*([\d,]{5,})", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg)))
    return bool(m and int(m.group(1).replace(",", "")))


def _one_source(seg, krw):
    found = []
    for m in re.finditer(r"<TABLE.*?</TABLE>", seg, re.S):
        rows = table_rows(m.group(0))
        before = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", seg[max(0, m.start() - 1500):m.start()]))   # 표 태그가 길어 원문 300자로는 제목에 못 닿는 경우가 있다
        ctx = before[-90:]
        if SKIP_CTX.search(re.sub(r"\s", "", ctx)) or re.search(r"전기\s*\(단위", ctx):
            continue
        for r in rows:
            k = next((i for i, x in enumerate(r[:3]) if LABEL.match(re.sub(r"\s", "", x))), None)
            if k is None or (k == 1 and re.sub(r"\s", "", r[0]).startswith("이자비용")):
                continue
            v = _pick_interest(r, k, [x for h in rows[:3] for x in h])
            if v is None:
                continue
            inner = UNIT_RE.search(re.sub(r"<[^>]+>", " ", m.group(0))[:300])
            um = list(UNIT_RE.finditer(before))
            u = (inner or (um[-1] if um else None))
            u = u.group(1) if u else None
            if u not in UNITS:
                continue
            found.append({"value": v * UNITS[u], "unit": UNITS[u], "fin": bool(FIN.search(ctx) or any(FIN.search(x) for row in rows for x in row[:2])), "cf": bool(CF_ADJ.search(re.sub(r"\s", "", ctx)))})
            break
    cnt = Counter(f["value"] for f in found if f["value"])
    fin_vals = [f["value"] for f in found if f["fin"] and f["value"]]
    agreed = next((v for v in fin_vals if cnt[v] >= 2), None)
    if agreed is None and not fin_vals:     # 금융표에 이자비용 행이 없으면 현금흐름 조정 표 + 다른 표 일치 (v0.17, 2026-11-05 결정)
        agreed = next((f["value"] for f in found if f["cf"] and f["value"] and cnt[f["value"]] >= 2), None)
    reason = "두 표 일치" if agreed else "비원화" if not krw else "표끼리 값 다름" if len(cnt) >= 2 and fin_vals else "표 1개뿐" if fin_vals else "표 없음"
    return agreed, reason, fin_vals, dict(cnt), next((f["unit"] for f in found if f["value"] == agreed), 1)
