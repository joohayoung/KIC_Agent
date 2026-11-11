"""해외진출 5단계: LLM 없는 그래프. 가짜 클라이언트로 정형 칸 읽기, R1·R3, 시점, 자금 공백을 시험한다."""
from datetime import date

from agents.overseas_funding.graph import run_nollm
from agents.overseas_funding.nodes.parse_major_events import parse_acquisition_form
from core.asof import FilingList, filter_asof
from core.clients import dart
from core.clients.dart import DartClient
from core.schemas import Request
from tests.unit.test_contract import check_contract

ACQ = ("타법인 주식 및 출자증권 취득결정 1. 발행회사 회사명(국적) 테스트 LLC(USA) 대표이사 갑 자본금(원) 1 회사와 관계 {rel} 발행주식총수(주) 1 주요사업 제조 2. 취득내역 취득금액(원) {amt} "
       "5. 취득목적 현지 생산 6. 취득예정일자 {sch} 7. 자산양수 10. 이사회결의일(결정일) 2026-04-13 [상대방에 관한 사항] 국적 미국 대표")


def rows(no, *, cash=100, st=10, ocf=20, prev=30):
    ids = [("BS", "ifrs-full_CashAndCashEquivalents", cash), ("BS", "ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents", st), ("CF", "ifrs-full_CashFlowsFromUsedInOperatingActivities", ocf)]
    return [{"rcept_no": no, "sj_div": s, "account_id": a, "account_nm": a, "thstrm_amount": str(v), "frmtrm_amount": str(prev), "currency": "KRW"} for s, a, v in ids]


class Fake:
    def __init__(self, filings, docs, events=None, fin=None):
        self.f, self.docs, self.events, self.fin = filings, docs, events or {}, fin or {}

    def corp_codes(self):
        return [{"corp_code": "00000001", "corp_name": "테스트", "stock_code": "000001"}]

    def get_json(self, endpoint, **k):
        return {"corp_cls": "Y"}

    def list_filings(self, as_of, bgn, end, corp_code=None, pblntf_ty=None):
        return FilingList(filter_asof([r for r in self.f if r.get("ty", "I") == pblntf_ty], "rcept_dt", as_of), bgn, as_of)

    def document(self, no):
        return {"a": ("<DOCUMENT-NAME>x</DOCUMENT-NAME>" + self.docs.get(no, "")).encode()}

    def financials(self, cc, year, code, fs, filings, dt):
        return DartClient._versioned(self.fin.get((year, code, fs), []), filings, dt)

    def major_event(self, kind, cc, a, b, filings):
        return DartClient._versioned(self.events.get((kind, a.strftime("%Y%m%d")), []), filings, a)


def f(no, dt, nm, ty="I"):
    return {"rcept_no": no, "rcept_dt": dt, "report_nm": nm, "ty": ty}


REPORTS = [f("20260301000001", "20260301", "사업보고서 (2025.12)", "A"), f("20260814000001", "20260814", "반기보고서 (2026.06)", "A")]
FIN = {(2025, "11011", "CFS"): rows("20260301000001", ocf=200), (2026, "11012", "CFS"): rows("20260814000001", ocf=20, prev=30)}


def execute(monkeypatch, fake, as_of=date(2026, 11, 5)):
    monkeypatch.setattr(dart, "get_client", lambda: fake)
    return run_nollm(Request(request_id="q", agent="overseas_funding", mode="single", corp_code="00000001", as_of=as_of))


def metric(r, mid):
    return next(m for m in r.metrics if m.metric_id == mid)


def contract_sample():
    keep = dart.get_client
    fake = Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")], {"A1": ACQ.format(rel="-", amt="500", sch="2027-01-01")}, fin=FIN)
    dart.get_client = lambda: fake
    try:
        return run_nollm(Request(request_id="q", agent="overseas_funding", mode="single", corp_code="00000001", as_of=date(2026, 11, 5)))
    finally:
        dart.get_client = keep


def test_contract_and_gap(monkeypatch):
    fake = Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")], {"A1": ACQ.format(rel="-", amt="500", sch="2027-01-01")}, fin=FIN)
    r = execute(monkeypatch, fake)
    assert check_contract(r) == [] and r.status == "complete", r.errors
    assert metric(r, "ovs.overseas_investment_amount").value == 500
    assert metric(r, "fin.ttm_operating_cash_flow").value == 190          # 20 + 200 − 30
    assert metric(r, "ovs.available_internal_funds").value == 300          # 100 + 10 + 190
    assert metric(r, "ovs.funding_gap").value == 200 and metric(r, "ovs.funding_gap_ratio").value == 0.4
    assert r.extra["s4_items"][0]["note"] == "집행 예정일 2027-01-01, 완료 미확인"
    s = r.extra["signals"][0]
    assert s["signal_type"] == "S4_confirmed" and s["purpose_category"] == "unknown" and s["is_overseas"] is True and s["target_country"] == "미국"     # 라벨은 6단계 전까지 unknown


