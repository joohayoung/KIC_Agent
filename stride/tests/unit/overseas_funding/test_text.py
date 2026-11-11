"""8.4, 8.5, 8.1.3 규칙 시험."""
import pytest

from agents.overseas_funding.nodes.collect_disclosures import pick_latest_previous, to_filing
from agents.overseas_funding.text.dart_sections import Paragraph, extract_business_section, filter_overseas_paragraphs
from agents.overseas_funding.text.diff import explain_new, mark_new_paragraphs, proper_nouns
from core.filings import classify_filing, normalize_report_nm

XML = """<DOCUMENT><TITLE>I. 회사의 개요</TITLE><P>개요 문단</P>
<TITLE ATOC="Y">II. 사업의 내용</TITLE><TITLE>1. 사업의 개요</TITLE><P>당사는 부품을 만듭니다.</P>
<TABLE><TR><TD>구분</TD><TD>금액</TD></TR><TR><TD>미국 법인</TD><TD>100</TD></TR></TABLE>
<TITLE>2. 주요 제품</TITLE><P>  </P><P>헝가리 공장을 2027년 착공할 계획입니다.</P>
<TITLE>III. 재무에 관한 사항</TITLE><P>재무 문단</P></DOCUMENT>""".encode()


def p(i, text):
    return Paragraph(f"p{i}", text)


def test_extract_business_section():
    out = extract_business_section(XML)
    assert [x.paragraph_id for x in out] == ["p1", "p2", "p3"]
    assert out[1].text == "구분 금액 | 미국 법인 100"          # 표는 행을 ' | '로 잇는다
    assert out[0].subsection == "1. 사업의 개요" and out[2].subsection == "2. 주요 제품"
    assert "개요 문단" not in [x.text for x in out] and "재무 문단" not in [x.text for x in out]
    assert extract_business_section(b"<DOCUMENT><P>x</P></DOCUMENT>") == []


def test_filter_keeps_keyword_and_neighbors():
    rows = [p(1, "무관"), p(2, "무관"), p(3, "베트남 공장"), p(4, "무관"), p(5, "무관")]
    assert [x.paragraph_id for x in filter_overseas_paragraphs(rows)] == ["p2", "p3", "p4"]
    assert filter_overseas_paragraphs([p(1, "무관")]) == []


def test_filter_prefers_plan_paragraphs_over_limit():
    rows = [p(1, "중국 " + "가" * 50), p(2, "미국 공장 신설 계획 " + "나" * 50)]
    assert [x.paragraph_id for x in filter_overseas_paragraphs(rows, window=0, max_chars=70)] == ["p2"]


def test_year_only_change_is_existing():
    prev = [p(1, "2024년 말 기준 미국 법인에서 생산 중입니다.")]
    assert mark_new_paragraphs([p(1, "2025년 말 기준 미국 법인에서 생산 중입니다.")], prev) == set()


def test_new_amount_alone_is_not_new():
    prev = [p(1, "미국 공장을 증설합니다. 설비를 늘립니다.")]
    cur = [p(1, "미국 공장을 증설합니다. 설비를 늘립니다. 1,000억 원")]
    assert explain_new(cur, prev)["p1"]["label"] == "기존"


def test_new_country_or_company_is_new_even_if_similar():
    prev = [p(1, "미국 공장 1,000억 원 투자"), p(2, "유럽 진출을 검토합니다.")]
    assert mark_new_paragraphs([p(1, "베트남 진출을 검토합니다.")], prev) == {"p1"}
    got = explain_new([p(1, "미국 공장 1,000억 원 투자 TESTCO, LLC")], prev)["p1"]
    assert got["new"] and got["new_nouns"] == ["TESTCO"]
    assert mark_new_paragraphs([p(1, "미국 공장 1,000억 원 투자")], prev) == set()


def test_rewritten_paragraph_with_known_nouns_is_not_new():
    prev = [p(1, "TESTCO USA, INC는 미국에 있고 2004년 설립되었습니다. 차체 부품을 만듭니다."), p(2, "수원시 본사 공장")]
    got = explain_new([p(1, "미국에 소재한 TESTCO USA, INC에서는 고객사에 납품할 제품을 생산하고 있으며 품질 관리를 합니다.")], prev)["p1"]
    assert got["label"] == "표현 변경" and not got["new"]


def test_new_action_word_keeps_low_similarity_paragraph_new():
    prev = [p(1, "일상적인 영업에 필요한 설비투자는 지속적으로 이루어지고 있습니다.")]
    got = explain_new([p(1, "미국 현지의 자동차부품 회사를 새롭게 인수하는 등 지속가능한 성장을 위한 활동을 합니다.")], [*prev, p(2, "미국 판매 시장")])["p1"]
    assert got["new"] and got["new_actions"] == ["인수"] and not got["new_nouns"]


def test_action_word_in_similar_paragraph_is_not_new():
    prev = [p(1, "미국 공장을 증설하여 생산 능력을 늘리고 있습니다.")]
    assert not explain_new([p(1, "미국 공장을 증설해 생산 능력을 늘리는 중입니다.")], prev)["p1"]["new"]


