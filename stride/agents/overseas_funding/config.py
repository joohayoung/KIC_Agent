"""해외진출 설정값 (개발문서 8장)."""
AGENT_KEY = "overseas_funding"
AGENT_VERSION = "0.22"
# 8.1.4 국적 칸 표기 통일. 실측 표기만 넣는다 (api_fields.md 4장, 21장)
COUNTRY_ALIASES = {"USA": "미국", "U.S.A": "미국", "US": "미국", "United States": "미국", "Vietnam": "베트남", "Indonesia": "인도네시아", "China": "중국", "Canada": "캐나다", "Poland": "폴란드", "Singapore": "싱가포르", "Cayman Islands": "케이만", "Republic of Korea": "대한민국", "Korea": "대한민국"}
# 7.6 기사 검색
NEWS_KEYWORDS = ["해외 공장", "해외 법인", "인수", "지분 투자", "현지 생산", "증설", "합작"]
NEWS_ACTIONS = ["공장", "증설", "인수", "지분", "합작", "법인"]     # 10.9 행위
NEWS_MAX_ITEMS = 40
NEWS_TITLE_SIMILARITY = 0.85
NEWS_RECENT_DAYS = 30
CLASSIFY_BATCH_MAX_CHARS = 40_000      # 7.5 보정 전
FUNDING_EXCERPT_CHARS = 3_000
ALERT_EXCERPT_CHARS = 2_000
PROJECT_WINDOW_DAYS = 548      # 7.8 18개월
CONFLICT_RATIO = 0.20          # 7.8 5
MAX_CONFLICTS_PER_RUN = 2      # 7.8a
VERIFY_AMOUNT_TOLERANCE = 0.005      # 7.11 C3
# 7.12. 원문에 임계값이 없어 부호 변화만 기준 (2026-11-09 결정 D7). None을 유지한다
ALERT_CONFIG = {"gap_change_ratio": None}
# 5.5 BatchGraph
BATCH_MAX_COMPANIES = 30       # 5.5 PoC 상한
LLM_CONCURRENCY = 1            # 동시 실행 기업 수. 처리량 실측(호출규칙 4장) 전까지 순차
SCREEN_SUB_KINDS = ("acquisition_stock", "new_facility", "acquisition_asset", "business_transfer")      # 해외 여부를 칸이나 기업 실행으로 확인할 수 있는 결정 공시
# 7.9 거래 상태 경고 (v0.21 채택). 시작 패턴, 끝 패턴. 공시 이름(공백 제거) 기준
TRADING_PATTERNS = {"halted": (r"매매거래정지|매매정지", r"정지해제|거래재개"), "management_item": (r"관리종목지정(?!우려)", r"관리종목(?:지정)?해제"), "delisting_review": (r"상장적격성실질심사|상장폐지|개선기간", r"상장유지|사유해소|실질심사.*(?:해당없음|비해당)")}
TRADING_TECHNICAL = r"병합|분할|무상증자|감자|자본감소|전자등록|변경상장|중요내용공시"      # 사유가 주식 사무인 단기 정지
KOREA_NAMES = ("대한민국", "대힌민국", "한국", "Korea", "KOREA", "Republic of Korea")     # 8.1.4 국적 칸 실측 표기 (api_fields.md 4장)
