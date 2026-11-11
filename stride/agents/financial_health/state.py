"""그래프 상태 (개발문서 5장). 노드 사이 원자료는 sources에 둔다 (v0.21, DB에 저장하지 않는다)."""
import operator
from typing import Annotated, TypedDict

from agents.financial_health.schemas import AccountValue, FinancialYear, MarketSnapshot, PeriodicReport, RestructuringEvent
from core.schemas import Alert, Classification, Evidence, Finding, Metric, Request


class FinancialHealthState(TypedDict, total=False):
    request: Request
    run_id: str
    company: dict | None
    reports: list[PeriodicReport]
    years: list[FinancialYear]
    latest_periodic: dict[str, AccountValue] | None
    sources: dict      # {"years": {연도: 보고서별 판독 결과}, "latest": 판독 결과, "unknown_years": [...]}
    audit: list[Classification]
    restructuring: list[RestructuringEvent]
    market: MarketSnapshot | None
    metrics: list[Metric]
    classifications: list[Classification]
    evidence: Annotated[list[Evidence], operator.add]
    open_questions: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    findings: list[Finding]
    alerts: list[Alert]
    report_markdown: str | None
