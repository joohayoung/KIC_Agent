"""저장소 (개발문서 9장). 원문은 저장하지 않는다. 재생 테스트는 매번 빈 DB 파일에서 시작한다."""
import hashlib
import json
from datetime import datetime

from agents.overseas_funding.text.diff import normalize
from core.config import settings
from core.db import connect as connect_common

DDL = """
CREATE TABLE IF NOT EXISTS overseas_funding_signals (
  signal_id TEXT, run_id TEXT, as_of TEXT, corp_code TEXT, signal_type TEXT, event_date TEXT,
  is_overseas INTEGER, target_country TEXT, method TEXT, purpose_category TEXT,
  amount_krw INTEGER, amount_original TEXT, stage INTEGER, is_new INTEGER,
  project_key TEXT, summary TEXT, evidence_ids_json TEXT,
  PRIMARY KEY (signal_id, run_id)
);
CREATE TABLE IF NOT EXISTS overseas_funding_periodic_paragraphs (
  corp_code TEXT, rcept_no TEXT, rcept_dt TEXT, paragraph_id TEXT,
  norm_hash TEXT, text_excerpt TEXT,
  PRIMARY KEY (rcept_no, paragraph_id)
);
CREATE TABLE IF NOT EXISTS overseas_funding_tracked (
  corp_code TEXT PRIMARY KEY, signal_status TEXT, main_project_key TEXT,
  gap_krw INTEGER, last_run_id TEXT, last_as_of TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS overseas_funding_history (
  corp_code TEXT, run_id TEXT, as_of TEXT, signal_status TEXT, gap_krw INTEGER,
  projects_json TEXT, PRIMARY KEY (corp_code, run_id)
);
"""


def connect(path=None):
    con = connect_common(path or settings.path(settings.stride_db_path))
    con.executescript(DDL)
    return con


def previous(con, corp_code: str, as_of: str):
    """직전 이력: 이번 as_of보다 앞선 기록 중 최신 1건. 미래 시점 기록은 읽지 않는다 (7.12 1)."""
    return con.execute("SELECT * FROM overseas_funding_history WHERE corp_code=? AND as_of<? ORDER BY as_of DESC, run_id DESC LIMIT 1", (corp_code, as_of)).fetchone()


def save(con, *, run_id, corp_code, as_of, status, main_key, gap, projects, signals, paragraphs, filings, agent):
    now = datetime.now().isoformat(timespec="seconds")
    for s in signals:
        con.execute("INSERT OR REPLACE INTO overseas_funding_signals VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (s.signal_id, run_id, as_of, corp_code, s.signal_type.value, s.event_date.isoformat(), None if s.is_overseas is None else int(s.is_overseas), s.target_country, s.method, s.purpose_category,
                     s.amount_krw, s.amount_original, int(s.stage), None if s.is_new is None else int(s.is_new), s.project_key, s.summary, json.dumps(s.evidence_ids, ensure_ascii=False)))
    for rcept_no, rcept_dt, pid, text in paragraphs:
        con.execute("INSERT OR REPLACE INTO overseas_funding_periodic_paragraphs VALUES (?,?,?,?,?,?)", (corp_code, rcept_no, rcept_dt, pid, hashlib.sha1(normalize(text).encode("utf-8")).hexdigest(), text[:300]))
    con.execute("INSERT OR REPLACE INTO overseas_funding_history VALUES (?,?,?,?,?,?)", (corp_code, run_id, as_of, status, gap, json.dumps(projects, ensure_ascii=False, default=str)))
    row = con.execute("SELECT last_as_of FROM overseas_funding_tracked WHERE corp_code=?", (corp_code,)).fetchone()
    if row is None or row["last_as_of"] <= as_of:      # 과거 시점 재생이 현재 상태를 덮지 않게 한다
        con.execute("INSERT OR REPLACE INTO overseas_funding_tracked VALUES (?,?,?,?,?,?,?)", (corp_code, status, main_key, gap, run_id, as_of, now))
    for no in filings:
        con.execute("INSERT OR REPLACE INTO processed_filings VALUES (?,?,?,?)", (no, agent, run_id, now))
    con.commit()
