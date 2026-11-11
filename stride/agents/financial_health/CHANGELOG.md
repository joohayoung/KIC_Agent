# financial_health CHANGELOG

기준 개발문서: `MVP_1차/에이전트_개발문서/재무_건전성_에이전트_개발문서.md` v0.22

## 5단계 (2026-11-06) — 개발문서 v0.21 → v0.22. **완료 기준 통과**

- 완료 기준: 13.2 전 유형 골든 통과, 13.3 재생 통과 (감사의견 변경 경보가 접수 전날 없고 다음 날 처음 발생)
- 구조조정 정정 공시는 같은 사건으로 세지 않음. `AgentResult.extra.restructuring_events`

## 4단계 (2026-11-06) — 개발문서 v0.20 → v0.21. **완료 기준 통과**

- 완료 기준: F-NORMAL(주·보조)·F-QUARTER 골든 통과, AgentResult 공통 계약 테스트 통과, 13.1에서 미룬 5행 통과
- `graph.py`, `nodes/` 10개, `store.py`, `schemas.py`, `state.py`, `config.py`, `templates/report.md.j2`
- 시장 데이터 경로는 키가 없어 미구현, 항상 missing

## 2단계 마무리 (2026-11-06) — 개발문서 v0.19 → v0.20. **완료 기준 통과 (14개 유형 `ai_verified`, 사람 확인 0건)**

- 9.1a 감가상각비는 사용권 포함 합계끼리 비교. `무형자산감가상각` 행 분류. 표본 F 2023 EBITDA 1,691.0억 산출, 테스트 +3
- 잔여 검수 반영. 재점검 결과 `api_fields.md` 30.1

## 3단계 (2026-11-06) — 개발문서 v0.18 → v0.19

- `core/calc/ratios.py`, `cashflow.py`, `market.py` 신규. `fin_items.py`에 기본 항목, `amortization_sources`, `ebitda`, `interest_expense` 추가
- `core/clients/dart_notes.py` 신규 (프로브 판독 로직 이동), `core/units.py` `parse_krw`
- `tests/unit/core/test_calc.py`, `tests/unit/test_golden_values.py`
- 12장 시그니처를 구현과 맞춤. 13.1의 노드 의존 5행은 4단계로

## 2단계 후속 9 (2026-11-06) — 개발문서 v0.17 → v0.18

- 9.1a 이자비용 missing 사유 "이자비용 행 없음(차입원가 자본화 있음)". F-NOINTEREST_1, F-OFS_1 기대 사유 수정
- `separate_only` 확인: 연결재무제표 절 문구를 쓰지 않음. 수정 없이 테스트 +1
- 추가 검수 반영. 접수일·차입 계정 상태는 `verification_method: api_response`. F-NOMARKET_F는 F-NORMAL_F 상태를 따름

## 2단계 후속 8 (2026-11-05) — 개발문서 v0.16 → v0.17

- 9.1a 금융표 없음 + 현금흐름 조정 표와 다른 표 일치 → 채택. v0.16 "이자비용 구성 불명확" 규칙 철회. 파일끼리 표 단위 안 차이는 같은 값
- F-NOINTEREST_1 후보 교체. 차입원가 자본화 사유는 제안 (`api_fields.md` 28.6)
- 셋째 묶음 AI 검수 반영

## 2단계 후속 7 (2026-11-05) — 개발문서 v0.15 → v0.16

- 9.1 주석에 리스부채 합계만 있으면 재무상태표 합과 원 단위 대조 (`fin_items.total_borrowings`, 테스트 +1). F-OFS_1 총차입금 재계산
- 9.1a 이자비용 missing 사유 "이자비용 구성 불명확(…)", F-NOINTEREST_1 기대값 수정

## 2단계 후속 6 (2026-11-05) — 개발문서 v0.14 → v0.15

- 9.1a·3.3 별도 기준 조건과 "별도 기준" 표시. `dart_docs.separate_only`, `note_sources`, `attached_statements`, 테스트 +2
- 13.2 F-NOINTEREST, F-CORRECTED 추가
- 셋째 묶음 초안 draft: F-NETCASH_1, F-OFS_1, F-NOINTEREST_1, F-CORRECTED_KOSPI
- 프로브 판독 오류 3건 수정(`api_fields.md` 28.2). 첫째·둘째 묶음 수집 결과 변화 없음

