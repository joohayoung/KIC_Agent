"""재무 건전성 13.1 계산 케이스. 값은 손으로 계산했다."""
from types import SimpleNamespace as NS

import pytest

from core.calc import cashflow, fin_items, market, ratios
from core.units import parse_krw


def row(aid, v, nm="x", sj="BS"):
    return {"account_id": aid, "account_nm": nm, "sj_div": sj, "thstrm_amount": "" if v is None else str(v)}


# ---- ttm_operating_cash_flow (재무 13.1, 해외 12.1) ----
@pytest.mark.parametrize("cum,prev,fy,period,want", [
    (100, None, None, "FY", 100),       # 사업보고서: 연간 그대로
    (30, 20, 110, "1Q", 120),
    (60, 50, 110, "H1", 120),
    (90, 80, 110, "3Q", 120),
    (-62, 361, 264, "H1", -159),        # 음수 그대로
])
def test_ttm(cum, prev, fy, period, want):
    assert cashflow.ttm_operating_cash_flow(cum, prev, fy, period) == want


def test_ttm_missing_inputs():
    assert cashflow.ttm_operating_cash_flow(60, None, 110, "H1") is None        # 전기 동기 없음
    assert cashflow.ttm_operating_cash_flow(60, 50, None, "H1") is None
    # 직전 사업보고서 미접수: 호출자가 그 전 사업보고서와 맞는 전기 동기를 넘긴다 (2023 3Q 누적 + 2022 연간 − 2022 3Q 누적)
    assert cashflow.ttm_operating_cash_flow(75, 70, 95, "3Q") == 100


# ---- 비율 ----
def test_net_debt_to_ebitda():
    assert ratios.net_debt_to_ebitda(300, 100) == 3
    assert ratios.net_debt_to_ebitda(-410, 100) == -4.1                         # 순현금
    assert ratios.net_debt_to_ebitda(300, 0) is None and ratios.net_debt_to_ebitda(300, -5) is None
    assert ratios.net_debt_to_ebitda(None, 100) is None and ratios.net_debt_to_ebitda(300, None) is None


def test_ebitda_interest_coverage():
    assert ratios.ebitda_interest_coverage(100, 25) == (4, None)
    assert ratios.ebitda_interest_coverage(100, 25, "이자비용 출처: 금융원가 주석") == (4, "이자비용 출처: 금융원가 주석")
    assert ratios.ebitda_interest_coverage(-100, 25) == (-4, "EBITDA 음수")
    assert ratios.ebitda_interest_coverage(100, 0) == (None, "이자비용 없음")
    assert ratios.ebitda_interest_coverage(100, None, "이자비용 확인 불가: 표 없음") == (None, "이자비용 확인 불가: 표 없음")
    assert ratios.ebitda_interest_coverage(None, 25, "이자비용 출처: 금융원가 주석") == (None, "EBITDA 산출 불가")


@pytest.mark.parametrize("capital,equity,want", [(100, 100, 0), (100, 50, 50), (100, 0, 100), (100, -20, 120), (100, 150, -50)])
def test_capital_impairment_ratio(capital, equity, want):
    assert ratios.capital_impairment_ratio(capital, equity) == want


def test_capital_impairment_uses_equity_excluding_nci():
    bs = [row("ifrs-full_EquityAttributableToOwnersOfParent", 40), row("ifrs-full_Equity", -200)]   # 비지배지분이 큰 음수
    assert ratios.capital_impairment_ratio(100, fin_items.equity_ex_nci(bs, "CFS")) == 60
    assert fin_items.equity_ex_nci([row("ifrs-full_Equity", 70)], "OFS") == 70
    assert fin_items.equity_ex_nci([row("ifrs-full_Equity", 70)], "CFS") is None
    assert ratios.capital_impairment_ratio(0, 10) is None and ratios.capital_impairment_ratio(None, 10) is None


