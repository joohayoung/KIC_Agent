"""공통 계약 테스트 (공통 양식 12장).

에이전트가 생기면 AGENT_SAMPLES에 "fixture 응답으로 만든 AgentResult를 돌려주는 함수"를 추가한다.
"""
from datetime import date

import pytest
from pydantic import ValidationError

from core import catalog
from core.schemas import FORBIDDEN_FIELDS, AgentResult, Classification, Evidence, Metric



def _financial_health_sample():
    from tests.unit.financial_health.test_graph import contract_sample
    return contract_sample()


def _overseas_funding_sample():
    from tests.unit.overseas_funding.test_graph import contract_sample
    return contract_sample()


AGENT_SAMPLES: list = [_financial_health_sample, _overseas_funding_sample]


def _forbidden_keys(obj, path="") -> list[str]:
    """extra·meta 같은 자유 dict 안까지 금지 필드 이름을 찾는다."""
    hits = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k).lower() in FORBIDDEN_FIELDS:
                hits.append(f"{path}.{k}")
            hits += _forbidden_keys(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            hits += _forbidden_keys(v, f"{path}[{i}]")
    return hits


def check_contract(result) -> list[str]:
    """계약 위반 목록 (빈 목록 = 통과)."""
    r = AgentResult.model_validate(result if isinstance(result, dict) else result.model_dump())
    errs = [f"금지 필드 {p}" for p in _forbidden_keys(r.model_dump())]
    for m in r.metrics:
        if not m.methodology:
            errs.append(f"{m.metric_id}: methodology 없음")
        if m.band is not None:
            errs.append(f"{m.metric_id}: band는 None이어야 함 (v1.5)")
    errs += catalog.validate(r)
    return errs


def sample_result(**over) -> AgentResult:
    c = catalog.get("fin.cash_and_equivalents")
    eid = "FIN:20250515000001:CFS:ifrs-full_CashAndCashEquivalents"
    base = dict(
        request_id="q1", agent="test", agent_version="0", corp_code="00000000", corp_name=None,
        as_of=date(2025, 6, 30), status="complete",
        metrics=[Metric(metric_id=c["metric_id"], name=c["name"], value=1, unit=c["unit"],
                        period="2025Q1", methodology=c["methodology"], data_status="ok", evidence_ids=[eid])],
        classifications=[Classification(key="fin.fs_basis", value="CFS", rule="연결 우선", evidence_ids=[eid])],
        evidence=[Evidence(evidence_id=eid, source_grade="A", source_type="dart_fin", corp_code="00000000",
                           published_at=date(2025, 5, 15), title="분기보고서")],
    )
    base.update(over)
    return AgentResult(**base)


def test_sample_passes():
    assert check_contract(sample_result()) == []


@pytest.mark.parametrize("factory", AGENT_SAMPLES)
def test_agent_contract(factory):
    assert check_contract(factory()) == []


def test_forbidden_top_level_field_rejected_by_schema():
    with pytest.raises(ValidationError):
        AgentResult(**sample_result().model_dump(), score=1)


def test_forbidden_field_in_extra_detected():
    assert check_contract(sample_result(extra={"projects": [{"rank": 1}]}))


def test_unregistered_metric_and_unit_mismatch():
    r = sample_result()
    bad = r.metrics[0].model_copy(update={"metric_id": "fin.nope"})
    wrong_unit = r.metrics[0].model_copy(update={"unit": "억원"})
    errs = check_contract(r.model_copy(update={"metrics": [bad, wrong_unit]}))
    assert any("미등록" in e for e in errs) and any("unit" in e for e in errs)


def test_band_must_be_none():
    r = sample_result()
    m = r.metrics[0].model_copy(update={"band": "x"})
    assert check_contract(r.model_copy(update={"metrics": [m]}))


def test_metric_requires_evidence():
    with pytest.raises(ValidationError):
        Metric(metric_id="fin.ebitda", name="EBITDA", value=1, unit="원", period="2025FY",
               methodology="m", data_status="ok", evidence_ids=[])
