# `claude -p` 호출 규칙 (core/llm.py)

> 버전: v1.5 (2026-11-09) — 4.5 5곳 실제 실행 (해외진출 7단계)
> (v1.4 (2026-11-06)) — 4.4 코드 실측 (해외진출 6단계)
> (v1.3 (2026-11-05)) — 4.3 분류 묶음 호출 채택, LLM은 라벨만
> (v1.2 (2026-11-05)) — 4.3 주요사항 분류 묶음 호출 제안 실측
> (v1.1 (2026-11-05)) — 4장에 기업 1곳 실제 자료 실측 추가
> (v1.0 (2026-11-04)) — 실측으로 확정. 측정 기록: `data/logs/claude_cli_check*.json`, 도움말 `data/logs/claude_help.txt`
> 환경: Claude Code 2.1.318, Claude Pro 구독 로그인, Windows PowerShell

## 1. 고정 실행 옵션

`core/llm.py`의 `call_llm`은 항상 아래 옵션으로 실행한다. 프롬프트 본문은 stdin으로 넘긴다.

```
claude -p --output-format json --tools "" --strict-mcp-config --disable-slash-commands --no-session-persistence --system-prompt <system_common.md 내용> --json-schema <출력 Pydantic 모델의 JSON 스키마> --model <작업별 모델>
```

| 옵션 | 이유 (실측) |
|---|---|
| `--output-format json` | 결과 JSON의 `structured_output`(스키마 지정 시) 또는 `result`를 읽는다. `is_error`, `usage`, `duration_ms`도 로그에 남긴다 |
| `--tools ""` | 도구 사용 금지 (주어진 자료만 사용) |
| `--strict-mcp-config` | PC에 연결된 MCP 서버 도구 목록이 끼어들지 않게 한다. 없으면 입력 토큰이 11만 개까지 늘었다 |
| `--disable-slash-commands` | 스킬 목록 로딩 차단 |
| `--no-session-persistence` | 호출마다 세션 파일이 쌓이지 않게 한다 |
| `--system-prompt` | Claude Code 기본 시스템 프롬프트를 교체. 기본 대비 입력 토큰 약 2만 8천 → 약 3천 |
| `--json-schema` | 출력 형식 강제. `structured_output`에 스키마대로 들어옴 (6/6회 정상) |
| `--model` | 작업별 지정 (3장) |

**쓰지 않는 옵션**: `--bare` (API 키 전용, 구독 로그인을 읽지 않음).

## 2. 실측 결과 (최소 옵션, 짧은 추출 프롬프트)

| 모델 | 성공 | 소요 시간 | 입력 토큰 (고정 부담 포함) |
|---|---|---|---|
| opus | 3/3 | 3.2~3.4초 | 3,093 |
| sonnet | 3/3 | 3.8~6.4초 | 3,097 |

고정 부담은 호출당 약 3천 토큰이다. 실제 작업은 자료(공시 섹션, 기사 40건 등) 길이만큼 더 든다.

## 3. 작업별 모델 (기본값, `config.py`에서 바꿀 수 있음)

| 작업 | 모델 | 이유 |
|---|---|---|
| 추출·분류 (extract_periodic_plan, classify_major_event, extract_news, generate_news_queries, parse_criteria, parse_intent, parse_board_filter) | sonnet | 정해진 스키마 추출. 구독 한도 절약 |
| 판단 지점 (replan, resolve_conflict, plan_followup) | sonnet | 선택지 고르기 |
| 검증 (verify_claims, check_claim) | sonnet | 문장-근거 대조 |
| 문장 작성 (write_report, summarize_board, synthesize_report, answer_question) | opus | 문장 품질. 호출 수가 적음 |

## 4. 처리량

### 4.1 실측 (2026-11-05, 표본 D 1곳, 순차 실행, `scripts/probe_llm_throughput.py`, 기록 `data/logs/llm_throughput_D.json`)

