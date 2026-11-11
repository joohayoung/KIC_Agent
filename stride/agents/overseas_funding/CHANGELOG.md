# overseas_funding CHANGELOG

기준 개발문서: `MVP_1차/에이전트_개발문서/해외진출_자금수요_기업발굴_에이전트_개발문서.md` v0.22

## 방향 수정 (2026-11-10) — 개발문서 v0.23 11.2a 유동성 원천·소요

- 지표 7개 추가 (지표 목록 v0.16): `ovs.overseas_investment_within_24m`, `ovs.overseas_investment_beyond_24m`, `fin.maturing_debt_1y`, `fin.dividends_paid_last_fy`, `ovs.liquidity_uses`, `ovs.liquidity_surplus`, `ovs.liquidity_sources_to_uses`. S&P Liquidity Descriptors 준용 STRIDE 정의 (원문 PDF 403, 문단 미확인)
- `calc/funding.py`: `horizon_end`, `investment_dates`(투자액에 들어간 건별 집행일), `investment_within_24m`/`beyond_24m`, `liquidity_uses`/`surplus`/`ratio`. `investment_amount` 항목에 `date`(확정일 또는 예정일)
- `core/calc/fin_items.py`: `maturing_debt_1y`(유동 차입 표준 계정 + 유동부채 절 위치·이름 규칙, 리스 제외, 미분류·빈 값 missing), `dividends_paid_last_fy`(지급 행 절댓값, 수취·신종자본증권 제외, 행 없음 0)
- `compute_funding_gap`: 직전 사업보고서 현금흐름표에서 배당금, 최신 정기보고서 재무상태표에서 만기 차입금. 모든 계산 값에 CALC 근거(impl·args 재계산). 자금 공백 지표는 그대로 계산
- `write_report`: 계산 근거 출처 줄을 지표 ID 대신 지표 이름으로 (ID `ovs.unconfirmed_overseas_funding`이 보고서에 옮겨지면 내부 이름 검사에 걸려 템플릿으로 대체되던 문제)
- 단위: `tests/unit/overseas_funding/test_liquidity.py` 16개 (소요 0, 원천 음수, 24개월 경계·윤일, 예정일 없음, 배당 행 없음·지급·수취·빈 값, 미분류 차입 행, 유동부채 절, 확정 조달 납입일 전후)

## 10단계 (2026-11-09) — 개발문서 v0.22. **완료 기준 통과**

- 완료 기준: 과거 1개월(2024-08) 재생, 처리 시간·LLM 호출 수 기록 — `scripts/run_batch_month.py 2024-08`: 후보 30곳 중 첫 실행 상한 5곳 실행, 25곳 분석 대기, 361.9초, LLM 19회(기업당 2~5회), 오류 0 (`data/logs/batch_2024-08.json`, `.md`)
- `agents/overseas_funding/batch.py`: `screen_universe`(LLM 없음, 3개월 단위 조회, 국적·금액 칸 반환), `company_graph`(Send), `aggregate_list`(10.7 표, 순위 열 없음, 최근 신호일 순). `BATCH_MAX_COMPANIES` 30, `LLM_CONCURRENCY` 1
- 직전 상태가 신호 없음·범위 밖·취소이고 새 공시가 없으면 다시 실행하지 않음
- D9(기사 근거 사실 "~로 보도되었다", 10.6), D7(gap_changed 부호 기준 확정) 반영
- 단위: `tests/unit/overseas_funding/test_batch.py` 3개

## 9단계 (2026-11-09) — 개발문서 v0.21. **코드·자동 기준 통과, 사람 검토 대기**

- `nodes/write_report.py`, 프롬프트 `write_report.md`(10.6 원문 + `{재생성_피드백}`), `ReportOutput`, `to_result`의 report_markdown·alerts
- 범위 안은 opus가 쓰고 출력 검사 4종(각주 매핑, 자료에 없는 숫자, 내부 이름, 판단 표현). 실패하면 1회 재생성, 그래도 실패하면 템플릿 + errors. 범위 밖·사실 없음·기업 식별 실패는 템플릿(LLM 없음)
- verify에 가용 자금 구성·미확정 조달 calc Finding 추가 (보고서 자금 공백 표 근거). 미확정 조달 calc 근거 추가 (`funding.total`)
- 사람 검토용 샘플: `tests/golden/_review_report.md` (빌더 `_build_review_report.py`)
- 검토 중 고친 것: 각주 번호를 허용 숫자에 넣던 검사 구멍, '원' 없는 칸 금액의 억원 환산, 같은 문서 각주 중복, 축소로 낮춘 단계 표시, 템플릿의 영어 방향어·내부 키

