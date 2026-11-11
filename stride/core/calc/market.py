"""시장 지표 (재무 건전성 개발문서 3.2, 선택 항목). 입력이 없으면 None."""


def market_cap(api_value: int | None, close_price: int | None, listed_shares: int | None) -> int | None:
    """API 제공값. 없으면 같은 날짜 종가 × 상장주식수."""
    if api_value is not None:
        return api_value
    return None if close_price is None or listed_shares is None else close_price * listed_shares


def net_debt_to_ev(net_debt: int | None, cap: int | None) -> float | None:
    """fin.net_debt / (fin.market_cap + fin.net_debt)."""
    if net_debt is None or cap is None or cap + net_debt == 0:
        return None
    return net_debt / (cap + net_debt)


def per(cap: int | None, net_income_parent: int | None) -> float | None:
    """순이익 ≤ 0이면 None."""
    return None if cap is None or net_income_parent is None or net_income_parent <= 0 else cap / net_income_parent


def pbr(cap: int | None, equity_parent: int | None) -> float | None:
    """지배주주지분 ≤ 0이면 None."""
    return None if cap is None or equity_parent is None or equity_parent <= 0 else cap / equity_parent


def ev_to_ebitda(cap: int | None, net_debt: int | None, ebitda: int | None) -> float | None:
    """EBITDA ≤ 0이면 None."""
    return None if cap is None or net_debt is None or ebitda is None or ebitda <= 0 else (cap + net_debt) / ebitda
