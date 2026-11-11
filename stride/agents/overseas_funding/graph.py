"""해외진출 그래프 (5.4). CompanyGraph는 write_report로 끝난다. 5·6단계 경로는 시험용으로 남긴다."""
from langgraph.graph import END, START, StateGraph

from agents.overseas_funding.config import AGENT_KEY, AGENT_VERSION
from agents.overseas_funding.nodes import NODE_FUNCS
from agents.overseas_funding.nodes.merge_signals import can_merge  # noqa: F401  (테스트·문서 참조)
from agents.overseas_funding.nodes.update_state import decide_status
from agents.overseas_funding.state import OverseasFundingState
from core import catalog
from core.evidence import validate_evidence
from core.schemas import AgentResult, Classification, Request

REEXTRACT_ORDER = ["periodic", "major_event", "news"]
REEXTRACT_NODE = {"periodic": "extract_periodic_plan", "major_event": "parse_major_events", "news": "extract_news"}


def route_after_resolve(state: OverseasFundingState) -> str:
    return "collect_disclosures" if state.get("company") else END


def route_after_merge(state: OverseasFundingState) -> str:
    """미해결 충돌이 있고 resolve_conflicts를 2회 미만 돌았으면 충돌 확인으로 간다 (D3)."""
    if any(not c.get("resolved") for c in state.get("conflicts") or []) and state.get("conflict_round", 0) < 2:
        return "resolve_conflicts"
    return "scope_gate"


def route_after_gate(state: OverseasFundingState) -> str:
    return "compute_funding_gap" if state.get("in_scope") else "update_state"


def route_after_verify(state: OverseasFundingState) -> str:
    """검증 실패 항목이 있고 재시도 2회 미만이면 가장 앞 추출 노드로 돌아간다 (5.3)."""
    targets = state.get("reextract_targets") or []
    if not targets or state.get("verify_round", 0) >= 2:
        return "update_state"
    return REEXTRACT_NODE[min(targets, key=REEXTRACT_ORDER.index)]


def _common(g):
    for name, fn in NODE_FUNCS.items():
        g.add_node(name, fn)
    g.add_edge(START, "parse_request")
    g.add_edge("parse_request", "resolve_company")
    g.add_conditional_edges("resolve_company", route_after_resolve, {"collect_disclosures": "collect_disclosures", END: END})


def _idle(g, *names):
    """이 경로에서 쓰지 않는 노드."""
    for n in names:
        g.add_edge(n, END)


def build_nollm_graph():
    """collect_disclosures → parse_major_events(분류 임시 unknown) → merge_signals → compute_funding_gap (13장 5단계). context no_llm=True로 실행한다."""
    g = StateGraph(OverseasFundingState)
    _common(g)
    for a, b in (("collect_disclosures", "parse_major_events"), ("parse_major_events", "merge_signals"), ("merge_signals", "compute_funding_gap")):
        g.add_edge(a, b)
    g.add_edge("compute_funding_gap", END)
    _idle(g, "extract_periodic_plan", "collect_news", "extract_news", "resolve_conflicts", "scope_gate", "verify", "update_state", "write_report")
    return g.compile()


def build_extraction_graph():
    """6단계: 추출 노드 3개 + collect_news D2 + merge_signals까지. 게이트·검증 없이 공백을 계산한다."""
    g = StateGraph(OverseasFundingState)
    _common(g)
    for a, b in (("collect_disclosures", "extract_periodic_plan"), ("extract_periodic_plan", "parse_major_events"), ("parse_major_events", "collect_news"), ("collect_news", "extract_news"), ("extract_news", "merge_signals"), ("merge_signals", "compute_funding_gap")):
        g.add_edge(a, b)
    g.add_edge("compute_funding_gap", END)
    _idle(g, "resolve_conflicts", "scope_gate", "verify", "update_state", "write_report")
    return g.compile()


