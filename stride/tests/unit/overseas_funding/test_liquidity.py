"""유동성 원천·소요 (S&P Liquidity Descriptors 준용 STRIDE 정의, 2026-11-10 방향 수정 5번 시험 목록)."""
from datetime import date

import pytest

from agents.overseas_funding.calc.funding import (available_funds, confirmed_funding, horizon_end, investment_amount, investment_beyond_24m, investment_dates,
                                                  investment_within_24m, judge_funding, liquidity_ratio, liquidity_surplus, liquidity_uses)
from core.calc.fin_items import dividends_paid_last_fy, maturing_debt_1y

AS = "2026-11-05"


def bs_row(aid, nm, amt):
    return {"account_id": aid, "account_nm": nm, "thstrm_amount": amt}


HEAD = [bs_row("ifrs-full_Liabilities", "부채총계", "900"), bs_row("ifrs-full_CurrentLiabilities", "유동부채", "500")]
NONCUR = [bs_row("ifrs-full_NoncurrentLiabilities", "비유동부채", "400"), bs_row("ifrs-full_LongtermBorrowings", "장기차입금", "300")]


def test_uses_zero_ratio_none_surplus_kept():
    assert liquidity_uses(0, 0, 0) == 0
    assert liquidity_ratio(100, 0) is None and liquidity_surplus(100, 0) == 100


def test_negative_sources_kept_as_is():
    src = available_funds(10, 0, -50, 0)
    assert src == -40 and liquidity_ratio(src, 20) == -2.0 and liquidity_surplus(src, 20) == -60


def test_any_missing_component_makes_uses_none():
    assert liquidity_uses(None, 1, 1) is None and liquidity_uses(1, None, 1) is None and liquidity_uses(1, 1, None) is None
    assert liquidity_ratio(None, 10) is None and liquidity_surplus(10, None) is None


@pytest.mark.parametrize("when,inside", [("2028-11-05", True), ("2028-11-06", False), ("2026-12-01", True)])
def test_24m_boundary(when, inside):
    parts = [[100, when]]
    assert investment_within_24m(parts, AS) == (100 if inside else 0)
    assert investment_beyond_24m(parts, AS) == (0 if inside else 100)


def test_horizon_leap_day():
    assert horizon_end("2024-02-29") == date(2026, 2, 28)


def test_no_date_counts_inside():
    assert investment_within_24m([[100, None], [50, "2030-01-01"]], AS) == 100
    assert investment_beyond_24m([[100, None], [50, "2030-01-01"]], AS) == 50
    assert investment_within_24m([], AS) is None


def test_investment_dates_follow_investment_amount():
    s4 = [{"rcept_no": "a", "rcept_dt": "20260801", "amount": 70, "relation": "", "scheduled_date": "2029-03-01"},
          {"rcept_no": "b", "rcept_dt": "20260901", "amount": 30, "relation": "", "scheduled_date": None}]
    inv = investment_amount(s4, date(2026, 6, 30), date(2026, 11, 5), mergeable=True)
    parts = investment_dates(s4, inv, mergeable=True, fallback=None)
    assert parts == [[70, "2029-03-01"], [30, None]]
    assert investment_within_24m(parts, AS) == 30 and investment_beyond_24m(parts, AS) == 70
    assert investment_dates([], {"items": []}, mergeable=False, fallback=55) == [[55, None]]      # S5·S1·S2 금액은 날짜 없음


def test_no_dividend_row_is_zero_with_note():
    assert dividends_paid_last_fy([{"account_id": "ifrs-full_DividendsReceivedClassifiedAsInvestingActivities", "account_nm": "배당금의 수취", "thstrm_amount": "5"}]) == (0, "배당 지급 행 없음")


def test_dividend_paid_rows():
    assert dividends_paid_last_fy([{"account_id": "ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "account_nm": "배당금의 지급", "thstrm_amount": "-1,200"}]) == (1200, None)
    assert dividends_paid_last_fy([{"account_id": "-표준계정코드 미사용-", "account_nm": "배당금 지급", "thstrm_amount": "300"}]) == (300, None)
    assert dividends_paid_last_fy([{"account_id": "dart_DividendsPaidToHybridBond", "account_nm": "신종자본증권의 배당", "thstrm_amount": "9"}])[0] == 0
    assert dividends_paid_last_fy([{"account_id": "ifrs-full_DividendsPaidClassifiedAsFinancingActivities", "account_nm": "배당금지급", "thstrm_amount": ""}])[0] is None


def test_maturing_debt_current_section_only_and_lease_excluded():
    bs = HEAD + [bs_row("ifrs-full_ShorttermBorrowings", "단기차입금", "100"), bs_row("-표준계정코드 미사용-", "유동성장기부채", "40"),
                 bs_row("dart_ConvertibleBonds", "전환사채", "10"), bs_row("ifrs-full_CurrentLeaseLiabilities", "리스부채", "999")] + NONCUR + [bs_row("dart_ConvertibleBonds", "전환사채", "77")]
    assert maturing_debt_1y(bs) == (150, None)


def test_maturing_debt_unclassified_row_missing():
    v, note = maturing_debt_1y(HEAD + [bs_row("-표준계정코드 미사용-", "유동성 기타 차입금(사채 제외)", "5")] + NONCUR)
    assert v is None and "미분류" in note
    v, note = maturing_debt_1y([bs_row("-표준계정코드 미사용-", "차입부채", "5")])      # 유동부채 절을 못 찾음
    assert v is None and "미분류" in note


def test_maturing_debt_no_rows_zero():
    assert maturing_debt_1y(HEAD + NONCUR) == (0, "유동 차입 행 없음")


@pytest.mark.parametrize("pay,counted", [("20260815", True), ("20260615", False)])
def test_confirmed_funding_pay_date_vs_base(pay, counted):
    """결과 공시 납입일이 재무 기준일(2026-06-30) 뒤면 원천에 더하고, 앞이면 이미 현금에 들어 있어 더하지 않는다."""
    dec = [{"rcept_no": "d", "rcept_dt": "20260701", "kind": "rights", "sub": "보통", "amount": 100, "board": None, "overseas_amount": 80}]
    res = [{"rcept_no": "r", "rcept_dt": "20260820", "nm": "증권발행실적보고서", "sec": ("rights", "보통"), "actual": 100, "planned": None, "pay": pay, "board": None}]
    judged = judge_funding(dec, res, date(2026, 11, 5), date(2026, 6, 30))
    assert confirmed_funding(judged)[0] == (80 if counted else 0)
