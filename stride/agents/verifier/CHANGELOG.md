# 검증 에이전트 CHANGELOG

기준 개발문서: `에이전트_개발문서/검증_에이전트_개발문서.md` v0.1

## 1~4단계 (2026-11-09) — **1~4단계 완료 기준 통과, 5단계는 오케스트레이터 시험으로 확인**

- 1단계 캐시 키: 공통 클라이언트 `get_json`(엔드포인트+파라미터 sha1)을 그대로 쓴다. FIN 근거는 근거 제목 `(YYYY.MM)`으로 보고서 코드를 정해 같은 파라미터로 재조회한다 (자체 결정 S6, 12월 결산 기준)
- 2단계 results 모드 R-01~R-07, 3단계 answer 모드 A-01·A-02·A-04, 4단계 A-03 (`prompts/check_claim.md`, 개발문서 11.1 원문)
- 단위: `tests/unit/verifier/test_verifier.py` 18개 (13장 단위 항목 전부)
- 골든: `tests/golden/test_verifier_golden.py` V-CLEAN(실제 해외진출·재무 결과, 실패 0건), V-TAMPER(숫자·날짜·각주 1개씩 변조 → 정확히 3건 실패) 통과
- 5단계: 오케스트레이터 review 통합 시험(검증 실패 주입 → 1회 재작성 → '검증 실패' 표시) 통과
- 자체 결정: S3(VALUE_TOLERANCE 0), S4(노드 한 파일), S5(answer 모드 입력 형식), S6·S7(재조회 범위), S8(R-04 같은 기간), S9(V-CLEAN 커버리지)
