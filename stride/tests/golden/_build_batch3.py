"""2단계 셋째 묶음 초안 작성: data/probe/golden_batch3.json → tests/golden/<agent>/*.json + tests/golden/_review_batch3.md

값은 코드가 읽은 값이다. 검수 상태는 _review_batch1_검수결과.md "셋째 묶음 검수" 절을 `REVIEW`로 옮긴 것이다. 검수 문구에 없는 값은 draft로 둔다.
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
G = ROOT / "stride/tests/golden"
B = json.loads((ROOT / "data/probe/golden_batch3.json").read_text(encoding="utf-8"))
C = json.loads((G / "_candidates_batch3.json").read_text(encoding="utf-8"))
URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
eok = lambda v: None if v is None else round(v / 1e8, 2)
num = lambda s: int(s.replace(",", ""))
docs = []


def chk(rcept_no, where, *values):
    return {"rcept_no": rcept_no, "url": URL.format(rcept_no), "where": where, "values": list(values), "value_status": ["draft"] * len(values), "status": "draft"}


AI = "AI 검수(claude.ai)"
# check_list 순서대로. v = 값 전부 일치, a = API 응답 대조, d = 미검수, 목록 = 값별. 없는 파일은 전부 미검수
REVIEW = {
    "G-POS_주": ["v", "v", "v", "v", "v", "v"],
    "G-POS_보조": ["v", "v", "v", "v", "v"],
    "G-CHANGE_1": ["v", "v", "v", "v", "v"],
    "G-DOM_EDGE": ["v", "v", "v", "v", "v", "v", "v"],
    "G-DOM_주": ["v", "v", "v", "v", "v", "v", "v", "v"],
    "G-MIX_1": ["v", "v", "v", "v", "v", "v"],
    "F-NETCASH_1": ["v", "v", "v", "v"],
    "F-OFS_1": ["v", "v", "v", "v", "v"],
    "F-NOINTEREST_1": ["v", "v", "v", "v"],
    "F-CORRECTED_KOSPI": [["v", "a"], ["a", "v", "v"]],
}


def case(agent, file, case_type, label, corp, request, expect, check, notes=()):
    if file == "G-POS_주":      # 2026-11-06 결정으로 G-POS_MIXED(구영)와 새 주 후보로 대체. _build_gpos_swap.py가 만든다
        return
    status, by, at = "draft", None, None
    if file in REVIEW:
        assert len(REVIEW[file]) == len(check), file
        for c_, f in zip(check, REVIEW[file]):
            vs = [f] * len(c_["values"]) if isinstance(f, str) else f
            assert len(vs) == len(c_["values"]), (file, c_["where"])
            c_["value_status"] = ["ai_verified" if v in ("v", "a") else "draft" for v in vs]
            if "a" in vs:      # 원문에 없는 값: list.json·API 응답 대조를 검수로 인정 (2026-11-06 결정)
                c_["verification_method"] = ["api_response" if v == "a" else "document" for v in vs]
            c_["status"] = "ai_verified" if all(v == "v" for v in vs) else "draft"
        every = [v for c_ in check for v in c_["value_status"]]
        status = "ai_verified" if all(v == "ai_verified" for v in every) else "ai_verified_partial" if "ai_verified" in every else "draft"
        by, at = AI, "2026-11-06"
    doc = {"case_type": case_type, "sample": label, "corp_code": corp["corp_code"], "corp_name": corp["corp_name"], "status": status, "request": request, "verified_by": by, "verified_at": at,
           "human_verified": {"verified": False, "by": None, "at": None}, "expect": expect, "check_list": check, "open_notes": list(notes)}
    (G / agent / f"{file}.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    docs.append(doc)


AS = "2026-11-05"
NOTE_INTERNAL = "연결 내부 출자, 집행 시점 확인 불가"

# ---- G-POS 주 ----
g, x = C["G-POS"][0], B["G-POS"]
h = x["h1"]
inv = num(x["acq"]["취득금액(원)"])
avail = h["cash"] + h["st"] + h["ttm"]
gap = inv - avail
case("overseas_funding", "G-POS_주", "G-POS", "주", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "in_scope": True, "signal_status": "해외 투자 확정",
    "must_have_signals": [{"signal_type": "S4_confirmed", "rcept_no": "20260413900715", "is_overseas": True, "purpose_category": "growth_investment", "target_country": "미국", "overseas_amount_krw": inv}],
    "no_signal": [{"rcept_no": "20260413900717", "rule": "R1 종속회사 유상증자"}],
    "open_questions": ["종속회사 증자 채무상환 용도 14,798,000,000: 자금 공백에 차입 상환 수요 포함 가능"],
    "financial_base": {"rcept_no": h["rcept_no"], "period": "2026H1"}, "cash_krw": h["cash"], "short_term_krw": h["st"], "ttm_ocf_krw": h["ttm"],
    "confirmed_funding_krw": 0, "unconfirmed_funding_krw": 0, "available_funds_krw": avail, "overseas_investment_krw": inv, "funding_gap_krw": gap, "funding_gap_ratio": round(gap / inv, 4), "funding_gap_sign": "positive",
    "investment_notes": [
        {"rcept_no": "20260413900715", "excluded": False, "scheduled_date": "2026-04-22", "note": NOTE_INTERNAL},
        {"rcept_no": "20250825900496", "latest_version": "20251215901187", "amount_krw": num(x["dup"]["correction"]["취득금액(원)"]), "confirmed_execution_date": "2025-10-31", "date_source_rcept_no": h["rcept_no"], "date_quote": "CAR TECH의 지분은 2025.10.31일자로 취득 완료", "excluded": True, "note": "제3자 거래, 재무 기준일 이전 취득 완료 (7.10 4a). 합산 판정 전에 빠진다"},
    ],
    "must_not_have_after": AS,
}, [
    chk("20260413900715", "타법인 취득결정", "CAR TECH, LLC(USA), 회사와 관계 종속회사", "취득금액 29,596,000,000 (USD 20,000,000)", "취득목적 '종속기업의 재무구조개선 및 시설투자자금 확보'", "결손 보전 표현이 없는지", "송금 예정 2026-04-13, 2026-04-22"),
    chk("20260413900717", "유상증자결정 (종속회사)", "시설자금 14,798,000,000", "채무상환자금 14,798,000,000", "결손 보전 칸·표현이 없는지"),
    chk("20250825900496", "2025 취득결정 원공시 (같은 대상)", "이사회 2025-08-25, 회사와 관계 '-'", "취득목적 '사업 확대를 위한 기업인수'"),
    chk("20251215901187", "2025 취득결정 정정본", "취득금액 6,797,368,634", "잔여 지분 18.39%를 2025.10.31.자로 취득 완료 문장"),
    chk(h["rcept_no"], "2026 반기보고서", f"현금및현금성자산 {h['cash']:,}", "단기금융상품 행 0 (재무상태표)", f"반기 누적 영업현금흐름 {h['cum']:,}, 전년 동기 {h['prev_same']:,}", "주석 30 'CAR TECH의 지분은 2025.10.31일자로 취득 완료'"),
    chk("20260316001359", "2025 사업보고서 현금흐름표", f"연간 영업현금흐름 {h['fy_prev']:,} (TTM {h['ttm']:,} 계산 입력)"),
], [
    "결손 보전 여부: 두 공시와 반기보고서 어디에도 결손 보전 표현이 없다. 공시된 증자 용도는 시설 148억 + 채무상환 148억. 그래서 주 후보를 유지했다 (사용자 조건)",
    "다만 절반이 채무상환이다. 금액은 정형 칸 전액(295.96억)을 쓰며 용도별로 나누지 않고, 채무상환 148억은 open_question으로 남긴다 (2026-11-05 결정). CAR TECH 2025년 자본총계 69.3억 / 자본금 431.8억, 부채 2,350.4억",
    "2025 취득 완료일 문장은 7.10 4a 정규식 예시에 없던 형식이라 해외 v0.13에서 형식을 추가했다",
    "유형자산 취득(종속) GUYOUNGTECH USA 398.3억의 원공시 2024-09-06은 lookback 24개월 밖이라 대상이 아니다",
])

# ---- G-POS 보조 ----
g, x = C["G-POS"][1], B["G-POS-ALT"]
h = x["h1"]
a1, a2 = num(x["acq_1"]["취득금액(원)"]), num(x["acq_2"]["취득금액(원)"])
avail = h["cash"] + h["st"] + h["ttm"]
case("overseas_funding", "G-POS_보조", "G-POS", "보조", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "in_scope": True, "signal_status": "해외 투자 확정",
    "must_have_signals": [
        {"signal_type": "S4_confirmed", "rcept_no": x["acq_1"]["rcept_no"], "original_rcept_no": "20251106800211", "is_overseas": True, "purpose_category": "growth_investment", "target_country": "인도네시아", "overseas_amount_krw": a1},
        {"signal_type": "S4_confirmed", "rcept_no": x["acq_2"]["rcept_no"], "is_overseas": True, "purpose_category": "growth_investment", "target_country": "인도네시아", "overseas_amount_krw": a2, "part_of_earlier": "no"},
    ],
    "no_signal": [{"rcept_no": "20260909800251", "rule": "R1 종속회사 유상증자"}],
    "project_count_for_target": 1, "merge_rule": "7.8: 회사명 칸 공백 제거 후 일치(정정본 기준), 이사회 2025-11-06 / 2026-09-09, 취득주식 159,840 + 140,000 = 취득 후 299,840",
    "financial_base": {"rcept_no": h["rcept_no"], "period": "2026H1"}, "cash_krw": h["cash"], "short_term_krw": h["st"], "ttm_ocf_krw": h["ttm"], "confirmed_funding_krw": 0, "unconfirmed_funding_krw": 0, "available_funds_krw": avail,
    "overseas_investment_krw": a1 + a2, "funding_gap_krw": a1 + a2 - avail, "funding_gap_ratio": round((a1 + a2 - avail) / (a1 + a2), 4), "funding_gap_sign": "negative_or_zero",
    "investment_notes": [{"rcept_no": x["acq_1"]["rcept_no"], "excluded": False, "scheduled_date": "2026-08-28", "note": NOTE_INTERNAL}, {"rcept_no": x["acq_2"]["rcept_no"], "excluded": False, "scheduled_date": "2027-03-31", "note": NOTE_INTERNAL}],
    "must_not_have_after": AS,
}, [
    chk("20251106800211", "타법인 취득결정 원공시", "PT. DUKSUNG ECOTECH INDONESIA (가칭), 국적 인도네시아", "취득금액 13,842,144,000", "취득목적 '합성피혁 사업부문의 해외사업 진출'"),
    chk("20260828800858", "정정 (취득예정일자 확정)", "회사명 (가칭) 삭제", "회사와 관계 자회사", "취득주식수 159,840, 취득예정일자 2026-08-28"),
    chk("20260909800257", "타법인 취득결정 (추가 출자)", "취득금액 10,654,000,000, 취득주식수 140,000", "취득 후 소유 299,840주 (별도 출자인지)", "취득목적 '합성피혁 제조시설 투자'", "최종 분할납입 2027-03-31"),
    chk(h["rcept_no"], "2026 반기보고서", f"현금및현금성자산 {h['cash']:,}", f"단기금융상품 {h['st']:,}", f"반기 누적 영업현금흐름 {h['cum']:,}, 전년 동기 {h['prev_same']:,}"),
    chk("20260318000948", "2025 사업보고서 현금흐름표", f"연간 영업현금흐름 {h['fy_prev']:,}"),
], [
    "후보 파일의 '가칭 때문에 합산 불명확 예상'은 틀렸다. 7.5는 정정본(최신본) 칸을 쓰므로 회사명이 일치한다",
    "교환사채 20250922000203·발행결과 20250930800828은 8.1.4 DS005 대상과 11.2 조달 종류(유상증자·CB·BW)에 없어 S5가 아니다. 납입 2025-09-30도 재무 기준일 이전이다",
])

# ---- G-CHANGE ----
g, x = C["G-CHANGE"][0], B["G-CHANGE"]
amt = num(x["plan"]["취득금액(원)"])
cancel = ["20250630900515", "20250630900523"]
next_amt = num(x["next"]["취득금액(원)"])
case("overseas_funding", "G-CHANGE_1", "G-CHANGE", "1", g, {"mode": "replay", "company": g["corp_code"], "as_of_sequence": g["replay_as_of"]}, {
    "plan_date": "2024-12-20", "change_date": "2025-06-30",
    "steps": [
        {"as_of": "2025-01-19", "in_scope": True, "signal_status": "해외 투자 확정", "alerts_must_have": ["new_signal"], "must_have_signals": [{"signal_type": "S4_confirmed", "rcept_no": "20241220900448", "target_country": "베트남", "overseas_amount_krw": amt}], "must_not_have_rcept_no": cancel + ["20250918900092"]},
        {"as_of": "2025-06-29", "alerts_must_not_have": ["plan_changed", "stage_down", "cancelled"], "must_not_have_rcept_no": cancel + ["20250918900092"], "leak_check": "변경 언급 시 미래 정보 누수"},
        {"as_of": "2025-07-07", "in_scope": False, "signal_status": "취소", "scope_reason_has": "G4", "stage": "MENTIONED", "alerts_must_have": ["cancelled", "stage_down"], "must_have_signals": [{"signal_type": "S6_alert", "rcept_no": "20250630900523", "change_direction": "취소/해제"}], "evidence_has": cancel, "must_not_have_rcept_no": ["20250918900092"]},
        {"as_of": "2025-10-28", "no_duplicate_project_for": "베트남", "must_have_signals": [{"signal_type": "S4_confirmed", "rcept_no": "20250918900092", "target_country": "싱가포르", "overseas_amount_krw": next_amt, "separate_project": True}], "must_not_have_rcept_no": ["20251128900796"]},
    ],
}, [
    chk("20241220900448", "타법인 취득결정", "SEED SEGYUNG VINA(베트남), 회사와 관계 관계회사", "취득금액 21,817,985,000, 지분 35%", "취득예정일자 2025-06-30"),
    chk("20250630900515", "정정", "정정사유 '투자구조 변경에 따른 취득결정 철회'", "정정 후 칸이 모두 '-'"),
    chk("20250630900523", "기타 주요경영사항 (철회)", "철회 사유 'SEED사 측의 투자구조 변경 요청'", "결정일 2025-06-30"),
    chk("20250918900092", "타법인 취득결정 (자율공시, 후속)", "SEED GLOBAL PTE. LIMITED (싱가포르), 지분 46.67%", "취득금액 12,059,528,160", "베트남 건과 같은 합작인지 원문에 적혀 있는지"),
    chk("20251128900796", "후속 건 정정", "취득예정일자 2025-11-28 → 2026-01-31 (as_of 2025-10-28 이후)"),
], [
    "기대값은 7.9·7.12 기준이다 (철회 → G4 실패, CANCELLED, cancelled 경보, 2026-11-05 결정으로 12.2·12.3 통일). stage 하락이라 stage_down도 함께 난다 (7.12)",
    "싱가포르 건은 7.8 키(국가·방식)가 달라 별도 프로젝트. 같은 상대와의 구조 변경이지만 묶는 규칙은 없다",
    "4번째 시점의 signal_status와 경보는 기대값에 넣지 않았다. 7.12에 '이전 CANCELLED → 새 프로젝트' 규칙이 없다",
    "자금 공백은 이 유형 시험 대상이 아니라 넣지 않았다",
])

# ---- G-DOM ----
g, x = C["G-DOM_EDGE"][0], B["G-DOM"]
d = x["decision"][0]
res = x["result"]
case("overseas_funding", "G-DOM_EDGE", "G-DOM", "EDGE", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "in_scope": False, "signal_status": "범위 밖", "scope_reason_has": "G2", "must_not_have_signal_types": ["S4_confirmed"],
    "must_have_signals": [{"signal_type": "S5_funding", "rcept_no": d["rcept_no"], "fund_use_scopes": {"fdpp_fclt": "domestic", "fdpp_op": "domestic"}, "overseas_amount_krw": None}],
    "funding_status": [{"rcept_no": d["rcept_no"], "decision_amount_krw": num(d["fdpp_fclt"]) + num(d["fdpp_op"]), "result_rcept_no": res["rcept_no"], "actual_krw": res["actual"], "pay": res["pay"]}],
    "major_event_batch_items": [{"rcept_no": "20250619900605", "is_overseas": False, "purpose_category": "domestic"}],
    "rule_only_no_llm": ["20241125000265", "20241125000256"], "periodic_plan_items_expected": 0, "must_not_have_after": AS,
    "edge_reason": "해외 진출 언급은 있으나 투자 계획 아님", "edge_evidence": [{"rcept_no": "20260323000808", "where": "II. 사업의 내용", "quote": "아시아 지역의 인도네시아, 중국, 베트남, 태국, 필리핀 5개 국가를 최우선 진출 국가로 지정하였으며, 향후 글로벌 임상 이후 국가별 공공시장, 민간시장 및 국제기구 (UNICEF 등)를 통한 공공 조달시장도 참여할 계획입니다."}],
}, [
    chk(d["rcept_no"], "유상증자 결정", "시설자금 7,000,000,000 'GMP 제조설비 확장'", "운영자금 3,000,000,167 '오송 바이오 플랜트 운영'", "소재지 표기: 시설 칸에는 없음"),
    chk("20260316901723", "발행결과", "실제발행금액 10,000,000,167", "납입일 2026-03-16"),
    chk("20250619900605", "신규시설투자", "투자금액 6,891,000,000", "'충청북도 청주시 흥덕구 오송 소재 당사 바이오플랜트 내 공사' (GMP 설비가 국내임을 보여주는 근거)"),
    chk("20260323000808", "2025 사업보고서 II. 사업의 내용", "해외 공장·법인·인수·합작 표현 없음 (코드 검색 0건)", "'인도네시아, 중국, 베트남, 태국, 필리핀 5개 국가를 최우선 진출 국가로 지정' 문장이 제품 판매 시장 설명인지", "필리핀 임상 2b/3상 IND"),
    chk("20260814002866", "2026 반기보고서 II. 사업의 내용", "해외 공장·법인·인수·합작 표현 없음 (코드 검색 0건)"),
    chk("20250131000553", "2024-11 유상증자 정정본", "운영자금 6,499,300,000 (R3)"),
    chk("20250131000554", "2024-11 유상증자 정정본", "운영자금 3,533,600,000 (R3)"),
], [
    "경계 사례 (2026-11-05 결정, 주 후보에서 내림). 해외 공장·법인·인수·합작 계획은 없고 44개국 판매권과 5개국 최우선 진출 지정 문장, 필리핀 임상이 있다. 10.2 정의상 판매 시장 진출은 해외 확장 계획이 아니라 추출 0건을 기대한다",
    "시설 칸 소재지가 공시에 없다. 국내 판단 근거는 다른 공시(2025-06 신규시설)의 오송 문장이라 LLM 묶음 라벨이 unknown일 수 있다. unknown이면 open_question이 추가되고 in_scope 결과는 같다",
    "CB 원공시 2024-10-31은 lookback 24개월 밖이다. 정정본만 창 안에 있고 용도는 운영 150억이다",
])

# ---- G-DOM 주 ----
g, x = C["G-DOM"][0], B["G-DOM-MAIN"]
d, cb, res, cres = x["decision"][0], x["cb"][0], x["result"], x["cb_result"]
case("overseas_funding", "G-DOM_주", "G-DOM", "주", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "in_scope": False, "signal_status": "범위 밖", "scope_reason_has": "G2", "must_not_have_signal_types": ["S4_confirmed"],
    "must_have_signals": [{"signal_type": "S5_funding", "rcept_no": d["rcept_no"], "fund_use_scopes": {"fdpp_fclt": "domestic"}, "overseas_amount_krw": None}],
    "funding_status": [{"rcept_no": d["rcept_no"], "decision_amount_krw": num(d["fdpp_fclt"]), "result_rcept_no": res["rcept_no"], "actual_krw": res["actual"], "pay": res["pay"]}],
    "rule_only_no_llm": [{"rcept_no": cb["rcept_no"], "rule": "R3 채무상환뿐", "purpose_category": "refinancing", "amount_krw": num(cb["fdpp_dtrp"])}],
    "periodic_plan_items_expected": 0, "must_not_have_after": AS,
}, [
    chk(d["rcept_no"], "유상증자 결정", "시설자금 1,000,000,000 '고다층 PCB 제조설비 구축'", "시설 칸 외 다른 용도 칸 없음", "소재지 표기: 시설 칸에는 없음"),
    chk(res["rcept_no"], "발행결과", f"실제발행금액 {res['actual']:,}", "납입일 2026-02-23"),
    chk(cb["rcept_no"], "2025 CB 결정", "권면총액 9,000,000,000", "채무상환자금 9,000,000,000 (제20회·제22회 전환사채)"),
    chk(cres["rcept_no"], "2025 CB 발행결과", f"실제발행금액 {cres['actual']:,}", "납입일 2025-04-11"),
    chk("20250416800495", "타법인 처분결정", "주식회사 스튜디오2046, 국적 대한민국 (처분이라 투자 신호 아님)"),
    chk(g["annual_rcept_no"], "2025 사업보고서 II. 사업의 내용", "해외 공장·법인·인수·합작·진출·수출 확대 계획 문구가 없는지", "코드 검색 2건: '선진 부품기업들이 국내에 진출', '납품 30일 후 인수증 발급' (회사 계획 아님)"),
    chk(g["annual_rcept_no"], "연결재무제표 주석 1 종속기업의 개요", "(주)우진 대한민국", "(주)스튜디오2046 대한민국", "루츠컴퍼니(주) 대한민국", "본사 인천광역시 남동구 남동대로 248"),
    chk(x["half_rcept_no"], "2026 반기보고서 II. 사업의 내용", "해외 공장·법인·인수·합작·진출·수출 확대 계획 문구가 없는지"),
], [
    "종속회사 소재지 확인 (사용자 조건): 본문 상세표는 2곳, 연결 주석은 손자회사 포함 3곳이고 모두 대한민국. 해외 법인이 아니라 후보를 유지했다",
    "관계기업(종속 아님) 케이피유폼텍인도, 소재지 인도, 지분 40%, 장부금액 1천원이 있다. 2025년 신규 공시나 계획 문구는 없다",
    "시설 칸에 소재지가 없고 근거는 본사·종속회사 소재지라 LLM 라벨이 unknown일 수 있다. unknown이면 open_question이 추가되고 in_scope 결과는 같다",
])

# ---- G-MIX ----
g, x = C["G-MIX"][0], B["G-MIX"]
d = x["decision"][0]
res = x["result"]
h = x["h1"]
QUOTE = "폴란드공장 조관 및 인발 제조 설비 구축 2026.06 ~ 2026.12 5,000,000,000 / 화성공장 심리스 제조 설비 구축 2026.06 ~ 2026.12 2,000,000,000"
case("overseas_funding", "G-MIX_1", "G-MIX", "1", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "must_have_signals": [{"signal_type": "S5_funding", "rcept_no": d["rcept_no"], "original_rcept_no": "20260522000505", "fund_use_scopes": {"fdpp_fclt": "mixed", "fdpp_op": "overseas"}, "overseas_amount_krw": num(d["fdpp_op"]),
                           "open_questions": [f"해외 용도 불명 칸: fdpp_fclt {num(d['fdpp_fclt']):,}", f"칸 안 세부 내역 (합산 안 함): {QUOTE}"]}],
    "funding_status": [{"rcept_no": d["rcept_no"], "decision_amount_krw": num(d["bd_fta"]), "result_rcept_no": res["rcept_no"], "actual_krw": res["actual"], "pay": res["pay"], "final": "확정·현금 반영"}],
    "must_not_sum_sentence_amount_krw": 5000000000, "financial_base": {"rcept_no": h["rcept_no"], "period": "2026H1"}, "confirmed_funding_krw": 0, "unconfirmed_funding_krw": 0,
    "funding_gap": "missing (단기금융상품 행 없고 기타유동금융자산 행만 있음)", "must_not_have_after": AS,
}, [
    chk("20260605000303", "CB 결정 정정본 【조달자금의 구체적 사용 목적】", "시설 7,000,000,000: 폴란드공장 5,000,000,000 + 화성공장 2,000,000,000", "운영 3,000,000,000: '인건비, 원재료 매입 등폴란드 공장 운영자금'", "권면총액 10,000,000,000"),
    chk("20260522000505", "CB 결정 원공시", "이사회 2026-05-22, 납입 예정 2026-06-01"),
    chk("20260601901588", "증권 발행결과", "실제발행금액 10,000,000,000", "납입일 2026-06-01", "제7회 CB, 최초 이사회결의일 2026-05-22"),
    chk(h["rcept_no"], "2026 반기보고서 정정본", f"현금및현금성자산 {h['cash']:,}", "단기금융상품 행 없음, 기타유동금융자산 행 있음"),
    chk("20260630900397", "유형자산 취득(종속회사) 정정", "Yulchon Poland 취득금액 18,119,750,206", "취득예정일 2026-06-30 → 2027-03-31"),
    chk("20250317900613", "타법인 취득 정정본 (출자전환)", "Yulchon Poland 취득금액 3,614,844,305", "취득방법 대여금의 출자전환, 취득목적 재무구조개선"),
], [
    "기존 G-MIX_D(해외 칸 + 불명 칸)와 달리 한 칸 안에 국내·해외가 금액과 함께 적힌 사례다",
    "폴란드 50억은 사용 목적 절 세부 내역의 금액이고 정형 칸이 아니라 합산하지 않는다 (2026-11-05 결정). open_question에 원문을 남긴다",
    "폴란드 S4 라벨·대표 금액은 이 유형 시험 대상이 아니라 넣지 않았다. 자금 공백은 입력이 missing이라 계산되지 않는다",
    "반기보고서 정정 20261002000046이 있어 2026-08-14~10-01 as_of는 재무 unknown이 된다. as_of는 정정 후로 두었다",
])

# ---- F-NETCASH ----
g, x = C["F-NETCASH"][0], B["F-NETCASH"]
no = x["fs_rcept_no"]
case("financial_health", "F-NETCASH_1", "F-NETCASH", "1", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "period": "2025FY", "fs_rcept_no": no, "fin.fs_basis": "CFS", "cash_krw": x["cash"], "short_term_krw": x["st"], "total_borrowings_krw": x["total_borrowings"], "total_borrowings_note": x["tb_note"], "fin.net_debt_krw": x["net_debt"], "net_debt_sign": "negative",
    "operating_income_krw": x["oi"], "depreciation_krw": x["dep"], "amortization_krw": x["amort"], "fin.ebitda_krw": x["ebitda"], "fin.net_debt_to_ebitda": x["nd_ebitda"], "interest_expense_krw": x["interest"], "interest_note": "이자비용 출처: 금융원가 주석", "fin.ebitda_interest_coverage": x["coverage"], "fin.ebitda_margin_pct": x["margin"], "fin.audit_opinion": x["audit"],
}, [
    chk(no, "2025 사업보고서 재무상태표", f"현금 {x['cash']:,}", f"단기금융상품 {x['st']:,}", f"총차입금 {x['total_borrowings']:,} (리스 주석 값 포함, 재무상태표에 리스부채 행 없음)"),
    chk(no, "비용의 성격별 분류 / 영업에서 창출된 현금", f"감가상각비 {x['N']['dep']:,}", f"사용권자산상각비 {x['N']['rou']:,}", f"무형자산상각비 {x['amort']:,}", f"영업이익 {x['oi']:,}"),
    chk(no, "금융비용 표 / 현금흐름 조정 표", f"이자비용 {x['interest']:,} (두 표 일치)"),
    chk(no, "회계감사인의 명칭 및 감사의견", "당기 적정의견"),
], [f"순차입금/EBITDA {x['nd_ebitda']}는 음수 그대로 출력한다"])

# ---- F-OFS ----
g, x = C["F-OFS"][1], B["F-OFS"]
no = x["fs_rcept_no"]
case("financial_health", "F-OFS_1", "F-OFS", "1", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "period": "2025FY", "fs_rcept_no": no, "fin.fs_basis": "OFS", "basis_note": "별도 기준", "separate_only_check": {"no_subsidiary_sentence": True, "consolidated_statements_in_zip": False}, "note_sources": x["sources"],
    "cash_krw": x["cash"], "short_term": "missing (단기금융상품 행 없고 기타유동금융자산 행만 있음)", "total_borrowings_krw": x["total_borrowings"], "lease_source": x["lease_src"], "lease_match": "주석 합계 2,454,602,303 = 재무상태표 유동+비유동 (원 단위)", "fin.net_debt": "missing", "fin.net_debt_to_ebitda": "missing",
    "operating_income_krw": x["oi"], "depreciation_krw": x["dep"], "amortization_krw": x["amort"], "fin.ebitda_krw": x["ebitda"], "fin.ebitda_margin_pct": x["margin"], "fin.debt_ratio_pct": x["debt_ratio"], "fin.ebitda_interest_coverage": "missing", "interest_note": f"이자비용 확인 불가: {x['interest_why']}", "fin.audit_opinion": x["audit"],
}, [
    chk(no, "I. 회사의 개요 / III. 2. 연결재무제표", "'연결대상 종속회사 현황(요약) : 해당사항 없음'", "연결재무제표 절에 표 없음. 원문 문구 '하당사항이 없습니다'(원문 오타)", "ZIP에 사업보고서·감사보고서만 있음"),
    chk(no, "재무제표 주석 34 금융수익과 금융비용", "금융원가 361,906,280 = 외환차손 340,461,353 + 외화환산손실 21,444,927", "이자비용 행이 없는지 (차입금 562.65억이 있는데도)"),
    chk(no, "비용의 성격별 분류 / 별도 감사보고서 첨부 현금흐름표", f"감가상각비와 상각비 합산 {x['N']['combined']:,}", f"감가상각비 {x['dep']:,}", f"무형자산상각비 {x['amort']:,}"),
    chk(no, "재무상태표 / 리스 주석", f"현금 {x['cash']:,}", "유동 리스부채 1,103,424,798 + 비유동 1,351,177,505 = 주석 합계 2,454,602,303", "단기차입금 12,000,000,000, 유동성장기차입금 21,500,000,000, 장기차입금 22,765,000,000", f"영업이익 {x['oi']:,}"),
    chk(no, "회계감사인의 명칭 및 감사의견", "당기 적정의견"),
], [
    "주석에 리스부채 합계만 있어 재무상태표 합과 원 단위로 대조한다 (재무 v0.16 9.1, 2026-11-05 결정)",
    "총차입금은 산출되지만 단기금융상품이 missing이라 순차입금은 missing이다",
    "후보 3곳 모두 separate_only=True",
    "이자비용 행이 없고 차입원가 주석에 '자본화된 차입원가 1,318,999,923'이 있다 (재무 9.1a)",
    "연결재무제표 절 문구는 판정에 쓰지 않는다. 원문 오타가 있어도 separate_only는 True다",
])

# ---- F-NOINTEREST ----
g, x = C["interest_missing_real"][0], B["F-OFS"]
no = x["fs_rcept_no"]
case("financial_health", "F-NOINTEREST_1", "F-NOINTEREST", "1", g, {"mode": "single", "company": g["corp_code"], "as_of": AS}, {
    "period": "2025FY", "fs_rcept_no": no, "fin.fs_basis": "OFS", "fin.ebitda_krw": x["ebitda"], "fin.ebitda_interest_coverage": "missing", "interest_note": f"이자비용 확인 불가: {x['interest_why']}", "total_borrowings_krw": x["total_borrowings"], "must_not_use": ["금융비용 합계", "이자의 지급", "리스부채에 대한 이자비용", "0"],
}, [
    chk(no, "재무제표 주석 34 금융수익과 금융비용", "금융원가 361,906,280 = 외환차손 340,461,353 + 외화환산손실 21,444,927", "이자비용 행 없음"),
    chk(no, "차입원가 주석 / 현금흐름표", "자본화된 차입원가 1,318,999,923", "이자의 지급 1,214,811,511"),
    chk(no, "재무상태표", "단기차입금 12,000,000,000, 유동성장기차입금 21,500,000,000, 장기차입금 22,765,000,000", "유동 리스부채 1,103,424,798 + 비유동 1,351,177,505 = 2,454,602,303"),
    chk(no, "손익계산서 / 비용의 성격별 분류 / 첨부 현금흐름표", f"영업이익 {x['oi']:,}", f"감가상각비 {x['dep']:,}", f"무형자산상각비 {x['amort']:,}"),
], [
    "F-OFS_1과 같은 공시다. 디어유는 2026-11-05 정정으로 이자비용 2.01억을 채택하게 되어 이 유형에서 뺐다",
    "미검수 참고: 리스 주석에 '리스부채에 대한 이자비용 89,573,106'이 있으나 금융원가 표에는 없다. 이 값으로 채우지 않는다",
])

# ---- 정정 전 시점 ----
x = B["F-CORRECTED"]
corp = {"corp_code": x["corp_code"], "corp_name": json.loads((G / "financial_health/F-FULLIMPAIR_KOSPI.json").read_text(encoding="utf-8"))["corp_name"]}
case("financial_health", "F-CORRECTED_KOSPI", "F-CORRECTED", "KOSPI", corp, {"mode": "single", "company": x["corp_code"], "as_of": "2026-04-08"}, {
    "report_selected": {"rcept_no": x["original"], "rcept_dt": "20260407"}, "api_response_rcept_no": x["correction"], "api_rcept_in_asof_list": False,
    "fin.audit_opinion": "unknown", "audit_note": "정정 전 원본 값 확인 불가", "metrics_2025FY_data_status": "unknown", "metrics_note": "정정 전 원본 값 확인 불가", "must_not_output_values": ["적정의견"],
    "human_reference": {"audit_opinion": "의견거절", "source_rcept_no": x["original"], "note": "사람 기준 정답. 시스템 기대값이 아니다. document.xml 원본 읽기는 Phase 2로 유지(재무 9.2)"},
    "must_not_have_after": "2026-04-08",
}, [
    chk(x["original"], "2025 사업보고서 원본, 독립된 감사인의 감사보고서", "감사의견 '의견거절'", "접수일 2026-04-07"),
    chk(x["correction"], "2025 사업보고서 정정본", "접수일 2026-09-01", "정정사유 2025사업년도 재감사", "API 감사의견 '적정의견' (as_of 시점에는 알 수 없는 값)"),
], ["F-FULLIMPAIR_KOSPI는 as_of를 정정 다음 날로 두어 같은 회사의 정정 후 값을 시험한다. 이 케이스는 정정 전 시점을 시험한다"])

# ---- 검토표 ----
lines = ["# 2단계 셋째 묶음 검토표\n", "값은 코드가 읽은 값이다. [x]는 AI 검수 일치(사람 확인 아님), [ ]는 미검수다. 검수 문구에 명시되지 않은 값은 [ ]로 두었다. 상세는 `_review_batch1_검수결과.md` 셋째 묶음 절.\n"]
for d in docs:
    lines.append(f"\n## {d['case_type']} — {d['corp_name']} ({d['sample']}) — {d['status']}\n- 파일: `{'overseas_funding' if d['case_type'].startswith('G-') else 'financial_health'}/{d['case_type']}_{d['sample']}.json`\n- as_of: {d['request'].get('as_of') or d['request'].get('as_of_sequence')}\n")
    for c in d["check_list"]:
        lines.append(f"- [{c['where']}]({c['url']})\n" + "".join(f"  - [{'x' if s == 'ai_verified' else ' '}] {v}{' (API 응답 대조)' if m == 'api_response' else ''}\n" for v, s, m in zip(c["values"], c["value_status"], c.get("verification_method", [None] * len(c["values"])))))
    if d["open_notes"]:
        lines.append("- 참고\n" + "".join(f"  - {n}\n" for n in d["open_notes"]))
(G / "_review_batch3.md").write_text("".join(lines), encoding="utf-8")

# ---- 원문 캐시 확인 ----
nos = sorted({c["rcept_no"] for d in docs for c in d["check_list"]})
missing = [n for n in nos if not (ROOT / "data/cache/dart" / hashlib.sha1(f"document.xml?rcept_no={n}".encode()).hexdigest()).exists()]
print("초안", len(docs), [d["case_type"] + "_" + d["sample"] for d in docs])
print("확인 공시", len(nos), "캐시 없음", missing)
