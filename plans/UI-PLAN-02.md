# UI-PLAN-02

입력·실행 제어. 기준: 설계 v0.8 2차 / D-01~90 / 2026-09-23.
선행: P4-04 완료(스키마 v17), UI-01 완료(v16). 이 세션에서 `scripts\run-tests.ps1` 로
pytest **539**, P1 계약 unittest **18** 통과를 다시 확인했다(4분 44초).
범위는 **UI-02 하나**다. UI-03 기본 대화 화면, 브라우저 초안 복구(D-83), P4-05 이후 업무
기능, P6-03 전체 단절·복구 수용은 포함하지 않는다.

## 1. 현재 구현과 이 작업이 메울 차이

코드를 대조해 확인한 사실이다([DEVELOPMENT.md](../DEVELOPMENT.md) 1.4절의 시작점).

1. **Runner 가 한 루프에서 동기로 일한다.** `poll_once` 가 heartbeat → 원문 저장 → 열람
   중계 → 작업공간 준비 → 배정 실행을 차례로 하고, 배정 실행은 `CliExecutor.execute` 의
   `proc.wait` 에서 CLI 가 끝날 때까지(기본 600초) 루프를 붙잡는다. 그동안 heartbeat·원문
   저장(카드 답변 포함)·열람이 멈춘다.
2. **CLI 를 멈출 수단이 없다.** 시간 초과 때 `proc.kill()` 이 PATH 진입점(`codex.CMD`) 하나만
   끝낸다 — P1-03 #6 에서 `codex.exe → codex-command-runner → pwsh` 가 남았다. 그래서 모든
   CLI 실행의 `residual_activity` 가 `unknown` 이다.
3. **요청 `unknown` 에서 나갈 길이 없다**(UI-01). `settle_request` 가 `unknown` 을 거부하고,
   불명 실행의 실제 종료·잔류 활동을 확인할 경로가 없다.
4. **Runner 가 죽으면 맡은 실행이 `assigned` 로 멈춘다.** 사람이 재배정(`bump_generation`)해야
   P4-04 복구 경로를 타고, 재배정이 새 세대 예약을 잡아 과대 정산된다(9절). worktree 권고
   잠금 파일도 남아 그 작업공간의 다음 쓰기가 `workspace_busy` 로 막힌다.
5. **서버가 PC 연결 상태를 쓰지 않는다**(`send.runner_connection_enforced = false`). heartbeat 가
   긴 실행 중 멈추므로 근거가 되지 못했다.
6. **중단이 없다.** 요청·실행 어느 쪽에도 중단 요청·전달·확인이 없다.
7. **결과 보고가 한 번 실패하면 끝이다.** 원장에는 결과가 있는데 실행은 `assigned` 로 남는다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| Runner 의 제어 루프(heartbeat·실행 중 표시·원문 저장·열람·제어 수신)와 실행 작업자 분리 | 새 기본 대화 화면·브라우저 초안 저장/복구 — UI-03 |
| CLI 프로세스 트리 제어: Windows job object 안에서 실행, 트리 종료, 활성 프로세스 0 확인 | 실행 중 끼어들기·일반 전송 대기열(D-70 에 따라 만들지 않음) |
| 잔류 활동의 실제 확인과 그 근거 기록, 불명 실행의 재확인 | 시간 예산 hard 도달 시 자동 중단(한도 강제 의미 변경) — 이후 결정 |
| 요청 중단: 후속 실행 차단, 미배정 실행 취소, Runner 로 전달, 확인 뒤 자동 해제 | 품질 게이트 검증 중단의 실제 종료 연결(검증 1회와 reviewer 실행이 실행 중에 연결되지 않음 — 3.9절) |
| 요청 `unknown` 해제(실제 종료 확인 → `interrupted`) | 여러 제어부·여러 PC 의 분산 조정, 백업 복원 대조 — P6-03·P6-04 |
| Runner 재시작 대조: 원장 v2(시작 기록)로 재실행 없이 결과·잔류·작업공간 변화·잠금 정리, 새 예약 없음 | 대화 전체 요약문(자연어) — UI-03 |
| 결과 보고 재시도, 재연결 뒤 원장 결과 재전송 | Linux·macOS 의 트리 제어(비 Windows 는 지금처럼 `unknown`) |
| PC 연결 상태 도출, 미연결 시 일반·카드 답변 전송 거부, 조회·관리 화면 표시 | Claude CLI 의 실제 중단 실증(능력 표는 `unknown` 유지) |
| 관리 화면의 중단·상태 재확인 버튼, 스키마 v18·이행, 자동 시험·실제 CLI 확인 | |

## 3. 설계

### 3.1 Runner 의 두 흐름

