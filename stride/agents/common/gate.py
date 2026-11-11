"""채택 게이트 (2026-11-10 자율성 지시 3). 조사 루프가 찾은 값은 바로 쓰지 않는다.

루프는 포인터(접수번호·표 제목 낱말·행 이름)와 표에 적힌 그대로의 숫자(claimed_raw, 단위 환산 없음)를 낸다. 이 모듈이 같은 접수번호 원문에서 그 표·행을 다시 읽고
  1) 기대 보고서(기간)와 접수번호가 같고  2) 원화 단위 표이고  3) 연결/별도가 기대와 같고  4) 당기 열(첫 금액)이며  5) 읽은 숫자와 claimed_raw가 같을 때만
채택한다. 채택 값은 코드가 읽은 값이다. LLM 출력의 숫자는 쓰지 않는다.
"""
import re

from core.clients import dart
from core.clients.dart_docs import UNITS, _UNIT_RE as UNIT_RE, body_xml, consolidated_audit_statements
from core.clients.dart_notes import amounts_after, num, table_rows
from core.clients.dart import DartQuotaError

_n = lambda s: re.sub(r"\s|\(.*?\)|[ㆍ·.,]", "", s or "")


def _tables(xml: str, scope_default: str | None):
    """(scope, 표 앞 글, 표 XML, 단위 표기)를 문서 순서대로. scope는 가장 가까운 앞 제목에 '연결'이 있으면 CFS, 없으면 OFS."""
    titles = [(m.start(), re.sub(r"\s", "", re.sub(r"<[^>]+>", "", m.group(1)))) for m in re.finditer(r"<TITLE[^>]*>(.*?)</TITLE>", xml, re.S)]
    for tm in re.finditer(r"<TABLE.*?</TABLE>", xml, re.S):
        head = [t for p, t in titles if p < tm.start()]
        scope = scope_default or ("CFS" if head and "연결" in head[-1] else "OFS")
        before = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", xml[max(0, tm.start() - 2000): tm.start()]))[-400:]      # 단위만 적힌 표·제목 문장 포함
        units = list(UNIT_RE.finditer(before)) or list(UNIT_RE.finditer(re.sub(r"<[^>]+>", " ", tm.group(0))[:400]))
        yield scope, (head[-1] if head else "") + " " + before, tm.group(0), (units[-1].group(1) if units else None)


def read_row(rcept_no: str, table_hint: str, row_label: str, *, files=None) -> list[dict]:
    """접수번호 원문(본문 + 연결감사보고서 첨부)에서 제목·앞 글에 table_hint가 있는 표의 row_label 행 당기 값. 후보 전부."""
    files = files or dart.get_client().document(rcept_no)
    out = []
    for src, xml, default in (("본문", body_xml(files), None), ("연결감사보고서", consolidated_audit_statements(files), "CFS")):
        for scope, ctx, tbl, unit in _tables(xml or "", default):
            if _n(table_hint) not in _n(ctx) and _n(table_hint) not in _n(re.sub(r"<[^>]+>", " ", tbl)[:200]):
                continue
            rows = table_rows(tbl)
            header = rows[:3]
            hdr = _n(" ".join(" ".join(h) for h in header))
            reversed_cols = "전기" in hdr and "당기" in hdr and hdr.index("전기") < hdr.index("당기")
            for r in rows:
                li = next((i for i, x in enumerate(r) if _n(x) and num(x) is None), None)
                if li is None or _n(r[li]) != _n(row_label):
                    continue
                vals = amounts_after(r, li, header)
                raw = vals[0] if vals else None
                out.append({"source": src, "scope": scope, "unit_text": unit, "unit": UNITS.get(unit), "raw": raw, "value_krw": raw * UNITS[unit] if raw is not None and unit in UNITS else None,
                            "reversed_cols": reversed_cols, "table": re.sub(r"\s+", " ", ctx.strip())[-60:], "row": r[li]})
    return out


def check(finding: dict, *, expected_rcept_nos: list[str], expected_scope: str, absolute: bool = False, allowed_rows: tuple[str, ...] = (), files=None) -> dict:
    """finding: {rcept_no, table_hint, row_label, claimed_raw}. 반환 {adopted, value(원), reason, read}."""
    no = finding.get("rcept_no")
    if no not in expected_rcept_nos:
        return {"adopted": False, "value": None, "reason": f"기간 불일치: 기대 보고서 {expected_rcept_nos}, 찾은 보고서 {no}", "read": []}
    if allowed_rows and _n(finding.get("row_label")) not in {_n(x) for x in allowed_rows}:      # 어떤 행이 그 지표인지는 규칙으로 정한다 (LLM 분류 금지)
        return {"adopted": False, "value": None, "reason": f"행 이름이 규칙 목록 밖: '{finding.get('row_label')}' (허용 {', '.join(allowed_rows)})", "read": []}
    claimed = finding.get("claimed_raw")
    if claimed is None:
        return {"adopted": False, "value": None, "reason": "LLM이 표에서 본 값을 적지 않음", "read": []}
    try:
        cands = read_row(no, finding.get("table_hint") or "", finding.get("row_label") or "", files=files)
    except DartQuotaError:      # DART 일일 한도(020): 삼키지 않고 올린다 (2026-11-11)
        raise
    except Exception as e:      # 원문을 못 읽으면 기각
        return {"adopted": False, "value": None, "reason": f"원문 다시 읽기 실패: {type(e).__name__}", "read": []}
    if not cands:
        return {"adopted": False, "value": None, "reason": "같은 표·행을 원문에서 다시 찾지 못함", "read": []}
    fit = [c for c in cands if c["scope"] == expected_scope]
    if not fit:
        return {"adopted": False, "value": None, "reason": f"연결/별도 불일치: 기대 {expected_scope}, 찾은 {sorted({c['scope'] for c in cands})}", "read": cands}
    fit = [c for c in fit if c["unit"] and not c["reversed_cols"]]
    if not fit:
        return {"adopted": False, "value": None, "reason": "원화 단위 표기 없음 또는 당기 열 확인 불가", "read": cands}
    f = (lambda x: abs(x)) if absolute else (lambda x: x)
    vals = {(f(c["raw"]), c["unit"]) for c in fit if c["raw"] is not None}
    if len(vals) != 1:
        return {"adopted": False, "value": None, "reason": f"같은 행 값이 여러 개이거나 없음: {sorted(vals)}", "read": fit}
    (raw, unit), c = vals.pop(), fit[0]
    if raw != f(claimed):
        return {"adopted": False, "value": None, "reason": f"값 불일치: 원문 {raw:,} / 주장 {f(claimed):,} ({c['unit_text']})", "read": fit}
    return {"adopted": True, "value": raw * unit, "reason": f"원문 일치 ({c['source']} · {c['table']} · {c['row']} · 단위 {c['unit_text']})", "read": fit}
