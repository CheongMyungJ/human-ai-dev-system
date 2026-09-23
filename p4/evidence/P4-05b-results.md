# P4-05b 실행 결과 — 진행 상한 설정

기준: [P4-PLAN-05b](../../plans/P4-PLAN-05b.md) / 사용자 결정 2026-09-24(DEVELOPMENT.md 1.8절) / 스키마 **v21**.
세션 S-025. 같은 세션에서 이어 한 P4-06 은 [P4-06 결과](P4-06-results.md)다.

## 1. 구현 결과

- **설정 둘**(`domain/work_flow.py`): `repair_limit`(초안·준비 산출물을 **다시 쓰는** 횟수, 기본 2),
  `task_retry_limit`(실패한 구현·검증·분석 작업을 **다시 시도하는** 횟수, 기본 1). 범위 0~10, 0 은 "자동으로
  다시 하지 않고 바로 사람에게". 무제한 값은 없다. 판정은 `FlowState.limits`(`ProgressLimits`) 값만 본다.
- **세는 방식**: QG-01 재작성은 재작성만(`intent_repair`), 준비 산출물은 첫 작성을 뺀 재작성(`prep:{stage}`
  시도 수 − 1), Task·분석은 첫 시도를 뺀 재시도. 상한 대기의 사유에 `limit_key`·`limit`·`used`·
  `limit_source` 를 싣는다(진입 거부에서 온 `gate_repair_exhausted` 에는 싣지 않는다 — 상한이 아니라 게이트
  판정이다).
- **시스템 기본값**(`controller/config.py`): `HADS_REPAIR_LIMIT`·`HADS_TASK_RETRY_LIMIT`. 정수가 아니거나
  범위 밖이면 기동 실패. 기동 로그 `repair_limit=N task_retry_limit=M`.
- **Case 별 조정**(v21 `progress_limit_setting`): 준 키만 새 행, 같은 키의 이전 행은 `superseded`(주체·사유·
  시각). 종료 Case 는 `case_already_closed`(409). 우선순위 `Case 명시 → 시스템 기본값`. 데이터 이행 없음.
- **API**: `GET /api/cases/{id}/progress` 에 `limits`(값·출처·설정 행·시스템 기본값·범위·이력), 진행 상태
  (`progress.limits`)·정책 조회(`policy.progress_limits`)에도 싣는다. `PUT /api/cases/{id}/progress/limits`
  (값·사유 요약) — 기록 뒤 **사람 입력으로 진행기를 부른다**(예산 한도 변경과 같은 경계).
- **화면**: 새 화면의 상한 대기 카드(`LimitWaitCard`) — "재시도 1/1 (시스템 기본값)"·**"한도를 올리고 계속"**
  (현재 + 1, 사유 "대기 카드에서 한도를 올림"), 최대(10)면 버튼 대신 안내. 상한 대기에서 아무 것도 하지
  않던 "다시 시도" 는 보이지 않는다. 관리 화면 정책 패널의 "진행 상한" 절(값·출처·시스템 기본값·변경·이력).
- **시험 도구**: 가짜 codex 표지 `HADS_FAKE_IMPL_NOCHANGE`(구현 실행이 파일을 바꾸지 않음 → 실패).

## 2. 코드 대조에서 찾아 고친 것 둘 (plan 1절)

1. **준비 산출물의 상한이 plan 보다 한 번 적었다.** P4-05 의 `_stage_step` 은 첫 작성까지 세어
   `attempts >= 2` 에서 멈췄다 — 재작성 **1** 회. P4-PLAN-05 AC-7·결과 문서는 "재작성 상한 2" 였다. 설정의
   뜻(다시 쓰는 횟수)에 맞춰 첫 작성을 빼고 세니 기본값에서 재작성이 **2** 회가 됐다(동작 변경,
   `test_preparation_rewrites_run_up_to_the_setting` — 계획 작성 3회: 첫 작성 1 + 재작성 2).