## 2단계 후속 5 (2026-11-05) — 개발문서 v0.13 → v0.14

- 9.1a 무형자산 변동표 조건부 채택 (`core/clients/dart_docs.py`, 테스트 +8). 0 판정의 재무상태표 대조는 구현 중 추가. 9곳 EBITDA 4/9 → 7/9
- 3.2 EBITDA 음수 시 EBITDA/이자비용 값 그대로 + note "EBITDA 음수", 지표 목록 v0.15
- 13.1·13.2 이자비용 missing 시험 이동 (F-NETCASH-NOEBITDA + 단위 테스트, 3단계에서 구현)
- 둘째 묶음 나머지 AI 검수 반영: F-IMPAIR50 2, F-FULLIMPAIR 2, F-KOSDAQ-EQ, F-RESTRUCT `ai_verified`. note 추가
- 미확보 유형 후보 `tests/golden/_candidates_batch3.json` (F-NETCASH, F-OFS)

## 2단계 후속 4 (2026-11-05) — 개발문서 v0.12 → v0.13

- document.xml ZIP 전체 읽기: `core/clients/dart_docs.py`, 테스트 +3. 본문 → 연결감사보고서(첨부 재무제표 + 주석), 별도 감사보고서 제외, DOCUMENT-NAME으로 판별
- 파서 수정: 주석 번호 열, `제26(당)기` 머리글, `무형고정자산상각` 라벨. 표끼리 값 대조는 파일별로 (같은 표 중복 계산 방지)
- 14곳 전후 비교 (`api_fields.md` 25장): 표본 E 이자비용 21.4억·상각비 분리. 나머지 변화 없음. 표본 B·C·H 무형 상각은 ZIP 문제가 아니라 변동표에 있음 → 제안 (미채택)
- F-NEGEBITDA 기대값 변경. 이자비용 missing 시험은 F-NETCASH-NOEBITDA로 이동
- 둘째 묶음 AI 검수 반영. 미검수 11건 원문 캐시 저장

## 2단계 후속 3 (2026-11-05) — 개발문서 v0.11 → v0.12

- 둘째 묶음 초안 10건 (F-IMPAIR50 2, F-FULLIMPAIR 2, F-KOSDAQ-EQ, F-RESTRUCT, F-NETCASH-NOEBITDA, F-NEGEBITDA, F-QUARTER, F-NOMARKET. draft). 정정이 있는 보고서는 as_of를 마지막 정정 다음 날로
- 9.1a 금융원가 주석 이자비용 채택 (2개 표 이상 일치). 지표 목록 v0.14. 9곳 EBITDA/이자비용 1/9 → 3/9
- F-NORMAL 보조 케이스 F의 역할을 금융원가 주석 이자비용으로 변경 (이자비용 missing은 F-NEGEBITDA에서 확인)
- `scripts/probe_interest_note.py` 함수화, 정답지 `human_verified` 추가

## 2단계 후속 2 (2026-11-05) — 개발문서 v0.10 → v0.11

- missing 사유 문구를 "현금흐름 조정 항목에 이자비용 행 없음"로 수정 (3.2, 13.2, 화면 명세, 정답지)
- 9.1a 금융원가 주석 이자비용 출처 제안 (미채택). 9곳 EBITDA/이자비용 1/9 → 3/9 (`api_fields.md` 23.2), `scripts/probe_interest_note.py`
- AI 검수 반영: F-AUDIT 2건 `ai_verified`(사람 기준 정답 note 추가, 시스템 기대값 unknown 유지), F-NORMAL 2건 `ai_verified_partial`

## 2단계 후속 (2026-11-05) — 개발문서 v0.9 → v0.10

- 13.2 F-NORMAL 조건 변경, G 주 케이스·F 보조 케이스. 사람 확인 전, status draft 유지
- 파서 오류 수정: 표본 G 2024 상각비(주석에 감가 행 없으면 본문, 9.1a), 감사의견 당기 행 판정(첫 기수, 8장). 9곳 EBITDA 변화 없음. 감사의견 재집계에서도 `부적정` 0건

## 2단계 착수 (2026-11-05) — 개발문서 v0.8 → v0.9

