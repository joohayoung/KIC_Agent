"""화면 쿼리 (화면_데이터_연결명세). 화면은 SQLite를 읽기만 한다. 반환 dict 키는 명세 표의 열 이름과 같게 둔다."""
import json
import sqlite3
from datetime import date, timedelta

from core.config import settings
from orchestrator.config import REGION_MAP
from orchestrator.store import DDL as ORC_DDL

DB_PATH = None      # 시험에서 fixture DB로 바꾼다


def con() -> sqlite3.Connection:
    """읽기 전용 연결. 테이블이 없으면 빈 결과가 되게 스키마만 만든다 (worker가 아직 실행되지 않은 경우)."""
    path = DB_PATH or settings.path(settings.stride_db_path)
    c = sqlite3.connect(str(path), check_same_thread=False)
    c.row_factory = sqlite3.Row
    try:
        from core.db import DDL
        c.executescript(DDL + ORC_DDL)
    except sqlite3.OperationalError:
        pass
    return c


def _j(s, default=None):
    return json.loads(s) if s else default


# ---- 공통 (1장) ----
def unread_feed_count() -> int:
    with con() as c:
        return c.execute("SELECT COUNT(*) FROM orc_feed WHERE read=0").fetchone()[0]


def last_update() -> dict:
    with con() as c:
        cur = c.execute("SELECT updated_at FROM orc_monitor_cursor WHERE id=1").fetchone()
        run = c.execute("SELECT errors_json FROM runs WHERE agent='orchestrator.monitor' ORDER BY finished_at DESC LIMIT 1").fetchone()
    stats = _j(run["errors_json"], {}) if run else {}
    return {"updated_at": cur["updated_at"] if cur else None, "polled": stats.get("polled") if isinstance(stats, dict) else None}


def company_names() -> dict:
    with con() as c:
        return {r["corp_code"]: r["corp_name"] for r in c.execute("SELECT corp_code, corp_name FROM orc_companies")}


# ---- 페이지 1 (2장) ----
def get_searches() -> list[dict]:
    with con() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM orc_searches ORDER BY is_system DESC, is_saved DESC, created_at")]
        for r in rows:
            r["criteria"] = _j(r["criteria_json"], {})
            r["new_match_unread"] = c.execute("SELECT COUNT(*) FROM orc_feed WHERE search_id=? AND kind='new_match' AND read=0", (r["search_id"],)).fetchone()[0]
            run = c.execute("SELECT * FROM orc_search_runs WHERE search_id=? ORDER BY created_at DESC LIMIT 1", (r["search_id"],)).fetchone()
            r["last_run"] = dict(run) if run else None
    return rows


def latest_run(search_id: str, as_of: str | None = None) -> dict | None:
    q = "SELECT * FROM orc_search_runs WHERE search_id=?" + (" AND as_of=?" if as_of else "") + " ORDER BY created_at DESC LIMIT 1"
    with con() as c:
        r = c.execute(q, (search_id, as_of) if as_of else (search_id,)).fetchone()
    if not r:
        return None
    d = dict(r)
    d["funnel"] = _j(d["funnel_json"], [])
    d["suggestions"] = _j(d["suggestions_json"], [])
    return d


def get_board(search_id: str, run_id: str) -> dict:
    """후보 기업 표(matched), 분석 대기(pending), 제외 목록(excluded)."""
    with con() as c:
        rows = c.execute("SELECT * FROM orc_search_matches WHERE search_id=? AND run_id=?", (search_id, run_id)).fetchall()
        names = {r["search_id"]: r["name"] for r in c.execute("SELECT search_id, name FROM orc_searches")}
        watched = {r["corp_code"] for r in c.execute("SELECT corp_code FROM orc_watchlist")}
    out = {"matched": [], "pending": [], "excluded": []}
    for r in rows:
        if r["status"] == "matched":
            b = _j(r["row_json"], {})
            b["matched_search_names"] = [names.get(s, s) for s in b.get("matched_search_ids") or []]
            b["is_watched"] = b["corp_code"] in watched
            out["matched"].append(b)
        elif r["status"] == "pending":
            out["pending"].append(_j(r["row_json"], {}))
        else:
            out["excluded"].append({"corp_code": r["corp_code"], "corp_name": (_j(r["row_json"], {}) or {}).get("corp_name") or r["corp_code"], "excluded_step": r["excluded_step"], "excluded_condition": r["excluded_condition"], "excluded_value": r["excluded_value"], "evidence_ids": _j(r["evidence_ids_json"], [])})
    return out


