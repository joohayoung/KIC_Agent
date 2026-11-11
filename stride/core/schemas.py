"""공통 스키마 (stride-agent-dev-standard 3장 + 오케스트레이터 개발문서 4.1 RouteDecision).

모든 모델은 extra="forbid": 정의되지 않은 필드(score, rank 등 금지 필드 포함)는 검증에서 거부된다.
"""
from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Request(_Strict):
    request_id: str
    agent: str                               # agent_key
    mode: Literal["single", "batch"]
    company: str | None = None               # 기업명 / 종목코드 / corp_code
    corp_code: str | None = None             # 오케스트레이터가 이미 확정했으면 전달
    as_of: date
    lookback_months: int = 24
    period_start: date | None = None
    budget_llm_calls: int = 20
    context: dict = {}                       # 다른 에이전트 결과 ID 등 (원문 전달 금지)


class Evidence(_Strict):
    evidence_id: str                         # 공통 양식 4장 형식
    source_grade: Literal["A", "B", "C", "D"]  # A 공시, B 공공통계, C 언론, D 기타
    source_type: str
    corp_code: str | None
    published_at: date
    title: str
    url: str | None = None
    quote: str | None = Field(default=None, max_length=300)
    meta: dict = {}


class Metric(_Strict):
    """수치 지표 1개. 판단 없이 값과 근거만."""
    metric_id: str
    name: str
    value: float | int | None
    unit: str
    period: str
    methodology: str
    band: str | None = None                  # v1.5: 구간 표시 Phase 2. 항상 None (계약 테스트가 검사)
    data_status: Literal["ok", "missing", "needs_due_diligence", "unknown"]  # unknown: 정정 전 원본 값 확인 불가
    evidence_ids: list[str] = Field(min_length=1)
    note: str | None = None


class Classification(_Strict):
    """규칙으로 정해지는 분류. 판단이 아님."""
    key: str
    value: str
    rule: str
    evidence_ids: list[str] = Field(min_length=1)


class Finding(_Strict):
    finding_id: str
    kind: Literal["fact", "calc", "inference", "unverified"]
    text: str
    evidence_ids: list[str] = Field(min_length=1)
    verified: bool | None = None
    verify_note: str | None = None


class Alert(_Strict):
    """사실 변화 알림. 좋고 나쁨을 판단하지 않는다."""
    agent: str
    corp_code: str
    alert_type: str
    message: str
    evidence_ids: list[str] = Field(min_length=1)


class AgentResult(_Strict):
    """모든 에이전트의 공통 출력. 점수·순위·등급·추천 필드를 추가하지 않는다."""
    request_id: str
    agent: str
    agent_version: str
    corp_code: str | None
    corp_name: str | None
    as_of: date
    status: Literal["complete", "partial", "failed"]
    metrics: list[Metric] = []
    classifications: list[Classification] = []
    findings: list[Finding] = []
    alerts: list[Alert] = []
    open_questions: list[str] = []
    evidence: list[Evidence] = []
    report_markdown: str | None = None
    errors: list[str] = []
    extra: dict = {}


class RouteDecision(_Strict):
    """LLM 판단 지점의 결정 1건 (오케스트레이터 개발문서 4.1). D1~D4 공통."""
    point: str                               # "D1" | "D2" | "D3" | "D4"
    action: str                              # 지점별 Literal은 각 모듈에서 검증
    reason: str = Field(max_length=300)
    evidence_ids: list[str] = []
    accepted: bool = True
    fallback_action: str | None = None


# 공통 양식 3장 금지 필드. AgentResult.status(실행 상태)는 정의된 필드라 예외.
FORBIDDEN_FIELDS = {"score", "rank", "rating", "grade", "recommendation", "priority"}