- `fin.short_term_financial_assets` 행 없음 처리 (`fin.net_debt`와 같은 규칙), 지표 목록 v0.12
- 13.2 F-NETCASH 조건에 EBITDA 산출 추가, F-NETCASH-NOEBITDA 신설
- 첫 묶음 초안: `tests/golden/financial_health/` F-NORMAL 2건, F-AUDIT 2건 (status draft, 사람 확인 전)
- `scripts/probe_ebitda_final.py` 수정: N 감가 = C 감가(사용권 제외)일 때 9.1a대로 사용권 포함 값 채택. 공개한 9곳 값 변화 없음

## 문서 정리 (2026-11-05)

- 이 파일의 실제 기업명 2곳을 표본 라벨로 교체. 개발문서 변경 없음

## 1단계 마무리 (2026-11-05) — 사용자 결정 반영, 개발문서 v0.7 → v0.8

- 9.1 최신 리스부채: 반기·분기보고서의 리스 0은 직전 사업보고서도 "리스 없음"일 때만. 아니면 총차입금·순차입금 missing ("최신 보고서 리스부채 미공시"). 직전 금액을 섞지 않음
- 9.1 사용권자산 신호: `ifrs-full_PropertyPlantAndEquipmentIncludingRightofuseAssets` 행 추가 (리스 0 금지)
- 9.1 `ifrs-full_OtherCurrentFinancialAssets` 제외 확정. 주석 내역 실측 (`api_fields.md` 16장)
- 3.1 영업현금흐름 사업연도 값 출력 (대표 차트 전환용). 화면 명세 v0.6 4.1
- 9.2 `AUDIT_OPINION_MAP` 채움: 한정·의견거절 실측. `부적정`·감사범위 제한 문구는 미확인, MVP에서 쓰지 않음
- 9.3 `RESTRUCTURING_PATTERNS` 실제 보고서명으로 확정 (정규화 이름 완전 일치). `기타 구조조정` 미확인, 출력 안 함
- 13.2 F-NETCASH 조건 "순차입금 < 0". 후보 `tests/golden/financial_health/_candidates.json`
- 코드: `core/calc/fin_items.py` `total_borrowings(…, *, zero_lease_ok)` (필수 인자), `PPE_ROU_ID`. 테스트 +2
- 재산출 (`api_fields.md` 15장): 순차입금 2025말 5/9·최신 5/9, ⚠ 0건. G 최신 값 폐기
- 지표 목록 v0.10
## 1단계 후속 5 (2026-11-05) — 리스부채 채택 규칙, 개발문서 v0.6 → v0.7

- 9.1 리스부채 채택 규칙: BS 리스부채 행 → BS 값 + 주석 대조(불일치·대조 불가 missing) / BS 행 없음 → 같은 보고서 리스 주석 값(note "리스부채 출처: 리스 주석") / BS 사용권자산 없음 + 주석 리스 절 없음 + 주석 값 없음일 때만 0 / 그 외 missing. v0.6의 사용권자산 신호 규칙과 BS만 보고 0으로 처리하는 경로 삭제
- 이중 합산 방지: 차입 행 이름에 '리스' 있음, 주석 리스부채 표가 총차입금 포함 행의 구성 표 → missing
- 코드: `core/calc/fin_items.py` `total_borrowings` (14장 3단계 함수 중 하나를 먼저 작성 — 이중 합산 테스트용). 테스트 `tests/unit/core/test_fin_items.py` +5: 26 passed (+live 1)
- 실측: 2026 반기 리스 주석 9곳 (`api_fields.md` 14.1). 8곳 읽힘, G는 요약 주석에 리스 잔액 없음 → 규칙 3번으로 리스 0 ⚠ (처리 방안 ※결정 필요, 9.1)
- 재산출 (14.2): 총차입금 2025말 6/9·최신 7/9, 순차입금 2025말 5/9·최신 6/9, ⚠ 1건(G 최신)
- 지표 목록 v0.9, 12장 `total_borrowings` 시그니처, 13.1 테스트 표
- 오케스트레이터 v0.5: `REQUIRED_METRICS`에 `fin.debt_ratio`·`fin.ttm_operating_cash_flow`, 순차입금·EBITDA 계열은 `OPTIONAL_METRICS`

