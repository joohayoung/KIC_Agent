"""해외진출 12.1 계산 케이스: funding_gap, 투자 제외(7.10 4a), 조달 연결(11.2). 값은 손으로 계산했다."""
from datetime import date

from agents.overseas_funding.calc.funding import (NOTE_ALL_EXCLUDED, NOTE_INTERNAL, available_funds, confirmed_funding, decision_amount, decision_sub, find_completion_date, funding_gap,
                                                  funding_gap_ratio, investment_amount, is_result, judge_funding, overseas_amount, parse_result, sec_type, unconfirmed_funding)

BASE, AS_OF = date(2026, 6, 30), date(2026, 11, 5)


# ---- funding_gap ----
def test_funding_gap():
    assert available_funds(100, 50, -30, 0) == 120      # OCF 음수 → 그대로 차감
    assert funding_gap(200, 120) == 80 and funding_gap_ratio(80, 200) == 0.4
    assert funding_gap(None, 120) is None and funding_gap_ratio(None, 200) is None      # 투자액 없음
    assert available_funds(100, None, -30, 0) is None and funding_gap(200, None) is None
    assert funding_gap(0, 120) == -120 and funding_gap_ratio(-120, 0) is None           # 투자액 0: 비율 None


def test_unconfirmed_does_not_change_gap():
    judged = judge_funding([dec(overseas_amount=70)], [], AS_OF, BASE)
    confirmed, status = confirmed_funding(judged)
    assert (confirmed, status) == (0, "ok") and unconfirmed_funding(judged) == 70
    assert funding_gap(200, available_funds(100, 50, 0, confirmed)) == 50


# ---- 투자 제외 (7.10 4a) ----
def s4(no="A", amount=100, relation="-", **k):
    return {"rcept_no": no, "rcept_dt": "20260101", "amount": amount, "relation": relation, **k}


def test_confirmed_on_or_before_base_is_excluded():
    r = investment_amount([s4(confirmed_date="2026-06-30", confirmed_rcept_dt="20260701")], BASE, AS_OF)
    assert r["amount"] == 0 and r["note"] == NOTE_ALL_EXCLUDED and r["items"][0]["excluded"]


def test_confirmed_after_base_is_kept():
    r = investment_amount([s4(confirmed_date="2026-07-31", confirmed_rcept_dt="20260814")], BASE, AS_OF)
    assert r["amount"] == 100 and r["items"][0]["note"] == "재무 기준일 이후 집행 2026-07-31"


def test_scheduled_only_is_kept():
    r = investment_amount([s4(scheduled_date="2026-03-01")], BASE, AS_OF)
    assert r["amount"] == 100 and r["items"][0]["note"] == "집행 예정일 2026-03-01, 완료 미확인"


def test_evidence_after_as_of_counts_as_none():
    r = investment_amount([s4(confirmed_date="2026-03-01", confirmed_rcept_dt="20261201", scheduled_date="2026-03-01")], BASE, AS_OF)
    assert r["amount"] == 100 and "완료 미확인" in r["items"][0]["note"]


def test_internal_contribution_is_kept_even_with_date():
    for relation in ("종속회사", "자회사"):
        r = investment_amount([s4(relation=relation, confirmed_date="2026-03-01", confirmed_rcept_dt="20260401")], BASE, AS_OF)
        assert r["amount"] == 100 and r["items"][0]["note"] == NOTE_INTERNAL and not r["items"][0]["excluded"]


def test_all_excluded_does_not_fall_back():
    r = investment_amount([s4(confirmed_date="2026-03-01", confirmed_rcept_dt="20260401")], BASE, AS_OF, fallback=999)
    assert r["amount"] == 0 and r["note"] == NOTE_ALL_EXCLUDED
    assert investment_amount([], BASE, AS_OF, fallback=999)["amount"] == 999            # S4가 없을 때만 다음 순위
    assert funding_gap_ratio(funding_gap(0, 120), 0) is None


