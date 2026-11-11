"""해외진출 6단계 노드: claude를 호출하지 않고 call_llm을 바꿔 끼워 시험한다."""
import json
from datetime import date
from importlib import import_module
from types import SimpleNamespace as NS

import pytest

from agents.overseas_funding.graph import can_merge, run_extraction
from agents.overseas_funding.schemas import GenerateNewsQueriesOutput, MajorEventBatchOutput, NewsExtractionOutput, NewsQuery, PeriodicPlanOutput
from core import llm as llm_mod
from core.clients import dart, news as news_client
from core.schemas import Request
from tests.unit.overseas_funding.test_graph import ACQ, FIN, REPORTS, Fake, f
from tests.unit.test_contract import check_contract

# nodes 패키지가 함수 이름을 다시 내보내므로 모듈은 이렇게 가져온다
news_node = import_module("agents.overseas_funding.nodes.collect_news")
news_extract = import_module("agents.overseas_funding.nodes.extract_news")
plan_node = import_module("agents.overseas_funding.nodes.extract_periodic_plan")
major = import_module("agents.overseas_funding.nodes.parse_major_events")


# ---- D2 검증기 ----
def q(query, nouns, ids=("E1",)):
    return NewsQuery(query=query, proper_nouns=list(nouns), evidence_ids=list(ids))


SENT = "[E1] 테스트의 베트남 하노이 공장 신설 계획"


@pytest.mark.parametrize("query,nouns,why", [
    ("테스트 폴란드 공장", ["폴란드"], "자료에 없는 고유명사"),
    ("테스트 베트남 공장", [], "고유명사 없음"),
    ("베트남 공장", ["베트남"], "기업명 없음"),
    ("테스트 베트남 호치민 공장", ["베트남"], "허용되지 않은 검색어 구성"),      # 선언하지 않은 고유명사
    ("테스트 베트남 매출", ["베트남"], "허용되지 않은 검색어 구성"),
])
def test_d2_rejects(query, nouns, why):
    good, rejected = news_node.validate_queries(GenerateNewsQueriesOutput(queries=[q(query, nouns)]), "테스트", SENT, {"E1"})
    assert not good and why in rejected[0]["reason"] and rejected[0]["point"] == "D2"


def test_d2_rejects_unknown_evidence():
    _, rejected = news_node.validate_queries(GenerateNewsQueriesOutput(queries=[q("테스트 베트남 공장", ["베트남"], ["E9"])]), "테스트", SENT, {"E1"})
    assert "근거 없음" in rejected[0]["reason"]


def test_d2_accepts():
    good, rejected = news_node.validate_queries(GenerateNewsQueriesOutput(queries=[q("테스트 베트남 하노이 공장", ["베트남", "하노이"])]), "테스트", SENT, {"E1"})
    assert good == ["테스트 베트남 하노이 공장"] and not rejected


# ---- 기사 ----
def item(title, day, url):
    return {"title": title, "pubDate": date(2026, 10, day), "url": url, "description": "요약"}


def test_refine_filters_and_dedups():
    rows = [item("테스트 미국 공장 착공 소식입니다", 1, "u1"), item("테스트 미국 공장 착공 소식입니다!", 2, "u2"), item("다른회사 공장", 3, "u3"), item("테스트 합작 법인", 4, "u1"), item("테스트 미래 기사", 20, "u9")]
    got = news_node.refine(rows, "테스트", date(2026, 1, 1), date(2026, 10, 10))
    assert {x["url"] for x in got} <= {"u1", "u2"} and "u3" not in {x["url"] for x in got} and "u9" not in {x["url"] for x in got}
    assert all(x["pubDate"] <= date(2026, 10, 10) for x in got)


def test_refine_keeps_one_of_similar_titles():
    rows = [item("테스트 미국 공장 착공 소식입니다", 1, "a"), item("테스트 미국 공장 착공 소식입니다!", 2, "b")]
    assert len(news_node.refine(rows, "테스트", date(2026, 1, 1), date(2026, 10, 10))) == 1


def test_source_by_recency():
    co = NS(corp_code="00000001")
    assert isinstance(news_node.select_source(co, date(2026, 11, 1), date(2026, 11, 6)), news_client.NaverNewsSource)
    assert isinstance(news_node.select_source(co, date(2024, 7, 31), date(2026, 11, 6)), news_client.FileNewsSource)
    assert news_client.FileNewsSource("없는기업").search("x", date(2024, 1, 1), date(2024, 2, 1)) == []