def test_percent_ratios():
    assert ratios.debt_ratio(50, 200) == 25
    assert ratios.debt_ratio(50, 0) is None and ratios.debt_ratio(50, -1) is None
    assert ratios.ebitda_margin(25, 100) == 25 and ratios.ebitda_margin(25, 0) is None and ratios.ebitda_margin(None, 100) is None
    assert ratios.current_ratio(150, 100) == 150 and ratios.borrowing_dependency(30, 120) == 25


def test_market():
    assert market.market_cap(500, 10, 7) == 500 and market.market_cap(None, 10, 7) == 70 and market.market_cap(None, None, 7) is None
    assert market.net_debt_to_ev(100, 400) == 0.2 and market.net_debt_to_ev(None, 400) is None
    assert market.per(100, 5) == 20 and market.per(100, -5) is None
    assert market.pbr(100, 50) == 2
    assert market.ev_to_ebitda(400, 100, 50) == 10 and market.ev_to_ebitda(400, 100, 0) is None


# ---- 재무 기본 항목 ----
def test_short_term_financial_assets():
    assert fin_items.short_term_financial_assets([row(fin_items.ST_ID, 5), row(fin_items.OTHER_CURRENT_ID, 9)]) == (5, None)   # 행이 있으면 그 값
    assert fin_items.short_term_financial_assets([row(fin_items.ST_ID, 0)]) == (0, None)
    assert fin_items.short_term_financial_assets([]) == (0, "단기금융상품 행 없음")
    assert fin_items.short_term_financial_assets([row(fin_items.OTHER_CURRENT_ID, 9)]) == (None, "단기금융상품 행 없음, 기타유동금융자산 행 있음")
    assert fin_items.short_term_financial_assets([row(fin_items.ST_ID, None)])[0] is None


def test_cash_and_net_debt():
    assert fin_items.cash_and_equivalents([row(fin_items.CASH_ID, 7)]) == (7, None)
    assert fin_items.cash_and_equivalents([])[0] is None
    assert fin_items.net_debt(100, 30, 20) == 50 and fin_items.net_debt(10, 30, 20) == -40
    assert fin_items.net_debt(None, 30, 20) is None and fin_items.net_debt(100, 30, None) is None


# ---- 상각비 판독·채택 (9.1a) ----
def doc(kind, body):
    return f"<DOCUMENT><DOCUMENT-NAME ACODE='1'>{kind}</DOCUMENT-NAME>{body}</DOCUMENT>".encode("utf-8")


def table(rows, unit="원"):
    trs = "".join("<TR>" + "".join(f"<TD>{c}</TD>" for c in r) + "</TR>" for r in rows)
    return f"(단위 : {unit})<TABLE>{trs}</TABLE>"


def report(n_rows=None, c_rows=None, unit="원"):
    n = f"<TITLE>20. 비용의 성격별 분류</TITLE>{table(n_rows, unit)}" if n_rows else ""
    c_ = f"<TITLE>31. 영업에서 창출된 현금</TITLE>{table(c_rows, unit)}" if c_rows else ""
    return {"a": doc("사업보고서", f"<TITLE>3. 연결재무제표 주석</TITLE>{n}{c_}<TITLE>4. 재무제표</TITLE>별도")}


HDR = ["구분", "당기", "전기"]
DEP, ROU, AM = "감가상각비", "사용권자산상각비", "무형자산상각비"


def adopt(n=None, c_=None, bs=(), unit="원"):
    return fin_items.amortization_sources("R1", report(n, c_, unit), list(bs))


def test_n_equals_c():
    r = adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]], [HDR, [DEP, "100", "9"], [AM, "5", "9"]])
    assert (r["depreciation"], r["amortization"], r["status"]) == (100, 5, "일치")
    assert "DART:R1:연결주석.비용의성격별분류#감가상각비" in r["evidence_ids"]


