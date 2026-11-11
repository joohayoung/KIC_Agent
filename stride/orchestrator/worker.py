"""orc_jobs worker (화면_데이터_연결명세 1.3). 화면은 작업을 넣고 진행 상황만 읽는다. queued 작업을 하나씩 처리한다."""
import json
import time
import traceback
from datetime import date

from orchestrator import store
from orchestrator.answer import parse_intent, run_answer, run_board_filter
from orchestrator.discover import default_criteria, parse_criteria, run_discover
from orchestrator.review import run_review
from orchestrator.schemas import DiscoveryCriteria


def enqueue(con, job_type: str, payload: dict) -> str:
    job_id = store.new_id("job")
    con.execute("INSERT INTO orc_jobs VALUES (?,?,?,?,?,?,?,?,?)", (job_id, job_type, json.dumps(payload, ensure_ascii=False, default=str), "queued", "{}", None, None, store.now(), store.now()))
    con.commit()
    return job_id


def _update(con, job_id, **k):
    sets = ", ".join(f"{c}=?" for c in k) + ", updated_at=?"
    con.execute(f"UPDATE orc_jobs SET {sets} WHERE job_id=?", (*k.values(), store.now(), job_id))
    con.commit()


def _criteria(con, payload, as_of) -> DiscoveryCriteria:
    if payload.get("criteria"):
        return DiscoveryCriteria(**{**payload["criteria"], "as_of": as_of})
    row = con.execute("SELECT criteria_json FROM orc_searches WHERE search_id=?", (payload.get("search_id") or store.DEFAULT_SEARCH_ID,)).fetchone()
    return DiscoveryCriteria(**{**json.loads(row["criteria_json"]), "as_of": as_of}) if row else default_criteria(as_of)


def handle(con, job, db_path=None) -> str | None:
    """반환 result_ref. 실패는 예외."""
    p = json.loads(job["payload_json"])
    as_of = date.fromisoformat(p.get("as_of") or date.today().isoformat())
    kind, job_id = job["job_type"], job["job_id"]
    progress_state = {"funnel": [], "deep_done": 0}

    def progress(step, **k):
        """병렬 노드(Send)는 다른 스레드에서 부른다. 스레드마다 연결을 새로 연다 (SQLite 연결은 만든 스레드에서만 쓸 수 있다)."""
        if step == "deep_done":
            progress_state["deep_done"] += 1
        else:
            progress_state["funnel"].append({"step": step, **k})
        c = store.connect(db_path)
        try:
            _update(c, job_id, progress_json=json.dumps(progress_state, ensure_ascii=False))
        finally:
            c.close()
    if kind == "intent":
        it = parse_intent(p["text"], as_of, job_id)
        result = {"intent": it.model_dump()}
        if it.intent == "answer":
            result["answer"] = run_answer(p["text"], it.company_mention, as_of, db_path=db_path).model_dump(mode="json")
        elif it.intent == "board_filter":
            result["board_filter"] = run_board_filter(it.filter_text or p["text"], as_of, job_id)
        elif it.intent == "discover":
            crit = parse_criteria(p["text"], as_of, job_id)
            sid = store.new_id("search")
            con.execute("INSERT INTO orc_searches VALUES (?,?,?,?,?,?,?,?,?)", (sid, p["text"][:40], p["text"], crit.model_dump_json(exclude={"as_of"}), 0, 0, 0, store.now(), store.now()))
            con.commit()
            result["search_id"] = sid
        elif it.intent == "review":
            result["company_mention"] = it.company_mention
        return json.dumps(result, ensure_ascii=False, default=str)
    if kind == "discover" and p.get("stage") == "parse_only":
        crit = parse_criteria(p["nl_text"], as_of, job_id)
        sid = p.get("search_id") or store.new_id("search")
        con.execute("INSERT OR REPLACE INTO orc_searches (search_id, name, nl_text, criteria_json, is_system, is_saved, tracking, created_at, updated_at) VALUES (?,?,?,?,COALESCE((SELECT is_system FROM orc_searches WHERE search_id=?),0),COALESCE((SELECT is_saved FROM orc_searches WHERE search_id=?),0),COALESCE((SELECT tracking FROM orc_searches WHERE search_id=?),0),?,?)",
                    (sid, p["nl_text"][:40], p["nl_text"], crit.model_dump_json(exclude={"as_of"}), sid, sid, sid, store.now(), store.now()))
        con.commit()
        return sid
    if kind in ("discover", "add_analysis"):
        sid = p.get("search_id") or store.DEFAULT_SEARCH_ID
        crit = _criteria(con, p, as_of)
        out = run_discover(sid, crit, db_path=db_path, progress=progress)
        return out["run_id"]
    if kind == "review":
        out = run_review(query=p.get("company"), corp_code=p.get("corp_code"), as_of=as_of, db_path=db_path)
        return out["report"].report_id if out.get("report") else json.dumps({"clarification": out["clarification"], "candidates": out["candidates"]}, ensure_ascii=False)
    if kind == "answer":
        return json.dumps(run_answer(p["question"], p.get("company"), as_of, db_path=db_path).model_dump(mode="json"), ensure_ascii=False)
    raise ValueError(f"알 수 없는 작업 {kind}")


def run_worker(*, db_path=None, once=False, poll_seconds=2.0) -> int:
    """queued 작업을 순서대로 처리한다. once면 지금 있는 작업만 처리하고 끝낸다. 반환 처리 수."""
    con = store.connect(db_path)
    n = 0
    try:
        while True:
            job = con.execute("SELECT * FROM orc_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if job is None:
                if once:
                    return n
                time.sleep(poll_seconds)
                continue
            _update(con, job["job_id"], status="running")
            try:
                ref = handle(con, job, db_path)
                _update(con, job["job_id"], status="done", result_ref=ref)
            except Exception as e:      # 한 작업 실패가 worker를 멈추지 않는다
                _update(con, job["job_id"], status="failed", error=f"{type(e).__name__}: {e}"[:500] + "\n" + traceback.format_exc()[-1500:])
            n += 1
    finally:
        con.close()
