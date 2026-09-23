# P4-PLAN-05b

진행 상한 설정 — 업무 단계 진행기의 재작성·재시도 상한을 설정으로 바꾼다. 기준: 설계 v0.8 2차 /
D-01~90 / 사용자 결정 2026-09-24(DEVELOPMENT.md 1.8절). 선행: P4-05 완료(스키마 v20).

이 세션(S-025)에서 시작 상태(`main`/`a933457`, clean, 로컬 `origin/main` 과 같음)를 확인하고
`scripts\run-tests.ps1` 로 기준선을 돌린 뒤 이 plan 을 **구현 전에** 기록한다. 기준선 수치는 5절에 적는다.

범위는 **P4-05b 하나**다. 같은 세션에서 이어 할 P4-06(지식)은 별도 plan(`P4-PLAN-06`)이다. Project
단위 상한·새 화면의 상세 설정(UI-04), QG-02~07 의 게이트별 수정 한도(P4-01 `quality_gate_setting.
repair_limit` — 이름이 같지만 다른 설정이다, 3.6)는 건드리지 않는다.

## 1. 현재 구현과 차이 (코드 대조)

1. `domain/work_flow.py` 의 상수 `REPAIR_LIMIT = 2`·`TASK_ATTEMPT_LIMIT = 2` 가 상한이다. 설정·이력·
   조회가 없다.
2. **준비 산출물의 상한이 plan 과 다르다.** `_stage_step` 은 `prep:{stage}` 키로 첫 작성과 재작성을
   **함께 세고** `attempts >= REPAIR_LIMIT(2)` 에서 멈춘다 — 첫 작성 1 + 재작성 **1**. P4-PLAN-05 3절·
   AC-7 과 결과 문서는 "재작성 상한 2" 라고 적었다. QG-01 재작성(`intent_repair`)은 재작성만 세서
   2회가 맞다. Task 재시도는 `task:{key}` 로 모든 시도를 세고 `>= 2` — 첫 시도 + 재시도 1 로 맞다.
3. **상한 뒤의 "계속 진행" 은 한 번 더 가지 않는다.** DEVELOPMENT.md 9절은 "사람의 계속 진행이 한 번
   더 시도한다" 라고 적었지만 `resume` 은 같은 판정을 다시 볼 뿐이라 시도 수가 상한 이상이면 같은
   대기로 돌아간다. 시험(`test_a_failed_task_is_retried_once_and_then_waits_for_a_person`)의 마지막
   단언이 `waiting_human` 도 받아 이 차이를 드러내지 못했다. 대기 카드의 "다시 시도" 도 상한 대기에서는
   아무 것도 하지 않는다.

2·3 은 이 작업이 **설정의 뜻에 맞춰 고친다**(3.2·3.4). 2 는 기본값에서 준비 재작성이 1 → 2 회로
늘어나는 동작 변경이며, P4-05 plan·사용자 결정의 정의("다시 쓰는 횟수, 기본 2")와 맞추는 것이다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| 설정 둘: `repair_limit`(초안·준비 산출물을 다시 쓰는 횟수, 기본 2), `task_retry_limit`(실패한 구현·검증·분석 작업을 다시 시도하는 횟수, 기본 1). 범위 0~10, 0 = 자동으로 다시 하지 않고 바로 사람에게 | 무제한 값, Project 단위 층(UI-04), 파일 설정 |
| 시스템 기본값 = 환경 변수 `HADS_REPAIR_LIMIT`·`HADS_TASK_RETRY_LIMIT`, 기동 때 검증(이상한 값이면 기동 실패)·기동 로그 | |
| Case 별 조정: DB 이력(누가·언제·짧은 사유, 이전 값은 대체 상태로 보존). 우선순위 `Case 명시 → 시스템 기본값`. 종료 Case 거부 | 종료 Case 의 조정(예산만 예외인 현재 규칙 유지) |
| 진행기가 걸음마다 그 시점의 유효 한도를 읽음(`FlowState.limits`), 시도 수 초기화 없음. 상한 대기의 사유에 한도·사용·출처 | QG-02~07 게이트 수정 한도(P4-01) |
| `GET /api/cases/{id}/progress` 에 유효 한도·출처·이력, `PUT /api/cases/{id}/progress/limits` | |
| 화면: 상한 대기 카드의 "재작성 2/2"·"한도를 올리고 계속", 관리 화면 정책 패널의 현재 한도·출처·변경 | 새 화면의 상세 설정(UI-04) |
| 스키마 v21(표 하나)·이행 시험 | |

