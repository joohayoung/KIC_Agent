"""검증 그래프 상태 (검증 개발문서 5장)."""
import operator
from typing import Annotated, TypedDict

from agents.verifier.schemas import CheckItem, VerificationReport
from core.schemas import AgentResult


class VerifierState(TypedDict, total=False):
    request: dict                    # {request_id, mode, as_of, corp_code, required_metrics}
    results: list[AgentResult]
    document: str | None
    footnotes: dict                  # answer 모드: {각주 번호: [evidence_id]} (자체 결정: 문서 각주 [n] ↔ 근거 대응)
    cited: dict                      # answer 모드: {evidence_id: {"value", "unit", "quote"}}
    sentences: list[dict]
    checks: Annotated[list[CheckItem], operator.add]
    llm_calls: int
    report: VerificationReport | None
    errors: Annotated[list[str], operator.add]
