from core.clients.dart_docs import attached_statements, audit_notes, body_xml, consolidated_audit_statements, consolidated_sources, doc_kind, intangible_from_sources, intangible_rollforward, note_sources, separate_only


def doc(kind, body):
    return f"<DOCUMENT><DOCUMENT-NAME ACODE='1'>{kind}</DOCUMENT-NAME>{body}</DOCUMENT>".encode("utf-8")


MAIN = doc("사업보고서", "<TITLE>2. 연결재무제표</TITLE>본문<TITLE>3. 연결재무제표 주석</TITLE>연결본문주석<TITLE>4. 재무제표</TITLE>별도본문")
CONS = doc("연결감사보고서", "<TITLE>(첨부)연 결 재 무 제 표</TITLE>연결현금흐름표<TITLE>주석</TITLE>연결감사주석<TITLE>외부감사 실시내용</TITLE>끝")
SEP = doc("감사보고서", "<TITLE>주석</TITLE>별도감사주석<TITLE>외부감사 실시내용</TITLE>끝")


def test_consolidated_audit_used_and_separate_excluded():
    # 파일 이름이 아니라 DOCUMENT-NAME으로 구분한다 (이름을 뒤집어도 같은 결과)
    files = {"x_00761.xml": SEP, "x_00760.xml": CONS, "x.xml": MAIN}
    src = consolidated_sources(files)
    assert [k for k, _ in src] == ["사업보고서", "연결감사보고서"]
    assert "연결본문주석" in src[0][1] and "별도본문" not in src[0][1]
    assert "연결감사주석" in src[1][1] and "연결현금흐름표" in src[1][1] and "외부감사" not in src[1][1]   # 첨부 재무제표 + 주석
    assert consolidated_audit_statements(files) == "연결현금흐름표" and consolidated_audit_statements({"b": SEP}) == ""
    assert all("별도감사주석" not in seg for _, seg in src)


def test_main_mode_and_body_only_zip():
    assert [k for k, _ in consolidated_sources({"a": MAIN, "b": CONS}, mode="main")] == ["사업보고서"]
    assert [k for k, _ in consolidated_sources({"a": MAIN})] == ["사업보고서"]        # 정정본은 본문만 있을 수 있다
    assert consolidated_sources({"b": SEP}) == []                                     # 별도 감사보고서만 있으면 연결 주석 없음


OFS_MAIN = doc("사업보고서", "연결대상 종속회사 현황(요약) : 해당사항 없음 <TITLE>2. 연결재무제표</TITLE>해당사항이 없습니다.<TITLE>3. 연결재무제표 주석</TITLE>해당사항이 없습니다."
                         "<TITLE>4. 재무제표</TITLE>재무제표 표<TITLE>5. 재무제표 주석</TITLE><TITLE>1. 일반사항</TITLE>별도본문주석</SECTION-2><TITLE>6. 배당</TITLE>배당")
OFS_SEP = doc("감사보고서", "<TITLE>(첨부)재 무 제 표</TITLE>현금흐름표<TITLE>주석</TITLE>별도감사주석<TITLE>외부감사 실시내용</TITLE>끝")


def test_separate_only_requires_both_conditions():
    assert separate_only({"a": OFS_MAIN, "b": OFS_SEP}) and separate_only({"a": OFS_MAIN})     # 정정본은 본문만 있을 수 있다
    assert not separate_only({"a": OFS_MAIN, "b": CONS})                                       # 연결감사보고서가 있음
    assert not separate_only({"a": MAIN, "b": SEP})                                            # 해당사항 없음 문구 없음
    with_tables = OFS_MAIN.replace("해당사항이 없습니다.".encode(), "<TABLE></TABLE>".encode())
    assert not separate_only({"a": with_tables})                                               # 본문에 연결재무제표 표가 있음
    assert not separate_only({"b": OFS_SEP})                                                   # 본문 없음


def test_separate_only_ignores_wording_of_consolidated_section():
    typo = OFS_MAIN.replace("해당사항이 없습니다.".encode(), "당사는 보고서 작성일 기준 현재 하당사항이 없습니다.".encode())      # 실제 원문 오타
    assert separate_only({"a": typo, "b": OFS_SEP})
    assert not separate_only({"a": typo, "b": CONS})                                           # 연결감사보고서가 있으면 문구와 무관하게 False
    silent = OFS_MAIN.replace("해당사항이 없습니다.".encode(), b"")
    assert separate_only({"a": silent, "b": OFS_SEP})


def test_note_sources_keeps_separate_out_of_consolidated_companies():
    src = note_sources({"a": OFS_MAIN, "b": OFS_SEP})
    assert [k for k, _ in src] == ["사업보고서", "감사보고서"]
    assert "별도본문주석" in src[0][1] and "배당" not in src[0][1]
    assert "별도감사주석" in src[1][1] and "현금흐름표" in src[1][1]
    assert [k for k, _ in note_sources({"a": OFS_MAIN, "b": OFS_SEP}, mode="main")] == ["사업보고서"]
    assert attached_statements({"a": OFS_MAIN, "b": OFS_SEP}) == "현금흐름표"
    con = note_sources({"a": MAIN, "b": CONS, "c": SEP})                                       # 연결 기업은 별도 감사보고서 제외 유지
    assert [k for k, _ in con] == ["사업보고서", "연결감사보고서"] and all("별도감사주석" not in s for _, s in con)
    assert attached_statements({"a": MAIN, "b": CONS, "c": SEP}) == "연결현금흐름표"


