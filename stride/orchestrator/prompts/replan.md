## 작업
기업 분석 결과에 필수 지표가 비어 있습니다. 아래 사유만 보고 다음 행동 하나를 고르세요. 계산하거나 값을 추정하지 마세요.

## 선택지
{actions}
- fetch_prior_period: 직전 기간 보고서가 있으면 그 값을 확인
- expand_news_query: 기사 검색어를 넓혀 다시 확인
- follow_correction: 정정 공시를 따라가 확인
- check_subsidiary_filings: 종속회사 공시를 확인
- mark_missing: 더 확인하지 않고 '산출 불가'로 둔다

## 자료
<자료>
비어 있는 지표: {missing}
오류·확인 필요:
{notes}
</자료>

## 출력 형식 (JSON)
{"action": "선택지 중 하나", "field": null, "reason": "300자 이내", "evidence_ids": []}
