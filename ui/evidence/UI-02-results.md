# UI-02 실행 결과 — 입력·실행 제어

상태: **완료**  
기준: 설계 v0.8 2차 / D-01~90 / 2026-09-23  
계획: [UI-PLAN-02](../../plans/UI-PLAN-02.md)

## 1. 구현 결과

- **Runner 를 두 흐름으로 나눴다.** `run_forever()` 는 **제어 루프**(heartbeat·실행 중 보고·
  원문 저장·열람·중단/재확인 수신, 1초)와 **실행 작업자**(작업공간 준비·배정·실행, 한 번에
  하나)를 따로 돈다. 긴 CLI 실행 중에도 카드 답변·다른 대화의 메시지가 저장되고 heartbeat 가
  이어진다. 두 흐름은 **실행 중 표**를 잠금 하나로 공유하고, 배정 수신과 표 등록은 같은 잠금
  안이다. HTTP 클라이언트는 흐름마다 따로다. `poll_once()` 는 두 흐름을 한 스레드에서 한 번씩
  도는 동기 경로로 남겼다(기존 시험·하네스 그대로).
- **CLI 는 Windows job object 안에서 돈다**(`runner/process_tree.py`). 실행마다 이름 있는 job
  (`KILL_ON_JOB_CLOSE`, 이탈 불허)을 만들고, CLI 를 **일시 정지 상태로 만들어** job 에 넣은 뒤
  원장에 시작 기록을 fsync 하고 **그 다음에 재개한다.** 중단이면 job 을 종료하고 **활성 0 을
  확인한다**. 정상 종료면 약 1초 기다린 뒤 남은 프로세스를 그 실행의 잔류로 보고 종료하며 수를
  남긴다. Runner 가 죽으면 마지막 핸들이 닫히며 OS 가 트리를 끝낸다. job 을 만들거나 넣지
  못하면 **실행하지 않는다**(`process_control_unavailable`). 비 Windows 는 지금처럼 실행하고
  잔류를 `unknown` 으로 보고한다.
- **잔류 `none` 은 확인 근거가 있을 때만이다.** 근거는 `job_empty`·`job_terminated`(종료한 수)·
  `job_closed_kill_on_close`·`host_rebooted`·`in_process`·`not_launched` 다. 제어부는 근거 없는
  `none` 을 409 로 거부한다(근거를 보내지 않는 옛 계약은 그대로 받는다). 루트 pid 가 같은 생성
  시각으로 살아 있거나, 그 실행을 맡은 다른 Runner 프로세스가 살아 있으면 확인이 아니다. 새 표
  `run_residual_observation` 이 관측을 쌓고 **`run.residual_activity` 는 결과 보고 값 그대로**
  둔다. 유효 잔류는 가장 최근 관측이다. 뒤늦은 확인이 시간 정산을 바꾸지 않는다.
- **중단된 실행은 `cancelled`**(P1 계약 7.2 의 값, 지금까지 쓰이지 않음)다. 원시 출력·이벤트·
  작업공간 전후 대조는 끊긴 데까지 남는다. 중단 신호보다 CLI 가 먼저 끝났으면 원래 판정이다.
- **요청 중단**(`POST .../requests/{rid}/stop`). 요청과 연결 미종료 실행에 중단을 적고(한
  트랜잭션), **후속 실행을 진입 검사·생성 트랜잭션 양쪽에서 막는다**(`request_stop_requested`).
  한 번도 배정되지 않은 실행은 제어부가 `cancelled` + `stop_requested` 로 끝낸다(소비 0 — 배정
  수신이 그 실행을 가져가지 않으므로 경쟁하지 않는다). 배정된 실행은 heartbeat 응답으로 Runner
  에 전달되고, 대기열·CLI 호출 직전이면(배정 내용·영수증 응답·원장 착수 뒤 재개 직전) CLI 를
  부르지 않는다. 처리하는 쪽은 중단된 요청을 적지 못한다 — **연결 실행이 전부 확인되면 제어부가
  `interrupted`(`stopped_by_request`)로 끝내 전송을 연다.** 확인되지 않으면 `unknown` 으로
  잠근다. 중단 재전송은 멱등이다.
