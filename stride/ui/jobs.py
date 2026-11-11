"""orc_jobs 넣기·읽기 (화면_데이터_연결명세 1.3). 쓰기는 작업 요청·관심 기업·조건 저장 표시만 한다."""
import json

from orchestrator import store
from ui import queries


def _con():
    return store.connect(queries.DB_PATH)


def enqueue(job_type: str, payload: dict) -> str:
    from orchestrator.worker import enqueue as put
    c = _con()
    try:
        return put(c, job_type, payload)
    finally:
        c.close()


def toggle_watch(corp_code: str, corp_name: str, on: bool, source: str) -> None:
    c = _con()
    try:
        if on:
            c.execute("INSERT OR IGNORE INTO orc_watchlist VALUES (?,?,?,?)", (corp_code, corp_name, store.now(), source))
        else:
            c.execute("DELETE FROM orc_watchlist WHERE corp_code=?", (corp_code,))
        c.commit()
    finally:
        c.close()


def save_search(search_id: str, name: str, tracking: bool = True) -> None:
    c = _con()
    try:
        c.execute("UPDATE orc_searches SET is_saved=1, tracking=?, name=?, updated_at=? WHERE search_id=?", (int(tracking), name, store.now(), search_id))
        c.commit()
    finally:
        c.close()


def set_tracking(search_id: str, on: bool) -> None:
    c = _con()
    try:
        c.execute("UPDATE orc_searches SET tracking=?, updated_at=? WHERE search_id=?", (int(on), store.now(), search_id))
        c.commit()
    finally:
        c.close()


def update_criteria(search_id: str, criteria: dict) -> None:
    c = _con()
    try:
        c.execute("UPDATE orc_searches SET criteria_json=?, updated_at=? WHERE search_id=?", (json.dumps({k: v for k, v in criteria.items() if k != "as_of"}, ensure_ascii=False, default=str), store.now(), search_id))
        c.commit()
    finally:
        c.close()


def new_search(name: str) -> str:
    from datetime import date

    from orchestrator.discover import default_criteria
    c = _con()
    try:
        sid = store.new_id("search")
        crit = default_criteria(date.today()).model_copy(update={"exclude_rule_ids": [], "min_funding_gap_ratio": None})
        c.execute("INSERT INTO orc_searches VALUES (?,?,?,?,?,?,?,?,?)", (sid, name, "", crit.model_dump_json(exclude={"as_of"}), 0, 0, 0, store.now(), store.now()))
        c.commit()
        return sid
    finally:
        c.close()


def mark_read(kind: str | None = None) -> None:
    c = _con()
    try:
        c.execute("UPDATE orc_feed SET read=1" + (" WHERE kind=?" if kind else ""), (kind,) if kind else ())
        c.commit()
    finally:
        c.close()