## 1단계 후속 4 (2026-11-05) — 순차입금 A안 확정·리스 0 처리 폐기·최신 보고서 기준, 개발문서 v0.5 → v0.6

- `fin.net_debt` A안 확정: 총차입금 − (현금및현금성자산 + 단기금융상품). 출처 한국기업평가 정의(리스부채 포함 부분만 STRIDE 정의). 기타유동금융자산만 있으면 missing
- `fin.total_borrowings`: 리스부채 0 처리 폐기. 사용권자산 신호(BS 사용권자산 > 0 또는 9.1a 사용권자산상각비 > 0) 있고 리스부채 행 없으면 missing ("리스부채 별도 행 없음")
- 3.1 기준 보고서 선택 규칙: 순차입금·총차입금·부채비율을 사업연도별 + 최신 정기보고서(TTM 영업현금흐름과 같은 보고서)로 계산. 새 metric_id 없음
- `fin.debt_ratio`: 한국기업평가 원문 "(부채총계/자본총계)*100"과 일치 재확인, 자본총계 ≤ 0이면 None
- 실측: 리스 주석 리스부채 잔액 probe (`scripts/probe_lease_note.py`, `api_fields.md` 12장) — BS 행 있는 4곳 원 단위 일치, 주석에만 있는 4곳(D·E·G·H). 문서 반영 결정 대기
- 9곳 결과 (`scripts/probe_board.py`, `api_fields.md` 13장): 순차입금 사업연도말 4/9·최신 5/9, 부채비율 8/9, TTM 영업현금흐름 8/9
- 지표 목록 v0.8. 화면 명세 v0.5·와이어프레임 v1.8·구성문서 7.1·오케스트레이터 v0.4 BoardRow(`debt_ratio`, `ttm_operating_cash_flow`)

## 1단계 후속 3 (2026-11-05) — 리스부채·순차입금·목록 기간 검사, 개발문서 v0.4 → v0.5

- `fin.total_borrowings`: 유동·비유동 리스부채 전체 포함 (STRIDE 정의, 원문 금융리스부채 포함 병기). 9.1 허용목록·탐지 규칙에 리스부채 추가, "리스부채 별도 행 없음" note
- `fin.net_debt`: 현금성자산 범위 A안/B안 비교 실측 (`scripts/probe_net_debt.py`, `api_fields.md` 11장). 9곳 중 산출 A안 5곳, B안 6곳. 결정 전까지 methodology "확인 중"
- 표본 B 무형자산 빈 값 → missing 유지
- 7장·9.1a: 정정 판정 공시 목록 기간이 대상 보고서 rcept_dt를 포함하지 않으면 `CoverageError` 중단
- 코드 (core): `core.asof.FilingList`(조회 기간 포함)·`CoverageError`·`ensure_covers`, `resolve_version(…, target_rcept_dt)`. `DartClient.list_filings`가 `FilingList` 반환, `financials`·`audit_opinion`에 `report_rcept_dt` 인자 추가, `major_event`는 조회 기간 검사. 검사는 API 호출 전
- 테스트 +4 (목록 기간 밖·기간 끝 이후·기간 정보 없는 목록·클라이언트가 API를 부르지 않음): 21 passed (+live 1)
- 지표 목록 v0.7, 화면_데이터_연결명세 v0.4 (대표 차트 영업현금흐름 TTM vs 순차입금, 기준 기간 표시 규칙, EBITDA 보조 표시)

## 1단계 후속 2 (2026-11-05) — 상각비 원문 읽기, 개발문서 v0.3 → v0.4

- 실측: XBRL 원본파일은 9/9 제공, 주석 태그는 5/9 → 참고만. document.xml 연결 주석(N 성격별 분류)·현금흐름(C 주석 또는 연결현금흐름표 본문) 2출처 파서 `scripts/probe_amortization.py`
- 결정 반영
  - `fin.ebitda` = 영업이익 + 감가상각비(사용권자산 포함) + 무형자산상각비 → STRIDE 정의 (한국기업평가 원문은 사용권자산 언급 없음)
  - 9.1a 신설: 출처·행 분류·단위 환산·합계 열·허용오차(표 단위 1)·합계 비교·비원화 missing·불일치 missing·무형자산상각비 미발견 시 BS 무형자산 규칙(없음/0 → 0, 있음·빈 값 → missing)·근거 ID
  - 9.1: depreciation·amortization을 9.1a로 이관, 무형자산 BS 허용 ID 추가
  - 12장: `ebitda` docstring, `amortization_sources` 신설. 13.1 단위 테스트 표 갱신
  - 3.2: `fin.ebitda`·`fin.net_debt_to_ebitda`·`fin.ebitda_margin` methodology를 STRIDE 정의로 (지표 목록 v0.6과 일치)
