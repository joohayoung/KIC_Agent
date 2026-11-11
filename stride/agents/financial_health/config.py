"""재무 건전성 설정값 (개발문서 9장)."""
AGENT_KEY = "financial_health"
AGENT_VERSION = "0.22"

# 9.1 계정 허용목록: key → (sj_div, account_id들)
ACCOUNTS = {
    "cash": (("BS",), ("ifrs-full_CashAndCashEquivalents",)),
    "st_fin_assets": (("BS",), ("ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents",)),
    "total_assets": (("BS",), ("ifrs-full_Assets",)),
    "total_liabilities": (("BS",), ("ifrs-full_Liabilities",)),
    "total_equity": (("BS",), ("ifrs-full_Equity",)),
    "equity_parent": (("BS",), ("ifrs-full_EquityAttributableToOwnersOfParent",)),
    "capital_stock": (("BS",), ("ifrs-full_IssuedCapital",)),
    "current_assets": (("BS",), ("ifrs-full_CurrentAssets",)),
    "current_liabilities": (("BS",), ("ifrs-full_CurrentLiabilities",)),
    "retained_earnings": (("BS",), ("ifrs-full_RetainedEarnings",)),
    "revenue": (("IS", "CIS"), ("ifrs-full_Revenue",)),
    "operating_income": (("IS", "CIS"), ("dart_OperatingIncomeLoss",)),
    "net_income_parent": (("IS", "CIS"), ("ifrs-full_ProfitLossAttributableToOwnersOfParent",)),
    "op_cash_flow": (("CF",), ("ifrs-full_CashFlowsFromUsedInOperatingActivities",)),
    "capex": (("CF",), ("ifrs-full_PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities",)),
}
# 9.2 (2026-11-05 실측). 부적정은 미확인이라 비워 둔다
AUDIT_OPINION_MAP = {"적정": ["적정의견", "적정", "의견적정"], "한정": ["한정의견", "한정"], "부적정": [], "의견거절": ["의견거절", "거절"]}
# 9.3 정규화 이름 완전 일치
RESTRUCTURING_PATTERNS = {
    "회생절차": ["회생절차개시신청", "회생절차개시결정", "회생계획인가"],
    "워크아웃": ["채권은행등의관리절차개시신청", "채권은행등의관리절차개시"],
    "파산": ["파산신청", "파산선고"],
    "종결": ["회생절차종결결정", "회생절차폐지결정", "회생절차개시신청기각", "파산신청기각", "채권은행등의관리절차해제", "채권은행등의관리절차중단"],
}
RESTRUCTURING_MONTHS = 24     # 3.3
LOOKBACK_YEARS = 4            # 8장 collect_financials
ANNUAL_YEARS = 3              # 3.1
BS_TOLERANCE_KRW = 1_000      # 보정 전: 원 단위 공시와 천원 단위 공시의 반올림 차이. 표본 합계 검증으로 정한다
EQUITY_ALERT_KRW = 1_000_000_000      # 한국거래소 KIND 코스닥 공시가이드(2026.2.2) 자기자본 10억 원 (13.2 F-KOSDAQ-EQ)
IMPAIRMENT_ALERTS = (50, 100)         # 8장 update_state impairment_crossed_50, _100
ALERT_TYPES = ["audit_opinion_changed", "impairment_crossed_50", "impairment_crossed_100", "equity_below_1bn", "restructuring_filed", "market_data_missing"]
DUE_DILIGENCE = ["fin.debt_maturity_profile", "fin.going_concern_note", "fin.credit_rating"]
MARKET_METRICS = ["fin.market_cap", "fin.net_debt_to_ev", "fin.per", "fin.pbr", "fin.ev_to_ebitda"]