def test_n_combined_equals_c_sum():
    r = adopt([HDR, ["감가상각비와 무형자산상각비", "125", "9"]], [HDR, [DEP, "100", "9"], [ROU, "20", "9"], [AM, "5", "9"]])
    assert (r["depreciation"], r["amortization"], r["status"]) == (120, 5, "일치(합계)")


def test_n_dep_includes_rou():
    r = adopt([HDR, [DEP, "120", "9"], [AM, "5", "9"]], [HDR, [DEP, "100", "9"], [ROU, "20", "9"], [AM, "5", "9"]])
    assert r["depreciation"] == 120
    r = adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]], [HDR, [DEP, "100", "9"], [ROU, "20", "9"], [AM, "5", "9"]])   # N이 사용권 제외여도 포함 값 채택
    assert r["depreciation"] == 120


def test_dep_and_rou_split_differently_between_sources():
    r = adopt([HDR, [DEP, "11,368,686", "9"], [ROU, "370,833", "9"]], [HDR, [DEP, "11,326,149", "9"], [ROU, "413,370", "9"], ["무형자산감가상각", "22,177", "9"]], unit="천원")
    assert (r["depreciation"], r["amortization"], r["status"]) == (11_739_519_000, 22_177_000, "일치")
    bad = adopt([HDR, [DEP, "100", "9"], [ROU, "10", "9"]], [HDR, [DEP, "100", "9"], [ROU, "20", "9"]])       # 감가만 같고 합계가 다르면 불일치
    assert bad["status"] == "불일치" and bad["depreciation"] is None


def test_combined_row_with_separate_rou_row():
    r = adopt([HDR, ["감가상각비와 무형자산상각비", "105", "9"], [ROU, "20", "9"]], [HDR, [DEP, "100", "9"], [ROU, "20", "9"], [AM, "5", "9"]])
    assert (r["depreciation"], r["amortization"], r["status"]) == (120, 5, "일치(합계)")


def test_intangible_depreciation_label_is_amortization_not_combined():
    r = adopt(None, [HDR, [DEP, "100", "9"], ["무형자산감가상각", "5", "9"]])
    assert (r["amortization"], r["combined"], r["status"]) == (5, None, "C에만")
    r = adopt([HDR, ["감가상각비와 무형자산상각비", "105", "9"]])      # 진짜 합산 행은 그대로
    assert (r["combined"], r["status"]) == (105, "N 합산만")


def test_tolerance_is_one_table_unit():
    ok = adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]], [HDR, [DEP, "101", "9"], [AM, "5", "9"]], unit="천원")
    assert ok["depreciation"] == 101_000
    bad = adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]], [HDR, [DEP, "102", "9"], [AM, "5", "9"]], unit="천원")
    assert bad["depreciation"] is None and bad["status"] == "불일치" and bad["note"].startswith("상각비 출처 불일치")


def test_amortization_mismatch_between_sources_is_missing():
    r = adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]], [HDR, [DEP, "100", "9"], [AM, "9", "9"]])
    assert r["amortization"] is None and r["note"].startswith("상각비 출처 불일치")


def test_one_side_only():
    r = adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]])
    assert (r["depreciation"], r["status"], r["note"]) == (100, "N에만", "상각비 출처: N")
    r = adopt(None, [HDR, [DEP, "100", "9"], [AM, "5", "9"]])
    assert (r["depreciation"], r["status"], r["note"]) == (100, "C에만", "상각비 출처: C")


def test_function_columns_use_total_column():
    r = adopt([["구분", "매출원가", "판관비", "합계"], [DEP, "70", "30", "100"], [AM, "2", "3", "5"]])
    assert (r["depreciation"], r["amortization"]) == (100, 5)


def test_group_title_in_first_cell():
    r = adopt(None, [HDR, ["당기순이익조정을 위한 가감", DEP, "100"], [AM, "5"]])      # 묶음 제목은 병합 셀이라 둘째 행에는 칸이 없다
    assert (r["depreciation"], r["amortization"]) == (100, 5)


