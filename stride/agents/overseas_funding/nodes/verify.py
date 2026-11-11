import re
from importlib import import_module

from agents.overseas_funding.config import VERIFY_AMOUNT_TOLERANCE
from agents.overseas_funding.schemas import SignalType, VerifyOutput
from core.llm import call_llm
from core.nodeguard import guarded
from core.schemas import Finding
from core.units import parse_krw

PROMPT = "agents/overseas_funding/prompts/verify_claims.md"
MAX_PER_PROJECT = 3
TARGET = {SignalType.PLAN: "periodic", SignalType.PROGRESS: "news", SignalType.CONFIRMED: "major_event", SignalType.FUNDING: "major_event", SignalType.ALERT: "major_event"}
_UNIT = {"조": 10 ** 12, "억": 10 ** 8, "천만": 10 ** 7, "백만": 10 ** 6, "만": 10 ** 4, "천": 10 ** 3}
LLM_TEXT = (SignalType.PLAN, SignalType.PROGRESS)      # 문장을 LLM이 쓴 신호. S4·S5·S6은 정형 칸 값이라 C1~C3으로 확인한다 (v0.20)
_ANY_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?\s*(?:조|억|백만|천)?\s*원?")


def amounts_in(text: str) -> list[int]:
    """'1,000억원', '106억 5400만원', '20원' → 원 단위. 복합 표기는 더한다."""
    out = []
    for m in re.finditer(r"(?:\d[\d,.]*\s*(?:조|억|천만|백만|만|천)\s*)*\d[\d,.]*\s*(?:조|억|천만|백만|만|천)?\s*원", text or ""):
        total, rest = 0.0, m.group(0)
        for num, unit in re.findall(r"(\d[\d,.]*)\s*(조|억|천만|백만|만|천)?", rest):
            total += float(num.replace(",", "").rstrip(".") or 0) * _UNIT.get(unit, 1)
        out.append(int(total))
    return out


def known_values(e) -> list[int]:
    """근거에 적힌 숫자: 정형 칸 값(meta)과 quote·제목의 숫자."""
    vals = [v for v in (e.meta.get("value"), *(e.meta.get("slots") or {}).values()) if isinstance(v, (int, float))]
    for m in _ANY_NUMBER.finditer(f"{e.quote or ''} {e.title or ''}"):
        s = m.group(0).strip()
        v = parse_krw(s if s.endswith("원") else s + "원") if re.search(r"조|억|백만|천", s) else None
        if v is None:
            try:
                v = int(float(re.sub(r"[^\d.]", "", s)))
            except ValueError:
                continue
        vals.append(v)
    return vals


def code_check(f: Finding, evidence: dict, as_of) -> str | None:
    """C1~C4. 실패 사유 또는 None."""
    missing = [i for i in f.evidence_ids if i not in evidence]
    if missing:
        return f"C1 근거 없음: {missing[0]}"
    rows = [evidence[i] for i in f.evidence_ids]
    late = [e.evidence_id for e in rows if e.published_at > as_of]
    if late:
        return f"C2 기준일 이후 근거: {late[0]}"
    if f.kind == "calc":
        for e in rows:
            if e.source_type != "calc" or "impl" not in e.meta:
                continue
            path, name = e.meta["impl"].rsplit(".", 1)
            value = getattr(import_module(path), name)(**e.meta["args"])
            if value != e.meta["value"]:
                return f"C4 재계산 불일치: {value} / {e.meta['value']}"
        known = {abs(v) for e in rows if e.source_type == "calc" for v in [e.meta.get("value"), *(e.meta.get("args") or {}).values()] if isinstance(v, (int, float))}
        stray = [a for a in amounts_in(f.text) if a not in known]
        if stray:
            return f"C4 문장 수치 불일치: {stray[0]:,}"
        return None
    pool = [v for e in rows for v in known_values(e)]
    pool += [a for e in rows for a in amounts_in(f"{e.quote or ''}")]
    for a in amounts_in(f.text):
        if not any(abs(a - abs(v)) <= abs(v) * VERIFY_AMOUNT_TOLERANCE for v in pool if v):
            return f"C3 숫자 불일치: {a:,}"
    return None


