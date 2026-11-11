"""오케스트레이터 모델 (오케스트레이터 개발문서 4.2). 점수·등급·추천 필드를 두지 않는다."""
from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from core.schemas import Evidence, RouteDecision


class IntentResult(BaseModel):
    intent: Literal["discover", "review", "answer", "board_filter", "unknown"]
    company_mention: str | None = None
    filter_text: str | None = None
    clarify_question: str | None = None


class DiscoveryCriteria(BaseModel):
    markets: list[Literal["KOSPI", "KOSDAQ"]] = ["KOSPI", "KOSDAQ"]
    industries: list[str] = []
    target_regions: list[str] = []
    investment_types: list[Literal["신설", "증설", "지분 인수"]] = []
    stages: list[int] = []
    min_investment_amount: int | None = None
    min_funding_gap_ratio: float | None = None
    market_cap_range: tuple[int | None, int | None] | None = None
    exclude_rule_ids: list[str] = []
    signal_types: list[str] = []
    lookback_months: int = 12
    as_of: date
    max_deep_analysis: int = 20
    unparsed: list[str] = []


class CriteriaLLM(BaseModel):
    """parse_criteria.md 출력. as_of는 코드가 채운다."""
    markets: list[Literal["KOSPI", "KOSDAQ"]] = ["KOSPI", "KOSDAQ"]
    industries: list[str] = []
    target_regions: list[str] = []
    investment_types: list[Literal["신설", "증설", "지분 인수"]] = []
    stages: list[int] = []
    min_investment_amount: int | None = None
    min_funding_gap_ratio: float | None = None
    exclude_rule_ids: list[str] = []
    signal_types: list[str] = []
    lookback_months: int = 12
    unparsed: list[str] = []


class BoardRow(BaseModel):
    corp_code: str
    corp_name: str
    market: str
    industry: str
    project: dict
    investment_amount: dict
    funding_gap: dict
    debt_ratio: dict
    ttm_operating_cash_flow: dict
    rule_hits: list[str]
    change_badges: list[str]
    verification: Literal["verified", "needs_check", "partial"]
    matched_search_ids: list[str]
    is_watched: bool
    liquidity: dict = {}          # B 유동성 원천·소요 (common.LIQUIDITY_KEYS → mdict)
    funding_status: dict = {}     # 해외 용도 조달 상태 {label, unconfirmed, confirmed, rcept_nos}
    risk_warnings: list[str] = []     # D 재무 위험 경고 (상장 규정 기준 해당·거래 상태)


class DiscoveryBoard(BaseModel):
    search_id: str
    run_id: str
    as_of: date
    criteria: DiscoveryCriteria
    funnel: list[dict]
    summary_md: str
    rows: list[BoardRow]
    pending: list[dict]
    excluded: list[dict]
    suggestions: list[RouteDecision] = []


class RuleResult(BaseModel):
    rule_id: str
    hit: bool | None
    label: str
    source: str
    source_date: str
    market: str
    inputs: dict
    evidence_ids: list[str] = Field(min_length=1)


class FinalReport(BaseModel):
    report_id: str
    corp_code: str
    as_of: date
    is_partial: bool
    sections: dict[str, str]
    rule_results: list[RuleResult]
    due_diligence: list[str]
    verification_status: Literal["passed", "partially_failed"]
    evidence: list[Evidence]


class Answer(BaseModel):
    question: str
    answer_md: str
    evidence_ids: list[str]
    links: list[dict]
    verification_status: Literal["passed", "partially_failed", "no_data"]


class FeedItem(BaseModel):
    item_id: str
    kind: Literal["new_match", "left_match", "watch_change"]
    search_id: str | None
    corp_code: str
    alert_type: str
    before: str | None
    after: str | None
    reason: str
    event_date: date
    evidence_ids: list[str] = Field(min_length=1)
    read: bool = False


# ---- LLM 출력 모델 (10장) ----
class Sentence(BaseModel):
    text: str
    evidence_ids: list[str] = []


class SentencesOutput(BaseModel):
    """summarize_board.md, answer_question.md"""
    sentences: list[Sentence]
    links: list[dict] = []


class ReportSectionsOutput(BaseModel):
    """synthesize_report.md: 섹션마다 문장 목록"""
    summary: list[Sentence]
    project: list[Sentence]
    funding_gap: list[Sentence]
    financial: list[Sentence]
    rules: list[Sentence]
    verification: list[Sentence]
    opinion: list[Sentence]


class RouteOutput(BaseModel):
    action: str
    field: str | None = None
    reason: str = Field(max_length=300)
    evidence_ids: list[str] = []


class FollowupOutput(BaseModel):
    suggestions: list[RouteOutput] = Field(max_length=2)


class BoardFilter(BaseModel):
    field: str
    op: Literal[">=", "<=", ">", "<", "==", "!="]
    value: float | str


class BoardFilterOutput(BaseModel):
    filters: list[BoardFilter]
