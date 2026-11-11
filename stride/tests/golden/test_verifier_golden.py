"""검증 에이전트 골든 V-CLEAN·V-TAMPER (검증 개발문서 13장). 해외진출(LLM 없는 경로)·재무 결과를 실제 DART 응답으로 만든다. 실행: pytest -m golden."""
import json
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import pytest

from agents.financial_health.graph import run as run_fin
from agents.overseas_funding.graph import run_nollm
from agents.verifier.graph import verify_results
from core.schemas import Request

pytestmark = pytest.mark.golden
G = Path(__file__).parent / "overseas_funding"


@lru_cache(maxsize=None)
def results():
    doc = json.loads((G / "G-POS_주.json").read_text(encoding="utf-8"))
    as_of = date.fromisoformat(doc["request"]["as_of"])
    req = dict(mode="single", corp_code=doc["corp_code"], as_of=as_of, context={"db_path": ":memory:"})
    return run_nollm(Request(request_id="v", agent="overseas_funding", **req)), run_fin(Request(request_id="v", agent="financial_health", **req)), as_of


def test_v_clean():
    ovs, fin, as_of = results()
    rep = verify_results([ovs, fin], as_of, [], request_id="v-clean")      # 커버리지(R-05)는 단위 테스트에서 본다
    assert rep.failed == [], [(c.code, c.kind, c.target, c.note) for c in rep.failed]
    assert any(c.code == "R-04" and c.outcome == "pass" for c in rep.checks), "두 에이전트가 같은 기간 현금을 냈다"
    assert any(c.code == "R-02" and c.outcome == "pass" and c.target.startswith("financial_health:fin.") for c in rep.checks), "재무 근거를 재조회로 대조했다"


def test_v_tamper_exactly_three():
    ovs, fin, as_of = results()
    calc = next(e for e in ovs.evidence if e.evidence_id.startswith("CALC:"))
    doc_ev = next(e for e in fin.evidence if not e.evidence_id.startswith("CALC:"))
    evidence = [e.model_copy(update={"meta": {**e.meta, "value": (e.meta["value"] or 0) + 1}}) if e is calc else e for e in ovs.evidence]          # 숫자 1개
    fin_ev = [e.model_copy(update={"published_at": as_of + timedelta(days=1)}) if e is doc_ev else e for e in fin.evidence]                      # 날짜 1개
    m0 = next(m for m in fin.metrics if m.evidence_ids)
    fin_metrics = [m.model_copy(update={"evidence_ids": ["DART:00000000000000:없음"]}) if m is m0 else m for m in fin.metrics]                     # 각주 1개
    rep = verify_results([ovs.model_copy(update={"evidence": evidence}), fin.model_copy(update={"evidence": fin_ev, "metrics": fin_metrics})], as_of, [], request_id="v-tamper")
    kinds = sorted({(c.code, c.kind) for c in rep.failed})
    assert kinds == [("R-01", "missing_evidence"), ("R-02", "value_mismatch"), ("R-03", "future_evidence")], [(c.code, c.kind, c.target) for c in rep.failed]