# ---- 페이지 2 (3장) ----
def tracked_searches() -> list[dict]:
    since = (date.today() - timedelta(days=30)).isoformat()
    out = []
    with con() as c:
        for s in c.execute("SELECT * FROM orc_searches WHERE tracking=1 OR is_saved=1 ORDER BY is_system DESC, created_at"):
            d = dict(s)
            d["criteria"] = _j(d["criteria_json"], {})
            run = c.execute("SELECT run_id FROM orc_search_runs WHERE search_id=? ORDER BY created_at DESC LIMIT 1", (s["search_id"],)).fetchone()
            d["matched_count"] = c.execute("SELECT COUNT(*) FROM orc_search_matches WHERE search_id=? AND run_id=? AND status='matched'", (s["search_id"], run["run_id"])).fetchone()[0] if run else 0
            d["feed"] = [dict(r) for r in c.execute("SELECT * FROM orc_feed WHERE search_id=? AND kind IN ('new_match','left_match') AND event_date>=? ORDER BY event_date DESC", (s["search_id"], since))]
            out.append(d)
    return out


def latest_result(corp_code: str, agent: str, as_of: str):
    from core.schemas import AgentResult
    with con() as c:
        r = c.execute("SELECT result_json, verification_json, as_of FROM orc_agent_results WHERE corp_code=? AND agent=? AND as_of<=? ORDER BY as_of DESC LIMIT 1", (corp_code, agent, as_of)).fetchone()
    return (AgentResult.model_validate_json(r["result_json"]), _j(r["verification_json"]), r["as_of"]) if r else (None, None, None)


def get_watchlist_rows(as_of: str) -> list[dict]:
    from orchestrator import common
    from orchestrator.rules import apply_rules
    with con() as c:
        wl = [dict(r) for r in c.execute("SELECT * FROM orc_watchlist")]
        info = {r["corp_code"]: dict(r) for r in c.execute("SELECT * FROM orc_companies")}
        latest_change = {r["corp_code"]: dict(r) for r in c.execute("SELECT * FROM orc_feed WHERE kind='watch_change' ORDER BY event_date")}
    out = []
    for w in wl:
        ovs, _, day = latest_result(w["corp_code"], "overseas_funding", as_of)
        fin, _, _ = latest_result(w["corp_code"], "financial_health", as_of)
        i = info.get(w["corp_code"], {"corp_code": w["corp_code"], "corp_name": w["corp_name"], "market": "-", "induty_code": "-"})
        row = common.board_row(ovs, fin, i, apply_rules(fin, None, i.get("market"), date.fromisoformat(as_of)) if fin else [], None, matched_search_ids=[], is_watched=True, change_badges=[]).model_dump() if ovs or fin else None
        out.append({"corp_code": w["corp_code"], "corp_name": w["corp_name"], "row": row, "rules": [r.model_dump() for r in apply_rules(fin, None, i.get("market"), date.fromisoformat(as_of))] if fin else [], "latest_change": latest_change.get(w["corp_code"]), "updated": day})
    return out


def get_feed(kind="watch_change", limit=20) -> list[dict]:
    with con() as c:
        return [dict(r) | {"evidence_ids": _j(r["evidence_ids_json"], [])} for r in c.execute("SELECT * FROM orc_feed WHERE kind=? ORDER BY event_date DESC, created_at DESC LIMIT ?", (kind, limit))]