## 3. 설계

### 3.1 값과 출처

- `domain/work_flow.py`: `DEFAULT_REPAIR_LIMIT = 2`, `DEFAULT_TASK_RETRY_LIMIT = 1`, `LIMIT_MIN = 0`,
  `LIMIT_MAX = 10`, `@dataclass(frozen=True) ProgressLimits(repair_limit, task_retry_limit)` 와
  범위 검사 `check_limit(key, value)`. 순수 판정은 값만 본다 — DB 도 환경도 모른다.
- `controller/config.py`: `HADS_REPAIR_LIMIT`·`HADS_TASK_RETRY_LIMIT` 를 정수로 읽고 범위를 벗어나거나
  정수가 아니면 `ValueError`(기동 실패, 인라인 한도·PC 판정 기준과 같은 자리). `ControllerConfig.
  progress_limits`. 기동 로그 `startup ... repair_limit=N task_retry_limit=M`.
- `Repository(..., progress_limits=ProgressLimits())` — `_repo`·`app` 이 설정값을 넘긴다.

### 3.2 판정 (`next_step`)

| 대상 | 세는 키 | 사람 대기 조건 | 기본값에서 |
|---|---|---|---|
| QG-01 재작성 | `intent_repair`(재작성만) | `repairs >= repair_limit` | 재작성 2 (그대로) |
| 준비 산출물 | `prep:{stage}`(첫 작성 포함) | `attempts - 1 >= repair_limit` | 재작성 1 → **2** (1.2 수정) |
| Task·분석 | `task:{key}`·`analysis`(모든 시도) | `attempts - 1 >= task_retry_limit` | 재시도 1 (그대로) |

상한 대기의 사유(`wait[0]`)에 `limit_key`·`limit`·`used`·`limit_source` 를 싣는다 — 카드가 "재작성
2/2" 를 그리고 어떤 한도를 올릴지 안다. 진입 거부에서 온 `gate_repair_exhausted`(QG-01 미통과 거부)
에는 싣지 않는다(상한이 아니라 게이트 판정이다).

### 3.3 Case 별 조정 (스키마 v21)

```
progress_limit_setting(id, case_id, revision, limit_key IN ('repair_limit','task_retry_limit'),
    limit_value INTEGER 0..10, set_by, reason_summary ≤200, state IN ('current','superseded'),
    created_at, superseded_at)
```

- `set_progress_limits(case_id, values: dict, set_by, reason_summary)` — 준 키만 바꾼다. 같은 키의
  현재 행을 `superseded` 로 두고 새 행을 넣는다(예산 한도와 같은 방식, `revision` 은 Case 안 순번).
  종료 Case 는 `PolicyRefused([case_already_closed])`. 범위 밖 값은 API 가 422 로, 저장 계층도 거부.
- `progress_limits(case_id)` → `{repair_limit: {value, source, setting}, task_retry_limit: {...},
  system_default: {...}, history: [...], range: {min, max}}`. `source` 는 `case_setting`·
  `system_default`.
- **데이터 이행 없음.** 옛 Case 는 행이 없고 시스템 기본값 출처다.

### 3.4 동작

- 진행기는 `flow_state` 가 모을 때 유효 한도를 넣는다 — 걸음마다 그 시점 값이다. 시도 수는 초기화하지
  않는다.
- `PUT /api/cases/{id}/progress/limits` 는 기록 뒤 **사람 입력으로 진행기를 부른다**(예산 한도 변경과
  같은 `_after_human_input`). 상한 대기에서 한도를 올리면 그 자리에서 다음 걸음이 한 번 더 가고, 다시
  실패하면 새 한도에서 멈춘다. 한도를 올리지 않은 "계속 진행" 은 같은 대기로 돌아간다(1.3 을 문서와
  시험에 바로 적는다).
- 한도를 내려 이미 쓴 시도 수보다 작아져도 기록은 그대로다 — 다음 판정에서 사람 대기가 될 뿐이다.

### 3.5 화면

