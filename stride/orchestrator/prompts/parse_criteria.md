## 작업
사용자 문장을 기업 탐색 조건으로 바꾸세요. 아래 허용 값만 쓰고, 수치 기준이 없는 표현(예: "성장성 좋은", "재무가 탄탄한")은 조건에 넣지 말고 unparsed에 원문 그대로 넣으세요.

## 허용 값
- markets: KOSPI, KOSDAQ
- industries: 표준산업분류 코드 접두어 (예: "C" 제조업 전체, "C29"). 문장에 업종이 없으면 빈 목록
- target_regions: {regions}
- investment_types: 신설, 증설, 지분 인수
- stages: 1 검토·언급, 2 계획 발표, 3 MOU·협약, 4 이사회 결의, 5 착공·인수 완료
- min_investment_amount: 원 단위 정수 (예: 500억 → 50000000000)
- min_funding_gap_ratio: 소수 (예: 자금 공백 30% 초과 → 0.3, "자금 공백 있음" → 0.0)
- exclude_rule_ids: 상장 규정 기준 해당 기업을 빼 달라고 하면 R1-KS, R1b-KS, R2-KS, R3-KS, R1-KQ, R2-KQ, R3-KQ
- signal_types: 연기·철회 기업을 찾으면 ["S6_alert"]
- lookback_months: 문장에 기간이 있을 때만 (기본 12)

## 자료
<자료>
{text}
</자료>