def test_units_converted():
    assert adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]], unit="백만원")["depreciation"] == 100_000_000


def test_foreign_currency_is_missing():
    r = adopt([HDR, [DEP, "100", "9"], [AM, "5", "9"]], unit="CNY")
    assert r["depreciation"] is None and r["note"] == "비원화"


def test_no_amortization_row_uses_bs():
    n = [HDR, [DEP, "100", "9"]]
    assert adopt(n)["amortization"] == 0
    assert adopt(n, bs=[row(fin_items.INTANGIBLE_IDS[0], 0)])["amortization"] == 0
    has = adopt(n, bs=[row(fin_items.INTANGIBLE_IDS[0], 50)])
    assert has["amortization"] is None and has["note"].startswith("무형자산상각비 미공시")
    assert adopt(n, bs=[row(fin_items.INTANGIBLE_IDS[0], None)])["amortization"] is None        # BS 금액 빈 값


def test_ebitda():
    year = NS(accounts={"operating_income": NS(amount=30, evidence_ids=["E1"])})
    sources = {"depreciation": 100, "amortization": 5, "combined": None, "note": None, "evidence_ids": ["E2"]}
    assert fin_items.ebitda(year, sources) == (135, ["E1", "E2"], None)
    assert fin_items.ebitda(NS(accounts={"operating_income": NS(amount=-130, evidence_ids=["E1"])}), sources)[0] == -25    # 음수 영업이익
    assert fin_items.ebitda(NS(accounts={}), sources) == (None, [], "계정 없음: 영업이익")
    combined = {**sources, "depreciation": None, "amortization": None, "combined": 90, "note": "감가+무형 합산 행만 있음(구성 불명)"}
    assert fin_items.ebitda(year, combined) == (120, ["E1", "E2"], "감가+무형 합산 행만 있음(구성 불명)")
    partial = {**sources, "amortization": None, "note": "무형자산상각비 미공시: 변동표 없음"}
    assert fin_items.ebitda(year, partial) == (None, [], "무형자산상각비 미공시: 변동표 없음")


# ---- 이자비용 (9.1a) ----
def notes(*tables):
    gap = "앞뒤 표와 떨어뜨리는 주석 문장입니다. " * 8      # 판독은 표 앞 90자로 표 성격을 본다. 실제 주석처럼 표 사이에 문장을 둔다
    body = "".join(f"{gap}{title} {table(rows, unit)}" for title, rows, unit in tables)
    return {"a": doc("사업보고서", f"<TITLE>3. 연결재무제표 주석</TITLE>{body}<TITLE>4. 재무제표</TITLE>별도")}


FINANCE = ("금융비용의 내역은 다음과 같습니다.", [HDR, ["이자비용", "50", "9"], ["외환차손", "7", "9"]], "원")
CF_TBL = ("31. 현금흐름표 영업활동현금흐름", [HDR, ["이자비용", "50", "9"]], "원")
CATEGORY = ("금융상품 범주별 손익", [HDR, ["이자비용", "50", "9"]], "원")


def interest(*tables, cf=()):
    return fin_items.interest_expense(list(cf), notes(*tables))


def test_interest_cf_row_first():
    assert interest(FINANCE, cf=[row("dart_AdjustmentsForInterestExpenses", 77, sj="CF")]) == (77, None)


def test_interest_foreign_currency_is_missing():
    cny = {**row("dart_AdjustmentsForInterestExpenses", 77, sj="CF"), "currency": "CNY"}
    assert interest(FINANCE, CF_TBL, cf=[cny]) == (None, "이자비용 확인 불가: 비원화")


def test_interest_two_tables_agree():
    assert interest(FINANCE, CF_TBL) == (50, "이자비용 출처: 금융원가 주석")


