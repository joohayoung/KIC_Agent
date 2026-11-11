import json
import re

from agents.overseas_funding.config import MAX_CONFLICTS_PER_RUN
from agents.overseas_funding.schemas import RouteOutput, SignalType
from core.clients import dart
from core.clients.dart_docs import plain_text
from core.llm import call_llm
from core.nodeguard import guarded
from core.schemas import RouteDecision

PROMPT = "agents/overseas_funding/prompts/resolve_conflict.md"
_AMOUNT = re.compile(r"(?:취득금액|투자금액|양수금액)\s*\(원\)\s*([\d,]+)")


def check_decision(out, allowed_ids: set[str]) -> tuple[str, str | None]:
    """코드 검증 (7.8a 3). 허용값이 아니거나 근거가 충돌 신호 밖이면 기본 경로 record_conflict."""
    if out.action not in ("fetch_original_text", "record_conflict"):
        return "record_conflict", "허용되지 않은 action"
    if not set(out.evidence_ids) <= allowed_ids:
        return "record_conflict", "충돌 근거 밖의 evidence_id"
    return out.action, None


def conflict_text(c: dict) -> str:
    return "금액 충돌: " + ", ".join(f"{a} {b:,}" for a, b in zip(c["sources"], c["amounts"]))


@guarded
def resolve_conflicts(state) -> dict:
    """충돌마다 원문을 더 볼지 LLM이 고르고, 확인은 코드가 한다 (7.8a, D3). LLM은 경로 선택만 한다."""
    signals = {s.signal_id: s for s in state.get("signals_merged") or []}
    open_ = sorted((c for c in state.get("conflicts") or [] if not c.get("resolved")), key=lambda c: max(signals[i].event_date for i in c["signal_ids"]), reverse=True)
    decisions, questions, new_signals, llm = [], [], [], state.get("llm_calls", 0)
    done = {}
    for n, c in enumerate(open_):
        rows = [signals[i] for i in c["signal_ids"]]
        allowed = {e for s in rows for e in s.evidence_ids}
        action, fallback = "record_conflict", "충돌 처리 상한 초과"
        reason = "처리 상한을 넘어 코드가 기록"
        ids = sorted(allowed)
        if n < MAX_CONFLICTS_PER_RUN:
            try:
                out = call_llm(PROMPT, {"conflict_json": json.dumps({**{k: c[k] for k in ("project_key", "amounts", "sources")}, "evidence_ids": ids}, ensure_ascii=False)}, RouteOutput, run_id=state["run_id"], as_of=state["request"].as_of)
                llm += 1
                reason, ids = out.reason, out.evidence_ids or ids
                action, fallback = check_decision(out, allowed)
            except Exception as e:      # 판단 실패는 기본 경로로 간다
                action, fallback, reason = "record_conflict", f"LLM 실패: {type(e).__name__}", "기본 경로"
        confirmed = None
        if action == "fetch_original_text":
            s4 = next((s for s in rows if s.signal_type == SignalType.CONFIRMED), None)
            if s4:
                m = _AMOUNT.search(plain_text(dart.get_client().document(s4.signal_id.split(":")[2])))
                confirmed = int(m.group(1).replace(",", "")) if m else None
                if confirmed is not None and s4.amount_krw is None:      # 같은 signal_id로 덧붙이면 merge_signals가 마지막 값을 쓴다
                    new_signals.append(s4.model_copy(update={"amount_krw": confirmed}))
            if confirmed is None:
                action, fallback = "record_conflict", "원문에서 금액 칸을 찾지 못함"
        questions.append(conflict_text(c) + (f" (원문 금액 칸 {confirmed:,})" if confirmed is not None else ""))
        decisions.append(RouteDecision(point="D3", action=action, reason=reason[:300], evidence_ids=ids, accepted=fallback is None, fallback_action="record_conflict" if fallback else None).model_dump() | {"note": fallback, "project_key": c["project_key"]})
        done[c["project_key"]] = {**c, "resolved": True, "action": action}
    conflicts = [done.get(c["project_key"], c) for c in state.get("conflicts") or []]
    return {"conflicts": conflicts, "conflict_round": state.get("conflict_round", 0) + 1, "decisions": decisions, "open_questions": questions, "signals": new_signals, "llm_calls": llm}