2. **상한 뒤 "계속 진행" 은 한 번 더 가지 않았다.** DEVELOPMENT.md 9절은 "사람의 계속 진행이 한 번 더
   시도한다" 고 적었지만 `resume` 은 같은 판정을 다시 볼 뿐이라 같은 대기로 돌아갔다. P4-05 시험의 마지막
   단언이 `done` 도 받아 차이를 드러내지 못했다. 그 시험을 실제 동작(같은 대기·구현 실행 2 그대로)으로 고치고,
   한 번 더 가는 길은 한도를 올리는 것으로 적었다.

## 3. 성공 기준 근거

| 기준 | 근거 (`tests/test_progress_limits.py` 등) |
|---|---|
| AC-1 | `test_a_case_setting_overrides_the_system_default_and_keeps_its_history`(시스템 기본값 출처 → Case 명시 출처, 주지 않은 키 그대로) |
| AC-2 | `test_the_system_default_comes_from_the_environment_and_bad_values_stop_startup`(정상·0·10·11·-1·비정수), `test_the_startup_log_records_the_limits` |
| AC-3 | 같은 AC-1 시험(이력 두 행: `superseded`·`current`, 주체·사유·대체 시각) |
| AC-4 | 같은 시험(11·-1·빈 요청 422, 거부는 이력을 남기지 않음), `test_a_closed_case_refuses_a_limit_change`(409 `case_already_closed`), `test_limits_have_no_unlimited_value` |
| AC-5 | `test_raising_the_limit_goes_once_more_and_stops_again_at_the_new_limit`(구현 2 → 한도 2 로 올림 → 진행 요청 `origin_ref = progress_limits` → 구현 3 → `used 2/2`·`case_setting` → 고친 뒤 한도 3 → 종료) |
| AC-6 | 같은 시험(올리지 않은 계속 진행 → 같은 대기·구현 2 그대로·전송 열림), `test_work_progressor.py::test_a_failed_task_is_retried_once_and_then_waits_for_a_person`(고친 단언) |
| AC-7 | `test_a_zero_retry_limit_waits_on_the_first_failure`(구현 1), `test_a_zero_repair_limit_waits_on_the_first_gate_finding`(의도 초안 1·독립 검토 1), 순수 판정 시험 셋(재시도·준비·QG-01 × 기본·0·올린 값) |
| AC-8 | `test_preparation_rewrites_run_up_to_the_setting`, `test_preparation_rewrites_count_only_the_rewrites` |
| AC-9 | `test_a_v20_database_gets_no_limit_it_never_had`(커밋된 v20 스키마 → v21 이상, 표 비어 있음, 옛 Case 시스템 기본값 출처, DB CHECK 가 11 거부, 멱등) |
| AC-10 | 브라우저 `test_web_shell.py::test_a_limit_card_raises_the_limit_and_goes_once_more`(카드 "재시도 1/1"·시스템 기본값·"다시 시도" 없음 → 누름 → 구현 3·"재시도 2/2"·"이 업무에서 정함", 이력 한 행) |

## 4. 검증

- 집중 시험: `tests/test_progress_limits.py` **23** 통과, 브라우저 1 통과, 기존 진행기·이행 시험 통과.
- 전체: [P4-06 결과](P4-06-results.md) 3절의 최종 `scripts\run-tests.ps1` 에 포함된다.
- 실제 CLI 라이브는 따로 하지 않았다 — 판정·기록·화면이며 CLI 동작이 바뀌지 않는다. P4-06 라이브의 업무
  진행이 기본값 경로를 함께 지난다.

## 5. 경계

- 한도는 사람의 결정이 아니며 권한을 만들지 않는다. 한도를 올리는 것은 "한 번 더 시도해도 된다" 이지 결과의
  인수·예외 수용이 아니다. 한 번 더 가는 실행도 진입 검사·예산 예약을 그대로 지난다.
- QG-02~07 의 게이트별 수정 한도(P4-01 `quality_gate_setting.repair_limit`)는 다른 설정이며 바꾸지 않았다.
- Project 단위 상한과 새 화면의 상세 설정은 UI-04 다.