LLM 노드 코드 전이라 개발문서 10장 프롬프트 + 실제 자료(최근 12개월 공시 38건 중 주요사항 대상 10건, 사업의 내용 키워드 문단 6,196자, 기사 40건)로 호출 흐름을 재현했다. 충돌 판단(0회)·재추출(0회)·검증 에이전트·오케스트레이터 호출은 포함하지 않았다.

| 노드 | 모델 | 호출 | 소요(초) | 입력 토큰 | 출력 토큰 |
|---|---|---|---|---|---|
| extract_periodic_plan | sonnet | 1 | 13.2 | 26,193 | 1,521 |
| classify_major_event | sonnet | 10 | 63.0 | 75,151 | 5,724 |
| generate_news_queries | sonnet | 1 | 4.6 | 5,866 | 272 |
| extract_news | sonnet | 1 | 19.3 | 13,444 | 2,449 |
| verify_claims | sonnet | 1 | 10.1 | 7,270 | 1,346 |
| write_report | opus | 1 | 58.0 | 7,497 | 6,349 |
| **합계** | | **15** (성공 15) | **168.2** | **135,421** | **17,661** |

- 20곳 환산(같은 기업 규모 가정, 측정 아닌 계산): 순차 약 56분, `LLM_CONCURRENCY=3`이 이상적으로 나뉘면 약 19분. 입력 약 271만·출력 약 35만 토큰, 호출 300회. 주요사항 공시가 없는 기업은 호출 5회·약 105초로 줄어든다.
- 동시 실행 효과와 Pro 구독 한도 소진량은 측정하지 않았다.

### 4.3 주요사항 분류 규칙 + 묶음 1회 호출 (2026-11-05 채택, 해외진출 v0.9 7.5)

채택 조건: LLM은 라벨(용도·해외 여부·변경 방향)만, 금액은 DS005 또는 거래소 공시 정형 칸에서만. 아래 측정은 채택 전 스키마(금액 필드 포함)로 잰 값이라 출력 토큰은 다소 줄 수 있다.

`scripts/probe_classify_batch.py`, 기록 `data/logs/classify_batch.json`. 표본 D 재측정.

- 규칙(LLM 없음): R1 종속회사·자회사 조달, R2 DS005 취득 대상 국적 대한민국, R3 DS005 조달 용도가 운영·채무상환뿐, R4 DS005 최신본이 아닌 중간 정정. 나머지는 묶어 1회.
- 묶음 6건 (입력 10,571자): 19.6초·입력 14,468·출력 3,063토큰. 같은 6건 개별 호출: 33.6초·입력 43,776·출력 2,665토큰.
- 개별과 비교: 용도·해외 여부·변경 방향 6/6 일치. 금액 표기 4/6 다름 (개별 null인데 묶음이 금액을 채운 2건, US$ 표기와 원 표기 1건, `원` 글자 유무 1건). 이 차이 때문에 금액 필드를 스키마에서 뺐다.

| 구분 | 호출 | 소요(초) | 입력 토큰 | 출력 토큰 | 20곳 순차 / 동시 3개 |
|---|---|---|---|---|---|
| 현재 설계 (4.1 실측) | 15 | 168.2 | 135,421 | 17,661 | 약 56분 / 19분 |
| 채택 설계 (4.1에서 분류 부분만 묶음 실측값으로 교체한 계산, 코드로 재측정 전) | 6 | 124.8 | 74,738 | 15,000 | 약 42분 / 14분 |

소요 시간의 46%는 write_report(opus 58초)다. 표본 9곳 분류 대상별 호출 필요 건수는 `core/docs/api_fields.md` 20장.

### 4.5 5곳 실제 실행 (2026-11-09, 해외진출 7단계 그래프, `stride/tests/golden/_usage_run.py`, 기록 `data/logs/usage_run_5.json`)