## 8단계 (2026-11-09) — 개발문서 v0.21. **완료 기준 통과**

- 완료 기준: `tests/replay/overseas_funding/test_replay.py` G-CHANGE 4시점(new_signal → 누수 없음 → cancelled·stage_down → 중복 없음), G-TRACK 3시점(new_funding)
- `store.py` (9장 테이블), `nodes/update_state.py` (7.12). 직전 기록은 as_of가 앞선 것만. 같은 취소 반복 경보 없음
- `gap_change_ratio` 값이 문서에 없어 None (부호 변화만 경보). 결정 대기
- 사용자 결정: v0.20 변경 5건 승인 기록, 7.9 거래 상태 경고 채택(`trading_status_warnings`), G-POS 주 후보 확정(검수 반영 `ai_verified_partial`), open_question "목적에 운영자금 포함, 금액 구분 없음"
- 버그: 국가 미상 기사·계획 사건을 해외 신호로 넣던 문제 (G-DOM 주가 범위 안으로 나옴)

## 7단계 (2026-11-07) — 개발문서 v0.19 → v0.20. **완료 기준 통과**

- 완료 기준: 8개 유형 골든 16 passed (`tests/golden/test_overseas_step7.py`, 같은 입력은 호출 기록 재사용 가능). G-MIX D3 결정 기록은 기사 금액만 주입해 시험 (실제 실행에는 충돌 0건)
- 노드: `merge_signals`, `resolve_conflicts`, `scope_gate`, `verify`, `graph.build_company_graph`. `provisional_merge` 삭제. update_state·write_report 자리는 END, 임시 상태 분류 `provisional_status`
- 사용자 결정: 칸 분할은 시설 칸만, 운영 칸은 `overseas_subsidiary_working_capital_krw`. S6 정형 연결, `unlinked_s6`. G-POS 재탐색: 주 후보 교체(draft), 이전 후보는 G-POS_HALTED. 7.9 거래 상태 경고는 제안만
- 사용자 지시 "라벨 흔들림과 무관"을 위해 추가로 바꾼 것 (문서 v0.20 기록): 합산 ③을 소유주식수 누적으로, S4가 있으면 단계는 S4만, S6 방향을 정형으로, 프로젝트 묶기에서 method 제외, 같은 입력 비교로 확인 (`_stability.py`)
- 7.11 변경: LLM 대조는 S1·S2만, 재추출은 contradicted만
- 5곳 실제 실행 (2026-11-09): 20회, 입력 253,828, 출력 22,233, 220.7초 (호출규칙 4.5). `/usage` 변화 미측정
- 버그: 국적 없는 양식을 해외로 읽던 문제, 상대방 표 국적, 철회 정정 빈 칸, 취득완료 정정 날짜, 국내 시설 공시의 S4 생성, 한도 오류 분류

## 6단계 완료 (2026-11-06) — 개발문서 v0.18 → v0.19. **완료 기준 통과**

- 완료 기준: `pytest -m llm` 2회 연속 3 passed (G-POS 주·보조·MIXED), D2 단위 테스트 통과. 주 후보 정답지는 draft
- 사용자 결정: 연결 종속회사 출자를 같은 날 증자 공시 칸으로 분할 (`Batch.split_signals`). 칸 합계가 취득금액과 다르면 나누지 않는다 (사용자 조건에 없던 안전 조건)
- 정답지: 이전 주 후보 → G-POS_MIXED (공백 -731,828,904), 새 주 후보 초안 + 검토표 `_review_gpos_swap.md`
- 회귀: 정탐 p1·p2 추가, 허용 오탐 p137·p97
- 버그: `plain_text`가 앞부분 스타일 표를 지움. R1 채무상환 정규식이 `(원)` 앞 공백을 놓치던 문제 수정
- 같은 입력 2회: 라벨 24개 중 17개 동일. change_direction 2건이 달라 S6 생성 여부가 달라짐 (`api_fields.md` 32.3, 결정 대기)

## 6단계 첫 시험 (2026-11-06) — 개발문서 v0.17 → v0.18. **완료 기준 미통과**

