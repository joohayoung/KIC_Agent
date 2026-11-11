"""[1회용, 다시 실행하지 않는다. 코맥스는 2026-11-06 결정으로 G-POS_HALTED로 옮겼다] 2026-11-06 결정: 구영테크를 G-POS_MIXED로 옮기고(투자액 시설 칸 기준 재계산), G-POS 주 후보를 코맥스 초안으로 교체 → tests/golden/_review_gpos_swap.md

값은 코드가 읽은 값이다. 코맥스 초안은 전부 draft이며 사람 검수 전이다.
"""
import json
from pathlib import Path

G = Path(__file__).parent / "overseas_funding"
OUT = Path(__file__).parent
URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
AS = "2026-11-05"


def chk(no, where, *values):
    return {"rcept_no": no, "url": URL.format(no), "where": where, "values": list(values), "value_status": ["draft"] * len(values), "status": "draft"}


# ---- 구영테크 → G-POS_MIXED ----
mixed_path, main_path = G / "G-POS_MIXED.json", G / "G-POS_주.json"
if not mixed_path.exists():
    m = json.loads(main_path.read_text(encoding="utf-8"))
    assert m["corp_name"] == "구영테크"
    e = m["expect"]
    fac, debt = 14_798_000_000, 14_798_000_000
    assert fac + debt == e["overseas_investment_krw"]
    gap = fac - e["available_funds_krw"]
    m["case_type"], m["sample"] = "G-POS_MIXED", "1"
    e["must_have_signals"] = [
        {"signal_type": "S4_confirmed", "rcept_no": "20260413900715", "is_overseas": True, "purpose_category": "growth_investment", "target_country": "미국", "overseas_amount_krw": fac},
        {"signal_type": "S4_confirmed", "rcept_no": "20260413900715", "signal_suffix": ":fdpp_dtrp", "is_overseas": True, "purpose_category": "refinancing", "target_country": "미국", "overseas_amount_krw": debt},
    ]
    e["open_questions"] = [f"종속회사 증자 채무상환 용도 {debt:,}: refinancing, 투자액에서 제외"]
    e.update(overseas_investment_krw=fac, funding_gap_krw=gap, funding_gap_ratio=round(gap / fac, 4), funding_gap_sign="negative_or_zero")
    m["open_notes"] = ["2026-11-06 결정: 성장 투자와 차입 상환이 섞인 출자 사례. 증자 공시 칸으로 나눠 시설 147.98억만 투자액, 채무상환 147.98억은 refinancing. 재계산 공백은 음수라 G-POS 주 후보에서 내렸다. 입력 값(check_list)은 그대로이고 검수 상태도 유지한다"] + [n for n in m["open_notes"] if not n.startswith(("결손 보전", "다만 절반"))] + ["결손 보전 여부: 두 공시와 반기보고서 어디에도 결손 보전 표현이 없다. CAR TECH 2025년 자본총계 69.3억 / 자본금 431.8억, 부채 2,350.4억"]
    mixed_path.write_text(json.dumps(m, ensure_ascii=False, indent=1), encoding="utf-8")