def test_normalize_item():
    x = news_client.normalize_item({"title": "<b>테스트</b> &amp; 공장", "originallink": "u", "pubDate": "Mon, 05 Oct 2026 09:00:00 +0900", "description": "<b>설명</b>"})
    assert x == {"title": "테스트 & 공장", "url": "u", "pubDate": date(2026, 10, 5), "description": "설명"}
    assert news_client.normalize_item({"title": "x"}) is None


def test_plain_text_drops_leading_style_only():
    from core.clients.dart_docs import plain_text
    doc = ".PGBRK {page-break-after:always} .A, .B {color:red; font-size:1px} 주권매매거래정지 기간변경 비고 {참고}"
    assert plain_text({"a": doc.encode("utf-8")}) == "주권매매거래정지 기간변경 비고 {참고}"


# ---- 프롬프트 치환 ----
def test_fill_keeps_json_braces():
    assert llm_mod.fill('{"a": 1} {name} {모름}', {"name": "값"}) == '{"a": 1} 값 {모름}'


class Proc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr


OUT = json.dumps({"structured_output": {"items": [], "no_plan_found": True}, "is_error": False, "usage": {"input_tokens": 10, "output_tokens": 5}})


@pytest.fixture
def logdir(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_mod.settings, "stride_log_dir", str(tmp_path))
    monkeypatch.setattr(llm_mod.shutil, "which", lambda n: "claude")
    return tmp_path


def test_call_llm_options_and_log(monkeypatch, logdir):
    seen = {}

    def fake(cmd, **k):
        seen.update(cmd=cmd, input=k["input"])
        return Proc(OUT)
    monkeypatch.setattr(llm_mod.subprocess, "run", fake)
    r = llm_mod.call_llm(plan_node.PROMPT, {"corp_name": "테스트"}, PeriodicPlanOutput, run_id="r1", as_of=date(2026, 1, 1))
    assert r.no_plan_found and "--bare" not in seen["cmd"]
    for opt in ("--tools", "--strict-mcp-config", "--disable-slash-commands", "--no-session-persistence", "--system-prompt", "--json-schema", "--output-format"):
        assert opt in seen["cmd"]
    assert seen["cmd"][seen["cmd"].index("--tools") + 1] == "" and seen["cmd"][seen["cmd"].index("--model") + 1] == "sonnet"
    assert "테스트의" in seen["input"]              # 프롬프트 본문은 stdin
    sys_prompt = seen["cmd"][seen["cmd"].index("--system-prompt") + 1]
    assert "2026-01-01" in sys_prompt
    rec = json.loads(next((logdir / "llm" / "r1").glob("*.json")).read_text(encoding="utf-8"))
    assert rec["attempts"][0]["input_tokens"] == 10 and "테스트" not in json.dumps({k: v for k, v in rec.items() if k == "input_sha1"})


def test_call_llm_retries_schema_error_then_raises(monkeypatch, logdir):
    calls = []

    def fake(cmd, **k):
        calls.append(k["input"])
        return Proc(json.dumps({"structured_output": {"items": "x"}, "is_error": False, "usage": {}}))
    monkeypatch.setattr(llm_mod.subprocess, "run", fake)
    with pytest.raises(llm_mod.LLMError):
        llm_mod.call_llm(plan_node.PROMPT, {}, PeriodicPlanOutput, run_id="r2")
    assert len(calls) == 2 and "이전 출력의 오류" in calls[1]


def test_call_llm_auth_and_limit_do_not_retry(monkeypatch, logdir):
    calls = []

    def run(text):
        def fake(cmd, **k):
            calls.append(1)
            return Proc(json.dumps({"is_error": True, "result": text, "usage": {}}), 1)
        return fake
    monkeypatch.setattr(llm_mod.subprocess, "run", run("Login expired"))
    with pytest.raises(llm_mod.LLMAuthError):
        llm_mod.call_llm(plan_node.PROMPT, {}, PeriodicPlanOutput, run_id="r3")
    assert len(calls) == 1
    for text in ("You have hit your limit", "You've hit your session limit · resets 8pm"):
        monkeypatch.setattr(llm_mod.subprocess, "run", run(text))
        with pytest.raises(llm_mod.LLMRateLimitError):
            llm_mod.call_llm(plan_node.PROMPT, {}, PeriodicPlanOutput, run_id="r4")


