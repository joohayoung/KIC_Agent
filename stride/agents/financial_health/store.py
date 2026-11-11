"""저장소 (개발문서 10장). 원문은 저장하지 않는다."""
import json
from datetime import datetime

from core.config import settings
from core.db import connect as connect_common

DDL = """
CREATE TABLE IF NOT EXISTS financial_health_snapshots (
  corp_code TEXT, run_id TEXT, as_of TEXT, fs_basis TEXT, metrics_json TEXT, classifications_json TEXT,
  latest_annual_rcept_no TEXT, latest_periodic_rcept_no TEXT, PRIMARY KEY (corp_code, run_id)
);
CREATE TABLE IF NOT EXISTS financial_health_tracked (
  corp_code TEXT PRIMARY KEY, last_run_id TEXT, last_as_of TEXT, audit_opinion TEXT, capital_impairment_ratio REAL,
  restructuring_status TEXT, equity_ex_nci INTEGER, updated_at TEXT
);
"""


def connect(path=None):
    con = connect_common(path or settings.path(settings.stride_db_path))
    con.executescript(DDL)
    return con


def previous_snapshot(con, corp_code: str, as_of: str):
    """직전 이력: as_of < 이번 as_of 중 최신 (시점 누수 방지)."""
    return con.execute("SELECT * FROM financial_health_snapshots WHERE corp_code=? AND as_of<? ORDER BY as_of DESC, run_id DESC LIMIT 1", (corp_code, as_of)).fetchone()


def save(con, run_id, corp_code, as_of, fs_basis, metrics, classifications, annual_no, latest_no, tracked: dict):
    con.execute("INSERT OR REPLACE INTO financial_health_snapshots VALUES (?,?,?,?,?,?,?,?)",
                (corp_code, run_id, as_of, fs_basis, json.dumps(metrics, ensure_ascii=False, default=str), json.dumps(classifications, ensure_ascii=False, default=str), annual_no, latest_no))
    row = con.execute("SELECT last_as_of FROM financial_health_tracked WHERE corp_code=?", (corp_code,)).fetchone()
    if row is None or row["last_as_of"] <= as_of:     # 과거 시점 재생이 현재 상태를 덮지 않게 한다
        con.execute("INSERT OR REPLACE INTO financial_health_tracked VALUES (?,?,?,?,?,?,?,?)",
                    (corp_code, run_id, as_of, tracked.get("audit_opinion"), tracked.get("capital_impairment_ratio"), tracked.get("restructuring_status"), tracked.get("equity_ex_nci"), datetime.now().isoformat(timespec="seconds")))
    con.commit()