- `web/src/api.ts`: `ProgressLimitsView`, `progressApi.setLimits`, `progress.limits`.
- `ProgressCards.tsx`: 상한 대기(`limit_key` 가 있는 대기) 카드에 "재작성 N/M"·"재시도 N/M"·출처,
  버튼 **"한도를 올리고 계속"**(현재 한도 + 1, 사유 "대기 카드에서 한도를 올림"). 상한 대기에서는
  아무 것도 하지 않던 "다시 시도" 를 보이지 않는다. 한도가 이미 10 이면 버튼 대신 안내.
- 관리 화면 `PolicyPanel`: "진행 상한" 절 — 두 값·출처·시스템 기본값·변경 입력·이력.

### 3.6 이름이 같은 다른 설정

P4-01 의 `quality_gate_setting.repair_limit` 은 **QG-02~07 게이트별** 수정 한도(`remediation_cycle`)
이고 진행기가 쓰지 않는다. 이 작업의 `repair_limit` 은 **진행기의 QG-01·준비 산출물 재작성** 한도다.
API 경로(`/quality-gates` 대 `/progress/limits`)와 화면 절 제목으로 나누고 합치지 않는다 — 합치면
P4-01 의 판정·예약 모델을 함께 바꿔야 한다.

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | 유효 한도는 `Case 명시 → 시스템 기본값`(환경 변수 → 코드 기본값 2·1). 조회가 값·출처를 준다 |
| AC-2 | 환경 변수가 정수가 아니거나 0~10 밖이면 기동이 실패한다. 정상 값은 기동 로그에 남는다 |
| AC-3 | Case 조정은 이력으로 남는다(이전 값 `superseded`, 주체·사유·시각). 준 키만 바뀐다 |
| AC-4 | 범위 밖 값은 422, 종료 Case 는 409 `case_already_closed` 로 거부한다 |
| AC-5 | 상한 대기 뒤 한도를 올리면 한 번 더 가고, 다시 실패하면 새 한도에서 멈춘다. 시도 수는 초기화되지 않는다 |
| AC-6 | 한도를 올리지 않은 계속 진행은 새 실행 없이 같은 대기다 |
| AC-7 | `task_retry_limit = 0` 이면 첫 실패에서, `repair_limit = 0` 이면 첫 지적에서 사람 대기다 |
| AC-8 | 준비 산출물 재작성이 설정 값만큼(기본 2) 간다 |
| AC-9 | v20 DB 가 v21 로 이행되고 옛 Case 는 시스템 기본값 출처다. 기존 행을 바꾸지 않는다 |
| AC-10 | 대기 카드가 "N/M" 과 "한도를 올리고 계속" 을 보이고 누르면 진행이 이어진다(브라우저 시험) |

## 5. 검증

- 순수 판정: `FlowState` 를 직접 만들어 세 대상 × (기본값·0·올린 값)의 걸음을 본다.
- 제어부: `processing_harness` 위의 진행기 시험 — 실패하는 구현으로 상한 대기 → 계속 진행(같은 대기,
  실행 수 그대로) → PUT 로 한도 올림(실행 하나 더, 다시 대기, `used = limit`) → 이력 조회. 재시도 0.
  QG-01 재작성 0. 준비 산출물 재작성 2회(필수 항목이 빈 결합 기록).
- 설정: `load_config` 에 환경 변수를 주어 정상·비정수·범위 밖.
- 이행: v20 스키마 DB 를 만들어 v21 로 올리고 조회.
- 브라우저: `test_web_shell.py` 에 상한 대기 카드 → "한도를 올리고 계속" → 진행 재개.
- 전체: `scripts\run-tests.ps1`. 실제 CLI 라이브는 하지 않는다 — 판정·기록·화면이며 CLI 동작이 바뀌지
  않는다(P4-06 라이브에서 기본값 경로가 함께 돈다).

기준선(S-025 시작, 변경 전): 5.1 에 적는다.

### 5.1 기준선

`pwsh -File scripts\run-tests.ps1`(변경 전, HEAD `a933457`) → 웹 빌드 성공, 웹 단위 **18** 통과,
pytest **633 통과**(6분 57초, 흔들리는 P4-02 시험도 이번엔 통과), P1 계약 unittest **18** 통과.
경고 2건은 기존 deprecation 이다.

## 6. 경계

- 한도는 사람의 결정이 아니며 권한을 만들지 않는다. 한도를 올리는 것은 "한 번 더 시도해도 된다" 이지
  결과의 인수·예외 수용이 아니다.
- 예산 강제와 별개다 — 한 번 더 가는 실행도 진입 검사·예산 예약을 그대로 지난다.
