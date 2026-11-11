"""표시 변환 (화면_데이터_연결명세 0장 2·5·8번). 화면에서 수치를 계산하지 않는다. 단위 변환과 반올림만 한다."""
import re

STATUS_TEXT = {"missing": "산출 불가", "unknown": "확인 불가", "needs_due_diligence": "실사 필요"}
REPORT = {"FY": ("사업보고서", "12-31"), "H1": ("반기보고서", "06-30"), "1Q": ("1분기보고서", "03-31"), "3Q": ("3분기보고서", "09-30")}
DART_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"


def eok(v, digits=0) -> str:
    """원 → '1,410억'."""
    if v is None:
        return "산출 불가"
    return f"{v / 1e8:,.{digits}f}억"


def pct(v, *, ratio=True) -> str:
    """비율(0.441) → '44.1%', % 단위 값(142.0) → '142%'."""
    if v is None:
        return "산출 불가"
    return f"{v * 100:.1f}%" if ratio else f"{v:,.0f}%"


def value(m: dict | None, kind: str = "원") -> str:
    """{value, data_status, note} → 표시 문구. 칸을 비우지 않는다 (0장 5번)."""
    if not m:
        return "산출 불가"
    s = m.get("data_status") or ("ok" if m.get("value") is not None else "missing")
    if s != "ok" or m.get("value") is None:
        return STATUS_TEXT.get(s, "산출 불가")
    v = m["value"]
    return {"원": eok(v), "비율": pct(v), "%": pct(v, ratio=False), "배": f"{v:,.2f}배"}.get(kind, str(v))


def period_label(period: str | None) -> str:
    """Metric.period → '{기간 구분} · {보고서 종류} 기준일 {YYYY-MM-DD}' (0장 8번). 12월 결산 기준."""
    if not period:
        return ""
    if m := re.fullmatch(r"TTM (\d{4})(FY|H1|1Q|3Q)", period):
        rep, md = REPORT[m.group(2)]
        return f"TTM · {rep} 기준일 {m.group(1)}-{md}"
    if m := re.fullmatch(r"(\d{4})(FY|H1|1Q|3Q)(말)?", period):
        rep, md = REPORT[m.group(2)]
        kind = "시점" if m.group(3) else ("연간" if m.group(2) == "FY" else "시점")
        return f"{kind} · {rep} 기준일 {m.group(1)}-{md}"
    if m := re.fullmatch(r"(\d{4}-\d{2}-\d{2}) 기준", period):
        return f"시점 · 기준일 {m.group(1)}"
    return period


def tooltip(m: dict | None) -> str:
    if not m:
        return ""
    s = m.get("data_status")
    if s == "unknown":
        return m.get("note") or "정정 전 원본 값 확인 불가"
    return m.get("note") or ""


def evidence_link(eid: str) -> str | None:
    """DART 근거 → 뷰어 링크 (0장 3번)."""
    m = re.match(r"(?:DART|FIN):(\d{14})", eid or "")
    return DART_URL.format(m.group(1)) if m else None


def source(ids: list[str] | None) -> str | None:
    """첫 DART 근거의 뷰어 링크. 계산 근거만 있으면 None (화면에는 'STRIDE 계산')."""
    return next((u for u in map(evidence_link, ids or []) if u), None)


def mmdd(d: str | None) -> str:
    return d[5:10] if d and len(d) >= 10 else (d or "-")