def test_helpers():
    assert doc_kind(CONS.decode()) == "연결감사보고서"
    assert audit_notes(SEP.decode()) == "별도감사주석"
    assert "연결본문주석" in body_xml({"b": SEP, "a": MAIN})


def table(*rows):
    return "<TABLE>" + "".join("<TR>" + "".join(f"<TD>{c}</TD>" for c in r) + "</TR>" for r in rows) + "</TABLE>"


CTX = "16. 무형자산 당기 중 무형자산의 변동내역은 다음과 같습니다. (단위 : 천원)"


def test_rollforward_amort_row_including_gamga_label():
    seg = CTX + table(["구분", "영업권", "회원권", "합계"], ["기초", "3,632,000", "897,715", "4,529,715"], ["취득", "-", "854,215", "854,215"],
                      ["처분", "-", "(267,863)", "(267,863)"], ["감가상각", "-", "(25,607)", "(25,607)"], ["기말", "3,632,000", "1,458,460", "5,090,460"])
    assert intangible_rollforward(seg) == {"status": "amort", "value": 25_607_000, "reason": "변동표 상각 행"}


def test_rollforward_no_amort_balanced_is_zero_and_unbalanced_is_missing():
    ok = CTX + table(["구분", "기초", "취득", "처분", "기말"], ["영업권", "100", "-", "-", "100"], ["회원권", "50", "10", "(5)", "55"], ["합계", "150", "10", "(5)", "155"])
    assert intangible_rollforward(ok)["status"] == "zero" and intangible_rollforward(ok)["value"] == 0
    bad = CTX + table(["구분", "기초", "취득", "처분", "기말"], ["회원권", "50", "10", "(5)", "60"], ["합계", "50", "10", "(5)", "60"])
    assert intangible_rollforward(bad)["status"] == "missing"


def test_rollforward_goodwill_only_is_zero():
    seg = CTX + table(["구 분", "당기", "전기"], ["영업권", "영업권"], ["기초장부금액", "-", "108,838"], ["손상차손", "-", "(108,838)"], ["기말장부금액", "-", "-"])
    assert intangible_rollforward(seg) == {"status": "zero", "value": 0, "reason": "영업권만 있음"}


def test_rollforward_total_column_with_long_header():
    seg = CTX + table(["", "영업권", "회원권", "무형자산 및 영업권 합계"], ["기초", "100", "50", "150"], ["상각비", "0", "(5)", "(5)"], ["기말", "100", "45", "145"])
    assert intangible_rollforward(seg)["value"] == 5_000


def test_rollforward_duplicate_amort_row_counted_once():
    seg = CTX + table(["구분", "합계"], ["기초", "100"], ["상각비", "(9)"], ["상각비", "(9)"], ["기말", "91"])
    assert intangible_rollforward(seg)["value"] == 9_000


def test_sources_zero_needs_matching_balance_sheet_and_sources_must_agree():
    zero = CTX + table(["구분", "기초", "취득", "기말"], ["회원권", "50", "10", "60"], ["합계", "50", "10", "60"])
    assert intangible_from_sources([("본문", zero)], (60_000,))["status"] == "zero"
    assert intangible_from_sources([("본문", zero)], (999_000_000,))["status"] == "missing"     # 일부 자산만 담은 표
    a = CTX + table(["구분", "합계"], ["기초", "10"], ["상각비", "(3)"], ["기말", "7"])
    b = CTX + table(["구분", "합계"], ["기초", "10"], ["상각비", "(4)"], ["기말", "6"])
    assert intangible_from_sources([("본문", a), ("감사", a)])["value"] == 3_000
    assert intangible_from_sources([("본문", a), ("감사", b)])["status"] == "missing"
    assert intangible_from_sources([])["status"] == "missing"


def test_rollforward_uses_current_period_not_previous():
    seg = "무형자산의 변동내역 전기 (단위 : 천원)" + table(["구분", "합계"], ["기초", "10"], ["상각비", "(9)"], ["기말", "1"]) + CTX + table(["구분", "합계"], ["기초", "10"], ["상각비", "(3)"], ["기말", "7"])
    assert intangible_rollforward(seg)["value"] == 3_000


def test_rollforward_not_found_or_foreign_currency():
    assert intangible_rollforward("표 없음")["status"] == "missing"
    seg = "무형자산의 변동내역 (단위 : CNY)" + table(["구분", "합계"], ["기초", "10"], ["기말", "10"])
    assert intangible_rollforward(seg)["status"] == "missing"