기록 재사용 없음, 순차 실행, sonnet. 8·9단계(update_state, write_report의 opus 호출) 전이라 보고서 호출은 포함하지 않는다. **`/usage` 막대 변화는 재지 않았다** (실행 전 값을 받지 못함).

| 기업 유형 | 호출 | 입력 토큰 | 출력 토큰 | 전체 시간(초) |
|---|---|---|---|---|
| 양성 (G-POS_주) | 5 | 78,205 | 7,248 | 66.1 |
| 자금 충분 (G-RICH_F) | 5 | 74,674 | 7,650 | 65.9 |
| 지배구조 (G-GOV_I) | 3 | 35,810 | 4,493 | 39.5 |
| 국내 용도 (G-DOM_주) | 4 | 35,488 | 2,002 | 30.5 |
| 신호 없음 (G-NONE_H) | 3 | 29,651 | 840 | 18.6 |
| **합계** | **20** | **253,828** | **22,233** | **220.7** |

기업 1곳 평균: 호출 4.0회, 입력 50,766, 출력 4,447, 44초. 20곳 환산(순차): 호출 약 80회, 입력 약 102만, 출력 약 8.9만 토큰, 약 15분.
신호가 없는 기업은 3회(기사 검색어·검증 호출 없음), 해외 투자가 있는 기업은 5회다.

### 4.4 코드 실측 (2026-11-06, 해외진출 6단계 추출 4개 노드, 표본 G-POS 주 1곳, `scripts/measure_llm_company.py`, 기록 `data/logs/llm_measure_*.json`)

`core/llm.py`로 실제 호출. 검증·충돌 판단·보고서 호출은 포함하지 않는다(7~9단계). 사용량 소진 비율은 재지 않았다 (`/usage`는 코드에서 읽을 수 없음).

| 노드 | 모델 | 호출 | 소요(초) | 입력 토큰 | 출력 토큰 |
|---|---|---|---|---|---|
| extract_periodic_plan | sonnet | 1 | 7.5 | 12,502 | 723 |
| classify_major_event | sonnet | 1 | 19.2 | 20,718 | 2,794 |
| generate_news_queries | sonnet | 1 | 4.9 | 5,397 | 270 |
| extract_news | sonnet | 1 | 9.7 | 8,521 | 1,033 |
| **합계** | | **4** | **41.3** | **47,138** | **4,820** |

이번 세션 실제 호출 전체: 12회, 111.8초, 입력 146,103, 출력 12,263 (G-POS 주 2회, 보조 1회).

### 4.2 v1.0 추정 (보정 전, 4.1이 우선)

- 기업 1곳 해외진출 에이전트 LLM 호출: 약 6~9회 (계획 문단 1~3, 주요사항 분류 1~3, 검색어 1, 기사 1, 충돌 0~2, 검증 1, 보고 1)
- 재무 건전성 에이전트: 0회
- 탐색 1회(K=20): 약 120~180회 + 오케스트레이터 4~6회. 순차 4초 기준 약 8~12분, 동시 3개면 약 3~4분
- Pro 구독 한도 안에서 하루에 돌릴 수 있는 탐색 횟수는 실제 자료 길이에 따라 크게 달라진다 → 해외진출 6단계(골든 G-POS)에서 기업 1곳의 실제 토큰을 재고 K와 동시 실행 수(`LLM_CONCURRENCY`, 기본 3)를 정한다.

## 5. 오류 처리

- 종료코드 ≠ 0 또는 `is_error=true` → 1회 재시도 후 `LLMError`.
- 출력에 "Login expired" / 인증 오류 → 재시도하지 않고 `LLMAuthError` (사용자가 `claude` 실행 후 `/login`).
- 사용량 한도 메시지 → `LLMRateLimitError`. batch는 남은 기업을 다음 실행으로 넘긴다.
- Windows에서는 `shutil.which("claude")`로 실행 파일 경로를 찾는다 (`claude.cmd`일 수 있음). stdin·stdout 인코딩은 utf-8로 고정.