- **요청 `unknown` 해제.** 확인되지 않은 실행에 재확인 요청을 찍는다 — 요청이 `unknown` 이 될
  때, 사람이 "상태 다시 확인"을 누를 때(`POST .../reconcile`), 그 Runner 가 등록할 때. Runner 는
  원장의 시작 기록·job·pid·부팅 시각으로 확인해 올리고, 확인되면 제어부가 `interrupted` 로
  옮긴다. **확인하지 못하면 잠금이 남는다.** 사람이 확인을 선언하는 경로는 없다.
- **종료 판정 개정.** 결과 `unknown`·`cancelled` 이면서 잔류가 확인되지 않은 실행이 있으면
  `unknown`(잠금), 결과는 모르지만 끝난 것을 확인한 실행이 있으면 `interrupted`
  (`execution_ended_result_unknown` — 완료로도 실패로도 적지 않는다). **정상 종료 실행의 잔류
  `unknown` 은 UI-01 처럼 잠그지 않는다**(지금까지의 모든 실제 CLI 실행의 값, 소급하지 않는다).
  끝났는지 모르는 중단 실행은 업무 종료도 막는다(미정리 실행).
- **Runner 재시작 대조**(원장 v2). 기동하면 작업자보다 먼저 "나에게 배정돼 끝나지 않은 실행"을
  받아(`POST /api/runner/{id}/reconcile`) 원장으로 대조한다. **CLI 를 다시 부르지 않고 세대를
  올리지 않는다** — 새 예약이 없다. 끝남 → 재전송, 원장 없음·시작 기록 없음 → 시작하지 않음
  (`not_launched`, 소비 0), 시작 기록 있음 → P4-04 원시 출력 복구 + 잔류 확인 + 실행 전 관측과
  지금 트리의 대조 → `unknown`. 잔류가 확인된 때만 그 실행의 worktree 권고 잠금을 푼다. 제어부
  연결이 끊겼다 돌아오면 같은 대조로 보고되지 않은 결과를 보낸다. 작업자 흐름은 전송 오류
  (연결 실패·5xx)면 보고를 다시 보내고 409 는 다시 보내지 않는다.
- **PC 연결.** heartbeat 가 실행과 분리됐으므로 연결 판정의 근거가 된다. `last_heartbeat_at` 에서
  `connected`·`disconnected`·`never_seen` 을 **도출**한다(기준 `HADS_RUNNER_STALE_SECONDS`, 기본
  15초 — 상세 설계 제안값, 0 이하 기동 거부). 미연결 PC 로 가는 사용자 입력(일반·정정·카드
  답변·`/feedback`·`/intent-drafts`·`/questions/{id}/answer`)은 원문을 열기 전에 409
  `runner_disconnected` 다. 대기열도 자동 전송도 없다. 대화 조회가 기준 PC·판단 근거·마지막
  확인 시각을, 요청 조회가 실행마다 **실행 상태**(`pending`·`executing`·`unconfirmed`·`ended`·
  `ended_unconfirmed`)와 잔류 근거·중단 전달 시각·사실 요약을 보인다. 전송 거부는 걸리는 사유를
  전부 돌려준다(요청 잠금과 미연결이 함께 걸릴 수 있다).
- **요청에 연결되지 않은 실행**은 `POST /api/runs/{id}/stop` 으로 같은 실행 단위 중단을 받는다.
  요청에 연결된 실행은 거부한다 — 요청 단위로 중단한다(D-76).
- **능력 표.** `process_tree_control` 을 Windows 에서 `verified`(자동 시험), `cancel_confirmed` 는
  **codex 만** `verified`(3절 라이브)이고 claude 는 `unknown` 이다.
- **관리 화면**(`ConversationPanel`): PC 연결 줄, 요청 **중단**·**상태 다시 확인** 버튼, 실행별
  실행 상태·잔류 근거, 중단·불명 요약. 새 화면은 만들지 않았다(UI-03).
- 스키마 **v18**: 새 표 하나(`run_residual_observation`), 컬럼 여덟(`run.stop_requested_at`·
  `stop_requested_by`·`stop_delivered_at`·`liveness_at`·`residual_check_requested_at`,
  `conversation_request.stop_requested_at`·`stop_requested_by`·`stop_reason_summary`), 허용값
  확장(`not_started_reason` 에 `stop_requested`·`not_launched`·`process_control_unavailable`, 요청
  상태 `interrupted`, 이유 셋). **CHECK 를 바꾸려고 `run`·`conversation_request` 를 다시 만든다** —
  저장된 DDL 에서 목록만 바꿔 새 표를 만들고 행을 옮긴 뒤 이름을 바꾼다(외래 키 검사 끔,
  `foreign_key_check` 확인, 색인 재생성, 값으로 비교해 이미 같으면 하지 않음).

