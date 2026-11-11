"""검수된 골든 정답지의 입력값으로 계산 함수를 돌려 기대값과 맞는지 본다 (외부 호출 없음)."""
import json
from pathlib import Path

import pytest

from agents.overseas_funding.calc.funding import available_funds, funding_gap, funding_gap_ratio
from core.calc import ratios

G = Path(__file__).resolve().parents[1] / "golden"


def golden(path):
    return json.loads((G / f"{path}.json").read_text(encoding="utf-8"))["expect"]


@pytest.mark.parametrize("name", ["overseas_funding/G-POS_주", "overseas_funding/G-POS_보조", "overseas_funding/G-POS_MIXED"])
def test_funding_gap_matches_golden(name):
    e = golden(name)
    avail = available_funds(e["cash_krw"], e["short_term_krw"], e["ttm_ocf_krw"], e["confirmed_funding_krw"])
    assert avail == e["available_funds_krw"]
    gap = funding_gap(e["overseas_investment_krw"], avail)
    assert gap == e["funding_gap_krw"]
    assert funding_gap_ratio(gap, e["overseas_investment_krw"]) == pytest.approx(e["funding_gap_ratio"], abs=1e-4)


def test_net_cash_ratios_match_golden():
    e = golden("financial_health/F-NETCASH_1")
    assert ratios.net_debt_to_ebitda(e["fin.net_debt_krw"], e["fin.ebitda_krw"]) == pytest.approx(e["fin.net_debt_to_ebitda"], abs=0.01)
    assert ratios.ebitda_interest_coverage(e["fin.ebitda_krw"], e["interest_expense_krw"])[0] == pytest.approx(e["fin.ebitda_interest_coverage"], abs=0.01)


def test_negative_ebitda_matches_golden():
    e = golden("financial_health/F-NEGEBITDA_E")
    value, note = ratios.ebitda_interest_coverage(e["fin.ebitda_krw"], e["interest_expense_krw"])
    assert value == pytest.approx(e["fin.ebitda_interest_coverage"], abs=0.01) and note == e["coverage_note"]
    assert ratios.net_debt_to_ebitda(e["fin.net_debt_krw"], e["fin.ebitda_krw"]) is None


@pytest.mark.parametrize("name", ["F-IMPAIR50_KOSPI", "F-IMPAIR50_KOSDAQ", "F-FULLIMPAIR_KOSPI", "F-FULLIMPAIR_KOSDAQ", "F-KOSDAQ-EQ_KOSDAQ"])
def test_capital_impairment_matches_golden(name):
    e = golden(f"financial_health/{name}")
    assert ratios.capital_impairment_ratio(e["capital_stock_krw"], e["fin.equity_ex_nci_krw"]) == pytest.approx(e["fin.capital_impairment_ratio_pct"], abs=0.01)