- **제어 루프**(주 스레드, 1초): heartbeat(지금 실행 중인 실행 목록 포함) → 원문 저장 →
  열람 중계 → 제어 수신(중단·잔류 재확인). CLI 실행과 무관하게 돈다.
- **실행 작업자**(별도 스레드): 작업공간 준비 → 배정 수신 → 실행. **한 번에 하나**다 — 병렬
  실행을 새로 만들지 않는다(쓰기 자리 1 규칙과 별개로 이번 범위가 아니다).
- 두 흐름은 **실행 중 표**(run_id → 대기/실행/중단 중, 세대)를 잠금 하나로 공유한다. 배정
  수신과 표 등록은 같은 잠금 안이다 — 재연결 대조가 "막 받은 실행"을 옛 실행으로 오인하지
  않게 한다.
- HTTP 클라이언트는 흐름마다 따로 둔다. `poll_once()` 는 **두 흐름을 한 스레드에서 한 번씩**
  돈다 — 기존 시험과 하네스가 쓰는 동기 경로이며 의미가 같다.
- 결과·이벤트·명령 보고는 작업자 흐름에서 **전송 오류(연결 실패·5xx)면 다시 보낸다.**
  409(옛 세대·다른 결과)는 다시 보내지 않는다. `poll_once` 경로는 재시도하지 않는다 — 보고
  유실을 주입하는 기존 시험의 뜻을 바꾸지 않는다.

### 3.2 CLI 프로세스 트리 제어 (Windows)

P1-03 결론 (가)~(다)를 구현한다.

1. 실행마다 **이름 있는 job object** 를 만든다(`Local\hads-run-{runner}-{run}-{세대}`).
   제한은 `KILL_ON_JOB_CLOSE` 하나이며 **이탈(breakaway)을 허용하지 않는다.**
2. CLI 를 **일시 정지 상태로 만들고**(`CREATE_SUSPENDED`) job 에 넣은 뒤, 원장에 시작 기록
   (job 이름·pid·프로세스 생성 시각)을 fsync 로 남기고 **그 다음에 재개한다.** 재개 전에
   죽으면 CLI 는 한 줄도 실행하지 않았다.
3. **중단:** job 을 종료(`TerminateJobObject`)하고 활성 프로세스가 0 이 될 때까지 기다린다
   (기본 15초). 0 을 보면 `residual_activity = none`(근거 `job_terminated`), 못 보면 `unknown`.
4. **정상 종료:** 루트가 끝난 뒤 job 의 활성 프로세스를 본다. 0 이면 `none`(`job_empty`).
   남아 있으면 **그 실행의 잔류 활동이므로 종료하고** 수와 함께 `job_terminated` 로 남긴다.
   실행의 경계는 CLI 호출 하나다 — 끝난 실행의 프로세스가 다음 실행과 겹쳐 쓰지 않게 한다
   (P1-03 (가)). 이 선택은 결과에 종료한 수로 드러나며 숨기지 않는다.
5. **Runner 가 죽으면** 마지막 job 핸들이 닫혀 OS 가 트리를 끝낸다(`KILL_ON_JOB_CLOSE`).
6. job 을 만들거나 넣지 못하면 **실행하지 않는다**(더 약한 방식으로 조용히 대체하지 않는다) —
   단 비 Windows 는 지금 동작 그대로 실행하고 잔류를 `unknown` 으로 보고한다.
7. 파이프는 트리가 끝난 뒤에 닫힌다. 손자 프로세스가 파이프를 물고 버티던 P1-03 의 40초
   지연은 트리 종료로 끝난다.

중단된 실행의 결과는 `outcome = cancelled`(P1 계약 7.2 의 값, 지금까지 쓰이지 않음), 원시
출력·정규화 이벤트·작업공간 전후 대조는 **그대로 남긴다**(부분 변경 보존). 중단 신호보다 CLI
가 먼저 끝났으면 원래 판정(`completed` 등)이다. 시간 초과(600초)는 지금처럼 `unknown` 이되
트리 종료와 잔류 확인은 같다.

### 3.3 원장 v2 와 재시작 대조

- 새 착수 기록은 `ledger_version = 2` 이고 **시작 기록**(`launch`)을 따로 둔다: CLI 는 job·pid·
  생성 시각, 골격 실행기·시험용 가짜는 `in_process`. 쓰기 실행은 착수 때 **실행 전 작업 트리
  관측**(HEAD·상태 줄·지문 — Runner 에만 남는다)도 적는다.
- Runner 가 기동하면 작업자를 띄우기 **전에** 제어부에 "나에게 배정돼 끝나지 않은 실행"을
  묻고(`POST /api/runner/{id}/reconcile`) 각 실행을 원장으로 대조한다. **CLI 를 다시 부르지
  않고 세대를 올리지 않는다** — 새 예약이 생기지 않는다(9절 과대 정산의 재시작 경로 해소).