def test_form_reads_last_form_not_counterparty_table():
    t = "정정사항 1. 발행회사 자본금 1 2 " + ACQ.format(rel="종속회사", amt="1,000", sch="2026-04-22")
    g = parse_acquisition_form(t)
    assert (g["name"], g["country"], g["amount"], g["relation"], g["purpose"], g["scheduled"]) == ("테스트 LLC", "USA", 1000, "종속회사", "현지 생산", "2026-04-22")
    g = parse_acquisition_form("1. 발행회사 회사명 PT. 테스트 국적 인도네시아 대표자 갑 자본금(원) 1 회사와 관계 자회사 발행주식총수(주) 1 취득금액(원) 7")
    assert (g["name"], g["country"], g["amount"], g["relation"]) == ("PT. 테스트", "인도네시아", 7, "자회사")
    assert parse_acquisition_form("없는 양식")["amount"] is None
    g = parse_acquisition_form("1. 발행회사 회사명(국적) (주)테스트 대표이사 갑 취득금액(원) 7")      # 국적 없음: 해외로 읽지 않는다
    assert (g["name"], g["country"]) == ("(주)테스트", None)
    g = parse_acquisition_form("1. 발행회사 회사명(국적) TEST CO LIMITED 대표이사 갑 취득금액(원) 7 [상대방에 관한 사항] 기본사항 성명(명칭) 국적 주소(본점소재지) 생년월일 TEST CO LIMITED 베트남 하노이 1")
    assert (g["name"], g["country"]) == ("TEST CO LIMITED", "베트남")
    g = parse_acquisition_form("1. 발행회사 회사명(국적) 테스트(주) 대표이사 갑 취득금액(원) 7")
    assert (g["name"], g["country"]) == ("테스트(주)", None)
    g = parse_acquisition_form("1. 발행회사 회사명(국적) (주)테스트 (대한민국) 대표이사 갑 취득금액(원) 7")
    assert (g["name"], g["country"]) == ("(주)테스트", "대한민국")