# ---- 그래프 ----
def label(eid, **k):
    base = dict(evidence_id=eid, purpose_category="growth_investment", is_overseas=True, fund_use_scopes=[], target_country="미국", target_entity="테스트 LLC", method="acquisition", change_direction="none", related_project=None, part_of_earlier="no", quote="현지 생산")
    return {**base, **k}


class FakeLLM:
    def __init__(self, major_items=None, plan=None, queries=None, news=None):
        self.major, self.plan, self.queries, self.news = major_items, plan, queries, news
        self.calls = []

    def __call__(self, prompt_path, variables, model, *, run_id, as_of=None):
        self.calls.append((model.__name__, variables))
        if model is PeriodicPlanOutput:
            return self.plan or PeriodicPlanOutput(items=[], no_plan_found=True)
        if model is MajorEventBatchOutput:
            return MajorEventBatchOutput(items=self.major(variables) if self.major else [])
        if model is GenerateNewsQueriesOutput:
            return self.queries or GenerateNewsQueriesOutput(queries=[])
        return self.news or NewsExtractionOutput(events=[])


def wire(monkeypatch, fake, llm, news_items=()):
    monkeypatch.setattr(dart, "get_client", lambda: fake)
    for mod in (plan_node, major, news_node, news_extract):
        monkeypatch.setattr(mod, "call_llm", llm)
    source = NS(search=lambda *a: list(news_items))
    monkeypatch.setattr(news_node, "select_source", lambda *a: source)


def execute(as_of=date(2026, 11, 5)):
    return run_extraction(Request(request_id="q", agent="overseas_funding", mode="single", corp_code="00000001", as_of=as_of))


def metric(r, mid):
    return next(m for m in r.metrics if m.metric_id == mid)


DOCS = {"A1": ACQ.format(rel="-", amt="500", sch="2027-01-01")}
FILINGS = REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")]


def test_labels_applied_and_llm_amount_ignored(monkeypatch):
    llm = FakeLLM(lambda v: [label("DART:A1:정형")])
    wire(monkeypatch, Fake(FILINGS, DOCS, fin=FIN), llm)
    r = execute()
    assert check_contract(r) == [] and not r.errors, r.errors
    s = next(x for x in r.extra["signals"] if x["signal_id"].endswith("A1"))
    assert s["purpose_category"] == "growth_investment" and s["amount_krw"] == 500 and s["target_country"] == "미국" and s["method"] == "acquisition"
    assert metric(r, "ovs.overseas_investment_amount").value == 500
    assert r.extra["major_labels"]["A1"]["part_of_earlier"] == "no"


def test_bad_quote_or_id_drops_label(monkeypatch):
    llm = FakeLLM(lambda v: [label("DART:A1:정형", quote="자료에 없는 문장"), label("DART:XX:정형")])
    wire(monkeypatch, Fake(FILINGS, DOCS, fin=FIN), llm)
    r = execute()
    s = next(x for x in r.extra["signals"] if x["signal_id"].endswith("A1"))
    assert s["purpose_category"] == "unknown" and "분류 결과 폐기(인용 불일치): DART:A1:정형" in r.open_questions and "분류 결과 폐기(근거 없음): DART:XX:정형" in r.open_questions