## 2. 성공 기준 근거

시험은 `tests/test_run_control.py`(20)·`tests/test_process_control.py`(13)·
`tests/test_runner_process_control.py`(1)와 표시한 기존 파일이다.

| 기준 | 근거 |
|---|---|
| AC-1 긴 실행 중 입력 | `test_a_stop_ends_an_executing_run_and_unlocks_after_confirmation`(작업자 스레드가 CLI 를 붙든 동안 제어 루프가 다른 대화 원문 저장·실행 중 보고), `test_a_real_runner_stops_a_real_tree_and_reconciles_after_its_own_crash`(실제 Runner 프로세스), 라이브 A |
| AC-2 한 번에 하나·`poll_once` 의미 유지 | 기존 시험 전부 통과(`poll_once` 경로), `execution_tick` 이 배정을 차례로 처리 |
| AC-3 트리 중단·확인 | `test_stopping_ends_the_whole_tree_and_confirms_zero`, `test_a_stop_signal_ends_the_cli_tree_mid_run`(원시 출력 남음, 90초를 기다리지 않음, OS 에서 pid 사망), 실제 Runner 시험, 라이브 B |
| AC-4 정상 종료 잔류 | `test_what_a_finished_root_leaves_behind_is_ended_and_counted`, `test_leftover_processes_of_a_finished_cli_are_ended_and_counted`, `test_a_clean_exit_leaves_an_empty_job`, `test_the_adapter_records_the_launch_before_the_cli_runs_and_confirms_a_clean_end` |
| AC-5 Runner 사망 → 트리 종료 | `test_killing_the_owner_ends_the_tree_and_a_new_process_can_confirm_it`, `test_a_suspended_process_runs_nothing_before_it_is_resumed`, `test_a_failing_launch_record_keeps_the_cli_from_running`, 실제 Runner 시험, 라이브 C |
| AC-6 중단 전달·후속 차단 | `test_stopping_before_any_run_is_assigned_costs_nothing`, `test_a_stop_blocks_follow_up_runs_and_reaches_a_claimed_run`(진입 409·영수증 응답으로 CLI 호출 없음), `test_a_run_level_stop_is_only_for_runs_outside_a_request` |
| AC-7 확인 뒤 해제 | 위 시험들의 `interrupted`·전송 열림, `test_an_unconfirmed_stop_stays_locked_until_a_recheck_confirms_it`(`unknown` 잠금), `test_explicit_settle_follows_the_actual_end`, `test_the_controller_settles_a_request_only_after_stop_or_while_unknown` |
| AC-8 보존·요약 | `test_a_stop_ends_an_executing_run...`(출력 남음·요약), `test_stopping_before_any_run...`(소비 0·`not_started`) |
| AC-9 재시작 대조 | `test_restart_reconciliation_reports_without_reexecution_or_new_reservation`(원장 넷: 없음·시작 기록 없음·시작 기록 있음(실제 codex 원시 출력)·끝남 — CLI 호출 0, 세대 1, 예약 세대 {1}), 실제 Runner 시험, 라이브 C |
| AC-10 확인 근거 | `test_none_needs_a_confirming_basis`, `test_a_reused_pid_is_not_the_same_process`, `test_none_is_accepted_only_with_a_confirming_basis`, `test_residual_claims_need_a_basis_at_the_api`, `test_a_run_whose_owner_process_is_alive_is_left_alone`, `test_a_live_job_found_later_is_ended_before_it_is_confirmed`, `test_a_run_counts_as_ended_only_with_confirmation` |
| AC-11 재확인·선언 없음 | `test_an_unconfirmed_stop_stays_locked_until_a_recheck_confirms_it`(원래 보고 값 유지·관측 `recheck`), `test_a_recheck_without_evidence_leaves_the_lock_and_nobody_can_declare_it`(근거 없는 `none` 409) |
| AC-12 결과 불명·종료 확인 | `test_a_run_whose_result_is_unknown_but_ended_settles_as_interrupted`, `test_explicit_settle_follows_the_actual_end`(정상 종료 잔류 불명은 잠그지 않음) |
| AC-13 잠금 해제 | `test_a_stale_workspace_lock_is_released_only_for_its_own_run` |
| AC-14 보고 재시도 | `test_the_worker_resends_a_result_after_a_transport_error`(연결 실패 2회 뒤 전달, 409 는 다시 보내지 않음) |
| AC-15 미연결 거부 | `test_a_disconnected_pc_refuses_every_user_input_and_queues_nothing`(네 경로 409·intake 0·질문 열린 채·재연결 뒤 수동 재전송만), 실제 Runner 시험, 라이브 C |
| AC-16 조회 | `test_send_state_names_every_reason_and_connection_is_derived`, `test_an_assigned_run_on_a_disconnected_pc_is_unconfirmed`(다른 세대의 실행 중 보고 무시), `npm run build` |
| AC-17 이행 | `test_migration.py::test_a_v17_database_is_rebuilt_without_losing_rows_or_inventing_stops`(행·외래 키·부분 유일 색인·옛 `unknown` 잠김·새 값 허용·모르는 값 거부·반복 이행에서 DDL 같음), `test_a_new_database_needs_no_rebuild` |
| AC-18 실제 프로세스 | `test_runner_process_control.py` — 실제 uvicorn·실제 Runner 프로세스·가짜 codex(실제 트리): 실행 중 저장 → 중단 → 트리 종료(OS) → Runner 프로세스만 강제 종료 → 트리 종료 → 미연결 거부 → 재기동 대조(재실행 없음, 세대 1) → `interrupted` → 재연결 뒤 수동 재전송 |
| AC-19 실제 CLI | 3절 — 실제 `codex-cli 0.154.0`, 제품 규칙 23건 통과, `test_capabilities_say_which_cli_was_proven_to_stop` |
| AC-20 경계 | `test_ui02_records_keep_no_bodies_and_enforcement_is_unchanged`, 기존 데이터 경계 시험 통과 |