def test_domestic_acquisition_has_no_amount(monkeypatch):
    doc = ACQ.replace("테스트 LLC(USA)", "테스트(대한민국)").format(rel="-", amt="500", sch="2027-01-01")
    r = execute(monkeypatch, Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")], {"A1": doc}, fin=FIN))
    s = r.extra["signals"][0]
    assert s["is_overseas"] is False and s["purpose_category"] == "domestic" and s["amount_krw"] is None
    assert metric(r, "ovs.overseas_investment_amount").value is None and metric(r, "ovs.funding_gap").value is None


def test_subsidiary_funding_is_r1_with_debt_question(monkeypatch):
    sub = "종속회사인 테스트 LLC 의 주요경영사항 신고 시설자금(원) 70 채무상환자금(원) 1,480 운영자금(원) -"
    fake = Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정"), f("S1", "20260413", "유상증자결정(종속회사의주요경영사항)")], {"A1": ACQ.format(rel="종속회사", amt="500", sch="2026-04-22"), "S1": sub}, fin=FIN)
    r = execute(monkeypatch, fake)
    assert not [s for s in r.extra["signals"] if s["signal_type"] == "S5_funding"]
    assert "종속회사 증자 채무상환 용도 1,480: 자금 공백에 차입 상환 수요 포함 가능" in r.open_questions
    assert r.extra["s4_items"][0]["note"] == "연결 내부 출자, 집행 시점 확인 불가"


def test_completed_third_party_acquisition_is_excluded_by_report_note(monkeypatch):
    docs = {"A1": ACQ.format(rel="-", amt="500", sch="2025-08-25"), "20260814000001": "테스트 LLC의 지분은 2025.10.31일자로 취득 완료 되었습니다."}
    r = execute(monkeypatch, Fake(REPORTS + [f("A1", "20250825", "타법인주식및출자증권취득결정")], docs, fin=FIN))
    assert r.extra["s4_items"][0]["excluded"] and metric(r, "ovs.overseas_investment_amount").value == 0
    assert metric(r, "ovs.overseas_investment_amount").note == "확정 집행 완료분 제외" and metric(r, "ovs.funding_gap_ratio").value is None


def test_correction_used_and_completion_correction_excludes(monkeypatch):
    corr = "정정일자 2025-12-01 2. 정정관련 공시서류제출일 2025-11-19 3. 정정사유 취득완료에 따른 정정 4. 정정사항 " + ACQ.format(rel="-", amt="900", sch="2025-11-28")
    r = execute(monkeypatch, Fake(REPORTS + [f("A1", "20251119", "타법인주식및출자증권취득결정"), f("A2", "20251201", "[기재정정]타법인주식및출자증권취득결정")], {"A1": ACQ.format(rel="-", amt="500", sch="2025-12-19"), "A2": corr}, fin=FIN))
    x = r.extra["s4_items"][0]
    assert x["amount"] == 900 and x["latest_rcept_no"] == "A2" and x["excluded"] and x["confirmed_date"] == "2025-11-28"


def test_two_filings_without_label_use_latest_with_question(monkeypatch):
    fake = Fake(REPORTS + [f("A1", "20260101", "타법인주식및출자증권취득결정"), f("A2", "20260901", "타법인주식및출자증권취득결정")], {"A1": ACQ.format(rel="자회사", amt="500", sch="2027-01-01"), "A2": ACQ.format(rel="자회사", amt="70", sch="2027-02-01")}, fin=FIN)
    r = execute(monkeypatch, fake)
    assert metric(r, "ovs.overseas_investment_amount").value == 70 and "취득 공시 합산 불명확: A1, A2" in r.open_questions


def test_as_of_filters_future_filings(monkeypatch):
    fake = Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정"), f("A2", "20260901", "타법인주식및출자증권취득결정")], {"A1": ACQ.format(rel="-", amt="500", sch="2027-01-01"), "A2": ACQ.format(rel="-", amt="70", sch="2027-02-01")}, fin=FIN)
    r = execute(monkeypatch, fake, date(2026, 8, 20))
    assert {s["signal_id"].split(":")[2] for s in r.extra["signals"]} == {"A1"} and all(e.published_at <= date(2026, 8, 20) for e in r.evidence)


def test_funding_links_result_and_op_only_is_r3(monkeypatch):
    row = {"rcept_no": "D1", "bd_fta": "100", "fdpp_op": "100", "bddd": "2026년 05월 01일"}
    cap = {"rcept_no": "D2", "bd_fta": "60", "fdpp_ocsa": "60", "bddd": "2026년 05월 02일"}
    res = "1. 증권의 종류 제1회 전환사채 2. 발행방법 사모 3. 발행내역 발행예정금액(원) 60 발행결정 최초 이사회결의일 2026-05-02 실제발행금액(원) 60 납입일 2026-09-01"
    fake = Fake(REPORTS + [f("D1", "20260501", "주요사항보고서(전환사채권발행결정)", "B"), f("D2", "20260502", "주요사항보고서(전환사채권발행결정)", "B"), f("R1", "20260901", "증권발행결과(자율공시)")], {"R1": res}, {("cb", "20260501"): [row], ("cb", "20260502"): [cap]}, FIN)
    r = execute(monkeypatch, fake)
    purposes = {s["signal_id"].split(":")[2]: s["purpose_category"] for s in r.extra["signals"]}
    assert purposes == {"D1": "working_capital", "D2": "unknown"}
    finals = {d["rcept_no"]: d["final"] for d in r.extra["funding_decisions"]}
    assert finals == {"D1": "미확정", "D2": "확정·합산"}
    assert "해외 용도 불명 칸: fdpp_ocsa 60" in r.open_questions and metric(r, "ovs.confirmed_overseas_funding").value == 0


def test_correction_after_as_of_makes_funding_unknown(monkeypatch):
    row = {"rcept_no": "D9", "bd_fta": "100", "fdpp_ocsa": "100"}
    r = execute(monkeypatch, Fake(REPORTS + [f("D1", "20260501", "주요사항보고서(전환사채권발행결정)", "B")], {}, {("cb", "20260501"): [row]}, FIN))
    s = next(x for x in r.extra["signals"] if x["signal_type"] == "S5_funding")
    assert s["value_status"] == "unknown" and "정정 전 원본 값 확인 불가: 전환사채권발행결정 2026-05-01" in r.open_questions
    assert metric(r, "ovs.confirmed_overseas_funding").data_status == "unknown"


def test_report_correction_after_as_of_makes_gap_unknown(monkeypatch):
    fin = {**FIN, (2026, "11012", "CFS"): rows("20261002000001")}
    r = execute(monkeypatch, Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")], {"A1": ACQ.format(rel="-", amt="500", sch="2027-01-01")}, fin=fin))
    assert metric(r, "ovs.funding_gap").data_status == "unknown" and metric(r, "fin.cash_and_equivalents").data_status == "unknown"


def test_unknown_company_fails(monkeypatch):
    monkeypatch.setattr(dart, "get_client", lambda: Fake([], {}))
    r = run_nollm(Request(request_id="q", agent="overseas_funding", mode="single", company="없는회사", as_of=date(2026, 11, 5)))
    assert r.status == "failed" and r.corp_code is None
