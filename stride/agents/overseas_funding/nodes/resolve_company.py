from agents.overseas_funding.schemas import Company
from core import company as company_mod
from core.clients import dart
from core.nodeguard import guarded


@guarded
def resolve_company(state) -> dict:
    """기업을 확정한다 (7.2). 비상장사는 company를 쓰되 errors에 unlisted를 남긴다. 후보가 여러 개면 고르지 않는다."""
    req = state["request"]
    co, err, names = company_mod.resolve(dart.get_client(), req.company, req.corp_code)
    if co is None:
        return {"errors": [f"resolve_company: {err}"], "open_questions": [f"기업 후보: {', '.join(names)}"] if names else []}
    return {"company": Company(**co), "errors": ["resolve_company: unlisted"] if co["market"] == "UNLISTED" else []}