## 3. 검증

### 자동 시험

- 기준선(이 세션 시작, 변경 전): `scripts\run-tests.ps1` → pytest **539**, P1 계약 unittest
  **18** 통과(4분 44초).
- 최종: `scripts\run-tests.ps1` → pytest **575건 중 574 통과·1 실패**, P1 계약 unittest **18** 통과(5분 15초). 실패 1건은 UI-02 와 무관하게 이전부터 흔들리던 P4-02 시험(`test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure`, 시계 해상도 15.6ms — 9절)이며 UI-02 를 적용하지 않은 HEAD 워크트리에서도 3회 중 2회 실패했다. 같은 코드의 직전 전체 실행에서는 통과했다.
  새 시험 36건(`test_run_control.py` 20, `test_process_control.py` 13,
  `test_runner_process_control.py` 1, v17→v18 이행 2). 알려진 deprecation warning 외 실패 없음.
  웹 `npm run build` 성공.
- **기존 시험 네 건을 고쳤다. 검사를 지우지 않았다.**
  - `test_migration.py::test_a_v16_database_gets_no_receipt_or_freshness_it_never_had` 가
    `SCHEMA_VERSION == 17` 을 고정했다 → `>= 17`(뜻은 "현재 판으로 이행", v18 고정은 새 시험).
    UI-01·P4-04 가 한 것과 같은 판단이다.
  - `test_migration.py::test_a_v15_database_gets_no_conversation_it_never_had` 의 시험용 Runner 에
    heartbeat 가 없었다. 전송 가능 여부가 PC 연결도 보게 되어 **heartbeat 가 없던 PC 는 미연결**이
    맞다. 이 시험이 보는 것은 "요청 잠금을 지어내지 않는다"이므로 연결된 PC 로 두었다.
  - `test_conversation.py::test_general_input_is_locked_on_the_server_while_a_request_is_processing`
    가 `send.general` 을 dict 전체로 비교했다 — 새 필드 `refusals`(걸리는 사유 전부)를 기대값에
    더했다.
  - `test_context.py` 의 도우미 `_simulate_crash_after_start` 가 원장 착수만 적었다. 원장 v2 에서
    그것은 "CLI 가 재개되지 않았다"(시작하지 않음)이다. 그 시험들이 보는 P4-04 사용량 복구를
    유지하려고 **트리 제어 없이 시작된** 시작 기록을 더했다(잔류는 지금처럼 `unknown`).
