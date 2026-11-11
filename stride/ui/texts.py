"""고정 문구 (화면_데이터_연결명세 1.1, 2.3, 3.4)."""
USAGE_CHIPS = [
    ("🔎 조건으로 기업 찾기", "미국에 공장을 짓는 코스닥 제조업 찾아줘"),
    ("🏢 기업 검토", "OO 검토해줘"),
    ("❓ 결과 질문", "OO 유동성 원천과 소요는 어떻게 계산됐어?"),
    ("⚡ 표 필터", "원천÷소요 1배 미만만"),
]
DEFAULT_SEARCH_TEXT = ("최근 12개월 안에 해외 성장 투자가 공시·보도로 확인되고(범위 조건 G1~G4), 그 프로젝트에 취득·투자 결정 공시(S4) 또는 해외 용도 자금 조달 공시(S5)가 있는 상장사입니다. "
                       "유동성 원천·소요, 차입 여력, 재무 위험은 거르는 조건이 아니라 표에 보여 주는 값이며, 값이 없어도 제외하지 않습니다.")
FOOTER = "공시로 확인되는 항목만 반영(은행 약정 한도·회사 전망치 미포함)"
LIQUIDITY_NOTE = "원천 ÷ 소요 (S&P Liquidity Descriptors 준용, STRIDE 정의). 원천 = 현금 + 단기금융상품 + TTM 영업현금흐름 + 확정 해외 조달, 소요 = 24개월 내 해외 투자액 + 1년 내 만기 차입금 + 직전 사업연도 배당금. 1배 선만 표시하고 구간·등급은 두지 않음"
ALERT_LABELS = {
    "new_signal": "새 신호", "stage_up": "단계 상승", "stage_down": "단계 하락", "new_funding": "자금 조달 공시", "plan_changed": "일정·계획 변경", "gap_changed": "자금 공백 변경", "cancelled": "취소",
    "audit_opinion_changed": "감사의견 변경", "impairment_crossed_50": "자본잠식률 50% 도달", "impairment_crossed_100": "자본전액잠식", "equity_below_1bn": "자기자본 10억 원 미만", "restructuring_filed": "회생·워크아웃 관련 공시", "market_data_missing": "시장 데이터 없음",
    "new_match": "신규 매칭", "left_match": "조건 이탈", "amount_changed": "금액 변경",
}
SIGNAL_LABELS = {"S1_plan": "S1 정기보고서 계획", "S2_progress": "S2 보도", "S4_confirmed": "S4 취득·투자 결정", "S5_funding": "S5 해외 용도 조달", "S6_alert": "S6 정정·철회"}
METHOD_LABELS = {"new_plant": "신설", "expansion": "증설", "new_subsidiary": "법인 설립", "acquisition": "인수", "equity_investment": "지분 출자", "jv": "합작", "other": "기타"}
SOURCE_LABELS = {"major_event": "공시", "periodic": "공시", "news": "보도", "missing": "출처 없음"}
VERIFICATION_LABELS = {"verified": "확인됨", "needs_check": "확인 필요", "partial": "부분 결과"}
MARKET_LABELS = {"KOSPI": "코스피", "KOSDAQ": "코스닥"}
PROGRESS_STEPS = {"universe": "상장사", "events": "해외 관련 공시", "prefilter": "1차 조건 충족", "deep": "상세 분석", "final": "최종 조건 충족"}
CRITERIA_LABELS = {"markets": "시장", "industries": "업종", "target_regions": "지역", "investment_types": "방식", "stages": "진행 단계", "min_investment_amount": "최소 해외 투자액", "min_funding_gap_ratio": "자금 공백 비율 >",
                   "market_cap_range": "시가총액 범위", "exclude_rule_ids": "상장 규정 기준 해당 제외", "signal_types": "신호 종류", "lookback_months": "기간(개월)", "max_deep_analysis": "상세 분석 최대 기업 수"}