@pytest.mark.parametrize("text", ["(1) 생산설비 현황", "(2) 설비의 신설ㆍ매입 계획", "가. 영업개황", "다. 시장여건 및 영업의 개황", "(기준일 : 2025.12.31)", "② 베트남 공장 현황"])
def test_heading_is_never_new(text):
    got = explain_new([p(1, text)], [p(1, "전혀 다른 내용")])["p1"]
    assert got["label"] == "소제목" and not got["new"]


def test_long_numbered_paragraph_is_not_heading():
    text = "(1) 당사는 베트남 현지 법인을 통해 생산 능력을 확대하기 위하여 제2공장을 건립하는 계획을 진행하고 있습니다."
    assert explain_new([p(1, text)], [p(1, "무관한 문단")])["p1"]["new"]


def test_generic_words_are_not_names():
    assert proper_nouns("판매법인 생산공장 수원시 Rooms 601 BMW KOSPI 요인에도 대해서도") == {"수원"}


@pytest.mark.parametrize("nm,kind,sub", [
    ("타법인주식및출자증권처분결정", "other", "disposal"),
    ("주요사항보고서(타법인주식및출자증권양도결정)", "other", "disposal"),
    ("사업보고서 (2025.12)", "periodic", "annual"),
    ("[기재정정]반기보고서 (2026.06)", "periodic", "half"),
    ("[첨부추가]분기보고서 (2026.03)", "periodic", "quarter"),
    ("타법인주식및출자증권취득결정(자율공시)", "major_event", "acquisition_stock"),
    ("주요사항보고서(타법인주식및출자증권양수결정)", "major_event", "acquisition_stock"),
    ("주요사항보고서(유형자산양수결정)", "major_event", "acquisition_asset"),
    ("유형자산취득결정(종속회사의주요경영사항)", "major_event", "acquisition_asset"),
    ("주요사항보고서(영업양수결정)", "major_event", "business_transfer"),
    ("신규시설투자등 ", "major_event", "new_facility"),
    ("주요사항보고서(유상증자결정)", "major_event", "rights_issue"),
    ("주요사항보고서(전환사채권발행결정)", "major_event", "cb"),
    ("주요사항보고서(신주인수권부사채권발행결정)", "major_event", "bw"),
    ("증권발행실적보고서", "other", "issue_result"),
    ("증권발행실적보고서(합병등)", "other", None),
    ("증권발행결과(자율공시)(제2회차CB)", "other", "issue_result"),
    ("유상증자또는주식관련사채등의발행결과(자율공시)", "other", "issue_result"),
    ("기타주요경영사항(타법인주식및출자증권취득결정철회)", "alert", "change"),
    ("투자판단관련주요경영사항(공장 착공 연기)", "alert", "change"),
    ("주요사항보고서(자본으로인정되는채무증권발행결정)", "other", "hybrid_capital"),
    ("임원ㆍ주요주주특정증권등소유상황보고서", "other", None),
])
def test_classify_filing(nm, kind, sub):
    c = classify_filing(nm)
    assert (c["kind"], c["sub_kind"]) == (kind, sub)


def test_normalize_prefix_wrapper_suffix():
    n = normalize_report_nm(" [기재정정][첨부추가] 주요사항보고서(유상증자결정) ")
    assert n["norm"] == "유상증자결정" and n["prefixes"] == ["기재정정", "첨부추가"] and n["is_correction"] and n["wrapper"] == "주요사항보고서"
    s = normalize_report_nm("유상증자결정(종속회사의주요경영사항)")
    assert s["filer_scope"] == "subsidiary" and s["suffixes"] == ["종속회사의주요경영사항"]
    assert normalize_report_nm("[발행조건확정]증권신고서")["is_correction"] is False


def filing(no, dt, nm):
    return to_filing({"rcept_no": no, "rcept_dt": dt, "report_nm": nm})


def test_pick_latest_previous():
    a24, a25 = filing("A", "20250301", "사업보고서 (2024.12)"), filing("B", "20260301", "사업보고서 (2025.12)")
    q1, h1 = filing("C", "20260515", "분기보고서 (2026.03)"), filing("D", "20260814", "반기보고서 (2026.06)")
    assert [x.rcept_no for x in pick_latest_previous([a24, a25, q1, h1])] == ["D", "C"]        # 분기·반기: 직전 정기보고서
    assert [x.rcept_no for x in pick_latest_previous([a24, q1, a25])] == ["C", "B"]
    assert [x.rcept_no for x in pick_latest_previous([a24, a25])] == ["B", "A"]                # 사업보고서: 직전 사업보고서
    late = filing("E", "20261201", "사업보고서 (2025.12)")
    assert pick_latest_previous([a24, q1, late])[1].rcept_no == "A"                            # 사업보고서는 분기를 건너뛴다
    assert pick_latest_previous([a24])[1] is None and pick_latest_previous([]) == (None, None)
    corr = filing("F", "20260901", "[기재정정]사업보고서 (2025.12)")
    assert pick_latest_previous([a24, a25, corr])[0].rcept_no == "F"                           # 같은 기간은 정정본 최신