- 하네스: `FakeCliExecutor` 가 새 인자(`on_launch`·`stop_event`·`job_name`)를 받고 시작 기록
  (`in_process`)을 먼저 남기며, `hold` 로 "CLI 가 도는 동안"을 만든다. 하네스 제어부의 미연결
  기준은 3600초이고 미연결 시험은 heartbeat 시각을 직접 옮긴다(`Harness.age_heartbeat`).
- **실제 프로세스 시험은 AI 를 부르지 않는다.** PATH 앞에 둔 시험용 `codex.cmd` →
  `tests/fake_cli/fake_codex.py` 가 codex `exec --json` 줄 형식을 내고 손자 프로세스를 만든다.
  제품 코드에 시험용 분기를 넣지 않았다.

### 실제 CLI (AC-19)

사전 확인(구현 첫 단계): 실제 codex 가 **이탈을 허용하지 않는 job 안에서** 정상 동작하는지
짧은 명령 하나로 봤다 — 최대 활성 프로세스 17개(샌드박스·명령 실행기·pwsh)가 모두 job 안에
있었고 루트 종료 뒤 0 이었다. 설계를 바꿀 이유가 없었다.

`ui/live/ui02_control.py` 로 실제 `codex-cli 0.154.0` 을 불렀다. 기능 Case 하나(질문 하나가 열린
의도 초안), 옆 대화 하나. 라이브 데이터는 `%LOCALAPPDATA%\Temp\hads-ui-02-live\195435011`,
저장소 `var\` 는 건드리지 않았다. 증거 사본은 `ui/evidence/UI-02-live*` 다. **프로세스 확인은
제품 코드가 아니라 OS(`Win32_Process` 명령줄)에 물었다.**

| 단계 | 제품 규칙(멈춤) | 관측 |
|---|---|---|
| A. 긴 실행 중 입력 — "`Start-Sleep -Seconds 91` 을 실행하고 끝날 때까지 기다린 뒤 done" | 같은 Case 카드 답변 202·저장, 옆 대화 메시지 저장, 같은 Case 일반 전송 409 `request_in_progress`, 그동안 실행은 끝나지 않음, 실행 상태 `executing` | codex 가 11.4초 만에 셸 대기 시작. 트리(OS): `cmd.exe(codex.CMD) → node.exe → codex.exe → … → pwsh.exe Start-Sleep 91`. 카드 답변 저장 0.3초, 옆 대화 저장 0.9초, 입력 뒤에도 셸 대기가 살아 있음 |
| B. 중단 | 중단 직후 `stopping`, 요청 `interrupted(stopped_by_request)`, 실행 `cancelled` + 잔류 `none`(`job_terminated`), **OS 목록에 그 트리 없음**, 중단 뒤 전송 202 | 중단 요청 → 요청 종료 0.5초, 종료한 프로세스 **10개**, 중단 전달 기록, 원시 출력은 `item.started`(셸 대기)까지 남음(`UI-02-live-B-raw.stdout.jsonl`) |
| C. Runner 강제 종료 — 같은 지시(92초) | 원장 v2·시작 기록(`KILL_ON_JOB_CLOSE`), **Runner 프로세스 하나만(`/T` 없이) 죽여도 트리가 끝남(OS)**, 미연결 전송 409 `runner_disconnected`(사유 하나), 끊긴 동안 실행은 끝나지 않은 채, 재기동 대조 `unknown` + 잔류 `none`(`reconcile`/`job_closed_kill_on_close`), 세대 1, **CLI 부수효과 1회**(재실행 없음), 원시 출력에서 세션 id 복구, 요청 `interrupted(execution_ended_result_unknown)`, 재연결 뒤 자동 전송 없음·수동 재전송 202 | 트리 소멸 0.45초. 사용량은 원시 출력에 `turn.completed` 가 없어 `not_reported`(지어내지 않음, P4-04 와 같음). 저장소 변경 없음, 종료 뒤 남은 프로세스 없음 |

**3회 실행했다.** 1회차는 라이브 하네스의 OS 목록 도우미가 한글 명령줄을 `text=True` 로
읽다가 출력을 통째로 잃어 A 에서 멈췄다(하네스를 바이트로 읽게 고침). 2회차는 A·B 가 같은
모양으로 통과했고 C 의 "Runner 만 죽여도 트리가 끝남(OS)"까지 확인했으나, 하네스가 옆 대화의
요청을 닫지 않아 미연결 전송이 `['request_in_progress', 'runner_disconnected']` 두 사유로 거부됐다
— **제품은 맞게 두 사유를 돌려줬다**(하네스 기대가 틀림). 옆 요청을 닫도록 고친 3회차가 제품
규칙 23건을 모두 통과했다. 위 증거는 3회차다. 지시와 다른 AI 동작 관찰은 없었다. **표본은 한
업무·중단 하나·강제 종료 하나다.** claude 는 실제로 중단해 보지 않았다(`cancel_confirmed =
unknown` 유지).

## 4. 구현 중 찾은 것

- **2시간짜리 첫 전체 시험.** 구현 도중 돌린 첫 전체 시험이 2시간 14분 걸렸다. 같은 코드로 곧바로
  다시 돌린 시간 측정 실행은 5분 13초였고 가장 느린 시험도 7초 미만이었다 — 코드가 아니라 그
  사이 호스트가 쉬었던 것으로 본다(원인을 확정하지는 못했다). 이후 전체 실행은 정상 시간이다.
- **정산 판정의 순서.** 중단된 요청에 처리하는 쪽이 종료를 적으면 처음에는 "실행이 끝나지
  않았다"가 먼저 나왔다. 그 요청은 제어부가 끝내므로 "중단 요청됨"을 먼저 돌려주게 바꿨다.
- **전송 거부의 사유.** 메시지 API 가 PC 미연결을 따로 먼저 거부해 요청 잠금 사유가 빠졌다.
  대화 조회의 `send.general` 과 같은 판정으로 합쳐 걸리는 사유를 전부 돌려준다.
- **중단된 실행과 업무 종료.** 끝났는지 모르는 `cancelled` 실행이 미정리 실행에 들지 않았다 —
  트리가 남아 쓰고 있을 수 있는데 자동 완료가 열린다. 미정리 실행에 넣고, 확인되면 빠진다.
- **정상 종료 직후의 잔류 판정.** 루트와 함께 끝나는 중인 자식을 잔류로 셀 수 있어, 정상 종료
  뒤 약 1초 활성 0 을 기다린 뒤 남은 것만 잔류로 종료·계수한다.
- **이전부터 있던 흔들리는 시험 하나.** `test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure`(P4-02)가 예약 요청 시각과 반영 시각이 다르다고 단언하는데, 이 PC 의 Python 3.12 벽시계 해상도가 15.6ms(`GetSystemTimeAsFileTime`)라 두 요청이 한 틱 안에 끝나면 같아진다. UI-02 를 적용하지 않은 HEAD 워크트리에서도 3회 중 2회 실패했다. UI-02 범위 밖이라 고치지 않았고 DEVELOPMENT.md 9절에 남겼다.
- **근거 이름.** job 이 사라지는 것은 Runner 가 죽을 때만이 아니라 실행기가 핸들을 닫을 때도
  같다(`KILL_ON_JOB_CLOSE`). 근거 이름을 `job_closed_kill_on_close` 로 정했다.

## 5. 경계와 남은 것

- **강제 축은 넷 그대로다.** `autonomy`·`controlled_checkpoint`·`budget`·`repository_selection`
  이 `enforced`, `publish` 만 P5 다. 중단·확인·재확인이 권한·동의·위임을 만들지 않는다.
- **넣지 않은 것**(UI-PLAN-02 2절·3.9절): 품질 게이트 검증 중단의 실제 종료 연결(검증 1회와
  reviewer 실행이 완료 때에야 연결된다), 시간 예산 hard 도달 시 자동 중단, 사람의 확인 선언,
  비 Windows 트리 제어, claude 실제 중단 실증, 새 기본 화면·초안 복구(UI-03), 분산 조정(P6-03).
- 남은 한계는 [DEVELOPMENT.md](../../DEVELOPMENT.md) 9절 표에 배정했다.
