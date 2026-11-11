"""시험 전용: 같은 프롬프트 입력이면 data/logs/llm 기록의 가장 최근 출력을 재사용한다. 입력이 다르면 실제로 호출한다."""
import hashlib
import json
from importlib import import_module
from pathlib import Path

from core import llm as llm_mod
from core.config import settings

NODES = ["extract_periodic_plan", "parse_major_events", "collect_news", "extract_news", "resolve_conflicts", "verify", "write_report"]


def _index() -> dict:
    out = {}
    root = settings.path(settings.stride_log_dir) / "llm"
    for f in sorted(root.glob("*/*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        if r.get("input_sha1") and "output" in r:
            out[r["input_sha1"]] = r["output"]
    return out


def install(monkeypatch=None):
    """노드의 call_llm을 재사용 함수로 바꾼다. 반환 {"hit": n, "miss": n}."""
    index, count = _index(), {"hit": 0, "miss": 0}
    real = llm_mod.call_llm

    def replay(prompt_path, variables, model, *, run_id, as_of=None, **k):
        text = llm_mod.fill((llm_mod.ROOT / prompt_path).read_text(encoding="utf-8"), variables)
        hit = index.get(hashlib.sha1(text.encode("utf-8")).hexdigest())
        if hit is not None:
            count["hit"] += 1
            return model.model_validate(hit)
        count["miss"] += 1
        return real(prompt_path, variables, model, run_id=run_id, as_of=as_of, **k)
    for n in NODES:
        mod = import_module(f"agents.overseas_funding.nodes.{n}")
        if monkeypatch:
            monkeypatch.setattr(mod, "call_llm", replay)
        else:
            mod.call_llm = replay
    return count


__all__ = ["install", "Path"]