- 통과: D2 검증기 단위 테스트, G-POS 보조 must_have_signals (투자액 합산·자금 공백 포함)
- 미통과: G-POS 주 `purpose_category` (growth_investment 기대, unknown·governance_restructuring으로 나옴). 금액·공백은 일치
- `core/llm.py`, `core/clients/news.py`, 프롬프트 4개, `nodes/extract_periodic_plan.py`, `parse_major_events.py`(LLM), `collect_news.py`, `extract_news.py`, `graph.build_extraction_graph`
- 측정: 기업 1곳 4회, 41.3초, 입력 47,138, 출력 4,820 (호출규칙 4.4)

## 3단계 재검수 반영 (2026-11-06). **완료 기준 통과**

- `text/diff.py` 구조 수정. 신규 표시 23 → 7, 정탐 3 유지, 검수 오탐 20 → 3. 회귀 테스트 고정
- 사용자 조건(규칙 3)만으로는 정탐 G-POS 주 p39가 빠져 '새 실행어' 예외를 추가했다

## 5단계 (2026-11-06) — 개발문서 v0.16 → v0.17. **완료 기준 통과**

- 완료 기준: G-POS 케이스로 collect_disclosures → parse_major_events(분류 임시 unknown) → compute_funding_gap 실행. 주 후보 자금 공백이 정답지와 일치
- 보조 후보는 합산 라벨이 없어 투자액이 최신 1건이다 (7단계에서 정답지 합산값 확인). 가용 자금은 일치
- `graph.build_nollm_graph`, `nodes/` 5개, `schemas.py`, `state.py`

## 3단계 (2026-11-06). **구현 완료, 사람 확인 대기**

- `text/dart_sections.py`, `text/diff.py`, `core/filings.py` `classify_filing`. 검수표 `tests/golden/_review_text.md`

## 2단계 마무리 (2026-11-06). **완료 기준 통과 (8개 유형 `ai_verified`, 사람 확인 0건)**

- G-GOV_I 잔여 검수 반영, `G-DOM_주`

## 4단계 (2026-11-06) — 개발문서 v0.15 → v0.16

- `agents/overseas_funding/calc/funding.py` 신규: 투자 제외(7.10 4a), 해외 용도 금액, 결정·결과 연결(11.2), 자금 공백
- `tests/unit/overseas_funding/test_funding.py`. 12.1 계산 케이스 통과
- 3단계(`text/`)는 아직 하지 않음

## 2단계 후속 9 (2026-11-06) — 개발문서 v0.14 → v0.15

- 12.2 `verification_method`. 추가 검수 반영, G-DOM 주 후보 확정

## 2단계 후속 8 (2026-11-05) — 개발문서 변경 없음 (v0.14 유지)

- 셋째 묶음 AI 검수 반영. G-DOM_주 초안 추가 (draft)

## 2단계 후속 7 (2026-11-05) — 개발문서 v0.13 → v0.14

- 12.2·12.3 G-CHANGE 취소·철회 기대값을 7.9·7.12로 통일
- 7.5 R1 종속회사 증자 채무상환 칸 open_question, G-POS_주 기대값 추가
- G-DOM_1 → G-DOM_EDGE (경계 사례, 근거 문장 기록). 주 후보 탐색 `scripts/probe_search_gdom.py`

## 2단계 후속 6 (2026-11-05) — 개발문서 v0.12 → v0.13

- 7.5·11.2 세부 내역·문장에만 있는 해외 금액 합산 제외 유지, open_question에 원문 기록
- 7.10 4a 완료일 문장 형식 추가
- 셋째 묶음 초안 draft: G-POS_주, G-POS_보조, G-CHANGE_1, G-DOM_1, G-MIX_1

## 2단계 후속 5 (2026-11-05) — 개발문서 변경 없음 (v0.12 유지)

- 미확보 유형 후보 `tests/golden/_candidates_batch3.json` (G-POS, G-CHANGE, G-DOM, G-MIX). `scripts/probe_search_missing.py`

## 2단계 후속 4 (2026-11-05) — 개발문서 변경 없음 (v0.12 유지)

- 7.5 발췌·칸 제외 수정 사용자 승인
- G-MIX_D AI 검수 반영(`ai_verified`, 부분 후보 유지). 본래 조건 후보 탐색 대기
- 표본 E 해외 후보 870억 재확인: 해외 200억 + 불명 670억 (`api_fields.md` 26장)

## 2단계 후속 3 (2026-11-05) — 개발문서 v0.11 → v0.12

