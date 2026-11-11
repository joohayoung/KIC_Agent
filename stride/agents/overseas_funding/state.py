"""그래프 상태 (개발문서 4장). 5단계 노드가 쓰는 원자료는 s4_items, funding_decisions에 둔다."""
import operator
from typing import Annotated, TypedDict

from agents.overseas_funding.schemas import Company, FinancialSnapshot, Filing, FundingGap, Signal, SignalStatus
from core.schemas import Alert, Evidence, Finding, Metric, Request


class OverseasFundingState(TypedDict, total=False):
    request: Request
    run_id: str
    company: Company
    filings: list[Filing]
    periodic_sections: dict
    signals: Annotated[list[Signal], operator.add]
    evidence: Annotated[list[Evidence], operator.add]
    signals_merged: list[Signal]
    projects: list[dict]
    in_scope: bool
    scope_reason: str
    financials: FinancialSnapshot | None
    funding_gap: FundingGap | None
    s4_items: list[dict]            # 7.10 입력 (금액 칸, 관계 칸, 예정일, 정정 공시)
    funding_decisions: list[dict]   # 11.2 입력
    raw_filings: object             # FilingList (정정 판정용)
    major_labels: dict              # {rcept_no: 7.5 묶음 라벨}. change_direction, part_of_earlier, fund_use_scopes
    news_items: list[dict]
    trading_status_warnings: list[dict]     # 7.9 거래 상태 경고 (사실 표시만)
    unlinked_s6: list[dict]         # 프로젝트에 연결되지 않은 S6 기록. 단계·G4·경보에 쓰지 않는다 (7.9, 7.12)
    conflicts: list[dict]
    conflict_round: int
    verify_round: int
    verify_note: str
    reextract_targets: list[str]
    news_queries: list[str]
    decisions: Annotated[list[dict], operator.add]
    metrics: list[Metric]
    findings: list[Finding]
    signal_status: SignalStatus
    alerts: list[Alert]
    open_questions: Annotated[list[str], operator.add]
    report_markdown: str | None
    report_source: str              # llm / template
    errors: Annotated[list[str], operator.add]
    llm_calls: int
