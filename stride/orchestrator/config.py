"""오케스트레이터 설정 (오케스트레이터 개발문서 3.1, 7장). 출처 없는 기준값을 두지 않는다."""
STAGE_LABELS = {1: "검토·언급", 2: "계획 발표", 3: "MOU·협약", 4: "이사회 결의", 5: "착공·인수 완료"}
# 지역 키 → 국가명(해외진출 config.COUNTRY_ALIASES로 통일된 한글 이름). STRIDE 정의 묶음이다 (화면 명세 3.5: 미국, EU, 아시아 기타)
REGION_MAP = {
    "US": ["미국"], "NA": ["미국", "캐나다", "멕시코"],
    "EU": ["독일", "프랑스", "폴란드", "헝가리", "스페인", "이탈리아", "네덜란드", "체코", "슬로바키아", "룩셈부르크", "벨기에", "오스트리아", "스웨덴", "핀란드", "덴마크", "포르투갈", "루마니아", "아일랜드"],
    "SEA": ["베트남", "인도네시아", "태국", "말레이시아", "필리핀", "싱가포르", "캄보디아", "미얀마", "라오스"],
    "CN": ["중국", "홍콩", "대만"], "JP": ["일본"], "IN": ["인도"],
}
REGION_LABELS = {"US": "미국", "NA": "북미", "EU": "EU", "SEA": "동남아", "CN": "중화권", "JP": "일본", "IN": "인도"}
# DiscoveryCriteria.investment_types → 해외진출 method
INVESTMENT_TYPE_MAP = {"신설": ["new_plant", "new_subsidiary"], "증설": ["expansion"], "지분 인수": ["acquisition", "equity_investment", "jv"]}
REQUIRED_METRICS = ["ovs.in_scope", "ovs.project_stage", "ovs.overseas_investment_amount", "ovs.liquidity_sources_to_uses", "fin.debt_ratio", "fin.ttm_operating_cash_flow", "fin.capital_impairment_ratio", "fin.equity_ex_nci", "fin.audit_opinion"]
OPTIONAL_METRICS = ["fin.net_debt", "fin.total_borrowings", "fin.ebitda", "fin.net_debt_to_ebitda", "fin.ebitda_margin"]
INSTANT_FILTER_FIELDS = {"investment_amount": "해외 투자액", "liquidity_ratio": "원천÷소요 (배)", "liquidity_surplus": "원천−소요", "debt_ratio": "부채비율 (%)", "funding_gap": "자금 공백", "funding_gap_ratio": "자금 공백 비율", "stage": "진행 단계", "rule_hit": "제외 기준 해당", "verification": "검증 상태"}
D1_ACTIONS = ("fetch_prior_period", "expand_news_query", "follow_correction", "check_subsidiary_filings", "mark_missing")
D4_ACTIONS = ("suggest_relax", "suggest_extend_lookback", "none")
# 7.7 1일 2회. 시각은 문서에 없다 (자체 결정 2026-11-09). 작업 스케줄러 등록 값과 화면 '다음 업데이트' 표시에만 쓴다
MONITOR_TIMES = ["08:30", "18:30"]
# 4.2 route_by_event 규칙표 (구성문서 4.2). 정규화 공시 이름 시작 → 호출 에이전트
ROUTE_BY_EVENT = [
    (("타법인주식및출자증권취득결정", "신규시설투자등", "유형자산취득결정", "영업취득결정"), ("overseas_funding",)),
    (("유상증자결정", "전환사채권발행결정", "신주인수권부사채권발행결정"), ("overseas_funding", "financial_health")),
    (("사업보고서", "반기보고서", "분기보고서"), ("overseas_funding", "financial_health")),
    (("감사보고서제출", "주권매매거래정지", "기타시장안내", "내부결산시점관리종목지정", "상장폐지결정"), ("financial_health",)),
]
CORRECTION_AGENTS = ("overseas_funding",)      # 기재정정, 투자 연기·철회 관련
MONITOR_MAX_COMPANIES = 20     # 감시 1회 재분석 상한. 탐색 K(구성문서 4.0 max_deep_analysis 20)와 같은 값. 첫 감시는 first_run_max_deep_analysis(5)
