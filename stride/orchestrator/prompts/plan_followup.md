## 작업
탐색 결과가 0건이거나 확인 불가가 많습니다. 조건을 완화하거나 기간을 늘리는 제안을 최대 2개 만드세요. 실행하지 않습니다. 제안할 것이 없으면 action "none"을 하나 내세요.

## 선택지
- suggest_relax: field에 완화할 조건 이름 (예: min_funding_gap_ratio, target_regions)
- suggest_extend_lookback: 조회 기간 늘리기
- none

## 자료
<자료>
단계별 기업 수: {funnel}
제외 사유 분포: {reasons}
</자료>

## 출력 형식 (JSON)
{"suggestions": [{"action": "...", "field": null, "reason": "300자 이내", "evidence_ids": []}]}
