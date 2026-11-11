from datetime import date, datetime
from random import randint

from agents.financial_health.config import AGENT_KEY
from core.nodeguard import guarded


@guarded
def parse_request(state) -> dict:
    """Request를 검증하고 run_id를 만든다. as_of가 미래면 오늘로 바꾸고 errors에 기록한다."""
    req = state["request"]
    errors = []
    if req.agent != AGENT_KEY:
        errors.append(f"parse_request: agent {req.agent}")
    if req.as_of > date.today():
        errors.append(f"parse_request: as_of {req.as_of}가 미래라 오늘로 바꿈")
        req = req.model_copy(update={"as_of": date.today()})
    return {"request": req, "run_id": f"r_{datetime.now():%Y%m%d%H%M%S}{randint(0, 9999):04d}", "errors": errors}
