"""해외진출 10단계: 과거 1개월 배치 재생. 사용: python scripts/run_batch_month.py 2024-08
결과: data/logs/batch_{월}.json (처리 시간·호출 수), data/logs/batch_{월}.md (목록). 기업명은 콘솔에 출력하지 않는다. 빈 DB로 시작해 첫 실행 상한(5곳)이 걸린다."""
import calendar
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stride"))
from agents.overseas_funding.batch import run_batch  # noqa: E402
from core.schemas import Request  # noqa: E402

y, m = (int(x) for x in sys.argv[1].split("-"))
start, end = date(y, m, 1), date(y, m, calendar.monthrange(y, m)[1])
db = ROOT / f"data/batch_{sys.argv[1]}.db"
db.unlink(missing_ok=True)
out = run_batch(Request(request_id=f"batch-{sys.argv[1]}", agent="overseas_funding", mode="batch", as_of=end, period_start=start, context={"db_path": str(db)}))
rows = [{"corp_code": x["screen"]["corp_code"], "strength": x["screen"]["strength"], "seconds": x["seconds"], "llm_calls": x["llm_calls"], "error": x["error"],
         "status": next((c.value for c in x["result"].classifications if c.key == "ovs.signal_status"), None) if x["result"] else None, "errors": x["result"].errors if x["result"] else None} for x in out["results"]]
summary = {"month": sys.argv[1], "seconds": out["seconds"], "companies": len(rows), "pending": len(out["pending"]), "llm_calls": sum(r["llm_calls"] for r in rows), "rows": rows}
(ROOT / f"data/logs/batch_{sys.argv[1]}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
(ROOT / f"data/logs/batch_{sys.argv[1]}.md").write_text(out["table_markdown"] or "", encoding="utf-8")
print(json.dumps({k: v for k, v in summary.items() if k != "rows"}), [(r["strength"], r["seconds"], r["llm_calls"], r["status"], bool(r["error"] or r["errors"])) for r in rows])
