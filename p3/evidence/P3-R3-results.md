# P3-R3 결과 — 예산 예약·집계·정지

기준: [P3-PLAN-R3](../../plans/P3-PLAN-R3.md) / 설계 v0.7 / D-01~67 / 2026-09-22.
선행: P3-R2 완료(스키마 v9, pytest 313 + P1 계약 18). 이 단계 후 스키마 **v10**.

## 1. 한 줄 요약

R1이 기록만 하던 예산이 **실제로 배정을 정한다.** 배정 전에 Run 생성과 같은
트랜잭션에서 원자적으로 예약하고, 종료 후 정산하며, hard 도달은 그 한도를 소비하는
새 실행과 재배정을 막는다. 다만 **"강제한다"가 지표마다 같은 약속이 아니다** — 실행
수·검토 수·컨텍스트 크기는 절대 상한이고, 시간은 새 배정만 막으며 진행 중 실행의
초과 노출이 있을 수 있다. 토큰·비용의 hard 한도는 여전히 설정을 받지 않는다.

## 2. 검증 요약

| 항목 | 결과 |
|---|---|
| 자동 시험 | **pytest 341 + P1 계약 unittest 18 통과** (R2 시점 313 → +28). 저장소의 시험 스크립트로 확인 |
| 화면 빌드 | `npm run build` 성공 |
| 스키마 | **v10**. 커밋 이력의 v9 스키마로 만든 실제 DB의 이행 확인 |
| 실제 CLI | **실제 codex 1회**(codex-cli 0.154.0)가 실제 git 저장소에서 실행되고 사용량이 집계·정산됨 |
| 실제 강제 종료 | 제어부 강제 종료 후 한도·소비·예약이 그대로 복원 |
| 외부 반영 | 없음. push·PR·이슈는 이 단계에 없다(P5) |

라이브 원문은 [P3-R3-live.log](P3-R3-live.log), 상태는
[집계](P3-R3-budget-after-live-run.json)·[정지](P3-R3-budget-stopped.json)·[최종](P3-R3-budget-final.json)·[거부](P3-R3-refused.json)·[실행](P3-R3-live-run.json).

## 3. 만든 것

### 3.1 예약 계약 — 이 단계의 중심

