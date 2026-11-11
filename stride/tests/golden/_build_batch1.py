"""2단계 첫 묶음 초안 작성: data/probe/golden_batch1.json → tests/golden/<agent>/*.json + tests/golden/_review_batch1.md

초안의 값은 코드가 읽은 값이다. status=draft, verified_by=null. 사람이 check_list를 DART 원문으로 확인하면 확정한다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
G = ROOT / "stride/tests/golden"
B = json.loads((ROOT / "data/probe/golden_batch1.json").read_text(encoding="utf-8"))
S = json.loads((G / "_probe_samples.json").read_text(encoding="utf-8"))["samples"]
URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
eok = lambda v: None if v is None else round(v / 1e8, 1)
num = lambda s: int(s.replace(",", ""))


def chk(rcept_no, where, *values):
    return {"rcept_no": rcept_no, "url": URL.format(rcept_no), "where": where, "values": list(values)}


AI = "AI 검수(claude.ai)"
# 검수 결과 파일(_review_batch1_검수결과.md) 대응. check_list 순서대로. v = 값 전부 일치, a = API 응답 대조, d = 미검수, 목록 = 값별
REVIEW = {
    "G-TRACK_D": ["v", "v", "v", "v", "v", "v", "v", "v", "v", "v", "v"],
    "G-RICH_F": ["v", "v", "v", "v", "v"],
    "G-NONE_H": ["v", "v", "v"],
    "G-GOV_I": ["v", ["v", "a"], "v", "v", "v", "v", "v", "v", "v"],
    "F-NORMAL_F": ["v", ["v", "v", "a", "v"], ["v", "v", "a"]],
    "F-NORMAL_G": ["v", ["v", "v", "a", "v"], ["v", "v", "a"]],
    "F-AUDIT_의견거절": ["v", "v", "v"],
    "F-AUDIT_한정": ["v", "v", "v"],
}


def apply_review(file, check):
    flags = REVIEW[file]
    assert len(flags) == len(check), file
    for c_, f in zip(check, flags):
        vs = [f] * len(c_["values"]) if isinstance(f, str) else f
        assert len(vs) == len(c_["values"]), (file, c_["where"])
        c_["value_status"] = ["ai_verified" if x in ("v", "a") else "draft" for x in vs]
        if "a" in vs:      # 원문에 없는 값: list.json·API 응답 대조를 검수로 인정 (2026-11-06 결정)
            c_["verification_method"] = ["api_response" if x == "a" else "document" for x in vs]
        c_["status"] = "ai_verified" if all(x == "v" for x in vs) else "draft"
    every = [x for c_ in check for x in c_["value_status"]]
    return "ai_verified" if all(x == "ai_verified" for x in every) else "ai_verified_partial"


def case(agent, file, case_type, label, request, expect, check, notes=(), corp=None):
    corp = corp or {"corp_code": S[label]["corp_code"], "corp_name": S[label]["corp_name"]}
    status = apply_review(file, check)
    doc = {"case_type": case_type, "sample": label, **corp, "status": status, "request": request, "verified_by": AI, "verified_at": "2026-11-05", "review_source": "_review_batch1_검수결과.md (AI 검수, 사람 확인 아님)", "human_verified": {"verified": False, "by": None, "at": None},
           "expect": expect, "check_list": check, "open_notes": list(notes)}
    p = G / agent / f"{file}.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    return doc


docs = []
# ---- G-TRACK (D) ----
t = B["G-TRACK"]; h = t["h1_2026"]; cb = t["cb_2026"][0]
avail = h["cash"] + h["st"] + h["ttm"]
ocsa = num(cb["fdpp_ocsa"])
docs.append(case("overseas_funding", "G-TRACK_D", "G-TRACK", "D", {"mode": "single", "as_of_sequence": ["2026-08-12", "2026-08-22", "2026-09-20"]}, {
    "steps": [
        {"as_of": "2026-08-12", "in_scope": True, "alerts_must_not_have": ["new_funding"], "must_not_have_rcept_no": ["20260813001527", "20260813001787", "20260821900585", "20260916900193"],
         "funding_status": [{"rcept_no": "20250903000369", "kind": "cb", "final": "확정·현금 반영", "fund_use_scopes": {"fdpp_ocsa": "overseas"}}, {"rcept_no": "20250903000379", "kind": "rights", "final": "확정·현금 반영", "fund_use_scopes": {"fdpp_ocsa": "overseas", "fdpp_fclt": "unknown"}, "open_question": "해외 용도 불명 칸: fdpp_fclt 3,000,000,000"}]},
        {"as_of": "2026-08-22", "in_scope": True, "alerts_must_have": ["new_funding"], "financial_base": {"rcept_no": h["rcept_no"], "period": "2026H1"},
         "must_have_signals": [{"signal_type": "S5_funding", "rcept_no": cb["rcept_no"], "overseas_amount_krw": ocsa, "fund_use_scopes": {"fdpp_ocsa": "overseas", "fdpp_op": "unknown"}, "open_question": "해외 용도 불명 칸: fdpp_op 20,000,000,000"}],
         "funding_status": [{"rcept_no": cb["rcept_no"], "decision_amount_krw": num(cb["bd_fta"]), "result_rcept_no": t["result_2026"]["rcept_no"], "actual_krw": t["result_2026"]["actual"], "pay": t["result_2026"]["pay"], "final": "확정·합산"}],
         "cash_krw": h["cash"], "short_term_krw": h["st"], "ttm_ocf_krw": h["ttm"], "confirmed_funding_krw": ocsa, "unconfirmed_funding_krw": 0,
         "available_funds_krw": avail + ocsa, "overseas_investment_krw": num(t["acq_1"]["취득금액(원)"]), "funding_gap_krw": num(t["acq_1"]["취득금액(원)"]) - (avail + ocsa),
         "investment_notes": [{"rcept_no": t["acq_1"]["rcept_no"], "excluded": False, "note": "연결 내부 출자, 집행 시점 확인 불가"}]},
        {"as_of": "2026-09-20", "project_count_same_as_previous": True, "new_signal_same_project": {"rcept_no": t["acq_2"]["rcept_no"], "amount_krw": num(t["acq_2"]["취득금액(원)"]), "part_of_earlier": "no"},
         "overseas_investment_krw": num(t["acq_1"]["취득금액(원)"]) + num(t["acq_2"]["취득금액(원)"]), "funding_gap_krw": num(t["acq_1"]["취득금액(원)"]) + num(t["acq_2"]["취득금액(원)"]) - (avail + ocsa), "available_funds_krw": avail + ocsa, "merge_rule": "7.8: 회사명 칸 동일, 이사회 2025-11-10 / 2026-09-16, 3차·4차 출자",
         "investment_notes": [{"rcept_no": t["acq_1"]["rcept_no"], "confirmed_execution_date": "2025-11-12", "date_source_rcept_no": t["acq_2"]["rcept_no"], "excluded": False, "note": "연결 내부 출자, 집행 시점 확인 불가"},
                              {"rcept_no": t["acq_2"]["rcept_no"], "scheduled_date": "2026-09-21", "excluded": False, "note": "연결 내부 출자, 집행 시점 확인 불가"}]},
    ],
    "same_decision": {"cb_rcept_no": cb["rcept_no"], "hybrid_capital_rcept_no": "20260813001612", "reason": "7.5 R5: 회차 2, 권면 800억, 목적 칸, 납입일 2026-08-21, 이사회 2026-08-13 일치"},
    "subsidiary_execution": [{"rcept_no": t["ppe_sub"]["rcept_no"], "label": "종속회사 집행", "amount_krw": 24331573328, "added_to_representative": False}],
    "must_not_be_overseas": [{"rcept_no": t["domestic_fac"]["rcept_no"], "reason": "국내 공장 (기타 사항 문장)"}],
}, [
    chk("20260813001612", "자본으로인정되는채무증권 발행결정", "회차 2, 권면총액 800억", "운영 200억, 타법인 600억", "납입일 2026-08-21, 이사회 2026-08-13 (CB와 같은 결정인지)"),
    chk("20251111900321", "유형자산 취득결정 (종속회사)", "취득금액 243.3억", "거래상대방 지배회사", "미국 인디애나주 소재 문장"),
    chk("20260813001787", "전환사채권 발행결정 정정본", "권면총액 800억 (80,000,000,000)", "타법인 증권 취득자금 600억, 운영자금 200억", "납입일 2026-08-21 (예정)", "자금 사용 목적 600억이 해외(미국 종속회사) 용도인지"),
    chk("20260821900585", "증권 발행결과", "증권 종류 제2회 사모 전환사채(채권형신종자본증권)", "실제발행금액 800억", "납입일 2026-08-21", "최초 이사회결의일 2026-08-13"),
    chk("20251110900551", "타법인 취득결정", "HANJUNG AMERICA CO.(미국)", "취득금액 290.8억 (29,080,000,000)", "회사와 관계 종속회사", "취득목적: 종속회사 생산기반 확보를 위한 시설 및 운영자금"),
    chk("20260916900193", "타법인 취득결정 (같은 대상)", "취득금액 158.3억 (15,833,610,000)", "3차·4차 출자 문장 (별도 차수인지)", "취득예정일 2026-09-21"),
    chk("20251110900552", "신규시설투자", "투자금액 190억", "기타 사항 '해외가 아닌 국내 공장'"),
    chk("20250903000369", "2025 CB 결정", "권면총액 150억, 타법인 증권 취득자금 150억"),
    chk("20250903000379", "2025 유상증자 결정", "시설 30억, 타법인 120억, 제3자배정"),
    chk(h["rcept_no"], "2026 반기보고서 재무상태표·현금흐름표", f"현금및현금성자산 {eok(h['cash'])}억", f"단기금융상품 {eok(h['st'])}억", f"반기 누적 영업현금흐름 {eok(h['cum'])}억, 전년 동기 {eok(h['prev_same'])}억"),
    chk("20260318000730", "2025 사업보고서 현금흐름표", f"연간 영업현금흐름 {eok(h['fy_prev'])}억 (TTM {eok(h['ttm'])}억 계산 입력)"),
], ["자금 공백은 음수로 계산됨. G-TRACK 기대값은 추적 동작이라 문제없고 G-POS로는 쓰지 않음", "3차 출자 완료일 2025-11-12는 후속 공시(2026-09-16 접수)에 있어 as_of 2026-08-22에는 쓸 수 없다. 어느 시점이든 연결 내부 출자라 제외하지 않음"]))

# ---- G-RICH (F) ----
t = B["G-RICH"]; h = t["h1_2026"]; inv = num(t["acq"]["취득금액(원)"]); avail = h["cash"] + h["st"] + h["ttm"]; cb = t["cb"][0]
docs.append(case("overseas_funding", "G-RICH_F", "G-RICH", "F", {"mode": "single", "company": S["F"]["corp_code"], "as_of": "2026-11-05"}, {
    "in_scope": True, "signal_status": "해외 투자 확정",
    "must_have_signals": [{"signal_type": "S4_confirmed", "rcept_no": t["acq"]["rcept_no"], "is_overseas": True, "target_country": "미국", "overseas_amount_krw": inv}],
    "financial_base": {"rcept_no": h["rcept_no"], "period": "2026H1"}, "cash_krw": h["cash"], "short_term_krw": h["st"], "ttm_ocf_krw": h["ttm"],
    "funding_status": [{"rcept_no": cb["rcept_no"], "decision_amount_krw": num(cb["bd_fta"]), "result_rcept_no": t["result"]["rcept_no"], "actual_krw": t["result"]["actual"], "pay": t["result"]["pay"], "final": "확정·현금 반영", "fund_use_scopes": {"fdpp_fclt": "domestic", "fdpp_etc": "unknown"}, "overseas_candidate_krw": 0, "s5_amount_krw": None, "open_question": "해외 용도 불명 칸: fdpp_etc 10,000,000,000"}],
    "confirmed_funding_krw": 0, "unconfirmed_funding_krw": 0, "available_funds_krw": avail, "funding_gap_krw": inv - avail, "funding_gap_ratio": round((inv - avail) / inv, 4), "funding_gap_sign": "negative_or_zero",
    "investment_notes": [{"rcept_no": t["acq"]["rcept_no"], "confirmed_execution_date": "2026-07-31", "date_source_rcept_no": h["rcept_no"], "excluded": False, "note": "재무 기준일 이후 집행 2026-07-31"}],
    "must_not_have_after": "2026-11-05", "max_unverified_findings": 1,
}, [
    chk(t["acq"]["rcept_no"], "타법인 취득결정", "Tex-Isle, Inc., 국적 미국", "취득금액 737.8억 (73,780,000,000)", "지분비율 50.00%", "취득목적: 미국 현지 생산 및 유통 기반 확보"),
    chk(cb["rcept_no"], "전환사채권 발행결정 정정본", "권면총액 500억", "시설 400억 (포항3공장, 국내), 기타 100억 (해외 여부 불명)", "납입일 2026-06-30 (예정)"),
    chk(t["result"]["rcept_no"], "발행결과", "실제발행금액 500억", "납입일 2026-06-30 (재무 기준일과 같아 현금 반영)"),
    chk(h["rcept_no"], "2026 반기보고서", f"현금및현금성자산 {eok(h['cash'])}억", f"단기금융상품 {eok(h['st'])}억", f"반기 누적 영업현금흐름 {eok(h['cum'])}억, 전년 동기 {eok(h['prev_same'])}억"),
    chk("20260414002511", "2025 사업보고서 정정본 현금흐름표", f"연간 영업현금흐름 {eok(h['fy_prev'])}억"),
], ["반기보고서 주석에 2026-07-31 납입 완료. 재무 기준일 2026-06-30 이후라 투자액 유지 (7.10 4a)", "CB 시설 400억은 국내. api_fields.md 19장의 해외 후보 400은 프로브의 단순 합산 오류였고 이 정답지 기대값에 쓰인 적 없음"]))

# ---- G-NONE (H) ----
t = B["G-NONE"]; kw = t["keywords"]["20260814002580"]
docs.append(case("overseas_funding", "G-NONE_H", "G-NONE", "H", {"mode": "single", "company": S["H"]["corp_code"], "as_of": "2026-11-05"}, {
    "in_scope": False, "signal_status": "신호 없음", "must_not_have_signal_types": ["S4_confirmed", "S5_funding"],
    "major_event_batch_items": [{"rcept_no": t["facility"]["rcept_no"], "is_overseas": False, "purpose_category": "domestic"}],
    "keyword_paragraphs_in_latest_report": kw["keyword_paragraphs"], "llm_calls": {"extract_periodic_plan": 1, "classify_major_event": 1, "note": "기사 호출 수는 6단계에서 실측 후 확정"},
    "must_not_have_after": "2026-11-05",
}, [
    chk(t["facility"]["rcept_no"], "신규시설투자", "투자금액 391.2억 (39,120,000,000)", "투자목적: 소각로 신규투자", "해외가 아닌 국내 시설인지 (국적 칸 없음)"),
    chk("20260814002580", "2026 반기보고서 II. 사업의 내용", "해외 공장·법인·인수 계획이 없는지", "'북미' 표 행이 매출·시장 설명인지"),
    chk("20260320000662", "2025 사업보고서 II. 사업의 내용", "해외 확장 계획이 없는지"),
], ["이전 기록 'II장 키워드 0건'은 틀림. 키워드 문단 15개라 계획 추출 호출 1회가 필요", "사람 확인: 최근 12개월 다른 해외 투자·조달 공시 없음 (목록 확인 결과 신규시설투자 1건뿐)"]))

# ---- G-GOV (I) ----
t = B["G-GOV"]; ev = t["event"][0]
docs.append(case("overseas_funding", "G-GOV_I", "G-GOV", "I", {"mode": "single", "company": S["I"]["corp_code"], "as_of": "2026-09-30"}, {
    "must_have_signals": [{"signal_type": "S4_confirmed", "rcept_no": ev["rcept_no"], "original_rcept_no": "20260715000544", "original_rcept_dt": "20260716", "is_overseas": True, "purpose_category": "governance_restructuring", "target_country": "중국", "counted_as_new_investment": False}],
    "must_not_have_rcept_no": ["20261013000370", "20261019000188", "20261022000428"], "in_scope": True, "financial_base": {"rcept_no": "20260601001840", "period": "2026.03", "base_date": "2026-03-31"}, "overseas_investment_krw": 0, "overseas_investment_note": "확정 집행 완료분 제외", "funding_gap": "missing (가용 자금이 비원화로 missing)", "funding_gap_ratio": "None (투자액 0)", "governance_note": "양수금액 칸 3,131.5억은 외부평가(DCF) 최소값 1,423,879,000CNY × 219.93원/CNY 환산이고 무상양수도라 현금 유출 없음. 정정사유: 등기완료로 양수일 2026-08-31 → 2026-08-19", "must_not_have_after": "2026-09-30",
    "in_scope_source": "지배구조 공시가 아니라 종속회사 집행 S4 3건(윈난성 토지 사용권)으로 범위 안. 지배구조 건은 프로젝트 금액에 들어가지 않음",
    "subsidiary_execution": [{"rcept_no": "20251119900449", "amount_krw": 61853532750, "completed_by_correction": "20251128900729", "confirmed_execution_date": "2025-11-28", "excluded": True}, {"rcept_no": "20251119900452", "amount_krw": 66855641400, "completed_by_correction": "20251223900551", "confirmed_execution_date": "2025-12-23", "excluded": True}, {"rcept_no": "20260316902240", "amount_krw": 85905287100, "completed_by_correction": "20260330901340", "confirmed_execution_date": "2026-03-30", "excluded": True}],
}, [
    chk(ev["rcept_no"], "타법인 양수결정 정정본", "대상 복건영생활력생물공정유한공사, 국적 중국", "회사와 관계 자회사", "거래상대방 절강정성건강과기집단유한회사, 관계 자회사", "거래대금: 무상양수도", "양수금액 칸 3,131.5억은 외부평가 최소값 환산, 현금 유출 없음", "취득 후 지분율 100%", "취득목적: 지배구조 재편"),
    chk("20260715000544", "같은 건 원공시", "같은 거래, 원문 작성일 2026-07-15", "list.json 접수일 2026-07-16 (원문에 없는 값, 시점 판정 테스트용)"),
    chk("20251119900449", "유형자산 취득결정 (종속회사) 1", "윈난성 토지 사용권 618.5억, 차 재배단지"),
    chk("20251119900452", "유형자산 취득결정 (종속회사) 2", "윈난성 토지 사용권 668.6억"),
    chk("20260316902240", "유형자산 취득결정 (종속회사) 3", "윈난성 토지 사용권 859.1억"),
    chk("20260330901340", "취득완료 정정", "완료일 2026-03-30"),
    chk("20251128900729", "취득완료 정정", "완료일 2025-11-28 (검수 파일에 없음)"),
    chk("20251223900551", "취득완료 정정", "완료일 2025-12-23 (검수 파일에 없음)"),
    chk("20260601001840", "2026.03 분기보고서", "as_of 2026-09-30의 재무 기준 보고서 (검수 파일에 없음)"),
], ["as_of를 2026-09-30으로 둔 이유: 2026-10-13 별도 신규 인수(케이만, 606.1억)가 있어 그 이후는 G-GOV 단독 시험이 안 됨", "회사 자체가 중국 사업 위주라 '해외' 판정의 경계 사례. 소재지 문장이 지역명(윈난성)이고 국가명이 없어 라벨 판단 대상", "토지 3건은 제3자 거래이고 취득완료 정정일이 모두 재무 기준일 2026-03-31 이전이라 전액 제외 (7.10 4a). 합산 판정 전에 빠진다"]))

# ---- F-NORMAL (F, G) ----
for label, key in (("F", "F-NORMAL"), ("G", "F-NORMAL-ALT-G")):
    ys = B[key]
    exp = {}
    for y, v in ys.items():
        exp[f"{y}FY"] = {"fs_rcept_no": v["fs_rcept_no"], "total_borrowings_krw": v["total_borrowings"], "total_borrowings_note": v["tb_note"], "net_debt_krw": v["net_debt"], "ebitda_krw": v["ebitda"],
                         "ebitda_note": v["note"] if v["ebitda"] is None else None, "net_debt_missing_reason": v["tb_note"] if v["net_debt"] is None else None, "coverage_missing_reason": v.get("interest_missing"), "interest_source": v.get("interest_source"), "operating_income_krw": v["oi"], "revenue_krw": v["revenue"], "depreciation_krw": v["dep"], "amortization_krw": v["amort"],
                         "interest_expense_krw": v["interest"], "net_debt_to_ebitda": v.get("nd_ebitda"), "ebitda_interest_coverage": v.get("coverage"), "ebitda_margin_pct": v.get("margin"),
                         "debt_ratio_pct": v["debt_ratio"], "audit_opinion_raw": sorted({a[1] for a in v["audit"]})}
    c25, c24 = ys["2025"], ys["2024"]
    check = [chk(c25["fs_rcept_no"], "2025 사업보고서 재무제표·주석", f"영업이익 {eok(c25['oi'])}억, 매출액 {eok(c25['revenue'])}억", f"감가상각비(사용권 포함) {eok(c25['dep'])}억, 무형자산상각비 {eok(c25['amort'])}억 (비용의 성격별 분류·영업에서 창출된 현금)",
                 f"총차입금 {eok(c25['total_borrowings'])}억 (차입·사채·리스부채 행 합)", f"현금 {eok(c25['cash'])}억, 단기금융상품 {eok(c25['st'])}억", f"이자비용 {eok(c25['interest'])}억 (출처 {c25['interest_source']})", f"감사의견 {c25['audit'][0][1] if c25['audit'] else '없음'}"),
             chk(c24["fs_rcept_no"], "2024 사업보고서", f"영업이익 {eok(c24['oi'])}억, 매출액 {eok(c24['revenue'])}억", f"감가상각비 {eok(c24['dep'])}억, 무형자산상각비 {eok(c24['amort'])}억" if c24["dep"] else "감가상각비 행을 주석·현금흐름에서 찾을 수 있는지", f"차입 계정 상태: {c24['tb_note'] or '산출'}", f"이자비용 {eok(c24['interest'])}억 (출처 {c24['interest_source']})"),
             chk(ys["2023"]["fs_rcept_no"], "2023 사업보고서", f"영업이익 {eok(ys['2023']['oi'])}억, 매출액 {eok(ys['2023']['revenue'])}억", f"EBITDA 상태: {ys['2023']['note'] or eok(ys['2023']['ebitda'])}", f"차입 계정 상태: {ys['2023']['tb_note'] or '산출'}")]
    notes = ["보조 케이스. 현금흐름 조정 행이 없어 이자비용은 금융원가 주석 값 (재무 9.1a 채택)", "2023 EBITDA는 N·C가 감가와 사용권을 다르게 나눴지만 합계가 같아 산출한다 (재무 v0.20 9.1a). 이전 '출처 불일치'는 오판", "2023·2024 순차입금은 표준코드 미사용 차입 행으로 missing"] if label == "F" else ["주 케이스. 2025·2024 핵심 지표 3개 모두 산출", "2023 순차입금은 단기차입금이 표준코드 미사용이라 missing, 순차입금/EBITDA도 missing", "2023 감사의견 행은 (당기)가 아니라 (주1) 표기"]
    docs.append(case("financial_health", f"F-NORMAL_{label}", "F-NORMAL", label, {"mode": "single", "company": S[label]["corp_code"], "as_of": "2026-11-05"}, {"role": "주 케이스" if label == "G" else "금융원가 주석 이자비용 보조 케이스", "latest_year_all_core_computed": True, "years": exp, "tolerance": 0.01, "fs_basis": "CFS"}, check, notes))

# ---- F-AUDIT ----
for a, name in zip(B["F-AUDIT"], ("의견거절", "한정")):
    cands = json.loads((G / "financial_health/_candidates.json").read_text(encoding="utf-8"))["candidates"]["F-AUDIT"]
    cd = next(x for x in cands if x["corp_code"] == a["corp_code"])
    raw = a["rows"][0]["adt_opinion"]
    no = a["annual"]["rcept_no"]
    check = [chk(no, "사업보고서 '회계감사인의 명칭 및 감사의견'", f"제{a['rows'][0]['bsns_year'].split('기')[0].replace('제', '')}기 당기 감사의견 {raw}", f"감사인 {a['rows'][0]['adtor']}"),
             chk(no, "첨부 감사보고서", f"{name} 근거 문단", "근거가 감사범위 제한인지 (API는 판별 불가, 기대값 unknown)"),
             chk(no, "재무상태표", f"자본금 {eok(cd['capital_stock_krw'])}억", f"자기자본 {eok(cd['equity_krw'])}억 (자본잠식률 {cd['impair_pct']}%)")]
    docs.append(case("financial_health", f"F-AUDIT_{name}", "F-AUDIT", f"{a['market']} 후보",
                     {"mode": "single", "company": a["corp_code"], "as_of": a["as_of"]},
                     {"bsns_year": a["fy"], "fin.audit_opinion": raw, "audit_opinion_map": "의견거절" if name == "의견거절" else "한정", "fin.audit_scope_limitation": "unknown", "orchestrator_rule_note": "감사범위 제한 부분은 확인 불가",
                      "capital_stock_krw": cd["capital_stock_krw"], "equity_ex_nci_krw": cd["equity_krw"], "capital_impairment_ratio_pct": cd["impair_pct"], "fs_basis": cd["fs_div"], "must_not_have_after": a["as_of"], "annual_rcept_no": no},
                     check, ["사람 기준 정답: 원문 감사보고서에 '이러한 감사범위 제한으로' 문구 있음. 시스템 기대값은 API 칸으로 판별할 수 없어 unknown 유지"] if name == "의견거절" else ["사람 기준 정답: 원문에 감사범위 제한 문구 없음 (한정 근거는 PT.BNP 광업권 관련 감사증거 입수 불가, 기초 잔액 감사절차 미실시). 시스템 기대값은 unknown 유지"],
                     corp={"corp_code": a["corp_code"], "corp_name": cd["corp_name"]}))

# ---- 검토표 ----
lines = ["# 2단계 첫 묶음 검토표\n", "값은 코드가 읽은 값이다. [x]는 AI 검수 일치(사람 확인 아님), [ ]는 미검수다. 상세는 `_review_batch1_검수결과.md`.\n"]
for d in docs:
    lines.append(f"\n## {d['case_type']} — {d['corp_name']} (표본 {d['sample']}) — {d['status']}\n")
    lines.append(f"- as_of: {d['request'].get('as_of') or ', '.join(d['request']['as_of_sequence'])}\n")
    for c in d["check_list"]:
        lines.append(f"- [{c['where']}]({c['url']})\n" + "".join(f"  - [{'x' if s == 'ai_verified' else ' '}] {v}{' (API 응답 대조)' if m == 'api_response' else ''}\n" for v, s, m in zip(c["values"], c["value_status"], c.get("verification_method", [None] * len(c["values"])))))
    if d["open_notes"]:
        lines.append("- 참고\n" + "".join(f"  - {n}\n" for n in d["open_notes"]))
(G / "_review_batch1.md").write_text("".join(lines), encoding="utf-8")
print("초안", len(docs))
print(json.dumps({d["case_type"] + " " + str(d["sample"]): {k: d["expect"].get(k) for k in ("funding_gap_krw", "available_funds_krw", "funding_gap_ratio")} for d in docs if "funding_gap_krw" in d["expect"]}, ensure_ascii=False))
g = next(d for d in docs if d["case_type"] == "G-TRACK")
print(g["expect"]["steps"][1]["funding_gap_krw"], g["expect"]["steps"][1]["confirmed_funding_krw"])