# ---- 코맥스 → G-POS_주 초안 ----
ACQ, BASE, FY = "20260828900607", "20260814004293", "20260320001378"
inv, cash, st, cum, prev, fy = 5_388_498_000, 5_787_907_490, 0, -18_822_993_944, -557_174_461, -4_143_227_279
ttm = cum + fy - prev
assert ttm == -22_409_046_762
avail, gap = cash + st + ttm, inv - (cash + st + ttm)
doc = {
    "case_type": "G-POS", "sample": "주", "corp_code": "00268118", "corp_name": "코맥스", "status": "draft", "request": {"mode": "single", "company": "00268118", "as_of": AS},
    "verified_by": None, "verified_at": None, "human_verified": {"verified": False, "by": None, "at": None},
    "expect": {
        "in_scope": True, "signal_status": "해외 투자 확정",
        "must_have_signals": [{"signal_type": "S4_confirmed", "rcept_no": ACQ, "is_overseas": True, "purpose_category": "growth_investment", "target_country": "캐나다", "overseas_amount_krw": inv}],
        "no_signal": [{"rcept_no": "20260428000673", "rule": "회사합병결정은 8.1.4 DS005 대상 아님"}],
        "funding_notes": [{"rcept_no": "20260128000145", "first_rcept_no": "20251216000526", "amount_krw": 19_999_999_791, "final": "확정·현금 반영", "pay": "2026-02-05", "purpose_category": "working_capital", "rule": "R3 운영자금뿐, 재무 기준일 이전 납입"}],
        "open_questions": [],
        "financial_base": {"rcept_no": BASE, "period": "2026H1"}, "cash_krw": cash, "short_term_krw": st, "ttm_ocf_krw": ttm,
        "confirmed_funding_krw": 0, "unconfirmed_funding_krw": 0, "available_funds_krw": avail, "overseas_investment_krw": inv, "funding_gap_krw": gap, "funding_gap_ratio": round(gap / inv, 4), "funding_gap_sign": "positive",
        "investment_notes": [{"rcept_no": ACQ, "excluded": False, "scheduled_date": "2026-09-02", "note": "집행 예정일 2026-09-02, 완료 미확인"}],
        "must_not_have_after": AS,
    },
    "check_list": [
        chk(ACQ, "타법인 취득결정", "NaviComm Inc. (Canada), 회사와 관계 '관계회사'", "취득금액 5,388,498,000, 취득주식 5,400,000", "취득 후 지분 40%, 현금취득(신주취득)", "취득목적 '글로벌 판로 다각화', 주요사업 '전자제품 유통'", "취득예정일자 2026-09-02, 이사회 2026-08-28", "정정 공시 없음 (as_of까지)"),
        chk("20260128000145", "유상증자결정 정정본 (최초 20251216000526)", "운영자금 19,999,999,791, 다른 칸 전부 '-'", "제3자배정, 납입일 2026-02-05"),
        chk("20260205900843", "증권발행결과", "실제발행금액 19,999,999,791, 납입일 2026-02-05"),
        chk(BASE, "2026 반기보고서(기재정정) 연결", f"현금및현금성자산 {cash:,}", "단기금융상품 행 없음 → 0 (3장 규칙)", f"반기 누적 영업현금흐름 {cum:,}, 전년 동기 {prev:,}"),
        chk(FY, "2025 사업보고서 연결 현금흐름표", f"연간 영업현금흐름 {fy:,} (TTM {ttm:,} 계산 입력)"),
        chk("20260824900688", "주권매매거래정지 기간변경", "정지 시작 2024-03-21, 변경 사유 개선기간 부여", "변경 후 개선기간 종료('27.03.24) 후 상장폐지 여부 결정일까지"),
        chk("20260428000673", "회사합병결정", "상대 코맥스씨에스, 100% 자회사, 무증자 소규모합병", "합병기일 2026-07-01 (20260702000417), 재무 기준일 이후"),
    ],
    "open_notes": [
        f"자금 공백 {gap / 1e8:.1f}억 중 투자액은 53.9억이고 나머지는 TTM 영업현금흐름 {ttm / 1e8:.1f}억에서 온다. 공백 비율이 {gap / inv:.2f}로 1을 넘는다",
        "2026 상반기 영업현금흐름 -188.2억은 전년 동기 -5.6억과 차이가 크다. 원인은 확인하지 않았다",
        "purpose_category growth_investment는 사람 확인이 필요하다. 근거: 신설 판매법인에 40% 출자, 취득목적 '글로벌 판로 다각화'. 공장 등 설비 투자는 아니다",
        "상대 NaviComm의 최대주주 Navien Canada, 회사 최대주주 경동나비엔이 관계회사로 기재되어 있고 '당사와 함께 출자 예정인 각 회사'가 있다. 계열 거래다",
        "주권매매거래정지 기간변경 공시(20260824900688): 정지 시작 2024-03-21, 변경 사유 개선기간 부여, 정지 기간 '개선기간 종료('27.03.24) 후 상장폐지 여부 결정일까지'. as_of에 거래정지·상장폐지 심사 중이라 주 후보로 적절한지 사용자 판단이 필요하다. 7.9 G1은 상장 여부만 본다",
        "반기보고서에 NaviComm 언급 없음 (재무 기준일 뒤 공시)",
    ],
}
main_path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

# ---- 검토표 ----
L = ["# G-POS 주 후보 교체 검토표 (2026-11-06)", "", "| 항목 | 구영테크 (재계산, G-POS_MIXED) | 코맥스 (새 주 후보 초안) |", "|---|---|---|"]
m = json.loads(mixed_path.read_text(encoding="utf-8"))["expect"]
e = doc["expect"]
for label, k in (("투자액", "overseas_investment_krw"), ("현금", "cash_krw"), ("단기금융상품", "short_term_krw"), ("TTM 영업현금흐름", "ttm_ocf_krw"), ("가용 자금", "available_funds_krw"), ("자금 공백", "funding_gap_krw")):
    L.append(f"| {label} | {m[k]:,} | {e[k]:,} |")
L.append(f"| 공백 비율 | {m['funding_gap_ratio']} | {e['funding_gap_ratio']} |")
L += ["", "구영테크 값의 검수 상태는 기존 그대로 ai_verified다. 코맥스 값은 전부 **draft**이며, 아래 표를 확인해 주세요.", "", "## 코맥스 확인 항목", "", "| 공시 | 위치 | 값 | 확인 |", "|---|---|---|---|"]
for c in doc["check_list"]:
    for v in c["values"]:
        L.append(f"| [{c['rcept_no']}]({c['url']}) | {c['where']} | {v} | ☐ |")
L += ["", "## 판단이 필요한 점", ""] + [f"- {n}" for n in doc["open_notes"]]
(OUT / "_review_gpos_swap.md").write_text("\n".join(L) + "\n", encoding="utf-8")
