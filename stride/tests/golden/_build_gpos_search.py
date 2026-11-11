"""[1회용, 다시 실행하지 않는다. 2026-11-09 검수 상태를 정답지에 직접 반영했다] 2026-11-06 결정의 G-POS 주 후보 재탐색 결과 → overseas_funding/G-POS_주.json 초안, _review_gpos_search.md.

값은 코드가 읽은 값이다. 전부 draft이며 사람 검수 전이다. 탐색: scripts/probe_search_gpos.py, data/probe/gpos_search.json
"""
import json
from pathlib import Path

G = Path(__file__).parent
URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={}"
AS = "2026-11-05"


def chk(no, where, *values):
    return {"rcept_no": no, "url": URL.format(no), "where": where, "values": list(values), "value_status": ["draft"] * len(values), "status": "draft"}


ACQ, OTHER, OLD, OLD_CORR, BASE, FY = "20260917900571", "20260917900593", "20251001900692", "20260911900290", "20260814000910", "20260323001100"
inv, cash, st, cum, prev, fy = 14_766_693_600, 431_280_512, 13_726_436_365, -350_891_328, -518_878_737, -381_834_943
ttm = cum + fy - prev
assert ttm == -213_847_534
avail, gap = cash + st + ttm, inv - (cash + st + ttm)
assert gap == 822_824_257 and inv > cash + st
doc = {
    "case_type": "G-POS", "sample": "주", "corp_code": "00367400", "corp_name": "모티브링크", "status": "draft", "request": {"mode": "single", "company": "00367400", "as_of": AS},
    "verified_by": None, "verified_at": None, "human_verified": {"verified": False, "by": None, "at": None},
    "expect": {
        "in_scope": True, "signal_status": "해외 투자 확정",
        "must_have_signals": [
            {"signal_type": "S4_confirmed", "rcept_no": ACQ, "is_overseas": True, "purpose_category": "growth_investment", "target_country": "인도", "overseas_amount_krw": inv},
            {"signal_type": "S4_confirmed", "rcept_no": OTHER, "is_overseas": True, "target_country": "인도", "overseas_amount_krw": 8_548_454_250},
        ],
        "no_signal": [], "open_questions": [], "financial_base": {"rcept_no": BASE, "period": "2026H1"}, "cash_krw": cash, "short_term_krw": st, "ttm_ocf_krw": ttm,
        "confirmed_funding_krw": 0, "unconfirmed_funding_krw": 0, "available_funds_krw": avail, "overseas_investment_krw": inv, "funding_gap_krw": gap, "funding_gap_ratio": round(gap / inv, 4), "funding_gap_sign": "positive",
        "investment_notes": [{"rcept_no": ACQ, "excluded": False, "scheduled_date": "2027-12-31", "note": "연결 내부 출자, 집행 시점 확인 불가"}], "must_not_have_after": AS,
    },
    "check_list": [
        chk(ACQ, "타법인 취득결정 (대표 프로젝트)", "MOTILINK INDIA PRIVATE LIMITED, 회사와 관계 종속회사", "취득금액 14,766,693,600 (USD 10,792,000)", "취득목적 '인도시장 사업확장 및 운영자금 확보', 현금출자, 지분 99.99%", "상대방 표 국적 인도 (회사명 칸에는 국적 없음)", "취득예정일자 2027-12-31, 이사회 2026-09-17"),
        chk(OTHER, "타법인 취득결정 (같은 날 다른 인도 법인)", "DNM AUTOPOWER PRIVATE LIMITED, 종속회사", "취득금액 8,548,454,250", "취득목적 '인도시장 공급망 확대 및 해외사업 진출'"),
        chk(OLD, "타법인 취득결정 원공시 (베트남)", "LONG BINH ELECTRONICS CO.,LTD., 취득금액 4,209,600,000"),
        chk(OLD_CORR, "같은 공시 정정", "취득금액 2,245,120,000으로 축소, 취득예정일자 2027-09-30", "정정사유 '투자계획 변경'"),
        chk(BASE, "2026 반기보고서 연결", f"현금및현금성자산 {cash:,}", f"단기금융상품 {st:,}", f"반기 누적 영업현금흐름 {cum:,}, 전년 동기 {prev:,}"),
        chk(FY, "2025 사업보고서 연결 현금흐름표", f"연간 영업현금흐름 {fy:,} (TTM {ttm:,} 계산 입력)"),
        chk("20260702900639", "최대주주 변경 계약", "양수인 동양이엔피 주식회사, 43.41%"),
    ],
    "open_notes": [
        "조건 (a) 거래 가능: 2024-05~2026-11-05 공시 목록에 거래정지·관리종목·상장폐지·실질심사 공시 없음. (b) 투자액 147.67억 > 현금+단기금융상품 141.58억. (c) 공백 +8.23억",
        "공백이 작다 (비율 0.0557). 같은 날 인도 법인 2건은 회사명이 달라 별도 프로젝트라 합산하지 않는다 (7.8). 합치면 232.15억이지만 대표 금액은 큰 쪽 1건이다",
        "취득목적에 운영자금 확보가 함께 있다. 같은 날 종속회사 증자 공시가 없어 칸 분할 대상이 아니고 전액이 투자액이다. 칸 구분이 없어 나눌 근거가 없다",
        "2026-07 최대주주 변경 계약이 있다. 해외 투자 판정과 직접 관련은 없다",
    ],
}
(G / "overseas_funding/G-POS_주.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
rows = json.loads((G.parents[2] / "data/probe/gpos_search.json").read_text(encoding="utf-8"))
L = ["# G-POS 주 후보 재탐색 검토표 (2026-11-07)", "", "조건: (a) 거래 가능 (b) 해외 투자액 > 현금 + 단기금융상품 (c) 자금 공백 > 0", "",
     f"탐색 범위: 2025-11-05~2026-11-05 거래소 양식 타법인 취득 공시, 해외 대상 {len(rows)}개사. 값은 LLM 없는 경로 실행값이다. **신규시설투자·유형자산 공시는 국적 칸이 없어 범위 밖이다.** 합산 라벨이 없어 같은 대상 여러 건은 최신 1건 기준이다.", "",
     "| 기업 | 투자액(억) | 현금+단기(억) | TTM(억) | 공백(억) | (a) 거래 공시 | 대상 / 목적 | 판단 |", "|---|---|---|---|---|---|---|---|"]
WHY = {"00367400": "**채택**: 인도 현지 법인 사업 확장", "01596425": "제외: 자회사 대상 대규모 구조 거래", "01412822": "제외: 풋옵션 이행 취득", "00961774": "제외: 취득목적 '재무구조 개선'", "01227039": "제외: (a) 상장폐지 진행, 정지"}
for x in sorted((r for r in rows if r.get("cond_b") and r.get("cond_c")), key=lambda r: r["corp_code"] != "00367400"):
    f = x["forms"][-1]
    L.append(f"| {x['corp_name']} | {x['inv'] / 1e8:,.1f} | {(x['cash'] + x['st']) / 1e8:,.1f} | {x['ttm'] / 1e8:,.1f} | {x['gap'] / 1e8:,.1f} | {'; '.join(x['trading'][-2:]) or '없음'} | {f['name']} / {f['purpose']} | {WHY.get(x['corp_code'], '')} |")
L += ["", "다른 후보 메모: 현대에이치티(베트남 신설 법인 120.1억)는 단기금융상품이 missing(기타유동금융자산 행만 있음)이라 공백을 계산할 수 없어 (c)를 확인하지 못했다. 제이앤티씨(베트남 4건 합 1,243.5억)는 합산 라벨이 있어야 공백이 양수가 되고 목적에 재무구조 개선이 섞여 있다.", "", "## 모티브링크 확인 항목", "", "| 공시 | 위치 | 값 | 확인 |", "|---|---|---|---|"]
for c in doc["check_list"]:
    for v in c["values"]:
        L.append(f"| [{c['rcept_no']}]({c['url']}) | {c['where']} | {v} | ☐ |")
L += ["", "## 판단이 필요한 점", ""] + [f"- {n}" for n in doc["open_notes"]]
(G / "_review_gpos_search.md").write_text("\n".join(L) + "\n", encoding="utf-8")
