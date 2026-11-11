"""검증 그래프 (검증 개발문서 6장). 재시도 루프 없음."""
from datetime import date, datetime

from langgraph.graph import END, START, StateGraph

from agents.verifier import nodes as n
from agents.verifier.schemas import VerificationReport
from agents.verifier.state import VerifierState
from core.config import settings
from core.db import connect
from core.schemas import AgentResult

DDL = """
CREATE TABLE IF NOT EXISTS verifier_reports (
  request_id TEXT, run_id TEXT, mode TEXT, as_of TEXT, corp_code TEXT,
  n_checks INTEGER, n_failed INTEGER, n_unverifiable INTEGER,
  report_json TEXT, created_at TEXT,
  PRIMARY KEY (request_id, mode, run_id)
);
"""


class _CoverageHolder(VerifierState, total=False):
    coverage: dict


def build_graph():
    g = StateGraph(_CoverageHolder)
    for name in ("route_mode", "check_evidence_links", "recheck_sources", "check_asof", "check_cross_agent", "check_coverage", "split_sentences", "check_numbers", "check_footnotes", "check_claims", "check_forbidden", "build_report"):
        g.add_node(name, getattr(n, name))
    g.add_edge(START, "route_mode")
    g.add_conditional_edges("route_mode", lambda s: s["request"]["mode"], {"results": "check_evidence_links", "answer": "split_sentences"})
    for a, b in (("check_evidence_links", "recheck_sources"), ("recheck_sources", "check_asof"), ("check_asof", "check_cross_agent"), ("check_cross_agent", "check_coverage"), ("check_coverage", "check_forbidden"),
                 ("split_sentences", "check_numbers"), ("check_numbers", "check_footnotes"), ("check_footnotes", "check_claims"), ("check_claims", "check_forbidden"), ("check_forbidden", "build_report"), ("build_report", END)):
        g.add_edge(a, b)
    return g.compile()


def save(report: VerificationReport, run_id: str, db_path=None) -> None:
    con = connect(db_path or settings.path(settings.stride_db_path))
    try:
        con.executescript(DDL)
        con.execute("INSERT OR REPLACE INTO verifier_reports VALUES (?,?,?,?,?,?,?,?,?,?)", (report.request_id, run_id, report.mode, report.as_of, report.corp_code, len(report.checks), len(report.failed), len(report.unverifiable), report.model_dump_json(), datetime.now().isoformat(timespec="seconds")))
        con.commit()
    finally:
        con.close()


def verify_results(results: list[AgentResult], as_of: date, required_metrics: list[str], *, request_id: str, corp_code: str | None = None) -> VerificationReport:
    out = build_graph().invoke({"request": {"request_id": request_id, "mode": "results", "as_of": as_of.isoformat(), "corp_code": corp_code, "required_metrics": required_metrics}, "results": results, "checks": [], "errors": []})
    return out["report"]


def verify_answer(document: str, footnotes: dict, cited: dict, as_of: date, *, request_id: str, corp_code: str | None = None) -> VerificationReport:
    """footnotes: {각주 번호: [evidence_id]}, cited: {evidence_id: {"value", "unit", "quote"}}."""
    out = build_graph().invoke({"request": {"request_id": request_id, "mode": "answer", "as_of": as_of.isoformat(), "corp_code": corp_code}, "document": document, "footnotes": {str(k): v for k, v in footnotes.items()}, "cited": cited, "checks": [], "errors": []})
    return out["report"]

