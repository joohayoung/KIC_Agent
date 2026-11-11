from datetime import date, datetime
from random import randint

from agents.overseas_funding.config import AGENT_KEY
from core.nodeguard import guarded


@guarded
def parse_request(state) -> dict:
    """요청을 검증하고 실행 ID를 발급한다 (7.1). as_of가 미래면 오늘로 바꾸지 않고 errors에 기록한다."""
    req = state["request"]
    if req.agent != AGENT_KEY or (req.mode == "single" and not (req.company or req.corp_code)):
        raise ValueError("요청 형식 오류")
    if req.as_of > date.today():
        raise ValueError(f"as_of {req.as_of}가 미래")
    return {"run_id": f"r_{datetime.now():%Y%m%d%H%M%S}{randint(0, 9999):04d}", "llm_calls": 0}
