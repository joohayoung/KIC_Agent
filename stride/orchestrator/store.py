"""오케스트레이터 저장소 (오케스트레이터 개발문서 9장). decisions는 core/db.py에 있다."""
import json
import uuid
from datetime import date, datetime

from core.config import settings
from core.db import connect as connect_common
from core.schemas import AgentResult

DDL = """
CREATE TABLE IF NOT EXISTS orc_searches (
  search_id TEXT PRIMARY KEY, name TEXT, nl_text TEXT, criteria_json TEXT,
  is_system INTEGER DEFAULT 0, is_saved INTEGER DEFAULT 0, tracking INTEGER DEFAULT 0,
  created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS orc_search_runs (
  search_id TEXT, run_id TEXT, as_of TEXT, funnel_json TEXT, summary_md TEXT,
  suggestions_json TEXT, created_at TEXT, PRIMARY KEY (search_id, run_id)
);
CREATE TABLE IF NOT EXISTS orc_search_matches (
  search_id TEXT, corp_code TEXT, run_id TEXT, as_of TEXT, status TEXT,
  excluded_step TEXT, excluded_condition TEXT, excluded_value TEXT, row_json TEXT,
  evidence_ids_json TEXT, PRIMARY KEY (search_id, corp_code, run_id)
);
CREATE TABLE IF NOT EXISTS orc_watchlist (corp_code TEXT PRIMARY KEY, corp_name TEXT, added_at TEXT, added_from TEXT);
CREATE TABLE IF NOT EXISTS orc_reports (report_id TEXT PRIMARY KEY, corp_code TEXT, as_of TEXT, run_id TEXT, report_json TEXT, verification_status TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS orc_answers (answer_id TEXT PRIMARY KEY, question TEXT, corp_code TEXT, as_of TEXT, answer_json TEXT, created_at TEXT);
CREATE TABLE IF NOT EXISTS orc_feed (
  item_id TEXT PRIMARY KEY, kind TEXT, search_id TEXT, corp_code TEXT, alert_type TEXT,
  before_text TEXT, after_text TEXT, reason TEXT, event_date TEXT,
  evidence_ids_json TEXT, read INTEGER DEFAULT 0, created_at TEXT
);
CREATE TABLE IF NOT EXISTS orc_jobs (
  job_id TEXT PRIMARY KEY, job_type TEXT, payload_json TEXT, status TEXT,
  progress_json TEXT, result_ref TEXT, error TEXT, created_at TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS orc_monitor_cursor (id INTEGER PRIMARY KEY CHECK (id = 1), last_rcept_no TEXT, last_rcept_dt TEXT, updated_at TEXT);
-- 자체 결정 (2026-11-09): 문서에 AgentResult 보관 테이블이 없다. 화면·load_cached·answer가 읽을 수 있게 결과 전체를 둔다
CREATE TABLE IF NOT EXISTS orc_agent_results (corp_code TEXT, agent TEXT, as_of TEXT, run_id TEXT, result_json TEXT, verification_json TEXT, created_at TEXT, PRIMARY KEY (corp_code, agent, as_of));
-- 자체 결정: 기업개황(시장·업종) 캐시 (구성문서 4.0 build_universe "기업개황은 SQLite에 캐시")
CREATE TABLE IF NOT EXISTS orc_companies (corp_code TEXT PRIMARY KEY, corp_name TEXT, market TEXT, induty_code TEXT, stock_code TEXT, updated_at TEXT);
-- 2026-11-10 자율성 지시: 조사 루프 스텝 기록 (purpose: fill | investigate). outcome: call | stop | budget | error | adopted | rejected | not_found
CREATE TABLE IF NOT EXISTS orc_agent_traces (trace_id TEXT, run_id TEXT, corp_code TEXT, as_of TEXT, purpose TEXT, subject TEXT, step INTEGER, tool TEXT, args_json TEXT, reason TEXT, result_summary TEXT, outcome TEXT, source_json TEXT, seconds REAL, tokens INTEGER, created_at TEXT);
-- 새 공시 조사 결과: 알림 시점(immediate|digest)과 검증 통과 요약
CREATE TABLE IF NOT EXISTS orc_investigations (investigation_id TEXT PRIMARY KEY, trace_id TEXT, run_id TEXT, corp_code TEXT, rcept_no TEXT, as_of TEXT, timing TEXT, summary_md TEXT, footnotes_json TEXT, verification_status TEXT, related_json TEXT, created_at TEXT);
"""
DEFAULT_SEARCH_ID = "default"


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{uuid.uuid4().hex[:6]}"