| 원장 | 보고 |
|---|---|
| 끝남 | 저장된 결과를 그 세대로 다시 보낸다 |
| v2 착수, 시작 기록 없음 / 원장 없음 | `cancelled`(중단 요청 시) 또는 `failed` + 잔류 `none` + `not_started_reason = not_launched` — CLI 는 실행되지 않았다, 소비 0 |
| 시작 기록 있음(v2) | P4-04 원시 출력 복구 + **잔류 확인**(3.4) + 실행 전 관측이 있으면 지금 트리와의 대조로 작업공간 변화 → `unknown` |
| v1 착수(P4-04 이전 형식) | P4-04 경로 그대로(`unknown`) + 잔류 확인은 재부팅 근거만 |

- 대조 뒤 그 실행이 잡고 있던 **worktree 권고 잠금**(내용이 `{runner}:{run}`)을 잔류가 `none`
  으로 확인된 때만 푼다. 확인하지 못하면 잠금을 남긴다 — 잔류 프로세스가 아직 쓰고 있을 수 있다.
- 제어부가 재시작돼도 Runner 는 같은 프로세스로 실행을 이어가고, 보고는 3.1 의 재시도로
  닿는다. 제어 루프가 **연결 복구를 관측하면** 같은 대조를 다시 해 원장에 결과가 있는데
  제어부가 끝나지 않았다고 보는 실행의 결과를 다시 보낸다(실행 중 표에 있는 것은 제외).

### 3.4 잔류 활동의 확인과 재확인

- 잔류 관측은 값(`none`/`unknown`)과 **근거**를 함께 남긴다: `job_empty`, `job_terminated`(종료한
  수), `job_closed_kill_on_close`(job 이 이미 없고 시작 기록이 `KILL_ON_JOB_CLOSE` — OS 가 트리를
  끝냈다), `host_rebooted`(호스트 부팅 시각이 실행 착수 뒤), `in_process`(Runner 프로세스 안의
  실행기), `not_launched`, `not_observable`(비 Windows·시작 기록 없음·확인 실패).
  **`none` 은 확인 근거가 있을 때만이다.** 루트 pid 가 같은 생성 시각으로 살아 있으면 job 이
  없어도 `unknown` 이다.
- 새 표 `run_residual_observation` 이 관측을 쌓는다(결과 보고 때 한 번, 재확인 때마다). **실행의
  `residual_activity` 컬럼은 결과 보고 값 그대로 둔다** — 뒤늦은 확인이 원래 보고를 고쳐 쓰지
  않는다. 유효 잔류 = 가장 최근 관측(없으면 컬럼 값).
- **재확인:** 잠긴 요청(`unknown`)의 확인되지 않은 실행에 재확인 요청 시각을 찍는다 — 요청이
  `unknown` 이 될 때, 사람이 "상태 다시 확인"을 누를 때(`POST .../requests/{rid}/reconcile`),
  그 Runner 가 등록할 때. Runner 는 제어 수신으로 받아 원장의 시작 기록·job·pid·부팅 시각으로
  확인하고 결과를 올린다. job 이 아직 살아 있으면 **종료하고 확인한다**(끝난 실행의 잔류다).
- 시간 지표 정산은 결과 보고 때의 잔류로 한다(기존 규칙). 뒤늦은 확인이 `unresolved` 시간을
  확정으로 바꾸지 않는다 — 언제 끝났는지는 여전히 모른다.

### 3.5 요청 중단

`POST /api/cases/{id}/requests/{rid}/stop` (행위자·짧은 이유). 처리 중(`processing`) 요청만.

1. `conversation_request.stop_requested_*` 를 적는다. 상태는 `processing` 그대로이고 조회가
   `stopping`(중단 요청 중)으로 보인다. **이미 요청된 중단의 재전송은 아무 것도 바꾸지 않는다.**
2. **후속 실행을 막는다.** 진입 검사 `request_stop_requested`, Run 생성 트랜잭션 안에서도 다시
   본다.
3. 연결된 미종료 실행에 `run.stop_requested_at` 을 찍는다.
   - **한 번도 배정되지 않은 실행**(세대 1, `assigned_at` 없음)은 제어부가 바로 끝낸다:
     `cancelled` + 잔류 `none` + `not_started_reason = stop_requested` — 소비 0.
   - 재배정된 대기 실행(세대 >1)은 이전 세대가 돌았을 수 있어 제어부가 끝내지 않는다. Runner 가
     받아 원장으로 판단한다(끝남 → 재전송, 시작 기록 → 복구, 없음 → 시작하지 않음).
   - 배정·실행 중 실행은 Runner 의 제어 수신으로 전달된다. Runner 는 실행 중이면 트리를 종료하고,
     작업자 대기열에 있거나 CLI 호출 직전이면(배정 내용·영수증 응답의 중단 표시) **CLI 를
     부르지 않고** `stop_requested` 로 끝낸다. 전달되면 `run.stop_delivered_at` 을 적는다.
