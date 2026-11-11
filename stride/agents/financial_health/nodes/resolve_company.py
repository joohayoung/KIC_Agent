from core import company as company_mod
from core.clients import dart
from core.nodeguard import guarded


@guarded
def resolve_company(state) -> dict:
    """기업을 확정한다. 상장사가 아니거나 후보가 0·2개 이상이면 company=None (오케스트레이터가 되묻는다)."""
    req = state["request"]
    co, err, names = company_mod.resolve(dart.get_client(), req.company, req.corp_code)
    if co is None:
        return {"company": None, "errors": [f"resolve_company: {err}"], "open_questions": [f"기업 후보: {', '.join(names)}"] if names else []}
    if co["market"] not in ("KOSPI", "KOSDAQ"):
        return {"company": None, "errors": ["resolve_company: 비상장"]}
    return {"company": co}