- 둘째 묶음 초안: G-MIX_D (부분 후보, draft)
- 7.10 4a: S4 전부 집행 완료 시 투자액 0·note "확정 집행 완료분 제외", 비율 None. 완료일 미발견 시 유지
- 7.5: 조달 공시 발췌를 사용 목적 절로 수정. mixed·unknown 칸만 제외하고 overseas 칸은 합산 (11.2도 수정). 사용자 알림 대상
- 원인 보고: 표본 F 해외 후보 400은 프로브의 단순 합산 오류 (`api_fields.md` 24장). 프로브 출력 문구 수정, 19장 표 정정
- 12.2 `human_verified`, 3단계 착수 조건
- 추가 검수 반영: G-TRACK·G-RICH `ai_verified`, G-GOV 접수일 값과 검수 파일에 없는 3건만 draft. G-GOV 투자액 0, 양수금액 note 수정

## 2단계 후속 2 (2026-11-05) — 개발문서 v0.10 → v0.11

- 11.2 TTM 음수 그대로, 지표 목록 v0.13, 구성문서 식, 화면 명세 v0.8
- 7.10 4a 확정 날짜 기준 투자 제외. 예정일만 있으면 유지, 연결 내부 출자는 제외 안 함. 전부 제외 시 missing (다음 순위로 내려가지 않음), 문장 날짜는 코드 정규식 (사용자 확인 대상)
- 12.2 정답지 status 정의. AI 검수 반영: G-NONE `ai_verified`, G-TRACK·G-RICH·G-GOV `ai_verified_partial`
- 재계산: G-TRACK -607.1억 / -448.8억, G-RICH -768.5억, G-GOV missing (`api_fields.md` 23.3)
- 미검수 5건 document.xml 캐시 저장

## 2단계 후속 (2026-11-05) — 개발문서 v0.9 → v0.10

- 7.8 같은 대상 취득 합산 조건, 8.1.3 '종속회사 집행' S4 후보, 자본인정 채무증권 R5, 10.3 `part_of_earlier` 라벨
- 표본 D 자본인정 공시 원문 대조: 회차·금액·납입일·이사회·목적 칸 일치 → 결정 1건
- 초안 수정: G-TRACK(대표 금액 449.1억, 집행 공시), G-GOV(in_scope True, 토지 3건). 사람 확인 전, status draft 유지
- 제안 2건 기록(`api_fields.md` 22.3, 미채택): TTM 음수 그대로, 재무 기준일 이전 집행 투자 제외

## 2단계 착수 (2026-11-05) — 개발문서 v0.8 → v0.9

- 7.5 분류 변경 채택: 규칙 R1~R4 + 남은 공시 묶음 1회. LLM은 라벨만, 금액은 DS005·거래소 정형 칸만 (칸별 evidence_id). 10.3 `MajorEventBatchOutput`, `fund_use_scopes` 추가, `overseas_amount_original` 삭제
- 3장·8.1.5 단기금융상품 0 규칙, 12.2 G-POS 재탐색 조건·G-MIX 칸 단위 기대값, 12.1 테스트
- `api_fields.md` 21장 거래소 정형 칸
- 첫 묶음 초안: `tests/golden/overseas_funding/` G-TRACK, G-RICH, G-NONE, G-GOV (status draft, 사람 확인 전)
- 표본 H "II장 키워드 0건" 기록 정정 (실제 15~16개)

## 1단계 후속 (2026-11-05) — 조달 확정 규칙 통일, 개발문서 v0.7 → v0.8

- 11.2 전면 정리: 유상증자·CB·BW 모두 결과 공시(증권발행실적보고서, 거래소 `증권발행결과`, `유상증자또는주식관련사채등의발행결과`) 연결 시에만 확정. 연결 조건 같은 회사·같은 증권 종류·금액 일치, 모호·불일치는 open_question. 결정 공시 납입일과 `pymd`는 예정일. v0.7의 "자율공시는 근거 아님" 규칙 폐기
- 신규 지표 `ovs.unconfirmed_overseas_funding`, `FundingGap.unconfirmed_funding_krw`. 자금 공백은 확정 기준. 지표 목록 v0.11, 화면 명세 v0.7, 오케스트레이터 v0.6 BoardRow, 10.6 보고서 표
- 8.1.3 issue_result 범위 확대. 12.1 테스트 표
- 실측 (`api_fields.md` 19장): 골든 후보·표본 결정 19건 연결 결과. `scripts/probe_funding_link.py` (형식 assert 포함)
- 분류 노드 설계 변경 제안 실측 (`claude_cli_호출규칙.md` 4.3, `api_fields.md` 20장). 7.5는 결정 대기로 그대로 둠
- `core/config.py` `first_run_max_deep_analysis=5`, 체크리스트 6장 구독 사용량 확인
- 테스트 28 passed (+live 1). 카탈로그 항목 수 기대값 37 → 38

