# 오케스트레이터 CHANGELOG

기준 개발문서: `에이전트_개발문서/오케스트레이터_개발문서.md` v0.9

## 도구 설계 보완 (2026-11-11) — 개발문서 v0.9

- `read_xbrl` 제거. TOOLS 설명을 "언제: / 입력: / 출력:" 한 줄로 (프롬프트에 그대로)
- DART status 020 → `core.clients.dart.DartQuotaError` (캐시 안 함, 같은 날 캐시 밖 호출 차단). 노드 가드·run_tool·게이트·배치·수집·검증 재조회·기업개황에서 삼키지 않음. 탐색은 분석 대기(사유 표시), 감시는 미룸(커서 = 미룬 첫 공시 날짜)
- 조사 루프: 같은 도구·인자 반복은 '이미 확인함'(스텝 포함), search_news 실패 시 '뉴스 사용 불가, 공시 근거로 진행' 후 그 실행 동안 제외. 결과에 tool_calls·repeats
- 시험 +9 (`tests/conftest.py`에 020 표시 초기화)

## 자율성 추가 (2026-11-11) — 개발문서 v0.8 7.6a

- 조사 도구 `agents/common/tools.py` 8개(읽기 전용, 기존 함수 감싸기, as_of 강제), 조사 루프 `core/agent_loop.py`(최대 6스텝·LLM 6회, 프롬프트 `core/prompts/agent_loop.md`), 채택 게이트 `agents/common/gate.py`(같은 접수번호·표·행 재판독, 기대 보고서·원화 단위·연결/별도·당기 열·허용 행 이름·값 일치)
- D1 = `fill.fill_missing`: 원천·소요 구성(현금, 단기금융상품, TTM 영업CF 구성 3개, 만기 차입금 빈 금액 행, 배당금)과 이자비용을 찾아 채택 값으로 파생 지표 재계산. 상각비·리스부채는 후보 기록만. discover·review에서 `replan` 대신 호출하고 채택이 있으면 검증 다시
- 감시: 새 공시마다 `investigate.investigate_filing`(루프 1회) → 알림 시점·검증 통과 요약을 `orc_investigations`에. 상한 = 재분석 상한
- 저장: `orc_agent_traces`(스텝·게이트 판정·토큰·시간), `orc_investigations`. `core/llm.py` 직전 호출 사용량(`usage_total`)
- `fin_items.maturing_debt_1y(overrides)`: 빈 금액 행만 채움(분류는 그대로)
- 시험: `tests/unit/orchestrator/test_autonomy.py` 16개 (as_of 차단, 기사 날짜 거르기, 루프 예산, 게이트 채택·기각 5종, 만기 차입금 덮어쓰기, 채우기 반영·재계산·근거 검사, 불일치 기각, LLM 없이 건너뜀, TTM 3구성, 조사 요약 검증·누수 셈)
- 평가: `scripts/eval_fill.py`, `scripts/monitor_replay.py`

## 방향 수정 (2026-11-10) — 개발문서 v0.7

- 기본 탐색 `default_criteria`: G1~G4 통과 + 대표 프로젝트에 S4 또는 S5. `min_funding_gap_ratio`·`exclude_rule_ids` 기본값 제거 (재무 위험은 표의 경고 열)
- `apply_criteria`: 진행 단계 조건은 `gates_g1_g4`(scope_reason이 'G5만 실패'면 통과)로 판정. 자금 공백 비율 조건은 값이 없으면 제외하지 않고 확인 필요
- `row_inputs.signal_types`: 게이트 통과 프로젝트의 신호만 (게이트 통과 프로젝트가 없으면 전체)
- `BoardRow`: `liquidity`(B 원천·소요 항목 mdict), `funding_status`(해외 용도 조달 상태), `risk_warnings`(상장 규정 해당 + 거래 상태 경고) 추가. 이전 행은 기본값으로 읽힘
- 기본 정렬 `common.default_sort_key` / `DEFAULT_SORT_TEXT`. `INSTANT_FILTER_FIELDS`에 원천÷소요·원천−소요·부채비율. `REQUIRED_METRICS`의 자금 공백 비율 → 원천÷소요
- 시험: 기본 탐색 3개 추가·1개 교체 (rule hit·자금 공백 음수·값 없음은 통과, S1·S2만이거나 G1~G4 실패면 제외, G5만 실패는 통과)

## 1~7단계 (2026-11-09)

| 단계 | 완료 기준 | 결과 |
|---|---|---|
| 1 `core` 추가분 | 기존 에이전트 테스트 통과 | 통과 (`RouteDecision`, `decisions`는 이미 있었음) |
| 2 `rules.yaml` + `apply_rules` | 단위 테스트 | 통과 (자본잠식 49.9/50/99.9/100 시장별, 코스닥 자기자본 9.9억/10억, 감사범위 제한 한정 시장별 문구, unknown → None, source_date > as_of 미적용) |
| 3 `review_graph` (D1) | 골든 기업 1곳 사전검토서, 검증 통과 | 통합 시험(검증 실패 주입 → 재작성 → 표시) 통과. 실제 실행 결과는 HANDOFF |
| 4 `discover_graph` (D4) + 기본 탐색 시드 | 통합 테스트, funnel·제외 목록 | 30개 기업 fixture로 funnel이 단계별 필터와 일치, 제외 사유 100% 기록, 첫 실행 5곳·이후 K=20 |
| 5 `route_intent`, `answer_graph`, `board_filter` | 의도·조건 골든 | **골든 미작성**: 정답을 사람이 써야 함 (자체 결정 S24). 코드와 허용 필드 검증은 있음 |
| 6 `monitor_graph` + FeedItem | 재생 테스트 | 실행 1회 누락 후 다음 실행에서 처리, 같은 공시 중복 FeedItem 0건, 첫 감시 5곳 상한·미룬 공시 다음 실행 처리 |
| 7 화면 연동 + worker | 연결명세 모든 쿼리가 실제 DB에서 값 반환 | fixture DB로 `ui/queries.py` 전 함수 값 반환, 3페이지 렌더링 예외 없음 (`tests/ui/test_ui.py`) |

- 코드: `orchestrator/` (config, rules.yaml, rules, schemas, store, common, discover, review, answer, monitor, worker, prompts 8개), `stride/cli.py`
- 단위·통합: `tests/unit/orchestrator/test_orchestrator.py` 32개
- 실제 실행에서 고친 버그: 병렬 노드 스레드에서 worker DB 연결을 쓰던 문제(5곳 전부 분석 실패), 감시 대상에 분석 대기 기업을 넣어 첫 감시에서 76곳을 분석한 문제, 실패한 실행도 '완료'로 세어 첫 실행 상한이 풀리던 문제, 구독 한도로 LLM이 실패한 결과를 저장·재사용해 범위 밖으로 잘못 판정한 문제
- 자체 결정: HANDOFF.md '자체 결정' 표 S10~S20, S25~S26

## 실제 실행·백테스트 (2026-11-09)

- 실제 실행: 새 DB에서 기본 탐색 5곳 분석(첫 실행), 최종 0곳(범위 안 2곳 자금 공백 비율 산출 불가, 3곳 범위 밖). 검토서·답변·감시 동작 확인. `data/logs/orchestrator_demo.json`
- 백테스트 `scripts/replay.py`: 사례 3건, 사전 포착률 0/3, as_of 이후 근거 0건. `data/logs/backtest_2026-11-09.md`