4. **확인 뒤 자동 종료.** 연결된 실행이 전부 끝났을 때 제어부가 판정한다 — 모두 유효 잔류
   `none`(또는 시작하지 않음)이면 요청을 `interrupted`(`stopped_by_request`)로 끝내 잠금을 푼다.
   하나라도 확인되지 않으면 `unknown` 으로 잠근다. 판정 시점은 중단 요청 때·실행 결과 때·잔류
   관측 때다.
5. 중단 요청된 요청은 처리하는 쪽이 `completed`·`failed` 로 적지 못한다
   (`request_stop_requested`) — 끝내는 것은 확인한 제어부다.
6. **중단은 취소 성공이나 롤백이 아니다.** 부분 변경·원시 출력·사용량·예산 소비·repair 누적은
   남는다. 요청 조회가 요약을 준다: 실행별 결과·잔류 근거, 결과를 모르는 실행, 작업공간을 바꾼
   실행과 누적 변경 수, 시작하지 않은 실행.
7. 요청에 연결되지 않은 실행(관리 화면·옛 경로)은 `POST /api/runs/{id}/stop` 으로 같은 실행
   단위 중단을 받는다. 요청에 연결된 실행은 거부한다 — 요청 단위로 중단한다(D-76).

### 3.6 요청 종료 판정의 개정과 `interrupted`

`domain/conversation.decide_settle` 과 새 판정 `settle_after_stop` 한 곳에 둔다.

| 조건(연결 실행 전부 종료 뒤) | 요청 상태 |
|---|---|
| 결과 `unknown`·`cancelled` 이면서 유효 잔류가 `none` 이 아닌(시작하지 않음 제외) 실행이 있음 | `unknown`(잠금) — `run_outcome_unknown` / `run_residual_unconfirmed` |
| 중단 요청됨 | `interrupted` — `stopped_by_request` |
| 결과 `unknown` 이고 잔류 `none` 인 실행이 있음 | `interrupted` — `execution_ended_result_unknown` (완료·실패를 요청해도) |
| 그 밖 | 요청한 `completed`·`failed`(기존 규칙: `completed` 는 여는 메시지 저장 필요) |

- `unknown` 요청은 확인되지 않은 실행이 전부 확인되면 제어부가 `interrupted` 로 옮긴다
  (중단 요청이 있었으면 `stopped_by_request`, 아니면 `execution_ended_result_unknown`).
  **확인하지 못하면 잠금이 남는다** — 사람이 확인을 대신 선언하는 경로는 만들지 않는다(D-76).
- **정상 종료 실행(`completed`·`failed`)의 잔류 `unknown` 은 UI-01 처럼 잠그지 않는다.**
  지금까지의 모든 실제 CLI 실행이 그 값이고, 소급해 잠그지 않는다. 새 어댑터는 정상 종료에서도
  잔류를 확인해 `none` 을 보고한다.
- `interrupted` 는 잠그지 않는 종료 상태다. 부분 유일 색인(활성 = `processing`·`unknown`)은
  그대로다.

### 3.7 PC 연결과 전송

- 연결 상태는 `runner.last_heartbeat_at` 에서 **도출한다**: `connected` / `disconnected`
  (마지막 확인 시각과 함께) / `never_seen`. 기준은 `HADS_RUNNER_STALE_SECONDS`(기본 15초,
  상세 설계 제안값, 0 이하는 기동 거부). 저장하지 않는다.
- **사용자 입력 경로가 미연결 PC 를 대상으로 하면 409 `runner_disconnected`** 다: 대화 메시지
  (일반·정정·카드 답변), `/feedback`, `/intent-drafts`, `/questions/{id}/answer`. 검사는 원문을
  열기 전이다(고아 intake 없음). 시스템 경로(`/artifacts`, `/api/runner/*`)는 그대로다(UI-01 과
  같은 구분). 대기열은 없다 — 거부된 입력은 사용자에게 남는다.
- 카드 답변은 요청 처리 중·중단 요청 중·`unknown` 에서도 **대상이 유효하면** 받는다. 답변이
  중단을 확인하거나 요청을 여닫지 않는다.