def test_judged_per_item_before_merge():
    rows = [s4("A", 100, confirmed_date="2026-03-01", confirmed_rcept_dt="20260401"), s4("B", 40, relation="자회사"), s4("C", 7, scheduled_date="2027-01-01")]
    r = investment_amount(rows, BASE, AS_OF, mergeable=True)
    assert r["amount"] == 47 and [x["excluded"] for x in r["items"]] == [True, False, False]


def test_not_mergeable_uses_latest():
    rows = [{**s4("A", 100, scheduled_date="2026-12-01"), "rcept_dt": "20260101"}, {**s4("B", 40, scheduled_date="2027-01-01"), "rcept_dt": "20260501"}]
    assert investment_amount(rows, BASE, AS_OF)["amount"] == 40


def test_find_completion_date():
    assert find_completion_date("3차 출자는 2025년 11월 12일에 진행되었습니다")[0] == date(2025, 11, 12)
    assert find_completion_date("2026년 7월 31일부로 납입을 완료하였습니다")[0] == date(2026, 7, 31)
    assert find_completion_date("대상 지분은 2025.10.31일자로 취득 완료 되었습니다")[0] == date(2025, 10, 31)
    assert find_completion_date("잔여 지분을 2025.10.31.자로 취득 완료하여")[0] == date(2025, 10, 31)
    assert find_completion_date("2026년 12월 31일까지 분할출자 예정") == (None, None)     # 완료일 미발견 → 금액 유지


# ---- 해외 용도 금액 ----
def test_overseas_amount():
    slots = {"fdpp_fclt": 70, "fdpp_op": 30, "fdpp_etc": None}
    assert overseas_amount(slots, {"fdpp_fclt": "mixed", "fdpp_op": "overseas"}) == (30, ["해외 용도 불명 칸: fdpp_fclt 70"])
    assert overseas_amount(slots, {"fdpp_fclt": "domestic", "fdpp_op": "unknown"}) == (None, ["해외 용도 불명 칸: fdpp_op 30"])     # overseas 칸 없음
    got = overseas_amount({"fdpp_fclt": 70}, {"fdpp_fclt": "mixed"}, {"fdpp_fclt": "공장A 50 / 공장B 20"})
    assert got == (None, ["해외 용도 불명 칸: fdpp_fclt 70", "칸 안 세부 내역 (합산 안 함): 공장A 50 / 공장B 20"])


# ---- 조달 연결 (11.2) ----
def dec(**k):
    return {"rcept_no": "D1", "rcept_dt": "20260501", "kind": "cb", "sub": None, "amount": 100, "board": "20260501", "overseas_amount": 60, "version": "ok", **k}


def res(**k):
    return {"rcept_no": "R1", "rcept_dt": "20260710", "nm": "증권발행결과(자율공시)", "sec": ("cb", None), "planned": 100, "actual": 100, "pay": "20260710", "board": "20260501", **k}


def judge(decs, results, **k):
    return judge_funding(decs, results, k.get("as_of", AS_OF), k.get("base", BASE))


def test_result_after_base_is_confirmed_and_added():
    j = judge([dec()], [res()])
    assert j[0]["final"] == "확정·합산" and confirmed_funding(j) == (60, "ok") and unconfirmed_funding(j) == 0


def test_filing_report_and_exchange_result_both_link():
    filing = res(nm="증권발행실적보고서")
    assert judge([dec()], [filing])[0]["final"] == "확정·합산"
    text = "구분 발행총액 비고 모집 500 / 모집 보통주 1,000 / 구분 발행총액 비고 공모 1,000,000 납입기일 2026년 07월 10일"
    assert parse_result(text, "증권발행실적보고서")["sec"] == ("rights", "보통")


def test_no_result_is_unconfirmed_even_past_scheduled_date():
    assert judge([dec(pymd="2026-05-02")], [])[0]["final"] == "미확정"


def test_result_after_as_of_is_unconfirmed():
    assert judge([dec()], [res(rcept_dt="20261201")])[0]["final"] == "미확정"


def test_other_securities_do_not_link():
    assert sec_type("기타파생결합사채")[0] == "other" and sec_type("제1회 무기명식 교환사채")[0] == "other"
    assert judge([dec()], [res(sec=sec_type("제1회 교환사채"))])[0]["final"] == "미확정"


