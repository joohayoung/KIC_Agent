"""SQLite 연결·공통 테이블 (공통 양식 10장 + 오케스트레이터 개발문서 9장 decisions).

runs / evidence / alerts / processed_filings 의 컬럼은 어느 문서에도 정의가 없어
공통 스키마 필드에서 최소로 정했다. TODO(확인 필요): 문서에 컬럼 정의 추가.
"""
import sqlite3
from pathlib import Path

DDL = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, agent TEXT NOT NULL, corp_code TEXT, as_of TEXT NOT NULL, mode TEXT, status TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT, llm_calls INTEGER DEFAULT 0, unknown_count INTEGER DEFAULT 0, errors_json TEXT
);
CREATE TABLE IF NOT EXISTS evidence (
  evidence_id TEXT, run_id TEXT, source_grade TEXT, source_type TEXT, corp_code TEXT,
  published_at TEXT, title TEXT, url TEXT, quote TEXT, meta_json TEXT,
  PRIMARY KEY (evidence_id, run_id)
);
CREATE TABLE IF NOT EXISTS alerts (
  run_id TEXT, seq INTEGER, as_of TEXT, agent TEXT, corp_code TEXT, alert_type TEXT,
  message TEXT, evidence_ids_json TEXT, created_at TEXT, PRIMARY KEY (run_id, seq)
);
CREATE TABLE IF NOT EXISTS processed_filings (
  rcept_no TEXT, agent TEXT, run_id TEXT, processed_at TEXT, PRIMARY KEY (rcept_no, agent)
);
CREATE TABLE IF NOT EXISTS decisions (
  run_id TEXT, seq INTEGER, point TEXT, module TEXT, corp_code TEXT,
  action TEXT, reason TEXT, evidence_ids_json TEXT, accepted INTEGER, fallback_action TEXT,
  created_at TEXT, PRIMARY KEY (run_id, seq)
);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    """DB를 열고 공통 테이블을 만든다. 테스트는 ':memory:' 또는 임시 파일을 쓴다."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    return con