- 대화 조회의 `send` 는 어느 Runner 를 기준으로 판단했는지 밝힌다: 질의의 `runner_id`, 없으면 이
  Case 의 마지막 사용자 메시지 원문을 가진 Runner, 없으면 등록된 Runner 가 하나일 때 그것,
  그 밖은 `not_determined`. `runner_connection_enforced = true`.
- heartbeat 는 실행 중인 실행을 함께 보고하고 제어부가 `run.liveness_at` 을 적는다. 실행 조회는
  실행 상태를 **도출**한다: `pending` / `executing`(Runner 연결·최근 확인) / `unconfirmed`(배정됐는데
  Runner 미연결 또는 확인이 끊김) / `ended`(유효 잔류 `none`) / `ended_unconfirmed`.
- 재연결 뒤 초안은 자동으로 보내지지 않는다 — 서버에 대기열이 없고, 관리 화면도 보내지
  않는다. 접수 여부는 기존 `by-client-id` 대조로 본다.

### 3.8 능력 표·조회·화면

- 능력 표: `process_tree_control` 을 Windows 에서 `verified`(UI-02 자동 시험), 비 Windows 는
  `unsupported`. `cancel_confirmed` 는 codex 를 **실제 CLI 실증 뒤에만** `verified` 로 올리고,
  claude 는 `unknown` 을 유지한다(D-76 "CLI별 실증"). `safe_stop_next_call`(훅) 은 바꾸지 않는다.
- 조회: 대화의 `send`(연결 기준 Runner·상태·마지막 확인), 요청의 중단 상태·요약·실행별 실행
  상태·잔류 근거·중단 전달 시각. 실행 조회에 `stop_requested_at`·`stop_delivered_at`·
  `liveness_at`·잔류 관측 목록.
- 관리 화면(`ConversationPanel`): PC 연결 줄, 요청 **중단** 버튼·중단 요청 중 표시, `unknown`
  의 **상태 다시 확인** 버튼, 실행별 실행 상태, 중단 요약. 서버 판정을 그대로 보인다.

### 3.9 넣지 않은 이유

- **품질 게이트 검증 중단.** P4-02 의 검증 1회(`quality_gate_run`)는 reviewer 실행과 **결과 기록
  때에야** 연결된다(`reviewer_run_id` 는 완료 때 채워진다). 실행 중에 어느 프로세스를 끝낼지
  모르므로 실제 종료를 연결할 수 없다 — 연결에는 P4-02 모델 변경이 필요하다. 요청만 적는 지금
  의미를 유지하고 9절에 남긴다.
- **시간 예산 자동 중단.** 중단 능력이 생겨도 hard 한도 도달 시 끊을지는 한도 강제의 의미를
  바꾸는 결정이다(D-88 "지원 능력 이상의 즉시 종료를 약속하지 않는다").
- **사람의 확인 선언.** 잔류를 확인하지 못한 요청을 사람이 풀게 하면 D-76 의 "확인한 뒤 허용"이
  사라진다.

## 4. 저장·API

스키마 **v18**.

- `run`: `stop_requested_at`, `stop_delivered_at`, `liveness_at`, `residual_check_requested_at`
  (새 컬럼). `not_started_reason` 의 허용값에 `stop_requested`·`not_launched` 를 더한다.
- `conversation_request`: `stop_requested_at`·`stop_requested_by`·`stop_reason_summary`(≤200) 컬럼,
  상태에 `interrupted`, 이유에 `stopped_by_request`·`execution_ended_result_unknown`·
  `run_residual_unconfirmed` 를 더한다.
- 새 표 `run_residual_observation`(실행·세대·순번·출처 `result`/`recheck`/`reconcile`·잔류·근거·
  종료한 수·Runner·시각). 본문·경로 없음.
- **CHECK 를 바꾸는 두 표(`run`·`conversation_request`)는 다시 만든다.** 기존 표의 저장된 DDL 에서
  허용값 목록만 바꿔 새 표를 만들고 행을 그대로 옮긴 뒤 이름을 바꾼다(외래 키 검사를 끄고
  `foreign_key_check` 로 확인, 색인 재생성). 새로 만드는 DB 는 schema.sql·컬럼 DDL 이 새 목록을
  갖는다. 반복 이행이 멱등이다.
- 이행은 **데이터를 쓰지 않는다.** 옛 실행에 관측·중단·확인 기록을 만들지 않는다. 옛 `unknown`
  요청은 그대로 잠겨 있고, 그 실행의 재확인은 Runner 의 확인 근거가 있을 때만 푼다.

API:

