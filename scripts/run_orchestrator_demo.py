"""오케스트레이터 첫 실제 실행: 기본 탐색 → 보드 첫 기업 검토서 → 질문 1건 → 감시 1회. worker 작업(orc_jobs)으로 처리해 화면과 같은 경로를 탄다.
사용: python scripts/run_orchestrator_demo.py 2026-11-05. 결과 요약: data/logs/orchestrator_demo.json (기업명은 콘솔에 출력하지 않는다)."""
import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "stride"))
from orchestrator import store  # noqa: E402
from orchestrator.monitor import run_monitor  # noqa: E402
from orchestrator.worker import enqueue, run_worker  # noqa: E402

as_of = sys.argv[1]
con = store.connect()
t0 = time.monotonic()
out = {"as_of": as_of}
enqueue(con, "discover", {"search_id": store.DEFAULT_SEARCH_ID, "as_of": as_of})
run_worker(once=True)
job = dict(con.execute("SELECT * FROM orc_jobs ORDER BY created_at DESC LIMIT 1").fetchone())
out["discover"] = {"status": job["status"], "run_id": job["result_ref"], "error": (job["error"] or "")[:300], "seconds": round(time.monotonic() - t0, 1)}
run = con.execute("SELECT * FROM orc_search_runs ORDER BY created_at DESC LIMIT 1").fetchone()
if run:
    out["discover"]["funnel"] = json.loads(run["funnel_json"])
    rows = con.execute("SELECT corp_code, row_json FROM orc_search_matches WHERE run_id=? AND status='matched'", (run["run_id"],)).fetchall()
    out["discover"]["matched"] = len(rows)
    first = rows[0]["corp_code"] if rows else con.execute("SELECT corp_code FROM orc_agent_results LIMIT 1").fetchone()[0]
    t1 = time.monotonic()
    enqueue(con, "review", {"corp_code": first, "as_of": as_of})
    run_worker(once=True)
    job = dict(con.execute("SELECT * FROM orc_jobs ORDER BY created_at DESC LIMIT 1").fetchone())
    rep = con.execute("SELECT verification_status FROM orc_reports WHERE report_id=?", (job["result_ref"],)).fetchone()
    out["review"] = {"status": job["status"], "verification": rep[0] if rep else None, "error": (job["error"] or "")[:300], "seconds": round(time.monotonic() - t1, 1)}
    name = con.execute("SELECT corp_name FROM orc_companies WHERE corp_code=?", (first,)).fetchone()[0]
    t2 = time.monotonic()
    enqueue(con, "answer", {"question": f"{name}의 자금 공백은 어떻게 계산됐어?", "company": first, "as_of": as_of})
    run_worker(once=True)
    job = dict(con.execute("SELECT * FROM orc_jobs ORDER BY created_at DESC LIMIT 1").fetchone())
    ans = json.loads(job["result_ref"]) if job["status"] == "done" else {}
    out["answer"] = {"status": job["status"], "verification": ans.get("verification_status"), "error": (job["error"] or "")[:300], "seconds": round(time.monotonic() - t2, 1)}
    con.execute("INSERT OR IGNORE INTO orc_watchlist VALUES (?,?,?,?)", (first, name, store.now(), "demo"))
    con.commit()
t3 = time.monotonic()
out["monitor"] = run_monitor(date.fromisoformat(as_of))
out["monitor"]["seconds"] = round(time.monotonic() - t3, 1)
out["total_seconds"] = round(time.monotonic() - t0, 1)
out["decisions"] = [dict(r) for r in con.execute("SELECT point, module, action, accepted, fallback_action FROM decisions WHERE module LIKE 'orchestrator%'")]
(ROOT / "data/logs/orchestrator_demo.json").write_text(json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
print(json.dumps({k: v for k, v in out.items() if k != "decisions"}, ensure_ascii=False, default=str)[:1500])
