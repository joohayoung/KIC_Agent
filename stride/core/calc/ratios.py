"""재무 비율 (재무 건전성 개발문서 3.2·12장). `%` 지표는 ×100 값, 배수는 그대로. 반올림하지 않는다. 입력이 없으면 None."""


def _pct(a: int | None, b: int | None) -> float | None:
    return None if a is None or not b else a / b * 100


def net_debt_to_ebitda(net_debt: int | None, ebitda: int | None) -> float | None:
    """같은 사업연도 값끼리 나눈다. ebitda가 None이거나 ≤ 0이면 None."""
    return None if net_debt is None or ebitda is None or ebitda <= 0 else net_debt / ebitda


def ebitda_interest_coverage(ebitda: int | None, interest: int | None, interest_note: str | None = None) -> tuple[float | None, str | None]:
    """fin.ebitda / 이자비용. 반환 (값, note). 이자비용이 없으면 interest_note를 그대로 돌려주고, 0이면 "이자비용 없음", EBITDA 음수면 값 그대로 + "EBITDA 음수"."""
    if interest is None:
        return None, interest_note
    if interest == 0:
        return None, "이자비용 없음"
    if ebitda is None:
        return None, "EBITDA 산출 불가"
    return ebitda / interest, "EBITDA 음수" if ebitda < 0 else interest_note


def ebitda_margin(ebitda: int | None, revenue: int | None) -> float | None:
    return _pct(ebitda, revenue)


def capital_impairment_ratio(capital_stock: int | None, equity: int | None) -> float | None:
    """(자본금 − 자기자본) / 자본금 × 100. 연결이면 equity = 지배기업 소유주지분 (fin_items.equity_ex_nci)."""
    return None if equity is None or not capital_stock else (capital_stock - equity) / capital_stock * 100


def debt_ratio(liabilities: int | None, equity: int | None) -> float | None:
    """부채총계 / 자본총계 × 100. 자본총계 ≤ 0이면 None."""
    return None if liabilities is None or equity is None or equity <= 0 else liabilities / equity * 100


def current_ratio(current_assets: int | None, current_liabilities: int | None) -> float | None:
    return _pct(current_assets, current_liabilities)


def borrowing_dependency(total_borrowings: int | None, total_assets: int | None) -> float | None:
    return _pct(total_borrowings, total_assets)