| 경로 | 내용 |
|---|---|
| `POST /api/cases/{id}/requests/{rid}/stop` | 요청 중단(멱등) |
| `POST /api/cases/{id}/requests/{rid}/reconcile` | `unknown` 요청의 잔류 재확인 요청 |
| `POST /api/runs/{id}/stop` | 요청에 연결되지 않은 실행의 중단 |
| `POST /api/runner/{rid}/heartbeat` | 본문(선택): 실행 중 목록. **응답이 중단 대상·잔류 재확인 대상**(구현 중 변경 — 10절) |
| `POST /api/runner/runs/{id}/stop-ack` | 중단 전달 확인 |
| `POST /api/runner/runs/{id}/residual` | 잔류 관측 보고 |
| `POST /api/runner/{rid}/reconcile` | 이 Runner 에 배정돼 끝나지 않은 실행(배정 내용) |
| `POST /api/runner/runs/{id}/result` | 잔류 근거·종료한 수(선택), `cancelled`+시작하지 않음 허용 |
| `POST /api/runner/runs/{id}/context-receipt` | 응답에 그 실행의 중단 표시 |
| `GET /api/cases/{id}/conversation?runner_id=` | 연결 기준 Runner·상태 |

## 5. 성공 기준

| 기준 | 내용 |
|---|---|
| AC-1 | 긴 CLI 실행 중에도 heartbeat 가 계속되고, 사용자 메시지·카드 답변 원문이 저장(`stored`)되며 원문 열람이 중계된다(분리 전에는 실행이 끝날 때까지 멈췄다) |
| AC-2 | 실행은 한 번에 하나이고 `poll_once` 는 기존 의미 그대로다(기존 시험 통과) |
| AC-3 | CLI 트리가 job 안에서 돈다. 중단하면 손자까지 끝나고 활성 0 을 확인해 `cancelled` + 잔류 `none`(`job_terminated`) 이다. 원시 출력·이벤트·작업공간 전후 대조가 남는다 |
| AC-4 | 정상 종료 뒤 남은 프로세스는 종료되고 수가 기록되며 잔류 `none` 이다. 아무 것도 남지 않으면 `job_empty` 다. 확인하지 못하면 `unknown` 이다 |
| AC-5 | Runner 프로세스만 강제 종료해도 CLI 트리가 끝난다(`KILL_ON_JOB_CLOSE`) |
| AC-6 | 요청 중단은 후속 실행 생성을 API·트랜잭션 안에서 막고, 미배정 실행을 소비 0 으로 끝내며, 배정·실행 중 실행에 전달된다. CLI 호출 직전의 중단은 CLI 를 부르지 않는다. 중단 재전송은 멱등이다 |
| AC-7 | 연결 실행이 전부 확인되면 요청이 `interrupted` 가 되어 전송이 열리고, 확인되지 않으면 `unknown` 으로 잠긴다. 처리하는 쪽은 중단된 요청을 `completed`·`failed` 로 적지 못한다 |
| AC-8 | 중단 뒤 부분 변경·원시 출력·사용량·예산 소비·repair 누적이 남고 요청 조회가 요약(실행별 결과·잔류 근거·변경 수·시작하지 않은 실행)을 준다. 롤백·취소 성공으로 표시하지 않는다 |
| AC-9 | Runner 재시작 대조가 CLI 를 다시 부르지 않고 세대를 올리지 않으며(새 예약 없음): 끝난 결과 재전송, 시작 기록 없는 실행은 소비 0 의 시작하지 않음, 시작 기록 있는 실행은 원시 출력 복구 + 잔류 확인 + 작업공간 대조의 `unknown` |
| AC-10 | 잔류 `none` 은 확인 근거가 있을 때만이다(루트 pid 생존·job 확인 실패·비 Windows·v1 원장은 `unknown`). 관측이 근거와 함께 쌓이고 실행의 원래 보고 값은 바뀌지 않는다. 뒤늦은 확인이 시간 정산을 바꾸지 않는다 |
| AC-11 | `unknown` 요청은 재확인(자동·사람 요청·Runner 등록)으로 확인되면 `interrupted` 로 풀리고, 확인하지 못하면 잠금이 남는다. 사람의 선언으로 풀 수 없다 |
| AC-12 | 결과 `unknown`·잔류 `none` 실행이 있는 요청은 종료 기록 시 `interrupted`(`execution_ended_result_unknown`)다. 정상 종료 실행의 잔류 `unknown` 은 요청을 잠그지 않는다(UI-01 유지) |
| AC-13 | 잔류가 확인된 재시작 대조만 그 실행의 worktree 권고 잠금을 푼다 |
| AC-14 | 결과 보고가 전송 오류로 실패해도 작업자가 다시 보내고, 제어부 재시작 뒤 연결이 돌아오면 원장의 결과가 전달된다. 옛 세대 409 는 다시 보내지 않는다 |
| AC-15 | PC 미연결(heartbeat 기준 초과)이면 일반·정정·카드 답변·피드백·사람 의도 초안·질문 답변이 409 `runner_disconnected` 이고 intake 를 남기지 않는다. 연결되면 다시 받는다. 대기열·자동 전송 없음 |
| AC-16 | 대화 조회가 기준 Runner·연결 상태·마지막 확인 시각과 전송 가능 여부를 서버 판정 그대로 보이고, 실행 조회가 실행 상태를 도출한다(미연결 Runner 의 배정 실행은 `unconfirmed`) |
| AC-17 | v17→v18 이행이 두 표를 다시 만들며 행·색인·외래 키를 보존하고, 옛 실행·요청에 관측·중단 기록을 지어내지 않으며 멱등이다. 옛 `unknown` 요청은 잠긴 채다 |
| AC-18 | 실제 uvicorn·실제 Runner 프로세스·실제 프로세스 트리(가짜 CLI 명령)로: 실행 중 저장·중단·트리 종료 확인, Runner 강제 종료 → 트리 종료 → 재기동 대조 → `interrupted` 를 확인한다 |
| AC-19 | 실제 CLI(codex): 긴 실행 중 메시지·카드 답변 저장, 중단으로 `codex.exe`·명령 실행기·셸까지 끝남을 OS 목록으로 독립 확인, Runner 강제 종료 뒤 트리 종료와 재기동 대조, PC 미연결 거부와 재연결 |
| AC-20 | 기존 경계 유지: 강제 축 넷·게시 미강제, 중단·확인이 권한·동의·위임을 만들지 않음, 본문·경로를 제어부에 남기지 않음(데이터 경계 시험) |

