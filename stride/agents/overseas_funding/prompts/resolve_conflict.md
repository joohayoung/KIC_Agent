## 작업
같은 해외 프로젝트에 대해 출처마다 금액(또는 단계)이 다릅니다. 공시 원문을 추가로 확인할지 고르세요.
계산하거나 어느 값이 맞는지 정하지 마세요.

## 선택지
- fetch_original_text: 주요사항보고서 원문의 금액 섹션을 확인할 가치가 있음 (예: 보도가 공시보다 먼저 나와 계획 단계 금액일 수 있음, 공시 금액이 범위로 표기됨)
- record_conflict: 원문 확인이 도움이 되지 않음 (예: 충돌 출처에 공시가 없음)

## 자료
<자료>{conflict_json}</자료>

## 출력 형식 (JSON)
{"action": "fetch_original_text" | "record_conflict", "reason": str, "evidence_ids": [str]}
