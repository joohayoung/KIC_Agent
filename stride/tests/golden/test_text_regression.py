"""해외진출 3단계 회귀: 사용자 검수(_review_text_검수결과.md)와 2026-11-06 재분류를 고정한다. 캐시된 원문을 쓴다. 실행: pytest -m golden."""
from datetime import date

import pytest

from agents.overseas_funding.nodes.collect_disclosures import report_section
from agents.overseas_funding.text.dart_sections import filter_overseas_paragraphs
from agents.overseas_funding.text.diff import explain_new
from core.clients.dart import get_client
from core.filings import select_reports

pytestmark = pytest.mark.golden
AS = date(2026, 11, 5)
# (기업, 사업연도, 정탐, 허용 오탐). 구영 p1·p2는 직전 보고서에 없던 CAR TECH 법인명이 있어 정탐이다 (2026-11-06 결정)
CASES = [("00202060", 2025, {"p1", "p2", "p39"}, {"p137"}),
         ("00114093", 2025, {"p71"}, set()),
         ("00913689", 2024, set(), set()),
         ("00913689", 2025, {"p28"}, {"p97"})]
# 1차 검수 오탐 중 재분류된 구영 p2를 뺀 것. 남아도 되는 것은 허용 오탐 2건(p137, p97)뿐이다
FIRST_REVIEW_FALSE = {("00202060", 2025): {"p136", "p137"}, ("00114093", 2025): {"p13", "p14", "p15", "p64", "p69", "p74", "p77", "p185"},
                      ("00913689", 2024): {"p61"}, ("00913689", 2025): {"p23", "p25", "p27", "p24", "p96", "p98", "p100", "p97"}}


def labels(cc, year):
    c = get_client()
    reports = {g["year"]: g["latest"]["rcept_no"] for g in select_reports(c.list_filings(AS, date(2022, 1, 1), AS, corp_code=cc, pblntf_ty="A")) if g["kind"] == "annual"}
    cur, prev = report_section(c, reports[year]), report_section(c, reports[year - 1])
    return explain_new(filter_overseas_paragraphs(cur), prev)


@pytest.mark.parametrize("cc,year,true_pos,allowed", CASES)
def test_new_paragraphs(cc, year, true_pos, allowed):
    new = {k for k, v in labels(cc, year).items() if v["new"]}
    assert new == true_pos | allowed


def test_car_tech_paragraphs_are_true_positive():
    info = labels("00202060", 2025)
    assert all("CARTECH" in info[p]["new_nouns"] for p in ("p1", "p2"))


def test_false_positives_reduced():
    left = sum(len(FIRST_REVIEW_FALSE[(cc, y)] & {k for k, v in labels(cc, y).items() if v["new"]}) for cc, y, _, _ in CASES)
    assert left == 2      # 허용 오탐 p137, p97
