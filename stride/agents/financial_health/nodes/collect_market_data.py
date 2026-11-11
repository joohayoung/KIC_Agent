from agents.financial_health.schemas import MarketSnapshot
from core import evidence as ev
from core.nodeguard import guarded


@guarded
def collect_market_data(state) -> dict:
    """시가총액 (선택 항목). ① KRX ② 공공데이터 ③ missing.
    시세 API는 키가 없고 응답을 확인하지 못해(9.4 ※확인) 클라이언트를 아직 만들지 않았다. 항상 missing이다."""
    # ponytail: 키가 생기면 core/clients/krx.py로 ①②를 채운다. 지금 경로는 F-NOMARKET과 같다.
    req = state["request"]
    latest = (state.get("sources") or {}).get("latest")
    no = latest["rcept_no"] if latest else "none"
    return {"market": MarketSnapshot(base_date=req.as_of, market_cap=None, close_price=None, listed_shares=None, source="missing", evidence_ids=[ev.dart_section(no, "document")])}