def build_company_graph():
    """5.4 CompanyGraph."""
    g = StateGraph(OverseasFundingState)
    for name, fn in NODE_FUNCS.items():
        g.add_node(name, fn)
    g.add_edge(START, "parse_request")
    g.add_edge("parse_request", "resolve_company")
    g.add_conditional_edges("resolve_company", lambda s: "collect_disclosures" if s.get("company") else "write_report", {"collect_disclosures": "collect_disclosures", "write_report": "write_report"})
    for a, b in (("collect_disclosures", "extract_periodic_plan"), ("extract_periodic_plan", "parse_major_events"), ("parse_major_events", "collect_news"), ("collect_news", "extract_news"), ("extract_news", "merge_signals"), ("resolve_conflicts", "merge_signals"), ("compute_funding_gap", "verify"), ("update_state", "write_report"), ("write_report", END)):
        g.add_edge(a, b)
    g.add_conditional_edges("merge_signals", route_after_merge, {"scope_gate": "scope_gate", "resolve_conflicts": "resolve_conflicts"})
    g.add_conditional_edges("scope_gate", route_after_gate, {"compute_funding_gap": "compute_funding_gap", "update_state": "update_state"})
    g.add_conditional_edges("verify", route_after_verify, {"update_state": "update_state", "extract_periodic_plan": "extract_periodic_plan", "parse_major_events": "parse_major_events", "extract_news": "extract_news"})
    return g.compile()


def classifications(state: OverseasFundingState) -> list[Classification]:
    """3.6 분류. 게이트를 거친 경로만."""
    if "in_scope" not in state:
        return []
    ids = [m.evidence_ids[0] for m in state.get("metrics") or [] if m.metric_id == "ovs.overseas_project_count"]
    if not ids:
        return []
    projects = state.get("projects") or []
    status = state.get("signal_status") or decide_status(state)      # update_state를 거치지 않은 경로도 같은 규칙
    out = [Classification(key="ovs.signal_status", value=status.value, rule="7.9, 7.12", evidence_ids=ids), Classification(key="ovs.in_scope", value=str(state["in_scope"]).lower(), rule=state["scope_reason"], evidence_ids=ids)]
    rep = max((x for x in projects if x.get("gate_pass")), key=lambda x: x.get("amount_krw") or 0, default=None)
    if rep:
        out += [Classification(key="ovs.project_stage", value=str(rep["stage"]), rule="3.4 Stage, 7.8", evidence_ids=ids), Classification(key="ovs.investment_amount_source", value=rep["amount_source"], rule="7.8", evidence_ids=ids)]
    return out


def to_result(state: OverseasFundingState) -> AgentResult:
    """최종 상태를 공통 출력으로 바꾼다 (3.5). 판단 필드를 만들지 않는다."""
    req, company = state["request"], state.get("company")
    errors = list(state.get("errors") or [])
    evidence = {e.evidence_id: e for e in state.get("evidence") or []}
    gap = state.get("funding_gap")
    fin = state.get("financials")
    extra = {"projects": state.get("projects") or [], "signals": [s.model_dump(mode="json") for s in (state["signals_merged"] if "signals_merged" in state else state.get("signals") or [])], "unlinked_s6": state.get("unlinked_s6") or [], "conflicts": state.get("conflicts") or [], "trading_status_warnings": state.get("trading_status_warnings") or [], "report_source": state.get("report_source"), "s4_items": state.get("s4_items") or [], "funding_decisions": state.get("funding_decisions") or [],
             "financial_snapshot": fin.model_dump(mode="json") if fin else None, "funding_gap": gap.model_dump(mode="json") if gap else None, "periodic_sections": state.get("periodic_sections") or {}, "major_labels": state.get("major_labels") or {}, "news_queries": state.get("news_queries") or [], "news_count": len(state.get("news_items") or []), "decisions": state.get("decisions") or [], "llm_calls": state.get("llm_calls", 0)}
    result = AgentResult(request_id=req.request_id, agent=AGENT_KEY, agent_version=AGENT_VERSION, corp_code=company.corp_code if company else None, corp_name=company.corp_name if company else None, as_of=req.as_of,
                         status="failed" if not company else "partial" if errors else "complete", metrics=state.get("metrics") or [], classifications=classifications(state), findings=state.get("findings") or [], alerts=state.get("alerts") or [], report_markdown=state.get("report_markdown"), open_questions=list(dict.fromkeys(state.get("open_questions") or [])), evidence=list(evidence.values()), errors=errors, extra=extra)
    result = validate_evidence(result)
    bad = catalog.validate(result)
    return result.model_copy(update={"errors": result.errors + bad, "status": "partial"}) if bad else result


def _initial(request: Request) -> dict:
    return {"request": request, "evidence": [], "open_questions": [], "errors": [], "signals": [], "decisions": []}


def run_nollm(request: Request) -> AgentResult:
    return to_result(build_nollm_graph().invoke(_initial(request.model_copy(update={"context": {**request.context, "no_llm": True}}))))


def run_extraction(request: Request) -> AgentResult:
    return to_result(build_extraction_graph().invoke(_initial(request)))


def run_company(request: Request) -> AgentResult:
    return to_result(build_company_graph().invoke(_initial(request), {"recursion_limit": 80}))