## 6. 검증

1. 순수 규칙 단위 시험: 종료 판정 개정·중단 뒤 판정·연결 상태·실행 상태 도출·유효 잔류.
2. 프로세스 제어 시험(`tests/test_process_control.py`, Windows): 파이썬 손자 트리로 중단·정상
   종료 잔류·Runner 대역 프로세스 강제 종료(`KILL_ON_JOB_CLOSE`)·job 이름 확인·재개 전 사망.
3. API 하네스 시험(`tests/test_run_control.py`): AC-6~17 의 대표·거부 경로, 원장 v2 대조,
   잔류 재확인, 연결 거부.
4. 동시성: 실제 uvicorn + 스레드 Runner(제어·작업자) + 가짜 CLI 명령(PATH 앞의 `codex.cmd` 가
   파이썬 스크립트를 부른다 — 제품 코드에 시험용 분기를 넣지 않는다)로 AC-1·3·14·18.
5. 이행: 커밋된 v17 스키마 DB 를 v18 로 두 번 연다(AC-17).
6. 전체 `scripts\run-tests.ps1`(pytest 수와 P1 계약 18 을 따로 보고), 웹 `npm run build`.
7. 실제 CLI(AC-19): `ui/live/ui02_control.py`, 실제 `codex`. 긴 실행은 셸의 `Start-Sleep` 을
   고유한 초 수로 시켜 OS 프로세스 목록(명령줄)에서 찾는다. 라이브 데이터는
   `%LOCALAPPDATA%\Temp\hads-ui-02-live`, 저장소 `var\` 를 건드리지 않는다. 제품 규칙 위반만
   멈추고 AI 동작은 관찰로 적는다. **먼저 짧은 확인으로 codex 가 이탈 없는 job 안에서 정상
   동작하는지 본다** — 동작하지 않으면 설계를 바꾸기 전에 기록하고 plan 을 고친다.

기존 시험이 새 규칙과 충돌하면 의미를 검토해 고치고 검사를 지우지 않는다.

## 7. 구현 순서

1. 프로세스 제어 모듈(`runner/process_tree.py`)과 시험, codex 짧은 확인.
2. `domain`: 열거형·거부 사유, 판정(종료·중단·연결·실행 상태·유효 잔류)과 단위 시험.
3. 스키마 v18·이행(표 재생성 도우미)과 이행 시험.
4. 저장 계층: 중단·전달·잔류 관측·재확인·자동 종료, 연결 상태, 전송 거부, 대조 조회.
5. API.
6. Runner: 원장 v2, CliExecutor 트리 제어, 두 흐름·실행 중 표·보고 재시도·기동 대조·제어 수신.
7. 관리 화면, 능력 표.
8. 시험(대표·거부·동시성·재시작·이행), 전체 검증, 실제 CLI, diff 검토.
9. `ui/evidence/UI-02-results.md`, 이 plan 완료 기록, `DEVELOPMENT.md` 갱신.

## 8. 시작 관측

- `main`, HEAD `5840b83`, 작업 트리 clean, 로컬 추적 ref `origin/main` 과 같다(원격을 새로
  조회하지 않았다).
- 기준선: `scripts\run-tests.ps1` → pytest **539**, P1 계약 unittest **18** 통과(이 세션, 4분 44초).
- 외부 쓰기·commit·push·PR 허용은 받지 않았다. 결과는 작업 트리에 남겨 인계한다.

## 9. 완료 기록

- **상태: 완료(2026-09-23).** 범위는 UI-02 에 머물렀다. 강제 축은 넷 그대로이며 이 작업이
  더한 것은 **실행이 실제로 끝났는가**라는 축(결과와 별개)과 그 확인·중단·재시작 대조·PC 연결
  판정이다. 2절의 넣지 않는 것은 그대로 넣지 않았다.
- AC-1~20 을 구현·시험으로 확인했다. 상세 연결은 [UI-02 실행 결과](../ui/evidence/UI-02-results.md)에
  있다.
- 최종 검증은 `scripts\run-tests.ps1` 로 제품 pytest **575건 중 574 통과·1 실패**, P1 계약 unittest **18**(5분 15초),
  웹 `npm run build` 통과다(기준선 539 → +36). 실패 1건은 UI-02 와 무관하게 이전부터 흔들리던 P4-02 시험(`test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure`, 시계 해상도 15.6ms — 9절)이며 UI-02 를 적용하지 않은 HEAD 워크트리에서도 3회 중 2회 실패했다. 같은 코드의 직전 전체 실행에서는 통과했다. 새 시험 36건(`tests/test_run_control.py` 20,
  `tests/test_process_control.py` 13, `tests/test_runner_process_control.py` 1, v17→v18 이행 2)을
  포함한다.
- 실제 CLI: `codex-cli 0.154.0` 으로 긴 실행 중 입력·중단·Runner 프로세스 강제 종료·재기동
  대조·PC 미연결을 **세 번** 돌렸다(1·2회차는 하네스 결함 — 결과 3절). 3회차 제품 규칙 23건
  통과, 트리 종료는 OS 목록으로 확인, 지시와 다른 AI 동작 관찰 없음.
- 결과는 작업을 마친 뒤 **사용자 지시로 커밋·push** 했다(`592eb39`). 그 허용은 이 변경에만
  적용되며 다음 변경은 다시 확인받는다. PR 은 만들지 않았고 제품의 외부 게시는 P5다.

## 10. 구현 중 plan 에서 바꾼 것

- **제어 수신 경로.** 4절은 `GET /api/runner/{rid}/controls` 를 따로 두었다. heartbeat 응답이
  중단·잔류 재확인 대상을 돌려주게 합쳤다 — 제어 루프가 매초 두 번 왕복하지 않고, 생존 보고와
  할 일이 같은 시점의 값이다. 표를 고쳤다.
- **근거 이름.** `job_closed_with_runner` → `job_closed_kill_on_close`. job 은 Runner 가 죽을 때뿐
  아니라 실행기가 핸들을 닫을 때도 사라지며 둘 다 `KILL_ON_JOB_CLOSE` 로 남은 것이 끝난다.
- **컬럼 하나 더.** 요청 없는 실행의 중단 주체를 남기려고 `run.stop_requested_by` 를 더했다
  (4절의 컬럼 넷 → 다섯).
- **`not_started_reason` 에 `process_control_unavailable`.** 3.2절 6항("job 을 만들지 못하면
  실행하지 않는다")의 보고 값이 4절 목록에 없었다.
- **정산 거부의 순서.** 중단된 요청의 종료 기록은 미종료 실행보다 "중단 요청됨"을 먼저
  돌려준다 — 그 요청은 처리하는 쪽이 끝낼 수 없다는 것이 먼저다(3.5절 5항의 뜻).
- **전송 거부의 사유 목록.** 메시지 API 도 대화 조회의 `send.general` 과 같은 판정으로 걸리는
  사유를 전부 돌려준다(3.7절). 처음 구현은 PC 미연결만 따로 먼저 거부했다.
- **미정리 실행.** 끝났는지 모르는 `cancelled` 실행을 업무 종료의 미정리 실행에 넣었다 — 3.6절의
  잠금 규칙과 같은 판단을 자동 완료에도 적용한다.
- **정상 종료 직후 잔류 판정.** 루트와 함께 끝나는 중인 자식을 잔류로 세지 않게 약 1초 활성 0 을
  기다린 뒤 판단한다(3.2절 4항 보완).
- **시험 하네스.** 하네스 제어부의 PC 미연결 기준을 3600초로 두고 미연결 시험은 heartbeat 시각을
  직접 옮긴다 — 기본 15초면 느린 시험이 우연히 미연결에 걸린다.