def test_batch_is_single_call_and_no_call_without_targets(monkeypatch):
    llm = FakeLLM(lambda v: [])
    wire(monkeypatch, Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정"), f("A2", "20260501", "타법인주식및출자증권취득결정")], {**DOCS, "A2": ACQ.format(rel="-", amt="9", sch="2027-02-01")}, fin=FIN), llm)
    execute()
    assert [c[0] for c in llm.calls].count("MajorEventBatchOutput") == 1
    llm2 = FakeLLM()
    wire(monkeypatch, Fake(REPORTS, {}, fin=FIN), llm2)
    execute()
    assert not [c for c in llm2.calls if c[0] == "MajorEventBatchOutput"]


def test_domestic_rule_needs_no_llm(monkeypatch):
    doc = ACQ.replace("테스트 LLC(USA)", "테스트(대한민국)").format(rel="-", amt="500", sch="2027-01-01")
    llm = FakeLLM()
    wire(monkeypatch, Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")], {"A1": doc}, fin=FIN), llm)
    r = execute()
    assert not [c for c in llm.calls if c[0] == "MajorEventBatchOutput"] and r.extra["signals"][0]["purpose_category"] == "domestic"


def test_funding_only_overseas_slot_counts(monkeypatch):
    row = {"rcept_no": "D1", "bd_fta": "100", "fdpp_fclt": "70", "fdpp_op": "30", "bddd": "2026년 05월 01일"}
    doc = "【조달자금의 구체적 사용 목적】 폴란드공장 설비 50 화성공장 설비 20 폴란드 공장 운영 30 【미상환 주권】 다른 내용"
    llm = FakeLLM(lambda v: [label("DART:D1:정형", fund_use_scopes=[{"slot": "fdpp_fclt", "scope": "mixed"}, {"slot": "fdpp_op", "scope": "overseas"}], quote="폴란드 공장 운영 30")])
    wire(monkeypatch, Fake(FILINGS[:2] + [f("D1", "20260501", "주요사항보고서(전환사채권발행결정)", "B")], {"D1": doc}, {("cb", "20260501"): [row]}, FIN), llm)
    r = execute()
    s = next(x for x in r.extra["signals"] if x["signal_type"] == "S5_funding")
    assert s["amount_krw"] == 30 and "해외 용도 불명 칸: fdpp_fclt 70" in r.open_questions and any(q.startswith("칸 안 세부 내역 (합산 안 함): 【조달자금") for q in r.open_questions)
    material = next(c[1]["materials"] for c in llm.calls if c[0] == "MajorEventBatchOutput")
    assert "폴란드공장 설비 50" in material and "다른 내용" not in material     # 사용 목적 절만


def test_cancel_filing_makes_s6_and_no_acquisition(monkeypatch):
    name = "기타주요경영사항(타법인주식및출자증권취득결정철회)"
    llm = FakeLLM(lambda v: [label("DART:A1:정형"), label("DART:C1:정형", change_direction="cancelled", related_project="베트남 합작", quote="출자 철회")])
    wire(monkeypatch, Fake(FILINGS + [f("C1", "20260901", name)], {**DOCS, "C1": "출자 철회 결정 (1) 출자회사명 : 테스트 LLC"}, fin=FIN), llm)
    r = execute()
    s6 = [x for x in r.extra["signals"] if x["signal_type"] == "S6_alert"]
    assert len(s6) == 1 and s6[0]["summary"].startswith("cancelled") and r.extra["major_labels"]["C1"]["change_direction"] == "cancelled"
    assert len([x for x in r.extra["signals"] if x["signal_type"] == "S4_confirmed"]) == 1


def test_correction_is_one_entry_with_s4_and_s6(monkeypatch):
    corr = "2. 정정관련 공시서류제출일 2026-04-13 3. 정정사유 금액 축소 " + ACQ.format(rel="-", amt="300", sch="2027-01-01")
    llm = FakeLLM(lambda v: [label("DART:A2:정형", change_direction="reduced", quote="금액 축소")])
    wire(monkeypatch, Fake(FILINGS + [f("A2", "20260501", "[기재정정]타법인주식및출자증권취득결정")], {**DOCS, "A2": corr}, fin=FIN), llm)
    r = execute()
    material = next(c[1]["materials"] for c in llm.calls if c[0] == "MajorEventBatchOutput")
    assert material.count('id="DART:A2:정형"') == 1
    kinds = sorted(x["signal_type"] for x in r.extra["signals"])
    assert kinds == ["S4_confirmed", "S6_alert"] and next(x for x in r.extra["signals"] if x["signal_type"] == "S4_confirmed")["amount_krw"] == 300


def test_same_day_subsidiary_funding_goes_into_material(monkeypatch):
    sub = "종속회사인 테스트 LLC 의 주요경영사항 신고 시설자금(원) 148 운영자금(원) - 채무상환자금(원) 148"
    llm = FakeLLM(lambda v: [label("DART:A1:정형", quote="시설자금 148")])
    wire(monkeypatch, Fake(FILINGS + [f("S1", "20260413", "유상증자결정(종속회사의주요경영사항)")], {**DOCS, "S1": sub}, fin=FIN), llm)
    r = execute()
    material = next(c[1]["materials"] for c in llm.calls if c[0] == "MajorEventBatchOutput")
    assert "자금 목적: 시설자금 148, 채무상환자금 148" in material      # 관계가 종속회사가 아니면 분할하지 않는다
    assert next(x for x in r.extra["signals"] if x["signal_type"] == "S4_confirmed")["amount_krw"] == 500
    assert next(x for x in r.extra["signals"] if x["signal_type"] == "S4_confirmed")["purpose_category"] == "growth_investment"      # 인용 검사도 붙인 문장을 본다
    assert not [x for x in r.extra["signals"] if x["signal_type"] == "S5_funding"]


SUB_FUND = "종속회사인 테스트 LLC 의 주요경영사항 신고 시설자금 (원) {fac} 운영자금 (원) {op} 채무상환자금 (원) {debt}"


def split_run(monkeypatch, amt, fac, op, debt, major):
    docs = {"A1": ACQ.format(rel="종속회사", amt=amt, sch="2027-01-01"), "S1": SUB_FUND.format(fac=fac, op=op, debt=debt)}
    wire(monkeypatch, Fake(FILINGS + [f("S1", "20260413", "유상증자결정(종속회사의주요경영사항)")], docs, fin=FIN), FakeLLM(major))
    return execute()


def test_split_slots_override_llm_label(monkeypatch):
    r = split_run(monkeypatch, "296", "148", "-", "148", lambda v: [label("DART:A1:정형", purpose_category="governance_restructuring", quote="현지")])
    assert check_contract(r) == [] and not r.errors, r.errors
    s = {x["signal_id"].split(":", 2)[2]: x for x in r.extra["signals"] if x["signal_type"] == "S4_confirmed"}
    assert s["A1"]["purpose_category"] == "growth_investment" and s["A1"]["amount_krw"] == 148
    assert s["A1:fdpp_dtrp"]["purpose_category"] == "refinancing" and s["A1:fdpp_dtrp"]["amount_krw"] == 148 and s["A1:fdpp_dtrp"]["is_overseas"] is True
    assert metric(r, "ovs.overseas_investment_amount").value == 148
    assert "종속회사 증자 채무상환 용도 148: refinancing, 투자액에서 제외" in r.open_questions
    assert not any("자금 공백에 차입 상환 수요" in q for q in r.open_questions)
    assert "DART:S1:정형:시설자금(원)" in s["A1"]["evidence_ids"] and any(e.evidence_id == "DART:S1:정형:채무상환자금(원)" for e in r.evidence)
    assert r.extra["major_labels"]["A1"]["purpose_category"] == "governance_restructuring"      # LLM 원 라벨은 기록으로 남긴다


def test_op_slot_is_separate_field_whatever_the_label(monkeypatch):
    for purpose in ("growth_investment", "working_capital", "unknown"):
        r = split_run(monkeypatch, "300", "100", "50", "150", lambda v: [label("DART:A1:정형", purpose_category=purpose, quote="현지")])
        assert metric(r, "ovs.overseas_investment_amount").value == 100
        assert r.extra["funding_gap"]["overseas_subsidiary_working_capital_krw"] == 50 and r.extra["s4_items"][0]["subsidiary_working_capital"] == 50
        op = next(x for x in r.extra["signals"] if x["signal_id"].endswith("A1:fdpp_op"))
        assert op["purpose_category"] == "working_capital" and op["amount_krw"] == 50


def test_other_slot_label_follows_llm_but_never_counts(monkeypatch):
    docs = {"A1": ACQ.format(rel="종속회사", amt="300", sch="2027-01-01"), "S1": "종속회사인 테스트 LLC 의 주요경영사항 신고 시설자금 (원) 100 기타자금 (원) 200"}
    wire(monkeypatch, Fake(FILINGS + [f("S1", "20260413", "유상증자결정(종속회사의주요경영사항)")], docs, fin=FIN), FakeLLM(lambda v: [label("DART:A1:정형", quote="현지")]))
    r = execute()
    assert metric(r, "ovs.overseas_investment_amount").value == 100 and "종속회사 증자 기타자금 200: growth_investment, 투자액에서 제외" in r.open_questions


def test_split_works_without_label(monkeypatch):
    r = split_run(monkeypatch, "300", "100", "50", "150", lambda v: [])
    assert metric(r, "ovs.overseas_investment_amount").value == 100 and r.extra["funding_gap"]["overseas_subsidiary_working_capital_krw"] == 50


def test_split_only_debt_leaves_no_project_amount(monkeypatch):
    r = split_run(monkeypatch, "300", "-", "-", "300", lambda v: [label("DART:A1:정형", quote="현지")])
    assert not r.extra["s4_items"] and [x["purpose_category"] for x in r.extra["signals"] if x["signal_type"] == "S4_confirmed"] == ["refinancing"]


def test_split_needs_slot_sum_to_match_amount(monkeypatch):
    r = split_run(monkeypatch, "500", "148", "-", "148", lambda v: [label("DART:A1:정형", quote="현지")])
    assert metric(r, "ovs.overseas_investment_amount").value == 500
    assert any(q.startswith("종속회사 증자 칸 합계 불일치, 분할 안 함") for q in r.open_questions)
    assert any("자금 공백에 차입 상환 수요" in q for q in r.open_questions)      # 분할을 못 하면 기존 기록을 남긴다


def test_purpose_with_working_capital_without_split_is_recorded(monkeypatch):
    doc = ACQ.format(rel="종속회사", amt="500", sch="2027-01-01").replace("5. 취득목적 현지 생산", "5. 취득목적 사업확장 및 운영자금 확보")
    wire(monkeypatch, Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정")], {"A1": doc}, fin=FIN), FakeLLM(lambda v: [label("DART:A1:정형", quote="사업확장")]))
    r = execute()
    assert "목적에 운영자금 포함, 금액 구분 없음: A1" in r.open_questions and metric(r, "ovs.overseas_investment_amount").value == 500


def test_subsidiary_asset_needs_overseas_label(monkeypatch):
    nm = "유형자산취득결정(종속회사의주요경영사항)"
    doc = "종속회사 취득금액(원) 243 취득목적 공장 미국 인디애나주 소재"
    llm = FakeLLM(lambda v: [label("DART:P1:정형", quote="미국 인디애나주 소재", target_entity=None)])
    wire(monkeypatch, Fake(REPORTS + [f("P1", "20260401", nm)], {"P1": doc}, fin=FIN), llm)
    r = execute()
    s = r.extra["signals"][0]
    assert s["summary"].startswith("종속회사 집행") and s["amount_krw"] == 243
    llm2 = FakeLLM(lambda v: [label("DART:P1:정형", is_overseas=False, quote="미국 인디애나주 소재")])
    wire(monkeypatch, Fake(REPORTS + [f("P1", "20260401", nm)], {"P1": doc}, fin=FIN), llm2)
    r2 = execute()
    assert not r2.extra["signals"] and "종속회사 유형자산 소재지 확인 불가: P1" in r2.open_questions


def test_periodic_plan_validated_and_is_new(monkeypatch):
    sec = "<TITLE>II. 사업의 내용</TITLE><P>베트남 공장을 신설할 계획이며 투자 규모는 1,000억원입니다.</P><P>기존 미국 공장 설명입니다.</P><TITLE>III. 재무</TITLE>"
    plan = PeriodicPlanOutput(no_plan_found=False, items=[
        {"paragraph_id": "p1", "quote": "베트남 공장을 신설할 계획", "target_country": "베트남", "method": "new_plant", "stage": 2, "amount_original": "1,000억원", "timeline": None, "summary": "베트남 공장 신설"},
        {"paragraph_id": "p9", "quote": "x", "target_country": None, "method": "other", "stage": 1, "amount_original": None, "timeline": None, "summary": "없는 문단"},
        {"paragraph_id": "p2", "quote": "자료에 없는 인용", "target_country": None, "method": "other", "stage": 1, "amount_original": None, "timeline": None, "summary": "틀린 인용"}])
    wire(monkeypatch, Fake(REPORTS, {"20260814000001": sec, "20260301000001": "<TITLE>II. 사업의 내용</TITLE><P>기존 미국 공장 설명입니다.</P><TITLE>III. 재무</TITLE>"}, fin=FIN), FakeLLM(plan=plan))
    r = execute()
    s1 = [x for x in r.extra["signals"] if x["signal_type"] == "S1_plan"]
    assert len(s1) == 1 and s1[0]["amount_krw"] == 100_000_000_000 and s1[0]["amount_original"] == "1,000억원" and s1[0]["is_new"] is True and s1[0]["evidence_ids"] == ["DART:20260814000001:II.사업의내용#p1"]
    assert "계획 항목 폐기(문단 없음): p9" in r.open_questions and "계획 항목 폐기(인용 불일치): p2" in r.open_questions


def test_material_tags_new_existing_unknown():
    sec = {"paragraphs": [{"paragraph_id": "p1", "text": "a"}, {"paragraph_id": "p2", "text": "b"}], "new_paragraph_ids": ["p1"]}
    assert plan_node.build_material(sec) == "[p1][NEW] a\n[p2][EXISTING] b"
    assert plan_node.build_material({**sec, "new_paragraph_ids": None}).startswith("[p1][UNKNOWN]")


def test_news_flow_and_discard_unknown_ids(monkeypatch):
    from core import evidence as ev
    news = [item("테스트 미국 공장 착공", 1, "u1"), item("테스트 합작 법인 설립 추진", 2, "u2")]
    out = NewsExtractionOutput(events=[{"evidence_ids": [ev.news("u1"), ev.news("u2")], "target_country": "미국", "method": "new_plant", "stage": 5, "amount_original": "300억원", "is_rumor": False, "summary": "미국 공장 착공"}, {"evidence_ids": ["NEWS:없음"], "target_country": None, "method": "other", "stage": 1, "amount_original": None, "is_rumor": True, "summary": "지어낸 사건"}])
    llm = FakeLLM(lambda v: [label("DART:A1:정형")], queries=GenerateNewsQueriesOutput(queries=[q("테스트 폴란드 공장", ["폴란드"], ["DART:20260101:x"])]), news=out)
    wire(monkeypatch, Fake(FILINGS, DOCS, fin=FIN), llm, news)
    r = execute()
    s2 = [x for x in r.extra["signals"] if x["signal_type"] == "S2_progress"]
    assert len(s2) == 1 and s2[0]["event_date"] == "2026-10-01" and s2[0]["amount_krw"] == 30_000_000_000 and "기사 사건 폐기(근거 없음): 지어낸 사건" in r.open_questions
    assert r.extra["news_queries"] == [] and r.extra["decisions"][0]["action"] == "reject_query"
    assert r.extra["llm_calls"] >= 3 and any(e.source_grade == "C" for e in r.evidence)


def test_news_llm_failure_falls_back_to_base_queries(monkeypatch):
    def boom(*a, **k):
        raise llm_mod.LLMError("x")
    wire(monkeypatch, Fake(FILINGS, DOCS, fin=FIN), FakeLLM(lambda v: [label("DART:A1:정형")]))
    monkeypatch.setattr(news_node, "call_llm", boom)
    r = execute()
    assert any("collect_news: D2" in e for e in r.errors) and r.extra["news_queries"] == []


def test_can_merge_rule():
    base = {"name": "PT.테스트", "rcept_dt": "2026-01-01", "board": "2026-01-01", "shares_after": 100}
    later = {"name": "PT. 테스트", "rcept_dt": "2026-09-01", "board": "2026-09-01", "shares_acquired": 40, "shares_after": 140}
    assert can_merge([base, later])
    assert not can_merge([base, {**later, "shares_after": 40}]) and not can_merge([base, {**later, "shares_acquired": None}])      # 누적이 안 맞거나 칸 없음
    assert not can_merge([base, {**later, "board": "2026-01-01"}]) and not can_merge([base, {**later, "name": "다른회사"}]) and not can_merge([base])


@pytest.mark.parametrize("label_part", ["no", "unknown", "yes"])
def test_two_filings_merged_by_share_fields_whatever_the_label(monkeypatch, label_part):
    """같은 입력에서 part_of_earlier가 흔들려도 금액이 같다 (2026-11-07 결정)."""
    llm = FakeLLM(lambda v: [label("DART:A1:정형", part_of_earlier=label_part), label("DART:A2:정형", part_of_earlier=label_part)])
    shares = "2. 취득내역 취득주식수(주) {a} 취득금액(원) {b} 3. 취득후 소유주식수 및 지분비율 소유주식수(주) {c} 5. 취득목적"
    a1 = ACQ.format(rel="자회사", amt="500", sch="2027-01-01").replace("2. 취득내역 취득금액(원) 500 5. 취득목적", shares.format(a="100", b="500", c="100"))
    a2 = ACQ.format(rel="자회사", amt="70", sch="2027-02-01").replace("2026-04-13", "2026-09-01").replace("2. 취득내역 취득금액(원) 70 5. 취득목적", shares.format(a="40", b="70", c="140"))
    wire(monkeypatch, Fake(REPORTS + [f("A1", "20260413", "타법인주식및출자증권취득결정"), f("A2", "20260901", "타법인주식및출자증권취득결정")], {"A1": a1, "A2": a2}, fin=FIN), llm)
    r = execute()
    assert metric(r, "ovs.overseas_investment_amount").value == 570 and not any(q.startswith("취득 공시 합산 불명확") for q in r.open_questions)