def test_common_decision_does_not_link_preferred_result():
    d = dec(kind="rights", sub="보통")
    assert judge([d], [res(sec=("rights", "기타"))])[0]["final"] == "미확정"
    assert judge([d], [res(sec=("rights", "보통"))])[0]["final"] == "확정·합산"


def test_amount_mismatch_is_open_question():
    j = judge([dec()], [res(actual=90)])
    assert j[0]["final"] == "open_question" and j[0]["open_question"] == "조달 금액 불일치: 결정 100 / 결과 90: R1"
    assert confirmed_funding(j)[0] == 0 and unconfirmed_funding(j) == 60


def test_two_candidates_narrow_by_board_date():
    a, b = res(rcept_no="R1", board="20260501", pay="20260710"), res(rcept_no="R2", board="20260401", pay="20260711")
    assert judge([dec()], [a, b])[0]["result"]["rcept_no"] == "R1"
    b2 = res(rcept_no="R2", board="20260501", pay="20260711")
    j = judge([dec()], [a, b2])
    assert j[0]["final"] == "open_question" and j[0]["open_question"] == "조달 결과 공시 연결 모호: D1"


def test_one_result_two_decisions_is_open_question():
    j = judge([dec(rcept_no="D1"), dec(rcept_no="D2")], [res()])
    assert [x["final"] for x in j] == ["open_question", "open_question"]


def test_paid_on_or_before_base_is_excluded_from_both():
    j = judge([dec()], [res(pay="20260630")])
    assert j[0]["final"] == "확정·현금 반영" and confirmed_funding(j)[0] == 0 and unconfirmed_funding(j) == 0


def test_merger_and_subsidiary_results_are_excluded():
    assert not is_result("증권발행실적보고서(합병등)") and not is_result("증권발행결과(종속회사의주요경영사항)")
    assert is_result("[기재정정]증권발행실적보고서") and is_result("증권발행결과(자율공시)(제2회차CB)") and is_result("유상증자또는주식관련사채등의발행결과(자율공시)")
    assert judge([dec()], [res(nm="증권발행실적보고서(합병등)")])[0]["final"] == "미확정"


def test_correction_replaces_same_security_and_payment():
    old, new = res(rcept_no="R1", rcept_dt="20260710", actual=90), res(rcept_no="R2", rcept_dt="20260715", nm="[기재정정]증권발행결과(자율공시)")
    j = judge([dec()], [old, new])
    assert j[0]["final"] == "확정·합산" and j[0]["result"]["rcept_no"] == "R2"


def test_unreadable_payment_date_is_open_question():
    assert judge([dec()], [res(pay=None)])[0]["final"] == "open_question"


def test_unknown_version_is_not_added():
    j = judge([dec(version="unknown")], [res()])
    assert confirmed_funding(j) == (0, "unknown")


def test_decision_helpers():
    row = {"fdpp_fclt": "70", "fdpp_op": "30", "fdpp_etc": "-", "nstk_ostk_cnt": "5", "nstk_estk_cnt": "-"}
    assert decision_amount("rights", row) == 100 and decision_sub("rights", row) == "보통"
    assert decision_sub("rights", {"nstk_ostk_cnt": "5", "nstk_estk_cnt": "3"}) == "혼합"
    assert decision_amount("cb", {"bd_fta": "1,000"}) == 1000 and decision_sub("cb", {}) is None


def test_parse_exchange_result():
    s = "1. 증권의 종류 기명식 상환전환우선주식 2. 발행방법 제3자배정 유상증자 3. 발행내역 발행예정금액(원) 14,999,903,912 발행결정 최초 이사회결의일 2025-09-03 실제발행금액(원) 14,999,903,912 납입일 2025-09-18"
    p = parse_result(s, "증권발행결과(자율공시)")
    assert p["sec"] == ("rights", "기타") and p["actual"] == 14999903912 and p["pay"] == "20250918" and p["board"] == "20250903"
