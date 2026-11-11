"""해외진출 12.3 재생: 같은 기업을 빈 DB에서 시점 순서대로 실행하고 상태·경보 변화를 본다. 실제 claude -p를 호출한다.
실행: pytest -m llm tests/replay/overseas_funding. STRIDE_LLM_REPLAY=1이면 같은 입력의 호출 기록을 재사용한다."""
import json
import os
from datetime import date
from pathlib import Path

import pytest

from agents.overseas_funding.graph import run_company
from core.schemas import Request
from tests.golden.test_overseas_step7 import check

pytestmark = pytest.mark.llm
G = Path(__file__).resolve().parents[2] / "golden/overseas_funding"
if os.environ.get("STRIDE_LLM_REPLAY"):
    from tests.golden import llm_replay
    llm_replay.install()


def run_sequence(name, tmp_path):
    doc = json.loads((G / f"{name}.json").read_text(encoding="utf-8"))
    db = str(tmp_path / f"{name}.db")
    out = []
    for step in doc["expect"]["steps"]:
        r = run_company(Request(request_id="r", agent="overseas_funding", mode="single", corp_code=doc["corp_code"], as_of=date.fromisoformat(step["as_of"]), context={"db_path": db}))
        out.append((step, r))
    return out


def alert_types(r):
    return {a.alert_type for a in r.alerts}


@pytest.mark.parametrize("name", ["G-CHANGE_1", "G-TRACK_D"])
def test_replay(name, tmp_path):
    """12.3: 계획 시점 new_signal → 변경 전날 경보 없음(누수 검사) → 변경 뒤 취소·stage_down → 중복 프로젝트 없음. G-TRACK은 new_funding."""
    for step, r in run_sequence(name, tmp_path):
        check(r, step, step["as_of"])
        got = alert_types(r)
        for a in step.get("alerts_must_have", []):
            assert a in got, (step["as_of"], got, [x.message for x in r.alerts])
        for a in step.get("alerts_must_not_have", []):
            assert a not in got, (step["as_of"], got)
        assert all(x.evidence_ids for x in r.alerts)