## 1단계 마무리 (2026-11-05) — 개발문서 v0.6.1 → v0.7

- 11.2 유상증자 확정 조달: 증권발행실적보고서(`pblntf_ty=C`) 접수 시 확정. 주요사항보고서 납입일은 예정일로 note에만 기록. 실적보고서 납입일로 중복 판정. 증권 종류 확인, 연결 불명확 시 미포함 (연결·납입일 세부 규칙은 구현자 제안, 사용자 확인 대상)
- 7.3 공시 목록에 C 추가, 8.1.3에 issue_result, 12.1 테스트 케이스
- 실측 (`api_fields.md` 17.1): 제3자배정 50건 중 주식 실적보고서 2건 → 대부분 확정 조달에 안 들어감
- 7.5·8.1.4 `bsnInhDecsn` 필드 확정 (5년 82건). 이전 "12개월 0건" 기록은 스캔 키워드 누락 오류였음. 국적 필드 없음
- 처리량 실측 (`공통기준/claude_cli_호출규칙.md` v1.1 4.1): 표본 D 1곳 15회·168.2초. 코드 없이 프롬프트로 재현한 값
- 지표 목록 v0.10 `ovs.confirmed_overseas_funding` 정의 갱신
- 공통 변경: `core/docs/api_fields.md` 3.2·4.6·15~18장, 구성문서 v1.5 .md(row 9, 4.2 route_by_event 확인, 그림 5 v1.8), 체크리스트 v0.4
## 공통 변경 알림 3 (2026-11-05) — 이 에이전트 문서 변경 없음 (v0.6.1 유지)

- 지표 목록 v0.8 → v0.9: `fin.net_debt` A안 확정, `fin.total_borrowings` 리스부채 채택 규칙, 순차입금·총차입금·부채비율 최신 정기보고서 기준 추가. 이 에이전트는 세 지표를 쓰지 않는다. 자금 공백에 쓰는 `fin.cash_and_equivalents`·`fin.short_term_financial_assets`·`fin.ttm_operating_cash_flow` 정의는 바뀌지 않음
- `core/calc/fin_items.py` 신설 (`total_borrowings`만). 11장 자금 공백 계산이 쓰는 `core.calc` 함수는 아직 없음
- 오케스트레이터 v0.4 BoardRow(`debt_ratio`, `ttm_operating_cash_flow`), v0.5 `REQUIRED_METRICS` 교체 — ovs 필수 지표 4개는 그대로
- 테스트 26 passed (+live 1), 계약 테스트 포함

## 공통 변경 알림 2 (2026-11-05) — 개발문서 v0.6 → v0.6.1

- 6.1: 정정 판정 공시 목록 기간이 대상 원공시 rcept_dt를 포함하지 않으면 `CoverageError` 중단 (unknown으로 덮지 않음)
- core 변경 (사용자 알림 대상): `list_filings` → `FilingList`, `major_event`가 조회 기간 검사, `financials`·`audit_opinion`에 `report_rcept_dt` 필수, `resolve_version`에 `target_rcept_dt` 필수
- 지표 목록 v0.7 (fin.total_borrowings·fin.net_debt 변경 — 이 에이전트는 사용하지 않음). 테스트 21 passed

## 공통 변경 알림 (2026-11-05)

- `metrics_catalog.yaml` v0.6 (fin.ebitda 정의 변경 — 이 에이전트는 사용하지 않음. 계약 테스트 재실행 통과)
- `core/docs/api_fields.md` 9·10장 추가

## 1단계 후속 (2026-11-04) — 사용자 결정 반영, 개발문서 v0.5 → v0.6

사용자 결정 8건을 문서·코드에 반영했다.

