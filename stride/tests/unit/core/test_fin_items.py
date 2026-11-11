from core.calc import fin_items


def total_borrowings(bs, lease_note, zero_lease_ok=True):
    return fin_items.total_borrowings(bs, lease_note, zero_lease_ok=zero_lease_ok)


def row(aid, nm, v):
    return {"account_id": aid, "account_nm": nm, "thstrm_amount": "" if v is None else str(v)}


ST = row("ifrs-full_ShorttermBorrowings", "단기차입금", 100)
NOTE = {"has_section": True, "current": 20, "noncurrent": 10, "total": None, "currency": "KRW", "unit": 1,
        "context": "기타금융부채의 구성내역은 다음과 같습니다."}
EMPTY = {**NOTE, "has_section": False, "current": None, "noncurrent": None}


def test_bs_lease_rows_matching_note():
    bs = [ST, row("ifrs-full_CurrentLeaseLiabilities", "리스부채", 20), row("ifrs-full_NoncurrentLeaseLiabilities", "리스부채", 10)]
    assert total_borrowings(bs, NOTE) == (130, None, "재무상태표")
    assert total_borrowings(bs, {**NOTE, "noncurrent": 12})[0] is None          # 불일치 → missing
    assert total_borrowings(bs, None)[0] is None                                # 주석 대조 불가 → missing


def test_total_only_note_must_match_bs_sum_exactly():
    bs = [ST, row("ifrs-full_CurrentLeaseLiabilities", "유동리스부채", 20), row("ifrs-full_NoncurrentLeaseLiabilities", "비유동리스부채", 10)]
    only_total = {**NOTE, "current": None, "noncurrent": None, "total": 30}
    assert total_borrowings(bs, only_total) == (130, None, "재무상태표")
    assert total_borrowings(bs, {**only_total, "total": 31, "unit": 1000}) == (None, "리스부채 재무상태표·주석 불일치 (합계)", None)   # 표 단위 허용 없음
    assert total_borrowings(bs, {**only_total, "current": 20})[0] is None                                                              # 칸이 있으면 기존 칸별 대조


def test_note_used_when_no_bs_lease_row():
    assert total_borrowings([ST], NOTE) == (130, "리스부채 출처: 리스 주석", "리스 주석")


def test_no_double_count_when_lease_inside_borrowing_row():
    bs = [row("ifrs-full_Borrowings", "차입금및리스부채", 130)]               # 리스부채가 차입금 행에 이미 들어 있음
    assert total_borrowings(bs, NOTE)[0] is None
    host = {**NOTE, "context": "단기차입금의 내역은 다음과 같습니다."}         # 주석 표가 총차입금 포함 행의 구성
    assert total_borrowings([ST], host)[0] is None


def test_zero_lease_only_without_rou_and_section():
    assert total_borrowings([ST], EMPTY) == (100, None, "리스 없음")
    assert total_borrowings([ST, row("ifrs-full_RightofuseAssets", "사용권자산", 5)], EMPTY)[0] is None
    assert total_borrowings([ST], {**EMPTY, "has_section": True})[0] is None    # 리스 절은 있는데 값을 못 읽음
    assert total_borrowings([ST], None)[0] is None                              # 주석 못 읽음
    assert total_borrowings([], EMPTY) == (0, "차입금 계정 없음", "리스 없음")


def test_ppe_including_rou_tag_blocks_zero_lease():
    ppe = row(fin_items.PPE_ROU_ID, "유형자산", 500)
    assert total_borrowings([ST, ppe], EMPTY) == (None, "리스부채 확인 불가", None)


def test_interim_zero_lease_needs_prior_annual_without_lease():
    # 직전 사업보고서에 리스부채가 있으면(zero_lease_ok=False) 그 금액을 섞지 않고 missing
    assert total_borrowings([ST], EMPTY, zero_lease_ok=False) == (None, "최신 보고서 리스부채 미공시", None)
    # 직전 사업보고서에도 없으면 0 인정
    assert total_borrowings([ST], EMPTY, zero_lease_ok=True) == (100, None, "리스 없음")
    # 주석에서 값을 읽었으면 직전 사업보고서와 무관
    assert total_borrowings([ST], NOTE, zero_lease_ok=False) == (130, "리스부채 출처: 리스 주석", "리스 주석")


def test_unclassified_and_blank():
    assert total_borrowings([ST, row("-표준계정코드 미사용-", "유동성리스부채", 3)], NOTE)[0] is None
    assert total_borrowings([row("ifrs-full_ShorttermBorrowings", "단기차입금", None)], NOTE)[0] is None