def connect(path=None):
    con = connect_common(path or settings.path(settings.stride_db_path))
    con.executescript(DDL)
    seed_default(con)
    return con


def seed_default(con) -> None:
    """6장 기본 탐색. as_of는 실행일에 정한다."""
    from orchestrator.discover import default_criteria
    if con.execute("SELECT 1 FROM orc_searches WHERE search_id=?", (DEFAULT_SEARCH_ID,)).fetchone():
        return
    c = default_criteria(date.today())
    con.execute("INSERT INTO orc_searches VALUES (?,?,?,?,?,?,?,?,?)", (DEFAULT_SEARCH_ID, "STRIDE 기본 탐색", None, c.model_dump_json(exclude={"as_of"}), 1, 1, 1, now(), now()))
    con.commit()


def save_result(con, result: AgentResult, verification=None) -> None:
    if llm_failed(result):      # 실패한 결과는 저장하지 않는다
        return
    con.execute("INSERT OR REPLACE INTO orc_agent_results VALUES (?,?,?,?,?,?,?)", (result.corp_code, result.agent, result.as_of.isoformat(), result.request_id, result.model_dump_json(), verification.model_dump_json() if verification else None, now()))
    con.commit()


LLM_FAILURE = ("LLMRateLimitError", "LLMAuthError", "LLMError", "DartQuotaError")


def llm_failed(result: AgentResult | None) -> bool:
    """LLM 호출이 실패한 결과. 라벨이 비어 범위 판정이 틀어지므로 재사용·표시하지 않는다 (자체 결정 S25)."""
    return bool(result) and any(k in e for e in result.errors for k in LLM_FAILURE)


def load_result(con, corp_code: str, agent: str, as_of: str) -> AgentResult | None:
    row = con.execute("SELECT result_json FROM orc_agent_results WHERE corp_code=? AND agent=? AND as_of=?", (corp_code, agent, as_of)).fetchone()
    r = AgentResult.model_validate_json(row["result_json"]) if row else None
    return None if llm_failed(r) else r


def latest_result(con, corp_code: str, agent: str, as_of: str) -> AgentResult | None:
    """as_of 이하 중 최신 결과 (화면·answer)."""
    for row in con.execute("SELECT result_json FROM orc_agent_results WHERE corp_code=? AND agent=? AND as_of<=? ORDER BY as_of DESC", (corp_code, agent, as_of)):
        r = AgentResult.model_validate_json(row["result_json"])
        if not llm_failed(r):
            return r
    return None


def save_decision(con, run_id: str, module: str, corp_code: str | None, d) -> None:
    seq = con.execute("SELECT COALESCE(MAX(seq), 0) + 1 FROM decisions WHERE run_id=?", (run_id,)).fetchone()[0]
    con.execute("INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)", (run_id, seq, d.point, module, corp_code, d.action, d.reason, json.dumps(d.evidence_ids, ensure_ascii=False), int(d.accepted), d.fallback_action, now()))
    con.commit()


def add_feed(con, item) -> bool:
    """같은 항목 중복 저장 0건 (item_id가 결정적이다)."""
    if con.execute("SELECT 1 FROM orc_feed WHERE item_id=?", (item.item_id,)).fetchone():
        return False
    con.execute("INSERT INTO orc_feed VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (item.item_id, item.kind, item.search_id, item.corp_code, item.alert_type, item.before, item.after, item.reason, item.event_date.isoformat(), json.dumps(item.evidence_ids, ensure_ascii=False), 0, now()))
    con.commit()
    return True


def save_trace(con, trace_id: str, run_id: str, corp_code: str, as_of: str, purpose: str, subject: str, steps: list[dict]) -> None:
    """조사 루프 스텝과 게이트 판정을 orc_agent_traces에 남긴다."""
    for s in steps:
        con.execute("INSERT INTO orc_agent_traces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (trace_id, run_id, corp_code, as_of, purpose, subject, s.get("step"), s.get("tool"), json.dumps(s.get("args") or {}, ensure_ascii=False),
                                                                                         (s.get("reason") or "")[:500], (s.get("result") or "")[:500], s.get("outcome"), json.dumps(s.get("source") or {}, ensure_ascii=False), s.get("seconds"), s.get("tokens"), now()))
    con.commit()


def traces(con, corp_code: str, as_of: str | None = None) -> list[dict]:
    q = "SELECT * FROM orc_agent_traces WHERE corp_code=?" + (" AND as_of<=?" if as_of else "") + " ORDER BY created_at, trace_id, step"
    return [dict(r) for r in con.execute(q, (corp_code, as_of) if as_of else (corp_code,))]