def test_interest_missing_reasons():
    other = ("31. 현금흐름표 영업활동현금흐름", [HDR, ["이자비용", "60", "9"]], "원")
    assert interest(FINANCE, other) == (None, "이자비용 확인 불가: 표끼리 값 다름")
    assert interest(FINANCE) == (None, "이자비용 확인 불가: 표 1개뿐")
    assert interest(("판매비", [HDR, ["급여", "1", "2"]], "원")) == (None, "이자비용 확인 불가: 표 없음")


def test_interest_cash_flow_route_without_finance_table():
    assert interest(CF_TBL, CATEGORY) == (50, "이자비용 출처: 현금흐름 조정 주석")
    only_finance_other = ("금융비용 내역", [HDR, ["이자비용", "40", "9"]], "원")
    assert interest(only_finance_other, CF_TBL, CATEGORY)[0] is None       # 금융표 값이 있으면 이 경로를 쓰지 않는다


def test_interest_ignores_lease_and_pension_tables():
    lease = ("리스부채 변동", [HDR, ["이자비용", "50", "9"]], "원")
    pension = ("확정급여채무의 변동", [HDR, ["이자비용", "50", "9"]], "원")
    assert interest(FINANCE, lease, pension) == (None, "이자비용 확인 불가: 표 1개뿐")


def test_interest_year_header_and_unit():
    years = ("금융비용 내역", [["구 분", "2025", "2024"], ["금융비용", "이자비용", "5", "4"]], "천원")
    cf = ("31. 현금흐름표 영업에서 창출된 현금", [["구 분", "2025", "2024"], ["이자비용", "5", "4"]], "천원")
    assert interest(years, cf) == (5_000, "이자비용 출처: 금융원가 주석")


def test_interest_capitalized_borrowing_reason():
    fin_only = ("금융원가 내역", [HDR, ["외환차손", "7", "9"]], "원")
    cap = ("차입원가", [HDR, ["자본화된 차입원가", "1,318,999", "9"]], "원")
    assert interest(fin_only, cap) == (None, "이자비용 확인 불가: 이자비용 행 없음(차입원가 자본화 있음)")
    zero = ("차입원가", [HDR, ["자본화된 차입원가", "-", "1,112,185"]], "원")
    assert interest(fin_only, zero) == (None, "이자비용 확인 불가: 표 없음")      # 전기 값을 당기로 읽지 않는다


def test_interest_rounding_between_files():
    body = lambda *t: "".join(f"{a} {table(r, u)}" for a, r, u in t)
    main = doc("사업보고서", "<TITLE>3. 연결재무제표 주석</TITLE>" + body(("금융비용", [HDR, ["이자비용", "201,051,136", "9"]], "원"), ("현금흐름표", [HDR, ["이자비용", "201,051,136", "9"]], "원")) + "<TITLE>4. 재무제표</TITLE>")
    cons = doc("연결감사보고서", "<TITLE>주석</TITLE>" + body(("금융비용", [HDR, ["이자비용", "201,051", "9"]], "천원"), ("현금흐름표", [HDR, ["이자비용", "201,051", "9"]], "천원")) + "<TITLE>외부감사</TITLE>")
    assert fin_items.interest_expense([], {"a": main, "b": cons})[0] == 201_051_136      # 천원 반올림 차이는 같은 값, 원 단위 값을 쓴다


# ---- parse_krw (해외 12.1) ----
@pytest.mark.parametrize("text,fx,want", [
    ("약 1,000억원", None, 100_000_000_000),
    ("1.1조원", None, 1_100_000_000_000),
    ("2,500억 원", None, 250_000_000_000),
    ("300백만원", None, 300_000_000),
    ("USD 150 million", {"USD": 1400}, 210_000_000_000),
    ("USD 150 million", None, None),
    ("수천억원", None, None),
    ("", None, None),
])
def test_parse_krw(text, fx, want):
    assert parse_krw(text, fx) == want
