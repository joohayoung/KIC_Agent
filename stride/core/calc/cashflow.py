"""현금흐름 계산 (해외진출 개발문서 11.1, 지표 fin.ttm_operating_cash_flow). 금액 단위는 원(int)."""


def ttm_operating_cash_flow(cum_current: int | None, cum_prev_same: int | None, fy_prev: int | None, period: str) -> int | None:
    """최근 4분기(TTM) 영업현금흐름. period가 "FY"면 cum_current 자체가 TTM이다.

    그 외(1Q, H1, 3Q): 당기 누적 + 직전 사업연도 연간 − 전기 동기 누적. 입력 중 하나라도 없으면 None (부분 합계로 대체하지 않는다).
    fy_prev는 as_of 이전에 접수된 직전 사업보고서 값이다. 어느 보고서를 쓸지는 호출자가 고른다.
    """
    if period == "FY":
        return cum_current
    if cum_current is None or cum_prev_same is None or fy_prev is None:
        return None
    return cum_current + fy_prev - cum_prev_same
