"""5곳 실제 실행 (체크리스트 6장). 기록 재사용 없음. 사용: python tests/golden/_usage_run.py (stride 폴더). 결과: data/logs/usage_run_5.json. 기업명은 콘솔에 출력하지 않는다.
8·9단계 전이라 update_state·write_report 호출(보고서 opus)은 포함되지 않는다."""
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from agents.overseas_funding.graph import build_company_graph, _initial, to_result  # noqa: E402
from core.config import settings  # noqa: E402
from core.schemas import Request  # noqa: E402

G = Path(__file__).parent / "overseas_funding"
CASES = ["G-POS_주", "G-RICH_F", "G-GOV_I", "G-DOM_주", "G-NONE_H"]
rows, start = [], time.monotonic()
for name in CASES:
    doc = json.loads((G / f"{name}.json").read_text(encoding="utf-8"))
    t0 = time.monotonic()
    state = build_company_graph().invoke(_initial(Request(request_id="u", agent="overseas_funding", mode="single", corp_code=doc["corp_code"], as_of=date.fromisoformat(doc["request"]["as_of"]), context={"db_path": ":memory:"})), {"recursion_limit": 80})
    r = to_result(state)
    calls, inp, out, secs = 0, 0, 0, 0.0
    by = {}
    for f in sorted((settings.path(settings.stride_log_dir) / "llm" / state["run_id"]).glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        for a in rec["attempts"]:
            i = a.get("input_tokens", 0) + a.get("cache_creation_input_tokens", 0) + a.get("cache_read_input_tokens", 0)
            calls, inp, out, secs = calls + 1, inp + i, out + a.get("output_tokens", 0), secs + a.get("seconds", 0)
            by.setdefault(rec["prompt"], []).append(i)
    rows.append({"case": name, "run_id": state["run_id"], "calls": calls, "input_tokens": inp, "output_tokens": out, "llm_seconds": round(secs, 1), "wall_seconds": round(time.monotonic() - t0, 1), "by_prompt": {k: len(v) for k, v in by.items()}, "errors": r.errors, "in_scope": next((c.value for c in r.classifications if c.key == "ovs.in_scope"), None)})
    print(name, rows[-1]["calls"], rows[-1]["input_tokens"], rows[-1]["output_tokens"], rows[-1]["wall_seconds"], rows[-1]["errors"], flush=True)
total = {k: sum(x[k] for x in rows) for k in ("calls", "input_tokens", "output_tokens", "llm_seconds")}
total["wall_seconds"] = round(time.monotonic() - start, 1)
(ROOT.parent / "data/logs/usage_run_5.json").write_text(json.dumps({"rows": rows, "total": total}, ensure_ascii=False, indent=1), encoding="utf-8")
print("합계", total, flush=True)
