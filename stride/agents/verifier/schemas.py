"""검증 에이전트 모델 (검증 개발문서 4장). 점수·등급 필드를 두지 않는다."""
from typing import Literal

from pydantic import BaseModel, Field


class CheckItem(BaseModel):
    code: str
    outcome: Literal["pass", "fail", "unverifiable"]
    kind: str | None = None
    target: str
    expected: str | None = None
    actual: str | None = None
    note: str | None = None
    evidence_ids: list[str] = []


class VerificationReport(BaseModel):
    request_id: str
    mode: Literal["results", "answer"]
    as_of: str
    corp_code: str | None
    checks: list[CheckItem]
    failed: list[CheckItem]
    unverifiable: list[CheckItem]
    coverage: dict[str, str] = {}
    failed_targets: list[str] = []
    llm_calls: int = 0


class ClaimCheckOutput(BaseModel):
    verdict: Literal["supported", "not_supported", "insufficient"]
    reason: str = Field(max_length=200)