- `metrics_catalog.yaml` v0.6, `core/docs/api_fields.md` 9장(상각비)·10장(한국기업평가 원문 대조)
- 결과: 9곳 중 EBITDA 산출 4곳, TTM 영업현금흐름 산출 8곳
- 확인 사항: 표본 I 표 오독은 파서 오류 아님(원문 라벨 불일치). 정정 전 원본 값은 document.xml로 읽기 가능 — Phase 2 유지
- 미결정(보고): 순차입금 리스부채 포함 여부, `fin.net_debt`의 현금성자산 범위(원문은 단기금융상품 포함)

## 1단계 후속 (2026-11-04) — 사용자 결정 반영, 개발문서 v0.2 → v0.3, 표본 8곳

- 계정 확인 표본을 3곳에서 8곳으로 늘림 (대형 2·중형 3·소형 3, 유가 6·코스닥 2). 결과 `core/docs/api_fields.md` 5.2
- 9.1: 개념별 account_id 허용목록 + sj_div 매칭 (계정명 대체 삭제). 손익은 IS·CIS 모두 허용(표본 G가 IS)
- `fin.total_borrowings`: 차입·사채 계열 BS 행이 모두 허용목록일 때만 계산, 아니면 missing("미분류 차입 계정"). 리스부채는 한국기업평가 원문 확인 전 제외. 8곳 중 6곳 계산 가능
- `fin.ebitda`: 상각비는 CF `ifrs-full_AdjustmentsForDepreciationExpense`·`ifrs-full_AdjustmentsForAmortisationExpense`만. 없으면 missing("상각비 미공시"). 사용권자산상각비 제외. 8곳 중 1곳 계산 가능
- `fin.ebitda_interest_coverage`: 이자비용은 CF `dart_AdjustmentsForInterestExpenses`만. 금융비용·이자지급액 대체 금지
- 감사의견(3.3, 9.2): 응답 문자열 그대로, 연결·별도 구분 제거, 사업연도는 요청 파라미터, 범위제한 판별 불가 → unknown → 오케스트레이터 R1b-KS·R1-KQ 해당 부분 "확인 불가"
- 7장: 시점 판정은 list.json rcept_dt만, 정정공시 unknown 규칙("정정 전 원본 값 확인 불가")
- 0장 9번: missing은 화면 "산출 불가", unknown은 "확인 불가"
- 지표 목록 v0.5: `fin.short_term_financial_assets`·`fin.ebitda`·`fin.total_borrowings`·`fin.ebitda_interest_coverage`·`fin.audit_opinion`·`fin.audit_scope_limitation` 정의 갱신
- 남은 것: 9.3 구조조정 보고서명, 9.4 시세 API(선택), 비적정 감사의견 문자열, `ifrs-full_OtherCurrentFinancialAssets` 포함 여부(※결정 필요)

## 1단계 일부 (2026-11-04) — 해외진출 1단계와 함께 확인

결과: `core/docs/api_fields.md` 5·6장. 표본 3곳

- 확정: 9.1 계정 중 cash, total_assets/liabilities/equity(BS 한정), equity_parent(CFS만), capital_stock `ifrs-full_IssuedCapital`, current_assets/liabilities, retained_earnings, revenue(ID), operating_income, net_income_parent(ID 필수), op_cash_flow
- 문서와 다름: st_fin_assets ID, 차입금·사채 계정(고정 ID 불가), revenue 대체 계정명에 "수익"
- API에 없음: 이자비용 단독 행, 감가상각비·무형자산상각비(표본 2/3), 감사범위 제한 전용 필드
- 9.2 감사의견: 엔드포인트 `accnutAdtorNmNdAdtOpinion.json` 확정, 응답 필드 확정
- 0단계의 `core/calc/` 틀(fin_items, cashflow, ratios, market)은 아직 만들지 않음
