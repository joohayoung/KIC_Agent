"""기업 1곳 기준 LLM 호출 수·토큰 측정 (해외진출 6단계, 호출규칙 4장).

사용: python scripts/measure_llm_company.py <golden 파일 경로(tests/golden 기준)> [--dry]
--dry: claude를 호출하지 않고 호출 수와 입력 글자 수만 센다. 없으면 실제 호출하고 data/logs/llm/{run_id}의 기록을 합산한다.
기업명은 콘솔에 출력하지 않는다. 결과: data/logs/llm_measure_{파일 이름}{_dry}.json
"""
import json
import sys
from importlib import import_module
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stride"))
from agents.overseas_funding.graph import build_extraction_graph, to_result, _initial  # noqa: E402
from agents.overseas_funding.schemas import GenerateNewsQueriesOutput, MajorEventBatchOutput, NewsExtractionOutput, PeriodicPlanOutput  # noqa: E402
from core import llm as llm_mod  # noqa: E402
from core.config import settings  # noqa: E402
from core.schemas import Request  # noqa: E402

MODULES = ["extract_periodic_plan", "parse_major_events", "collect_news", "extract_news"]
EMPTY = {PeriodicPlanOutput: {"items": [], "no_plan_found": True}, MajorEventBatchOutput: {"items": []}, GenerateNewsQueriesOutput: {"queries": []}, NewsExtractionOutput: {"events": []}}
name = sys.argv[1]
dry = "--dry" in sys.argv
doc = json.loads((ROOT / "stride/tests/golden" / f"{name}.json").read_text(encoding="utf-8"))
q = doc["request"]
req = Request(request_id="m", agent="overseas_funding", mode="single", corp_code=q["company"], as_of=q["as_of"])
calls = []
if dry:
    def fake(prompt_path, variables, model, *, run_id, as_of=None):
        text = llm_mod.fill((llm_mod.ROOT / prompt_path).read_text(encoding="utf-8"), variables)
        calls.append({"prompt": Path(prompt_path).stem, "input_chars": len(text)})
        return model.model_validate(EMPTY[model])
    for m in MODULES:
        import_module(f"agents.overseas_funding.nodes.{m}").call_llm = fake
state = build_extraction_graph().invoke(_initial(req))
result = to_result(state)
if dry:
    out = {"mode": "dry", "calls": calls}
else:
    rows = []
    for f in sorted((settings.path(settings.stride_log_dir) / "llm" / state["run_id"]).glob("*.json")):
        rec = json.loads(f.read_text(encoding="utf-8"))
        for a in rec["attempts"]:
            rows.append({"prompt": rec["prompt"], "model": rec["model"], "input_chars": rec["input_chars"], "seconds": a.get("seconds"), "input_tokens": a.get("input_tokens", 0) + a.get("cache_creation_input_tokens", 0) + a.get("cache_read_input_tokens", 0), "output_tokens": a.get("output_tokens", 0), "ok": "output" in rec})
    out = {"mode": "real", "run_id": state["run_id"], "calls": rows, "total": {"calls": len(rows), "seconds": round(sum(r["seconds"] or 0 for r in rows), 1), "input_tokens": sum(r["input_tokens"] for r in rows), "output_tokens": sum(r["output_tokens"] for r in rows)}}
out["signals"] = [{k: s[k] for k in ("signal_type", "purpose_category", "is_overseas", "target_country", "amount_krw", "stage", "is_new")} for s in result.extra["signals"]]
out["news_count"] = result.extra["news_count"]
out["news_queries_accepted"] = len(result.extra["news_queries"])
out["decisions"] = len(result.extra["decisions"])
out["open_questions"] = len(result.open_questions)
out["errors"] = result.errors
out["gap"] = result.extra["funding_gap"]
(ROOT / "data/logs" / f"llm_measure_{Path(name).stem}{'_dry' if dry else ''}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: out[k] for k in out if k not in ("signals",)}, ensure_ascii=False, default=str))
print("신호", json.dumps(out["signals"], ensure_ascii=False))
