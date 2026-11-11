"""재무 건전성 그래프 (개발문서 6장). 점수·순위·판정 노드는 없다."""
from langgraph.graph import END, START, StateGraph

from agents.financial_health.config import AGENT_KEY, AGENT_VERSION
from agents.financial_health.nodes import NODES
from agents.financial_health.state import FinancialHealthState
from core import catalog
from core.evidence import validate_evidence
from core.schemas import AgentResult, Request


def route_after_resolve(state: FinancialHealthState) -> str:
    return "collect_financials" if state.get("company") else "write_report"


def build_graph():
    g = StateGraph(FinancialHealthState)
    for name in ["parse_request", "resolve_company", "collect_financials", "collect_audit_info", "collect_restructuring", "collect_market_data", "compute_metrics", "verify", "update_state", "write_report"]:
        g.add_node(name, NODES[name])
    g.add_edge(START, "parse_request")
    g.add_edge("parse_request", "resolve_company")
    g.add_conditional_edges("resolve_company", route_after_resolve, {"collect_financials": "collect_financials", "write_report": "write_report"})
    chain = ["collect_financials", "collect_audit_info", "collect_restructuring", "collect_market_data", "compute_metrics", "verify", "update_state", "write_report"]
    for a, b in zip(chain, chain[1:]):
        g.add_edge(a, b)
    g.add_edge("write_report", END)
    return g.compile()


def to_result(state: FinancialHealthState) -> AgentResult:
    """최종 상태를 공통 출력으로 바꾼다. 판단 필드를 만들지 않는다."""
    req, company = state["request"], state.get("company")
    errors = list(state.get("errors") or [])
    evidence = {e.evidence_id: e for e in state.get("evidence") or []}
    src = state.get("sources") or {}
    years = [{"bsns_year": y.bsns_year, "fs_div": y.fs_div, "rcept_no": y.rcept_no, "accounts": {k: a.amount for k, a in y.accounts.items()}} for y in state.get("years") or []]
    market = state.get("market")
    result = AgentResult(request_id=req.request_id, agent=AGENT_KEY, agent_version=AGENT_VERSION, corp_code=(company or {}).get("corp_code"), corp_name=(company or {}).get("corp_name"), as_of=req.as_of,
                         status="failed" if not company else "partial" if errors else "complete", metrics=state.get("metrics") or [], classifications=state.get("classifications") or [], findings=state.get("findings") or [],
                         alerts=state.get("alerts") or [], open_questions=state.get("open_questions") or [], evidence=list(evidence.values()), report_markdown=state.get("report_markdown"), errors=errors,
                         extra={"years": years, "unknown_years": src.get("unknown_years") or [], "restructuring_events": [{"rcept_no": e.rcept_no, "kind": e.kind, "rcept_dt": e.rcept_dt.isoformat()} for e in state.get("restructuring") or []], "market": market.model_dump(mode="json") if market else None})
    result = validate_evidence(result)
    bad = catalog.validate(result)
    if bad:
        result = result.model_copy(update={"errors": result.errors + bad, "status": "partial"})
    return result


def run(request: Request) -> AgentResult:
    return to_result(build_graph().invoke({"request": request, "evidence": [], "open_questions": [], "errors": []}))
