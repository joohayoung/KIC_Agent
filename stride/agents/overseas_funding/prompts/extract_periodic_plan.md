## 작업
{corp_name}의 {report_nm}(접수일 {rcept_dt}) 'II. 사업의 내용' 발췌에서
**해외 확장 계획**을 찾아 항목별로 추출하세요.

해외 확장 계획이란:
- 해외 공장·생산기지 신설 또는 증설
- 해외 법인 설립
- 해외 기업 인수 또는 지분 투자, 해외 합작법인 설립

해외 확장 계획이 아닌 것 (추출하지 않음):
- 수출 실적, 해외 매출 비중, 해외 영업망·판매 대리점 설명
- 이미 운영 중인 해외 공장의 현황 설명 (증설·신설 계획이 없는 경우)
- 국내 공장 증설
- "글로벌 경쟁력 강화" 처럼 대상 국가·방식이 없는 일반 표현

각 문단 앞에는 [p번호][NEW] 또는 [p번호][EXISTING] 표시가 있습니다.
NEW는 직전 보고서에 없던 문단입니다. 이 표시는 참고만 하고 그대로 출력에 옮기지 않습니다.

## 판단 기준
- stage: 1=검토·언급, 2=계획 공표(국가·규모·시기 중 2개 이상 구체적), 3=MOU·투자협약,
  4=이사회 결의, 5=착공·출자 완료. 문장에 근거가 없으면 1.
- amount_original: 문서에 적힌 금액 표기 그대로 (예: "약 1,000억원", "USD 300 million"). 없으면 null.
- target_country: 국가명(한글). 대륙만 있으면 "유럽", "북미" 처럼 적습니다.

{재추출_피드백}

## 자료
<자료>
{paragraphs}
</자료>

## 출력 형식 (JSON)
{
  "items": [
    {
      "paragraph_id": "p12",
      "quote": "자료 원문 그대로",
      "target_country": "<국가명>" | null,
      "method": "new_plant|expansion|new_subsidiary|acquisition|equity_investment|jv|other",
      "stage": 1-5,
      "amount_original": "<원문 금액 표기>" | null,
      "timeline": "2025년 완공 예정" | null,
      "summary": "한 문장 요약 (100자 이내)"
    }
  ],
  "no_plan_found": true | false
}
