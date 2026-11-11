"""STRIDE 명령 (저장소 최상위 폴더에서 실행).

python -m stride.cli orchestrator worker [--once]
python -m stride.cli orchestrator monitor [--as-of YYYY-MM-DD]
python -m stride.cli orchestrator discover [--search-id default] [--as-of YYYY-MM-DD]
python -m stride.cli orchestrator review --company <기업명|종목코드> [--as-of YYYY-MM-DD]
python -m stride.cli show --run-id <run_id>
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))      # 패키지 안의 agents·core·orchestrator를 최상위로 읽는다


def main(argv=None):
    p = argparse.ArgumentParser(prog="stride")
    p.add_argument("group", choices=["orchestrator", "show"])
    p.add_argument("command", nargs="?")
    p.add_argument("--once", action="store_true")
    p.add_argument("--as-of", default=date.today().isoformat())
    p.add_argument("--search-id", default="default")
    p.add_argument("--company")
    p.add_argument("--run-id")
    p.add_argument("--db")
    a = p.parse_args(argv)
    as_of = date.fromisoformat(a.as_of)
    if a.group == "show":
        from orchestrator import store
        con = store.connect(a.db)
        rows = [dict(r) for r in con.execute("SELECT * FROM decisions WHERE run_id LIKE ? ORDER BY run_id, seq", (f"{a.run_id}%",))]
        runs = [dict(r) for r in con.execute("SELECT * FROM runs WHERE run_id LIKE ?", (f"{a.run_id}%",))]
        print(json.dumps({"runs": runs, "decisions": rows}, ensure_ascii=False, indent=1))
        return
    if a.command == "worker":
        from orchestrator.worker import run_worker
        print("처리", run_worker(db_path=a.db, once=a.once))
    elif a.command == "monitor":
        from orchestrator.monitor import run_monitor
        print(json.dumps(run_monitor(as_of, db_path=a.db), ensure_ascii=False))
    elif a.command == "discover":
        from orchestrator import store
        from orchestrator.worker import _criteria
        from orchestrator.discover import run_discover
        con = store.connect(a.db)
        out = run_discover(a.search_id, _criteria(con, {"search_id": a.search_id}, as_of), db_path=a.db)
        print(json.dumps({"run_id": out["run_id"], "funnel": out["funnel"], "rows": len(out["rows"]), "pending": len(out["pending"]), "excluded": len(out["excluded"])}, ensure_ascii=False))
    elif a.command == "review":
        from orchestrator.review import run_review
        out = run_review(query=a.company, as_of=as_of, db_path=a.db)
        print(out["report"].report_id if out.get("report") else out["clarification"])


if __name__ == "__main__":
    main()