def build_findings(projects: list[dict], signals: dict, gap, metrics: list) -> list[tuple[Finding, object]]:
    """프로젝트별 1~3개 + 자금 공백 1개 (7.11 1). 문장의 값은 신호에서만 채운다. 반환 (Finding, 출처 신호)."""
    out = []
    for p in projects:
        if not p.get("gate_pass"):
            continue
        rows = [signals[i] for i in p["signal_ids"] if i in signals]
        rows.sort(key=lambda s: (s.signal_type != SignalType.CONFIRMED, s.signal_type != SignalType.FUNDING, s.event_date.toordinal() * -1))
        for s in rows[:MAX_PER_PROJECT]:
            label = "해외 용도 금액" if s.signal_type == SignalType.FUNDING else "금액"
            amount = f", {label} {s.amount_krw:,}원" if s.amount_krw else ""
            where = f" ({s.target_country})" if s.target_country else ""
            out.append((Finding(finding_id=f"F{len(out) + 1}", kind="fact", text=f"{s.event_date} {s.summary}{where}{amount}", evidence_ids=s.evidence_ids), s))
    m = {x.metric_id: x for x in metrics}
    if gap is not None and gap.gap_krw is not None:
        ids = m["ovs.funding_gap"].evidence_ids
        out.append((Finding(finding_id=f"F{len(out) + 1}", kind="calc", text=f"자금 공백 {gap.gap_krw:,}원 (투자액 {gap.overseas_investment_krw:,}원 − 가용 자금 {gap.available_funds_krw:,}원)", evidence_ids=ids), None))
        c, s, t, k = (m[i].value for i in ("fin.cash_and_equivalents", "fin.short_term_financial_assets", "fin.ttm_operating_cash_flow", "ovs.confirmed_overseas_funding"))
        out.append((Finding(finding_id=f"F{len(out) + 1}", kind="calc", text=f"가용 자금 {gap.available_funds_krw:,}원 = 현금및현금성자산 {c:,}원 + 단기금융상품 {s:,}원 + 최근 4분기 영업현금흐름 {t:,}원 + 확정 조달 {k:,}원", evidence_ids=m["ovs.available_internal_funds"].evidence_ids), None))
    u = m.get("ovs.unconfirmed_overseas_funding")
    if gap is not None and gap.gap_krw is not None and u is not None and u.value is not None:      # 0이어도 넣는다: 표의 미확정 조달 칸 근거
        out.append((Finding(finding_id=f"F{len(out) + 1}", kind="calc", text=f"미확정 조달 {u.value:,}원 (자금 공백 계산에 넣지 않음)", evidence_ids=u.evidence_ids), None))
    return out


def claims_text(findings: list[Finding], evidence: dict) -> str:
    """날짜는 C2와 list.json으로 코드가 확인하고, 정정본이면 접수일이 원공시일과 다르다. LLM에는 내용만 대조하게 한다."""
    lines = []
    for f in findings:
        lines.append(f"[CLAIM:{f.finding_id}] {re.sub(r'^\d{4}-\d{2}-\d{2} ', '', f.text)}")
        for i in f.evidence_ids:
            e = evidence.get(i)
            lines.append(f"[{i}] {f'공시명 {e.title} / {e.quote or ""}' if e else ''}")
    return "\n".join(lines)


@guarded
def verify(state) -> dict:
    """보고에 쓸 주장을 만들어 근거와 대조한다 (7.11). 코드 검사 후 통과분만 LLM으로 대조하고, 실패 출처를 재추출 대상으로 넘긴다."""
    req = state["request"]
    evidence = {e.evidence_id: e for e in state.get("evidence") or []}
    signals = {s.signal_id: s for s in state.get("signals_merged") or []}
    built = build_findings(state.get("projects") or [], signals, state.get("funding_gap"), state.get("metrics") or [])
    round_ = state.get("verify_round", 0)
    final, failed, retry, llm, errors = {}, [], [], state.get("llm_calls", 0), []
    for f, s in built:
        why = code_check(f, evidence, req.as_of)
        if why:
            final[f.finding_id] = f.model_copy(update={"verified": False, "verify_note": why})
            failed.append((f.finding_id, s))
    claims = [f for f, s in built if f.finding_id not in final and f.kind in ("fact", "inference") and s is not None and s.signal_type in LLM_TEXT]
    verdicts = {}
    if claims:
        try:
            out = call_llm(PROMPT, {"claims_with_evidence": claims_text(claims, evidence)}, VerifyOutput, run_id=state["run_id"], as_of=req.as_of)
            llm += 1
            verdicts = {r.finding_id: r for r in out.results}
        except Exception as e:      # 판정을 못 받은 주장은 미검증으로 남긴다. 추출 문제가 아니라 재추출하지 않는다
            errors.append(f"verify: LLM {type(e).__name__}")
    for f, s in built:
        if f.finding_id in final:
            continue
        if f.kind == "calc" or (s is not None and s.signal_type not in LLM_TEXT):
            final[f.finding_id] = f.model_copy(update={"verified": True, "verify_note": "코드 검사 통과"})
        elif f.finding_id not in verdicts:
            final[f.finding_id] = f.model_copy(update={"kind": "unverified", "verified": False, "verify_note": "LLM 판정 없음"})
        elif verdicts[f.finding_id].verdict == "supported":
            final[f.finding_id] = f.model_copy(update={"verified": True, "verify_note": verdicts[f.finding_id].reason})
        else:
            v = verdicts[f.finding_id].verdict
            final[f.finding_id] = f.model_copy(update={"verified": False, "verify_note": f"{v}: {verdicts[f.finding_id].reason}"})
            failed.append((f.finding_id, s))
            if v == "contradicted":      # not_enough는 근거가 짧은 것이라 다시 뽑아도 나아지지 않는다. 미검증으로 남긴다 (v0.20)
                retry.append(s)
    targets = sorted({TARGET[s.signal_type] for s in retry}) if round_ == 0 else []
    if round_ >= 1 or not targets:      # 두 번째 검증이거나 다시 추출할 일이 없으면 미검증으로 확정한다
        for i, _ in failed:
            final[i] = final[i].model_copy(update={"kind": "unverified"})
    for i, s in failed:      # 코드 검사 실패(C1~C3)는 항상 미검증이다
        if (final[i].verify_note or "")[:1] == "C":
            final[i] = final[i].model_copy(update={"kind": "unverified"})
    return {"findings": list(final.values()), "verify_round": round_ + 1, "reextract_targets": targets, "verify_note": "; ".join(final[i].verify_note or "" for i, _ in failed), "errors": errors, "llm_calls": llm}