R1의 `BUDGET_MEASUREMENT`("그 값을 어떻게 아는가") 옆에 `RESERVATION_KIND`("실행 전에
얼마를 잡을 수 있는가")를 두었다(`domain/budget.py`). **두 질문의 답이 다르기 때문에
표가 둘이다** — 실행 시간은 끝나면 정확히 잴 수 있지만 시작 전에는 얼마가 될지 모른다.

| 지표 | 측정 | 예약 | hard 보장 |
|---|---|---|---|
| `run_count` | exact | `exact_per_run` = 1 | **`absolute`** |
| `review_run_count` | exact | `exact_per_run` = 1 (reviewer 만) | **`absolute`** |
| `context_bytes` | exact | `exact_per_run` = 지시 + 고정 컨텍스트의 `byte_size` 합 | **`absolute`** |
| `execution_seconds` | exact | `open_ended_per_run` (진행 중 노출은 `now − assigned_at`) | `no_absolute_cap` |
| `elapsed_seconds` | exact | `case_clock` (예약 없음, Case 시작 시각에서 도출) | `no_absolute_cap` |
| `input/output_tokens`·`estimated_cost` | estimated | `post_hoc_reported` | **설정 거부** |

`budget_setting.enforcement` 에 `enforced_absolute` / `enforced_no_absolute_cap` /
`display_only` / `not_enforceable` 를 구분해 남기고, 조회의 `reservation_contract` 가
지표마다 **왜 그런지**를 함께 준다. 화면도 같은 구분을 보인다("절대 상한" / "새 배정만
차단 (절대 상한 아님)").

### 3.2 원자적 예약

`create_run()` 의 `transaction()`(=`BEGIN IMMEDIATE`) **안에서** 검사하고, Run 행과
고정 컨텍스트 참조와 예약 행을 함께 넣는다. 검사는 **두 층**이다.

- `evaluate_admission()` 의 `budget_hard_limit_reached` — 거부 사유가 진입 검사 표에
  기록된다(FR-14). 사람이 왜 실행이 열리지 않았는지 볼 수 있어야 한다.
- 트랜잭션 안의 재검사 — **마지막 한 칸의 경쟁**을 막는다. 진 쪽도 거부로 기록된다.

둘 중 하나만 두면 각각 다른 구멍이 생긴다. 앞의 것만 두면 동시 요청 둘이 같은 잔여량을
보고 함께 통과하고, 뒤의 것만 두면 실행이 사라진 이유가 기록되지 않는다.

`bump_generation()`(재배정)도 같은 검사를 지나고 **추가 예약**을 잡는다. 재배정은 CLI 를
다시 부르고 그것은 새 소비다(7절). 예산이 없으면 재배정하지 않으며 세대도 올리지 않는다.

### 3.3 정산 — 지표 단위 판단

| 예약 종류 | 정산 |
|---|---|
| `exact_per_run` | **언제나 확정.** 실패·취소·결과 불명이어도 호출은 있었고 이 값들은 더 커지지 않는다 |
| `open_ended_per_run` | 시계에서 도출(`assigned_at → finished_at`). 결과 불명·잔류 활동이면 값은 남기되 `unresolved` |
| `post_hoc_reported` | **어댑터가 준 값을 그대로 확정.** 주지 않았으면 `unresolved`·`unavailable` |

같은 결과의 재전송은 `report_result()` 의 기존 멱등 가드 **뒤에서** 정산하므로 중복
청구가 생기지 않는다.

### 3.4 집계와 정지

`budget_state()` 가 지표별 `settled / held / unresolved / exposure` 와 `complete`,
역할별·목적별 축, 경고, 정지, 예약 원문을 준다. **`exposure` 가 한도 판정값이다** —
확정 사용량만 보면 진행 중 실행과 결과 불명이 공짜가 된다.

`stop` 은 **도출한다. 저장하지 않는다.** `case.status` 를 바꾸지 않는다. 한도를 올리면
그 순간 다시 배정되며 별도의 "재개" 명령이 없다 — 상태를 컬럼에 적어 두면 그것을
되돌리는 경로가 필요해지고, 그 경로가 곧 `continue` 우회가 된다. 막는 것은 **새 실행
생성과 재배정 하나뿐**이고 결과 보고·이벤트 수신·산출물 저장·조회는 계속 받는다.

### 3.5 스키마 v10과 이행

새 표 `budget_reservation` 하나. **기존 표의 컬럼은 하나도 바꾸지 않았다.**

집계의 출처를 이 표 하나로 두었으므로 이행이 **기존 실행에도 행을 만든다**
(`source = migrated_from_run`). 그러지 않으면 스키마를 올리는 것만으로 소비가 0 이
된다 — "세션·Task 분할로 초기화하지 않는다"(D-61)는 이행에도 적용된다. 값은 `run` 표가
실제로 아는 것만 담고, 토큰을 보고하지 않은 옛 실행은 `NULL`·`unavailable` 이며 **0 이
아니다**.

## 4. 성공 기준 대조

| # | 기준 | 근거 |
|---|---|---|
| AC-1 | 한도 없는 Case 는 예산으로 막히지 않는다 | `test_an_unlimited_case_is_never_blocked_by_budget` + 기존 시험 전체 통과(예산 축 4건만 갱신) |
| AC-2 | hard 도달 시 거부되고 사유가 기록된다 | `test_a_hard_budget_now_stops_the_next_run`, 라이브 3번째 실행 409 |
| AC-3 | 마지막 한 칸의 경쟁에서 하나만 생성 | `test_the_last_slot_is_won_by_exactly_one_of_two_concurrent_requests` (두 연결·두 스레드) |
| AC-4 | 정지 중에도 진행 중 실행의 결과를 받는다 | `test_a_stopped_case_still_accepts_results_from_runs_already_in_flight` |
| AC-5 | Case 가 완료·취소로 바뀌지 않는다 | `test_reaching_a_hard_limit_does_not_close_or_cancel_the_case`, 라이브 `status = received` |
| AC-6 | 한도 변경으로만 재개. `continue` 우회 없음 | `test_raising_the_limit_resumes_and_there_is_no_continue_bypass`, 라이브 상향 후 201 |
| AC-7 | 검토 실행이 두 축에 한 번씩 | `test_a_review_run_is_counted_once_on_each_axis` |
| AC-8 | Task·역할·세션 분할로 초기화되지 않는다 | `test_splitting_tasks_and_roles_does_not_reset_the_case_budget` |
| AC-9 | 재시작 후 사용량·예약 복원 | `test_consumption_survives_a_reopened_database` + **실제 강제 종료** 시험 |
| AC-10 | 중복 보고가 두 번 세지 않는다 | `test_the_same_result_reported_twice_is_not_charged_twice` |
| AC-11 | 재배정이 새 소비, 예산 없으면 재배정 불가 | `test_a_reassignment_is_new_consumption_and_needs_budget` |
| AC-12 | 결과 불명의 예약을 해제하지 않는다 | `test_an_unknown_outcome_does_not_release_what_is_still_unknown` |
| AC-13 | 미보고는 `unavailable`, 0 이 아니다 | `test_unreported_tokens_are_unavailable_not_zero`, 라이브 `estimated_cost complete=False` |
| AC-14 | 추정 hard 거부 / 시간 hard 는 `no_absolute_cap` | `test_an_estimated_metric_still_refuses_a_hard_limit`, `test_a_time_limit_is_accepted_but_not_as_an_absolute_cap`, 라이브 409 |
| AC-15 | 실제 초과가 값·원인과 함께 기록된다 | `test_an_overshoot_is_recorded_with_its_cause` |
| AC-16 | `context_bytes` 는 전달한 패키지 크기 | `test_a_reservation_is_recorded_when_the_run_is_created` |
| AC-17 | v9 DB 의 기존 소비가 집계에 들어온다 | `test_a_v9_database_keeps_the_consumption_that_already_happened` |
| AC-18 | 예산이 게이트·기준·권한을 완화하지 않는다 | `test_a_budget_stop_does_not_relax_gates_criteria_or_permissions` |
| AC-19 | repair 한도와 분리 유지 | `test_the_budget_model_is_not_a_repair_counter` |
| AC-20 | 예산 축만 강제로 바뀌었다 | `test_budget_enforcement_did_not_spread_to_the_other_axes`, `test_the_policy_view_says_who_enforces_each_axis` |
| AC-21 | 제어부 DB 에 본문 없음 | `test_the_reservation_table_has_no_body_columns`, `test_no_prompt_or_output_bytes_reach_the_reservation_rows` |
| AC-22 | 실제 CLI 사용량이 집계·정산된다 | **라이브**: codex 가 `input_tokens 30627 / output_tokens 162` 를 보고했고 그대로 집계됨 |

계획에 없었지만 함께 고정한 것 둘. **멱등성이 예산보다 먼저다** — 같은 `run_id` 의 재전송은 예산이 소진돼도 409 가 아니라 기존 실행을 돌려준다(`test_resending_an_existing_run_id_is_not_refused_by_the_budget`). 그리고 **지표를 더하면 계약도 함께 더해야 한다**(`test_every_budget_metric_has_a_reservation_contract`) — 계약 없는 지표가 생기면 그 한도는 설정만 되고 아무 것도 막지 않는다.

## 5. 라이브 확인 원문 요약

실제 제어부·Runner 프로세스와 실제 git 저장소 하나, 실제 codex 실행 1회.

```
codex 능력: cancel_confirmed=unknown, installed=verified,
            safe_stop_next_call=verified, usage_reporting=verified
한도 설정: run_count 2.0 enforcement=enforced_absolute guarantee=absolute
추정 지표 hard 설정 → 409 ['hard_limit_not_enforceable']
실행 종료: outcome=completed exit=0 tool=codex-cli 0.154.0
어댑터 사용량: {"tokens": {"input_tokens": 30627, "cached_input_tokens": 27264,
               "output_tokens": 162, ...}, "cost_usd": "not_reported"}
집계: run_count 노출=1.0 확정=1.0
토큰: input=30627.0 complete=True / output=162.0
비용: 0.0 complete=False          ← codex 는 비용을 주지 않는다
실행 시간: 13.33초
두 번째 실행 → 201
세 번째 실행 → 409 ['budget_hard_limit_reached']
Case 상태: received (완료·취소로 바뀌지 않았다)
기록된 예산 거부: 1건
한도 상향 후 재요청 → 201
```

`cancel_confirmed = unknown` 이 이 단계의 설계를 정했다. 돌고 있는 CLI 를 확실히 끊을
수 없으므로 시간 지표의 hard 한도를 절대 상한으로 표시하지 않는다.

## 6. 구현 중 찾은 결함 — 라이브가 찾았다

### 어댑터가 실제로 준 값을 "모른다"로 내렸다

첫 라이브 실행에서 codex 가 `input_tokens: 30600` 을 보고했는데 **집계의 확정값이
0 이었다.**

원인: 정산의 확정 조건을 실행 단위로 잡고 `residual_activity == "none"` 을 요구했다.
그런데 **실제 codex 어댑터는 `residual_activity` 를 항상 `unknown` 으로 보고한다**
(P1-03의 프로세스 잔류 관측). 그래서 모든 실제 실행의 토큰이 영원히 `unresolved` 가
되고, 받은 관측을 전부 버리게 된다.

고침: 정산을 **지표 단위**로 판단한다. 잔류 프로세스가 **더 늘릴 수 있는 것**(실행
시간)과 **이미 보고된 것**(토큰)은 다르다. 실행 수·컨텍스트 크기는 결과가 불명해도 더
커지지 않으므로 언제나 확정하고, 보고된 토큰은 관측이므로 확정하되 `measurement =
estimated` 로 추정임을 남기며, 실행 시간만 결과 불명·잔류 활동에서 `unresolved` 로
둔다. 회귀 시험은
`test_a_reported_usage_is_settled_even_when_residual_activity_is_unknown` 이며
**실제 어댑터와 같은 보고(`residual_activity = unknown`)를 쓴다.**

같은 실수의 반대 방향도 막았다. 확정 조건을 느슨하게 묶으면 잔류 프로세스가 있는데
실행 시간을 최종으로 적게 된다.

### 같은 판단이 두 곳에 있었다

진입 검사와 Run 생성이 각각 예약값을 계산하면, 한쪽만 고쳐졌을 때 "검사는 통과했는데
생성이 막히는" 상태가 조용히 생긴다. `_planned_reservation_for()` 하나로 모았다.

## 7. 하지 않은 것 · 미검증

| 항목 | 위치 |
|---|---|
| **진행 중 실행을 초 단위로 끊는 것** | 하지 않는다. `cancel_confirmed = unknown`(P1-03)이며 시간 한도는 새 배정만 막는다. P6-03 정지·복구에서 다시 본다 |
| Autonomy·확인 지점의 강제 | **R4**. `enforcement` 가 여전히 `recorded_not_enforced / P3-R4` 다 |
| 게시 허용·실제 push·PR | **P5**. 예산이 강제로 바뀐 것이 게시 권한을 만들지 않는다 |
| `RemediationCycle`·repair 한도 모델 | **P4-01**. 예산 집계를 repair 횟수로 쓰지 않는다 |
| Project·Task 단위 예산 조정 | 계층이 없다. **만들지 않았다** — 없는 계층을 출처 값으로도 만들지 않는다 |
| 예산 preset(`low/normal/high`) | 범위 밖. 이름만으로 숨은 한도를 적용하지 않는다는 경계만 유지 |
| 지식 추출 실행의 소비 | **P4-07**. 그 실행이 생기면 같은 예약 경로를 탄다(별도 무제한 경로가 아니다) |
| 비용의 실제 청구액 대조 | 하지 않는다. codex 는 비용을 주지 않으며 `estimated_cost` 는 `complete = false` 다 |
| 여러 Runner·원격 환경의 예약 조정 | **P6-03**. 지금은 한 제어부 DB 의 트랜잭션으로만 보장한다 |
| CLI 내부 모델 호출 수 | 관측 범위 밖. `run_count` 는 **시스템이 시작한 호출**이며 그 사실을 계약에 남겼다 |

## 8. 이 단계가 만든 새 사실

- `enforcement.budget` 이 `recorded_not_enforced` → **`enforced`** 로 바뀌었다.
  R1이 "강제 없음"을 고정한 시험 4건을 갱신했다(`test_policy.py` 3건,
  `test_restart_recovery.py` 1건). **통과한 채로 남았다면 강제를 붙이지 않은 것이다.**
- `budget_setting.enforcement` 에 세 값이 늘었다(`enforced_absolute`,
  `enforced_no_absolute_cap`, `display_only`). R1·R2 시절 행의
  `recorded_not_enforced` 는 **지우지 않았고** 조회가 현재 판정을 따로 얹는다.
- `AdmissionRefusal.BUDGET_HARD_LIMIT_REACHED` 가 생겼다.
- `create_run()` 이 고정 컨텍스트 참조를 **같은 트랜잭션**에 넣는다. 예약한
  `context_bytes` 가 실제 참조와 어긋나지 않게 하기 위한 변경이며 판정은 그대로다.
