"""조사 루프 (2026-11-10 자율성 지시 2). LLM이 다음 도구와 이유를 고르고, 결과를 보고 다시 고른다.

자율은 '무엇을 더 찾아볼지'뿐이다. 루프 출력은 포인터·판단·문장이고, 숫자 채택은 agents/common/gate.py, 상태 변경은 기존 규칙이 한다.
예산: 1회당 최대 MAX_STEPS 스텝(= LLM 호출 수). 넘으면 그때까지의 결과로 끝내고 값은 missing으로 둔다.
"""
import json
import time
from typing import Literal

from pydantic import BaseModel

from core import llm

MAX_STEPS = 6
PROMPT = "core/prompts/agent_loop.md"


class Finding(BaseModel):
    target: str
    rcept_no: str | None = None
    table_hint: str | None = None
    row_label: str | None = None
    claimed_raw: int | None = None      # 표에 적힌 그대로의 숫자 (단위 환산 없음). 채택 값은 게이트가 원문에서 다시 읽는다


class LoopSentence(BaseModel):
    text: str
    evidence_ids: list[str] = []


class LoopStep(BaseModel):
    action: Literal["call", "stop"]
    tool: str | None = None
    args: dict = {}
    reason: str
    findings: list[Finding] = []
    timing: Literal["immediate", "digest"] | None = None      # 감시: 알림 시점
    sentences: list[LoopSentence] = []                          # 감시: 조사 요약 (검증 에이전트 통과분만 쓴다)
    related: list[str] = []                                     # 감시: 함께 본 관련 공시 접수번호


def summarize(result) -> str:
    s = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, default=str)
    return s[:2500]


def run_loop(goal: str, context: str, output_rules: str, tools: dict, *, as_of, run_id: str, max_steps: int = MAX_STEPS) -> dict:
    """반환 {"steps": [기록], "final": LoopStep|None, "calls", "tokens", "seconds", "seen": [도구 결과 원본]}.
    tools: {이름: (함수(as_of, **args), 설명)}. LLMRateLimitError·DartQuotaError는 호출자에게 넘긴다 (한도면 다음 실행으로 미룸).
    같은 도구·인자 반복은 실행하지 않고 "이미 확인함"을 돌려준다(스텝 포함). search_news가 실패하면 이 실행 동안 도구 목록에서 뺀다."""
    history, steps, seen = [], [], []
    calls = tokens = 0
    tools = dict(tools)      # 이 실행 동안 쓸 수 있는 도구 (search_news 실패 시 뺀다)
    done: dict[tuple, str] = {}      # (도구, 인자) → 결과 요약. 같은 호출은 다시 실행하지 않는다
    repeats = 0
    t0 = time.monotonic()
    final = None
    for i in range(1, max_steps + 1):
        last = i == max_steps
        s0 = time.monotonic()
        try:
            out = llm.call_llm(PROMPT, {"goal": goal, "context": context, "output_rules": output_rules, "tools": "\n".join(f"- {k}: {v[1]}" for k, v in tools.items()) or "(쓸 수 있는 도구 없음 — stop)",
                                        "history": "\n\n".join(history) or "(아직 없음)", "step": f"{i}/{max_steps}" + (" — 마지막 스텝: 반드시 action stop" if last else "")},
                               LoopStep, run_id=run_id, as_of=as_of)
        except llm.LLMRateLimitError:
            raise
        except llm.LLMError as e:
            steps.append({"step": i, "tool": None, "args": {}, "reason": f"LLM 실패: {str(e)[:150]}", "result": "", "outcome": "error", "seconds": round(time.monotonic() - s0, 1), "tokens": llm.usage_total()["tokens"]})
            calls += 1
            break
        u = llm.usage_total()
        calls += 1
        tokens += u["tokens"]
        if out.action == "stop" or last or not out.tool:
            final = out if out.action == "stop" else None
            steps.append({"step": i, "tool": None, "args": {}, "reason": out.reason, "result": f"종료: 발견 {len(out.findings)}건" if out.action == "stop" else "예산 소진", "outcome": "stop" if out.action == "stop" else "budget", "seconds": round(time.monotonic() - s0, 1), "tokens": u["tokens"]})
            break
        from agents.common.tools import run_tool      # 도구 모듈은 DART 클라이언트를 불러온다. 순환 import를 피한다
        key = (out.tool, json.dumps(out.args, ensure_ascii=False, sort_keys=True, default=str))
        if key in done:      # 같은 도구·같은 인자: 실행하지 않고 이전 결과 요약을 돌려준다 (스텝 수에는 포함)
            repeats += 1
            text, outcome = f"이미 확인함: {done[key][:500]}", "repeat"
        elif out.tool not in tools:
            text, outcome = summarize({"error": f"허용되지 않은 도구: {out.tool}"}), "error"
        else:
            result = run_tool(out.tool, out.args, as_of)      # DartQuotaError는 run_tool이 올려 루프를 멈춘다
            failed = isinstance(result, dict) and "error" in result
            if failed and out.tool == "search_news":      # 네이버 오류·한도: 이 실행 동안 뉴스 없이 공시 근거로
                tools.pop("search_news", None)
                result = f"뉴스 사용 불가, 공시 근거로 진행 ({result['error'][:120]})"
                outcome = "news_unavailable"
            else:
                outcome = "error" if failed else "call"
                seen.append({"tool": out.tool, "args": out.args, "result": result})
            text = summarize(result)
            done[key] = text
        history.append(f"[스텝 {i}] {out.tool}({json.dumps(out.args, ensure_ascii=False)}) 이유: {out.reason}\n결과:\n{text}")
        steps.append({"step": i, "tool": out.tool, "args": out.args, "reason": out.reason, "result": text[:300], "outcome": outcome, "seconds": round(time.monotonic() - s0, 1), "tokens": u["tokens"]})
    return {"steps": steps, "final": final, "calls": calls, "tokens": tokens, "seconds": round(time.monotonic() - t0, 1), "seen": seen, "repeats": repeats,
            "tool_calls": {k: sum(1 for s in steps if s["tool"] == k and s["outcome"] != "repeat") for k in {s["tool"] for s in steps if s["tool"]}}}
