"""이 에이전트 전용 모델 (개발문서 3.4)."""
from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class Company(BaseModel):
    corp_code: str
    corp_name: str
    stock_code: str | None
    market: Literal["KOSPI", "KOSDAQ", "KONEX", "UNLISTED"] | None = None


class Filing(BaseModel):
    """DART 공시 목록(list.json)의 1행."""
    rcept_no: str
    rcept_dt: date
    report_nm: str
    kind: Literal["periodic", "major_event", "alert", "other"]
    sub_kind: str | None = None
    is_correction: bool = False
    report_nm_norm: str = ""
    prefixes: list[str] = []
    suffixes: list[str] = []
    filer_scope: Literal["self", "subsidiary"] = "self"


class SignalType(str, Enum):
    PLAN = "S1_plan"
    PROGRESS = "S2_progress"
    CONFIRMED = "S4_confirmed"
    FUNDING = "S5_funding"
    ALERT = "S6_alert"


class Stage(int, Enum):
    MENTIONED = 1
    PLANNED = 2
    NEGOTIATING = 3
    DECIDED = 4
    EXECUTING = 5


class Signal(BaseModel):
    """해외 확장 신호 1건."""
    signal_id: str
    corp_code: str
    signal_type: SignalType
    event_date: date
    is_overseas: bool | None
    target_country: str | None
    method: Literal["new_plant", "expansion", "new_subsidiary", "acquisition", "equity_investment", "jv", "other"] | None
    purpose_category: Literal["growth_investment", "governance_restructuring", "refinancing", "working_capital", "domestic", "unknown"]
    amount_krw: int | None
    amount_original: str | None
    stage: Stage
    is_new: bool | None = None
    project_key: str | None = None
    summary: str = Field(max_length=200)
    value_status: Literal["ok", "unknown"] = "ok"
    value_note: str | None = None
    change_direction: Literal["postponed", "reduced", "cancelled", "expanded", "none"] | None = None     # S6만
    evidence_ids: list[str] = Field(min_length=1)


class FinancialSnapshot(BaseModel):
    """as_of 시점에 공개된 최신 재무 정보. 단위: 원."""
    corp_code: str
    fs_div: Literal["CFS", "OFS"]
    base_period: str
    source_rcept_no: str
    cash_and_equivalents: int | None
    short_term_financial_assets: int | None
    ttm_operating_cash_flow: int | None
    total_borrowings: int | None
    evidence_ids: list[str] = Field(min_length=1)


class FundingGap(BaseModel):
    overseas_investment_krw: int | None
    investment_amount_source: Literal["major_event", "periodic", "news", "missing"]
    available_funds_krw: int | None
    confirmed_funding_krw: int
    unconfirmed_funding_krw: int
    gap_krw: int | None
    gap_ratio: float | None
    note: str | None = None
    overseas_subsidiary_working_capital_krw: int = 0      # 해외 법인 운영자금 (7.5 R1 분할의 운영 칸). 투자액·공백에 넣지 않는다
    evidence_ids: list[str] = Field(min_length=1)


class SignalStatus(str, Enum):
    """규칙(7.9, 7.12)으로 정해지는 사실 분류."""
    NO_SIGNAL = "신호 없음"
    OUT_OF_SCOPE = "범위 밖"
    DETECTED = "해외 투자 신호"
    CONFIRMED = "해외 투자 확정"
    CHANGED = "계획 변경"
    CANCELLED = "취소"


ALERT_TYPES = ["new_signal", "stage_up", "stage_down", "new_funding", "plan_changed", "gap_changed", "cancelled"]


# ---- LLM 출력 모델 (10장) ----
Method = Literal["new_plant", "expansion", "new_subsidiary", "acquisition", "equity_investment", "jv", "other"]


class PeriodicPlanItem(BaseModel):
    paragraph_id: str
    quote: str = Field(max_length=200)
    target_country: str | None
    method: Method
    stage: int = Field(ge=1, le=5)
    amount_original: str | None
    timeline: str | None
    summary: str = Field(max_length=100)


class PeriodicPlanOutput(BaseModel):
    items: list[PeriodicPlanItem]
    no_plan_found: bool


class FundUseScope(BaseModel):
    slot: Literal["fdpp_fclt", "fdpp_bsninh", "fdpp_op", "fdpp_dtrp", "fdpp_ocsa", "fdpp_etc"]
    scope: Literal["overseas", "domestic", "mixed", "unknown"]


class MajorEventClassification(BaseModel):
    evidence_id: str
    purpose_category: Literal["growth_investment", "governance_restructuring", "refinancing", "working_capital", "domestic", "unknown"]
    is_overseas: bool
    fund_use_scopes: list[FundUseScope] = []
    target_country: str | None
    target_entity: str | None
    method: Method | None
    change_direction: Literal["postponed", "reduced", "cancelled", "expanded", "none"]
    related_project: str | None
    part_of_earlier: Literal["no", "yes", "unknown"] = "unknown"
    quote: str = Field(max_length=200)


class MajorEventBatchOutput(BaseModel):
    items: list[MajorEventClassification]


class NewsEvent(BaseModel):
    evidence_ids: list[str] = Field(min_length=1)
    target_country: str | None
    method: Method
    stage: int = Field(ge=1, le=5)
    amount_original: str | None
    is_rumor: bool
    summary: str = Field(max_length=100)


class NewsExtractionOutput(BaseModel):
    events: list[NewsEvent]


class NewsQuery(BaseModel):
    query: str
    proper_nouns: list[str]
    evidence_ids: list[str]


class RouteOutput(BaseModel):
    """10.10 D3. action은 코드가 검증한다 (7.8a 3)."""
    action: str
    reason: str
    evidence_ids: list[str] = []


class ClaimVerdict(BaseModel):
    finding_id: str
    verdict: Literal["supported", "contradicted", "not_enough"]
    reason: str = Field(max_length=50)


class VerifyOutput(BaseModel):
    results: list[ClaimVerdict]


class ReportOutput(BaseModel):
    """10.6. 마크다운을 JSON으로 감싸 받는다."""
    markdown: str


class GenerateNewsQueriesOutput(BaseModel):
    queries: list[NewsQuery] = Field(max_length=3)

