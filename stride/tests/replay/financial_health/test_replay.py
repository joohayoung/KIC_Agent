"""재무 건전성 13.3 재생: 같은 기업을 as_of 3개 시점으로 빈 DB에서 순서대로 실행한다. 캐시된 DART 응답을 쓴다. 실행: pytest -m golden."""
import json
from datetime import timedelta
from pathlib import Path

import pytest

from agents.financial_health.graph import run
from core.asof import to_date
from core.clients.dart import get_client
from core.filings import select_reports
from core.schemas import Request

pytestmark = pytest.mark.golden
G = Path(__file__).resolve().parents[2] / "golden/financial_health"


def load(name):
    return json.loads((G / f"{name}.json").read_text(encoding="utf-8"))


def execute(cc, as_of, db):
    return run(Request(request_id="r", agent="financial_health", mode="single", corp_code=cc, as_of=as_of, context={"db_path": db}))


def alerts(r):
    return [a.alert_type for a in r.alerts]


def annual_report_periods(r):
    return sorted({m.period for m in r.metrics if m.metric_id == "fin.ebitda"})


@pytest.mark.parametrize("name,changed", [("F-AUDIT_한정", False), ("F-AUDIT_의견거절", True)])
def test_replay_three_points(name, changed, tmp_path):
    """사업보고서 접수 전날 → 접수 다음 날 → 반기보고서 접수 다음 날. 기준 보고서가 시점에 맞게 바뀌고 감사의견 변경 Alert는 접수 다음 날 처음 생긴다."""
    doc = load(name)
    cc = doc["corp_code"]
    y = doc["expect"]["bsns_year"]
    latest = to_date(doc["request"]["as_of"])
    groups = select_reports(get_client().list_filings(latest + timedelta(days=400), latest.replace(year=latest.year - 3), latest + timedelta(days=400), corp_code=cc, pblntf_ty="A"))
    annual = next(g for g in groups if g["kind"] == "annual" and g["year"] == y)
    half = next(g for g in groups if g["kind"] == "half" and g["year"] == y + 1)
    filed, half_filed = to_date(annual["first_dt"]), to_date(half["first_dt"])
    db = str(tmp_path / "replay.db")
    before = execute(cc, filed - timedelta(days=1), db)
    assert f"{y}FY" not in annual_report_periods(before) and "audit_opinion_changed" not in alerts(before)
    assert all(e.published_at <= filed - timedelta(days=1) for e in before.evidence)
    prior_opinions = {c.value for c in before.classifications if c.key == "fin.audit_opinion"}
    after = execute(cc, filed + timedelta(days=1), db)
    assert f"{y}FY" in annual_report_periods(after)
    now = {c.value for c in after.classifications if c.key == "fin.audit_opinion"}
    assert (now != prior_opinions) == changed and ("audit_opinion_changed" in alerts(after)) == changed
    third = execute(cc, half_filed + timedelta(days=1), db)
    assert any(m.period == f"{y + 1}H1말" for m in third.metrics) or any(m.period == f"{y + 1}H1말" and m.data_status == "unknown" for m in third.metrics)
    assert not any(m.period == f"{y + 1}H1말" for m in after.metrics)
    assert "audit_opinion_changed" not in alerts(third)