- 문서 (`해외진출_자금수요_기업발굴_에이전트_개발문서.md` v0.6)
  - 6장: 시점 판정은 list.json `rcept_dt`만. 6.1 정정공시 규칙 신설 (as_of 이하 목록에 응답 rcept_no가 없으면 unknown, 원공시 list 정보만, "정정 전 원본 값 확인 불가", 원문 파싱 Phase 2, 백테스트 영향 건수)
  - 3.4: `Signal.value_status`·`value_note` 추가, `is_overseas`를 `bool | None`으로. `Filing`에 `report_nm_norm`·`prefixes`·`suffixes`·`filer_scope` 추가
  - 7.3·7.5·7.10: 정규화 분류, DS005를 원공시일로 조회 후 `resolve_version`, unknown 처리
  - 8.1.1·8.1.2·8.1.4·8.1.5: 확인된 필드로 교체. 8.1.3: 정규화(접두어·감싸기·접미어 제거, 양수=취득, 처분·양도 제외, 종속회사 공시는 본사 조달과 분리). 계정은 account_id 허용목록 + sj_div
  - 11.1: 전기 동기 누적 = 같은 보고서 `frmtrm_amount`. 11.2: CB·BW 납입일 `pymd`, 유상증자 납입일 없음 → ※결정 필요
  - 12.1 단위 테스트 표, 13장 1단계 완료 표시
- 공통 (사용자 알림 대상 core 변경)
  - `core.schemas.Metric.data_status`에 `"unknown"` 추가 (공통 양식 3장 수정)
  - `core.asof`: rcept_no 날짜 해석 삭제, `resolve_version` 추가
  - `core.clients.dart`: `major_event`·`financials`·`audit_opinion`이 `filings_asof`를 받아 행마다 `_version`(ok/unknown)을 붙이고 unknown 행의 값을 지움
  - 공통 양식 SKILL.md 6장(시점·정정)·10장(공통 테이블 컬럼 정식 정의, `runs.unknown_count` 추가)
  - `metrics_catalog.yaml` v0.5 (공통기준 원본과 `stride/core` 복사본)
- 그 밖의 문서: 구성문서 v1.5 .md(5장 확인 불가, 10.1 영향 건수, 0.00 7번), 오케스트레이터 v0.3, 화면_데이터_연결명세 v0.3("산출 불가"/"확인 불가"), 체크리스트 v0.3(2장 4번 삭제)
- 테스트: 18 passed (+live 1). `resolve_version`, unknown 값 제거 테스트로 교체

## 1단계 (2026-11-04) — `core/clients/dart.py` + DART 응답 필드 확인

- `core/clients/dart.py`: corpCode.xml, list.json(페이지 순회, 3개월 제한 확인), document.xml, DS005 6종, fnlttSinglAcntAll, 감사의견. 캐시·0.2초 간격·429/5xx 재시도, 오류 메시지에 키 미포함
- 확인 결과: `core/docs/api_fields.md` (표본 A·B·C, 대응표 `tests/golden/_probe_samples.json`)
- 확정한 ※확인 항목
  - 8.1.2 corp_code 없는 조회 기간 제한 = 3개월 (status 100)
  - 8.1.4 DS005 엔드포인트 6개 이름 = 문서와 같음. 자금 사용 목적 `fdpp_*` 6개 = 문서와 같음
  - 7.5 대상 국적 = `iscmp_nt` (값 정규화 필요)
  - 8.1.5 응답 필드: `thstrm_add_amount`는 CIS에만. sj_div는 BS/CIS/CF/SCE (IS 없음)
  - 8.1.5 단기금융상품 ID: 문서 ID 틀림 → `ifrs-full_ShorttermDepositsNotClassifiedAsCashEquivalents` 또는 `ifrs-full_OtherCurrentFinancialAssets`(회사별)
  - 8.1.5 장기차입금·사채 ID: 고정 ID로 안 됨 (회사·보고서마다 다름)
  - 11.1 전기 동기 누적 = 같은 보고서 CF의 `frmtrm_amount` (별도 조회 불필요)
  - 11.2 납입일: CB·BW는 `pymd`, 유상증자(piicDecsn)는 필드 없음
- 개발문서 수정 필요 사항은 사용자에게 보고 (문서는 아직 고치지 않음)

## 0단계 (2026-11-04) — core 기본 모듈

- `core/schemas.py`(공통 양식 3장 + `RouteDecision`), `evidence.py`, `asof.py`, `catalog.py`, `db.py`(공통 테이블 + `decisions`), `config.py`
- `core/metrics_catalog.yaml` = `공통기준/metrics_catalog.yaml` v0.4 복사
- 공통 계약 테스트 틀 `tests/unit/test_contract.py`