def get_weekly_signals(as_of: str) -> list[dict]:
    """3.5. 추적 범위 = 관심 기업 + 추적 중인 조건의 최신 matched 기업. signal_id로 중복 제거 후 주·지역으로 센다."""
    with con() as c:
        scope = {r["corp_code"] for r in c.execute("SELECT corp_code FROM orc_watchlist")}
        for s in c.execute("SELECT search_id FROM orc_searches WHERE tracking=1"):
            run = c.execute("SELECT run_id FROM orc_search_runs WHERE search_id=? ORDER BY created_at DESC LIMIT 1", (s["search_id"],)).fetchone()
            if run:
                scope |= {r["corp_code"] for r in c.execute("SELECT corp_code FROM orc_search_matches WHERE search_id=? AND run_id=? AND status='matched'", (s["search_id"], run["run_id"]))}
        if not scope:
            return []
        try:
            rows = c.execute(f"SELECT DISTINCT signal_id, event_date, target_country FROM overseas_funding_signals WHERE corp_code IN ({','.join('?' * len(scope))}) AND signal_type IN ('S1_plan','S2_progress','S4_confirmed','S5_funding') AND is_new=1 AND event_date BETWEEN date(?, '-84 days') AND ?",
                             (*scope, as_of, as_of)).fetchall()
        except sqlite3.OperationalError:      # 해외진출 저장소가 아직 없음
            return []
    seen, out = set(), []
    for r in rows:
        if r["signal_id"] in seen:
            continue
        seen.add(r["signal_id"])
        d = date.fromisoformat(r["event_date"])
        region = "미국" if r["target_country"] in REGION_MAP["US"] else "EU" if r["target_country"] in REGION_MAP["EU"] else "아시아 기타"
        out.append({"week": f"{d.isocalendar().year}-W{d.isocalendar().week:02d}", "region": region, "count": 1})
    return out


# ---- 페이지 3 (4장) ----
def get_report(corp_code: str, as_of: str) -> dict | None:
    with con() as c:
        r = c.execute("SELECT * FROM orc_reports WHERE corp_code=? AND as_of=? ORDER BY created_at DESC LIMIT 1", (corp_code, as_of)).fetchone()
    return dict(r) | {"report": _j(r["report_json"])} if r else None


def get_project_history(ovs, project_key: str | None) -> list[dict]:
    if not ovs:
        return []
    return sorted([s for s in ovs.extra.get("signals") or [] if project_key and s.get("project_key") == project_key], key=lambda s: s["event_date"])


def get_job(job_id: str) -> dict | None:
    with con() as c:
        r = c.execute("SELECT * FROM orc_jobs WHERE job_id=?", (job_id,)).fetchone()
    return dict(r) | {"progress": _j(r["progress_json"], {})} if r else None


def latest_intent_job() -> dict | None:
    with con() as c:
        r = c.execute("SELECT * FROM orc_jobs WHERE job_type='intent' ORDER BY created_at DESC LIMIT 1").fetchone()
    return dict(r) if r else None


# ---- 조사 과정 (2026-11-10 자율성 지시) ----
def get_traces(corp_code: str, as_of: str | None = None, purpose: str | None = None) -> list[dict]:
    """trace_id별 스텝 묶음. 최신 조사 먼저."""
    q = "SELECT * FROM orc_agent_traces WHERE corp_code=?" + (" AND as_of<=?" if as_of else "") + (" AND purpose=?" if purpose else "") + " ORDER BY created_at DESC, step"
    args = [corp_code] + ([as_of] if as_of else []) + ([purpose] if purpose else [])
    out = {}
    with con() as c:
        for r in c.execute(q, args):
            d = dict(r)
            d["args"], d["source"] = _j(d.pop("args_json"), {}), _j(d.pop("source_json"), {})
            out.setdefault(d["trace_id"], {"trace_id": d["trace_id"], "purpose": d["purpose"], "subject": d["subject"], "as_of": d["as_of"], "created_at": d["created_at"], "steps": []})["steps"].append(d)
    for t in out.values():
        t["steps"].sort(key=lambda s: s["step"] or 0)
    return list(out.values())


def get_investigations(limit: int = 20) -> list[dict]:
    with con() as c:
        rows = [dict(r) for r in c.execute("SELECT * FROM orc_investigations ORDER BY created_at DESC LIMIT ?", (limit,))]
    for r in rows:
        r["related"], r["footnotes"] = _j(r.pop("related_json"), []), _j(r.pop("footnotes_json"), {})
    return rows
