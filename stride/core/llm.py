"""LLM 호출 (공통 양식 7장, 공통기준/claude_cli_호출규칙.md). 에이전트 코드는 항상 call_llm만 쓴다. `--bare`와 API 키를 쓰지 않는다."""
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError

from core.config import settings

ROOT = Path(__file__).resolve().parents[1]
SYSTEM_PROMPT = ROOT / "core/prompts/system_common.md"
TASK_MODELS = {"write_report": "opus", "summarize_board": "opus", "synthesize_report": "opus", "answer_question": "opus"}    # 호출규칙 3장. 나머지는 sonnet
DEFAULT_MODEL = "sonnet"
_AUTH = ("login expired", "not logged in", "please run /login", "authentication")
_LIMIT = ("usage limit", "rate limit", "limit reached", "hit your limit", "hit your session limit", "session limit", "weekly limit", "limit · resets", "resets ")


class LLMError(Exception):
    pass


class LLMAuthError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


def fill(template: str, variables: dict) -> str:
    """{변수}만 치환한다. 프롬프트의 JSON 중괄호는 그대로 둔다."""
    for k, v in variables.items():
        template = template.replace("{" + k + "}", str(v))
    return template


def _command(system: str, schema: dict, model: str) -> list[str]:
    exe = shutil.which("claude") or shutil.which("claude.cmd")
    if not exe:
        raise LLMError("claude 실행 파일을 찾지 못함")
    return [exe, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence",
            "--system-prompt", system, "--json-schema", json.dumps(schema, ensure_ascii=False), "--model", model]


def _classify_failure(text: str) -> None:
    low = (text or "").lower()
    if any(k in low for k in _AUTH):
        raise LLMAuthError("claude 로그인이 필요함 (claude 실행 후 /login)")
    if any(k in low for k in _LIMIT):
        raise LLMRateLimitError("사용량 한도")


def _invoke(prompt: str, system: str, output_model: type[BaseModel], model: str, timeout: int) -> tuple[dict | None, dict, str | None]:
    """반환 (구조화 출력, 사용량 기록, 오류 문구). 인증·한도는 예외."""
    start = time.monotonic()
    try:
        p = subprocess.run(_command(system, output_model.model_json_schema(), model), input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, {"seconds": timeout}, "시간 초과"
    seconds = round(time.monotonic() - start, 1)
    try:
        j = json.loads(p.stdout)
    except json.JSONDecodeError:
        _classify_failure(p.stdout + p.stderr)
        return None, {"seconds": seconds}, f"JSON 아님, 종료코드 {p.returncode}"
    u = j.get("usage") or {}
    usage = {"seconds": seconds, "input_tokens": u.get("input_tokens", 0), "cache_creation_input_tokens": u.get("cache_creation_input_tokens", 0), "cache_read_input_tokens": u.get("cache_read_input_tokens", 0), "output_tokens": u.get("output_tokens", 0)}
    if p.returncode != 0 or j.get("is_error"):
        _classify_failure(str(j.get("result")) + p.stderr)
        return None, usage, f"is_error, 종료코드 {p.returncode}: {str(j.get('result'))[:200]}"
    return j.get("structured_output"), usage, None


def _log(run_id: str, seq: int, name: str, record: dict) -> None:
    d = settings.path(settings.stride_log_dir) / "llm" / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{seq:02d}_{name}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1, default=str), encoding="utf-8")


_seq: dict[str, int] = {}


LAST_USAGE: dict = {"attempts": []}


def usage_total() -> dict:
    """직전 call_llm 호출의 시도 합계 {seconds, tokens}."""
    at = LAST_USAGE.get("attempts") or []
    return {"seconds": round(sum(x.get("seconds") or 0 for x in at), 1), "tokens": sum(sum(x.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")) for x in at)}


def call_llm(prompt_path: str, variables: dict, output_model: type[BaseModel], *, run_id: str, as_of=None, timeout: int = 180, max_retries: int = 1) -> BaseModel:
    """system_common.md + 작업 프롬프트로 `claude -p`를 호출하고 Pydantic으로 검증한다.
    프롬프트 본문은 stdin. 실패·검증 오류는 max_retries회 재호출. 입력 해시·출력·소요시간·토큰을 data/logs/llm/{run_id}/에 남긴다."""
    name = Path(prompt_path).stem
    prompt = fill((ROOT / prompt_path).read_text(encoding="utf-8"), variables)
    system = fill(SYSTEM_PROMPT.read_text(encoding="utf-8"), {"as_of": as_of or ""})
    model = TASK_MODELS.get(name, DEFAULT_MODEL)
    _seq[run_id] = _seq.get(run_id, 0) + 1
    attempts, feedback, last = [], "", "호출 안 됨"
    LAST_USAGE["attempts"] = attempts      # 조사 루프 기록용 (core/agent_loop.py). 호출마다 새 목록
    for attempt in range(max_retries + 1):
        out, usage, err = _invoke(prompt + feedback, system, output_model, model, timeout)
        attempts.append(usage)
        if err is None:
            try:
                result = output_model.model_validate(out)
            except ValidationError as e:
                err = f"스키마 오류: {str(e)[:300]}"
                feedback = f"\n\n## 이전 출력의 오류\n{err}\n스키마에 맞게 다시 출력하세요."
            else:
                _log(run_id, _seq[run_id], name, {"prompt": name, "model": model, "input_sha1": hashlib.sha1(prompt.encode("utf-8")).hexdigest(), "input_chars": len(prompt), "attempts": attempts, "output": out})
                return result
        last = err
    _log(run_id, _seq[run_id], name, {"prompt": name, "model": model, "input_chars": len(prompt), "attempts": attempts, "error": last})
    raise LLMError(f"{name}: {last}")
