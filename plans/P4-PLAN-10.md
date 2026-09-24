# P4-PLAN-10

**상태: 완료(S-037, 2026-09-24)** — AC-1~13 충족, [P4-10 결과](../p4/evidence/P4-10-results.md). 최종 전체 시험 807·0·2(웹 단위 41·P1 18). 사용자 지시로 `44e4f04` 커밋·push, 이슈 #8·#9 닫음.

이슈 #8(실행 제한 시간이 고정 10분이고 시간 초과가 실패와 구분되지 않음)·#9(검증이 기준 미충족을 보고해도 구현으로 돌아가지
않음)의 **진행기 보강**. 범위는 **사용자 결정(2026-09-24, S-036): 다음 세션·UI-05b 앞·한 plan**, 실행 제한 시간 기본값은
**1시간(D-95)**. 기준: 설계 v0.8 2차 / D-01~95 / 이슈 #8·#9 본문(완료 조건) / DEVELOPMENT 1.11절 P4-10 항목·10절 S-036.
선행: P4-05(진행기)·P4-05b(진행 상한 이력)·UI-04b(프로젝트 기본값)·UI-02(Runner 중단·잔류 확인)·UI-05a(작업 탭·그래프 수정 경로·
D-94 repair 모양). 세션 S-037.

기준선(S-037 시작, 변경 전, `scripts\run-tests.ps1`): 5절 끝. 시작 상태 `main`/`b0122d2`, 작업 트리 clean, `git fetch` 뒤
`origin/main` 과 같음.

범위는 **P4-10 하나**다. UI-05b(관리 화면 정리 2단계)·P5 로 넓히지 않는다. 관리 화면(`?view=admin`)의 진행 상한 패널은
이번에 손대지 않는다(UI-05b 가 지운다).

## 0. 제품 판단

**새 제품 판단은 없다** — 사용자 결정 D-95(기본 1시간·설정화·시간 초과 구분·같은 제한으로 자동 재시도 않음·부분 결과 판정 제외)와
이슈 #9 본문의 방향(수정 구현 → 재검증 사이클, 한도, `unverified`·한도 뒤 사람 카드)을 그대로 구현한다. 인계가 "plan 에서
정한다" 로 넘긴 것과 상세 설계 선택(제품 정책이 아니다, 9절에도 적는다):

- **제한 시간은 진행 상한과 같은 자리·같은 층이다.** 새 키 `run_timeout_seconds` 를 진행 상한 키(`progress_limit_setting`·
  프로젝트 기본값·시스템 기본값)에 더한다 — Case 명시 → 프로젝트 기본값 → 시스템 기본값(`HADS_RUN_TIMEOUT_SECONDS`, 기본 3600),
  이력·출처·복귀가 기존 그대로 따라온다. 작업 종류별 층은 두지 않는다(D-95 "모든 실행 1시간"). 설정 범위는 **10초~24시간**
  (화면은 분 단위, 시험이 짧은 값을 쓸 수 있게 초로 저장). 시스템 기본값(환경 변수)은 1초부터 받는다(시험용).
- **적용 시점은 실행을 만들 때다.** 그때의 유효값을 실행 행에 적고(`run.timeout_seconds`) 배정이 그 값을 싣는다 — 바꾼 값은
  **다음 실행**부터이고, 재배정된 같은 실행은 적힌 값 그대로다. Runner 는 배정 값이 없으면(옛 제어부) 자기 기본값 1시간.
- **시간 초과는 `unknown` 그대로이고 사유가 따로 남는다.** Runner 가 결과에 `stop_reason`(`timeout`·`stop_requested`)과 적용한
  제한을 싣고 제어부가 `run.stop_reason` 에 적는다. 모르는 것을 실패로 바꾸지 않는다(P1 계약) — "시간 초과" 는 결과가 아니라
  **끊긴 이유**다.
- **시간 초과 실행의 부분 결과는 기준 판정에 쓰지 않는다**(D-95): 기준 보고를 적용하지 않는다(`run_timed_out`). 출력은 남아
  실행 상세에서 열린다.
- **끝난 것이 확인된 시간 초과 실행은 "결과를 확정할 수 없는 실행" 에서 뺀다.** 지금은 `unknown` 실행이 하나라도 있으면
  자동 완료·종료 확정이 영원히 보류된다 — 시간 초과 뒤 다시 시도해 통과해도 업무가 닫히지 않는다. 사람의 중단(`cancelled`)이
  종료 확인되면 빠지는 기존 규칙과 같게, **시스템이 끊었고 트리 종료가 확인된**(`execution_unconfirmed` 가 아님) 시간 초과
  실행만 뺀다. 다른 `unknown`(결과 유실 등)은 그대로 보류다.
- **같은 제한으로 자동 재시도하지 않는다 = 유효 제한이 그 실행의 제한보다 커야 다시 돈다.** 진행기가 실행 걸음을 만들 때
  같은 목적·같은 작업의 마지막 실행이 시간 초과였고 지금 유효 제한이 그 실행의 제한 이하이면 사람 대기 `run_timed_out`
  (작업·실행·적용 제한·지금 제한과 출처). 카드의 **"제한 시간 늘려 다시 시도"** 가 Case 제한을 올리면(이력) 진행기가 이어
  간다(기존 `PUT /progress/limits` 경로). 시간 초과 실행은 재시도 상한(`task_retry_limit`)의 소비로 세지 않는다 — 한도를 늘린
  다시 시도는 사람의 결정이다. 모든 진행기 실행 걸음(의도·준비·게이트 검토·작업·분석)에 같은 규칙.
- **수정 사이클 한도는 새 키 `remediation_limit`(기본 2, 0~10, 0 = 끔 → 바로 사람 카드)** — 진행 상한의 셋째 키. `repair_limit`
  (초안·준비 산출물 재작성)과 다른 축이다. D-29 "최초 품질 실패 뒤 repair 기본 2" 와 같은 수. 사용 수는 **이 Case 에서 진행기가
  연 수정 사이클의 수**이며 새 의도·계획 버전으로 초기화하지 않는다(FR-07).
- **수정 사이클의 기록은 작업 그래프 리비전이다.** `remediation_cycle`·`remediation_attempt` 표는 쓰지 않는다 — 그 표는
  품질 게이트 검증 1회(`quality_gate_run`, 외래 키 필수)의 repair 기록이고, 성공 기준의 검증 Task 는 게이트가 아니다
  (quality-gates 49행 "합의한 성공 기준을 확인하는 테스트는 별도 검증 작업"). 거기에 적으면 게이트 판정이 없는데 있는
  것처럼 보인다. 대신 새 리비전 출처 `progressor_remediation`(행위자 `work-progressor`, 사유 = 미충족 기준·근거 실행·차수)으로
  남기고, 사용 수·이력은 그 리비전들에서 도출한다(저장 값 없음). D-30(설정 변경은 다음 자동 수정부터)은 한도를 걸음마다
  다시 읽는 것으로 그대로 성립한다.
- **"근거와 함께 보고한 `not_met`" 의 뜻:** 끝까지 돈(`completed`) 검증 실행이 그 기준에 대해 요약을 적은 `not_met` 을
  보고했고 그 실행에 명령 기록이 하나 이상 있다(종료 코드 무관 — 실패한 시험이 바로 근거다). 명령 없는 `not_met`·검증이 아닌
  실행의 `not_met`·`unverified` 는 수정 사이클을 열지 않는다 — 사람 카드(지금의 `criteria_unresolved`)에 이유가 붙는다.
- **무엇을 더하는가:** 미충족 기준을 구현하는(`implements`) 구현 Task(없으면 그 검증 Task 가 기다리던 구현 Task, 그것도 없으면
  마지막 구현 Task — UI-05a QG-04 repair 와 같은 규칙)의 저장소마다 수정 구현 Task 하나(`FIX<n>`, 종류 implementation, 그 기준을
  `implements`, 출처 `observation`), 그리고 그 뒤의 재검증 Task 하나(`REVERIFY<n>`, 원래 검증 Task 의 종류·저장소, 수정 Task 들에
  의존, **원래 검증 Task 가 확인하던 기준 전부**를 `verifies` — 고친 뒤 다른 기준의 회귀도 본다). 구현 Task 를 찾지 못하면 사람 카드.
- **수정 실행의 입력:** 구현 Task 에 연결된 기준이 지금 `not_met` 이고 근거 검증 실행이 있으면, 그 검증 실행의 출력(PC 에
  있는 원문)을 핵심 고정 참조(새 역할 `verification_report`)로 싣고 지시문에 "검증이 보고한 미충족" 블록(기준·요약·근거 실행,
  "기준·시험을 약하게 만들어 통과시키지 않는다")을 넣는다. 사람이 작업 탭에서 더한 수정 Task 도 같은 입력을 받는다.
- **사이클은 남은 작업이 없을 때 연다.** 그래프에 배정 가능한 작업이 남아 있으면 그것부터(다른 검증이 같은 코드를 볼 수
  있다). 모든 작업이 끝났는데 근거 있는 `not_met` 이 있으면 한도 안에서 사이클, 아니면 완료 단계(사람 카드).

**구현 중 더한 상세 설계 선택(S-037, 기존 시험이 드러냄 — 구현 전에 여기 적었다):**

- **원인·조사 결론 의무(`cause`·`answer`)의 `not_met` 은 사이클을 열지 않는다**(`investigation_obligation`). 확정 필수 기준의
  판단 불가(`inconclusive` → `not_met`)는 구현 수정으로 충족되지 않는다 — 더 조사할지는 사람이 정한다(P4-08 의 혼합 목적
  시험이 이 경우를 고정하고 있었다).
- **"근거" 의 실제 모양:** 명령이 하나도 없는 검증은 Runner 가 이미 실패로 적는다(P3-03 — `no_command_executed`). 그래서 끝까지
  돈 검증에서 빠질 수 있는 근거는 **요약**이다(`no_summary`). 명령 기록 검사(`no_commands`)는 다른 경로(직접 API)의 방어로 남긴다.
- **Runner 는 시간 초과 실행의 결과를 `unknown` 그대로 보고한다.** 목적별 산출물 검사(명령 없음·변경 없음 → 실패)가 끊긴 출력을
  실패로 바꾸면 제어부가 `timeout`+`failed` 를 거부해 결과가 영원히 들어가지 않는다 — 검사 뒤 결과를 되돌리고 부분 기준 보고를
  싣지 않는다. 사람의 중단(`stop_requested`)은 UI-02 그대로 산출물 검사가 `failed` 로 적을 수 있어 제어부는 `completed` 만 거부한다.
- **DB 의 키별 범위 CHECK**(재작성·재시도·수정 사이클 ≤ 10, 제한 시간 ≥ 10)를 둔다 — P4-05b 의 "DB 도 범위 밖을 받지 않는다(마지막
  방어선)" 를 유지한다.
- 기존 시험 셋의 의미를 바꿨다(삭제 아님): `test_work_progressor` AC-10·`test_profile_flows` AC-3 은 **사이클을 끈 업무**
  (`remediation_limit = 0`)의 예외 카드를 보고 카드의 사이클 정보(`off`)를 확인한다. `test_profile_flows` AC-5 의 수정만 충족
  경우는 그대로 예외 카드이며 이유(`investigation_obligation`)를 확인한다. 진행 상한 조회 시험 둘은 키가 넷이 된 것을 반영했다.

**사람에게 알릴 사실(질문 아님, 인계에 적는다):** 이슈 #8 참고의 `blocked by policy` 는 코드 대조 결과 **제품의 샌드박스가 아니라
codex 자체의 파괴적 명령 거부**다(실행은 D-91 뒤 `danger-full-access` 로 돌았고, 거부된 것은 AI 가 만든 비교용 worktree 의
`Remove-Item -Recurse -Force`). D-91 의 범위(샌드박스)와 맞다. 그 거부까지 풀지(codex 의 승인·샌드박스 전부 우회)는 새 안전
판단이라 이번에 바꾸지 않는다.

## 1. 현재 구현과 차이 (코드 대조)

| 영역 | 지금 | P4-10 뒤 |
|---|---|---|
| CLI 제한 시간 | `runner/cli_adapter.py` `CliExecutor(timeout=600.0)` 고정. 설정 없음 | 배정의 `timeout_seconds`(없으면 3600). 제어부가 실행 생성 때 유효값(Case → 프로젝트 → 시스템 `HADS_RUN_TIMEOUT_SECONDS`=3600)을 `run.timeout_seconds` 에 적음 |
| 끊긴 이유 | `stop_reason` 이 Runner 안에서만 쓰이고 결과에 없음 | 결과 `stop_reason`·`timeout_seconds` → `run.stop_reason`·`run.timeout_seconds`. 조회·작업 탭 실행 목록·상세에 "시간 초과(제한 N분)" |
| 시간 초과 뒤 진행 | 일반 실패처럼 같은 조건으로 `task_retry_limit` 안에서 재시도 → `task_failed`("거듭 실패") | 같은 제한이면 재시도하지 않고 `run_timed_out` 대기 카드("제한 시간 늘려 다시 시도" + 그 실행 상세). 시간 초과는 재시도 소비로 세지 않음 |
| 시간 초과의 부분 결과 | 기준 보고가 있으면 `not_met`·`unverified` 는 적힐 수 있음 | 기준 판정에 쓰지 않음(`run_timed_out`) |
| 시간 초과 실행의 종료 보류 | `unknown` 이라 `unsettled_runs` 에 영원히 남아 자동 완료·종료 불가 | 트리 종료가 확인된 시간 초과는 뺌(사람 중단의 기존 규칙과 같게) |
| 검증 `not_met` 뒤 | 검증 Task `done` → 모든 Task 끝 → `criteria_unresolved` 카드(예외 수용·수정 요청) | 근거 있는 `not_met` 이면 진행기가 그래프 새 리비전(`progressor_remediation`)으로 `FIX<n>`→`REVERIFY<n>` 을 더해 돌림(한도 `remediation_limit`, 기본 2). 한도 뒤·`unverified`·근거 없음은 `criteria_unresolved` 카드에 사이클 정보(사용/한도·이력·이유)와 "수정 한도를 올리고 계속" |
| 수정 실행의 입력 | 없음(작업 탭에서 사람이 더한 Task 도 검증 보고를 받지 못함) | `verification_report`(근거 검증 실행의 출력, 핵심) + 지시문 "검증이 보고한 미충족" 블록 |
| 진행 상한 키 | `repair_limit`·`task_retry_limit`(0~10, DB CHECK) | + `remediation_limit`(0~10)·`run_timeout_seconds`(10~86400). 키별 범위를 조회가 준다 |

## 2. 범위

1. 스키마 **v29**: `run.timeout_seconds`·`run.stop_reason`(옛 행 NULL = 기록 없음), `progress_limit_setting` 재구성(키 넷·값 범위
   0~86400 — 키별 범위는 코드가 검사, 행 보존).
2. #8 — 제어부(설정·실행 생성·결과 기록·기준 보고 제외·종료 보류 규칙), Runner(배정 값 적용·결과 보고), 진행기(`run_timed_out`),
   화면(카드·설정 탭·프로젝트 설정·작업 탭의 시간 초과 표시).
3. #9 — 진행기(수정 사이클 걸음), 제어부(사이클 후보 계산·그래프 리비전·수정 실행 입력), Runner 지시문, 화면(`criteria_unresolved`
   카드의 사이클 정보·한도 올림, 작업 탭의 리비전 출처).
4. 시험(제어부·Runner·브라우저), 가짜 codex 표지 둘, 문서·인계.

범위 밖: 작업 종류별 제한 시간 층, 진행 중 실행의 제한 변경(다음 실행부터), 시간 예산 hard 한도의 자동 중단(D-88 그대로 —
이것은 실행 하나의 제한 시간이지 예산이 아니다), codex 의 파괴적 명령 거부 해제, 남은 계획 작업이 있는데 기준 충족으로 자동
완료되는 기존 완료 규칙(UI-05a 관찰 (1) — 9절, 사람에게 알림), UI-05b, P5.

## 3. 설계

### 3.1 스키마 v29 (`controller/schema.sql`·`controller/db.py`)

- `run`: `timeout_seconds INTEGER CHECK (timeout_seconds IS NULL OR timeout_seconds > 0)`,
  `stop_reason TEXT CHECK (stop_reason IS NULL OR stop_reason IN ('timeout', 'stop_requested'))` — `_add_column_if_missing`.
- `progress_limit_setting`: `limit_key IN ('repair_limit','task_retry_limit','remediation_limit','run_timeout_seconds')`,
  `limit_value BETWEEN 0 AND 86400` — `_rebuild_table`(멱등: 새 키가 CHECK 에 있으면 건너뜀).
- `work_graph_revision.source` 는 CHECK 가 없다(값 `progressor_remediation` 추가는 코드만). `SCHEMA_VERSION = 29`.

### 3.2 진행 상한 (`domain/work_flow.py`·`controller/config.py`·`domain/project_settings.py`)

- `LIMIT_KEYS = (repair_limit, task_retry_limit, remediation_limit, run_timeout_seconds)`, `LIMIT_RANGES`(키별 최소·최대),
  `check_limit` 이 키별 범위를 본다. `ProgressLimits` 에 두 필드(기본 2·3600). 시스템 기본값 검사는 `run_timeout_seconds` 만 1초부터.
- 환경 변수 `HADS_REMEDIATION_LIMIT`(0~10)·`HADS_RUN_TIMEOUT_SECONDS`(1~86400). 이상한 값이면 기동 실패(기존 규칙).
- 조회 `progress_limits_view` 에 `ranges`(키별). 기존 `range`(0~10)는 그대로 둔다(옛 화면 호환).
- API `ProgressLimitsIn` 에 두 키(범위는 도메인이 검사 → 409 가 아니라 422 로). 프로젝트 설정은 키 목록을 그대로 따른다.

### 3.3 실행 제한 시간 (#8)

- **생성:** `Repository.create_run` 이 `effective_progress_limits(case).run_timeout_seconds` 를 `run.timeout_seconds` 에 넣는다(모든
  경로 — 진행기·처리기·관리 API). 배정은 `run` 행을 싣으므로 `timeout_seconds` 가 따라간다.
- **Runner:** `CliExecutor(timeout=3600)`, `execute(..., timeout=None)` 가 호출별 값을 받는다. `agent._execute_with_cli` 가 배정의
  `timeout_seconds` 를 넘긴다. 결과 보고에 `stop_reason`(있으면)·`timeout_seconds`(적용한 값). 원장에도 같이 남아 재전송이 같다.
- **제어부 결과:** `ResultIn.stop_reason`·`timeout_seconds`. `timeout` 은 결과 `unknown`, `stop_requested` 는 `cancelled` 와만 받는다
  (어긋나면 409). `run.stop_reason` 과 적용 제한을 결과와 같은 트랜잭션에 적는다.
- **기준 보고:** `apply_criteria_report` — 실행의 `stop_reason = timeout` 이면 적지 않고 `run_timed_out`.
- **종료 보류:** `unsettled_runs` — `stop_reason = timeout` 이고 `execution_unconfirmed` 가 아니면 뺀다.
- **진행기(순수):** `finished_summary` 에 `stop_reason`·`timeout_seconds`. 새 대기 `WaitReason.RUN_TIMED_OUT`. `run_timeout_step(step,
  state)` — 실행 걸음이면 같은 `(purpose, task_id)` 의 마지막 끝난 실행을 보고, 시간 초과이고 `timeout_seconds ≥ 지금 유효 제한`이면
  대기(`run_id`·`task_key`·`purpose`·`timeout_seconds`·`limit`·`limit_source`). 진행기 `advance` 가 게이트 치환 뒤에 부른다.
  `_graph_phase`·`_analysis_phase` 의 재시도 수는 그 작업의 시간 초과 실행 수를 뺀다.
- **화면:** `RunTimeoutCard`(`wait-card-run_timed_out`) — 작업·목적·적용 제한·지금 제한(출처), "실행 상세 보기"(`hads:open-run`),
  분 입력(기본 = 적용 제한의 두 배, 최대 24시간)·사유, **"제한 시간 늘려 다시 시도"** → `setLimits({run_timeout_seconds})`. 설정 탭
  진행 상한 절과 프로젝트 설정 기본값에 두 키(제한 시간은 분 입력). 작업 탭 실행 목록·상세에 끊긴 이유와 적용 제한.

### 3.4 수정 사이클 (#9)

- **후보 계산(제어부, `Repository.verification_remediation_state`):** 현재 기준 중 `not_met` 인 것마다 근거 실행(`evidence_run_id`)을 보고 —
  검증 실행(`verification_run`)·`completed`·그 실행의 원래 보고 항목에 요약 있음·명령 기록 ≥ 1 이면 후보, 아니면 이유
  (`evidence_not_verification`·`run_not_completed`·`no_summary`·`no_commands`)와 함께 제외. 후보마다 근거 검증 Task, 고칠 구현
  Task(3절 0 규칙), 재검증이 확인할 기준(근거 검증 Task 의 `verifies` 전부). `unverified` 기준은 목록에 `unverified` 로. 사용 수 =
  출처 `progressor_remediation` 리비전 수, 이력 = 그 리비전들(차수·사유·더한 작업·시각).
- **판정(순수, `domain/work_flow.py` `_remediation_phase`):** 조사 Profile 이 아니고 그래프에 남은 작업이 없을 때(= `_graph_phase`
  가 `None`) 후보가 있고 `used < remediation_limit` 이면 걸음 `Step("remediation", …)`(더할 작업 명세). 아니면 완료 단계 — 그
  `criteria_unresolved` 대기에 `remediation{used, limit, limit_source, history, excluded, candidates}` 를 싣는다.
- **진행기:** `remediation` 걸음이면 `Repository.open_remediation_cycle`(현재 리비전 + 작업 둘 이상, 출처 `progressor_remediation`,
  사유) → 진행 이력 → 다음 걸음(수정 구현). 실패하면(오래된 그래프 등) 사유와 함께 `criteria_unresolved`.
- **수정 실행 입력:** `_compose_base_refs` 의 코드 작업 가지 — 구현 목적·작업 키가 있고 그 작업의 `implements` 기준 중 지금
  `not_met` 인 것의 근거 실행 출력 → `verification_report`(핵심, `ContextRefRole` 새 값). `task_for_assignment` 의 기준에
  `verdict`·`result_summary`·`evidence_run_id`. `runner/prompts.py` 가 "검증이 보고한 미충족" 블록과 역할 이름을 붙인다.
- **화면:** `ExceptionCard` 에 사이클 절 — 자동 수정 `used/limit`(출처), 이력(차수·수정·재검증 작업), 사이클을 열지 않은 이유
  (`unverified` = "확인하지 못함 — 구현 결함이 아니라 자동 수정하지 않는다", 근거 없음, 구현 작업 없음, 끔), 한도가 이유면
  **"수정 한도를 올리고 계속"**(`remediation_limit` + 1, 사유). 작업 탭 그래프 머리에 리비전 출처 "진행기 수정 사이클".
  `WAIT_LABEL`·단계 이름 추가.

## 4. 성공 기준

| AC | 기준 | 근거 |
|---|---|---|
| AC-1 | 새 실행의 `timeout_seconds` 가 유효 제한(Case → 프로젝트 → 시스템, 기본 3600)이고, Case 설정을 바꾸면 **다음** 실행부터 새 값·이력·출처가 남는다. 범위 밖 값은 거부 | 제어부 시험 |
| AC-2 | Runner 가 배정의 제한으로 CLI 를 끊고(실제 프로세스), 결과에 `stop_reason=timeout`·적용 제한을 싣는다. 배정 값이 없으면 1시간 | Runner 시험(가짜 codex, 실제 프로세스 트리) |
| AC-3 | 제어부가 `stop_reason`·적용 제한을 실행에 적고 조회가 보인다. 어긋난 조합(`timeout`+`completed`)은 거부 | 제어부 시험 |
| AC-4 | 시간 초과로 끝난 작업을 진행기가 같은 제한으로 다시 돌리지 않고 `run_timed_out` 대기(실행·적용 제한·지금 제한)로 멈춘다. 재시도 상한을 쓰지 않는다 | 제어부 시험 |
| AC-5 | 제한을 늘리면 진행기가 그 작업을 새 제한으로 다시 돌리고, 통과하면 이어 가 자동 완료한다(시간 초과 실행이 종료를 막지 않는다) | 제어부 시험 |
| AC-6 | 시간 초과 실행의 기준 보고는 기준 판정에 쓰이지 않는다 | 제어부 시험 |
| AC-7 | 검증이 근거(요약·명령)와 함께 `not_met` 을 보고하면 사람 없이 새 리비전(`progressor_remediation`, 사유)에 수정 구현·재검증 작업이 더해지고, 수정 실행이 검증 보고(`verification_report`)와 미충족 블록을 받으며, 재검증이 `met` 이면 자동 완료 | 제어부 시험 |
| AC-8 | 재검증도 `not_met` 이면 한도(`remediation_limit`) 안에서 다음 차수, 한도 뒤 `criteria_unresolved` 대기에 사용/한도·이력이 실린다. 한도를 올리면 한 번 더. 0 이면 사이클 없이 바로 카드 | 제어부 시험 |
| AC-9 | `unverified`·근거(요약) 없는 `not_met`·원인·조사 결론의 `not_met` 은 사이클을 열지 않고 카드에 이유가 실린다 | 제어부 시험 |
| AC-10 | 시간 초과 카드에서 제한을 늘려 다시 시도하면 작업이 이어지고, 실행 상세에 "시간 초과(제한 …)" 가 보인다 | 브라우저 시험(가짜 codex, 실제 Edge) |
| AC-11 | 검증 미충족 뒤 수정·재검증 작업이 작업 탭에 리비전 출처와 함께 보이고 업무가 자동 완료된다. 한도 0 이면 카드가 사이클 정보·한도 올림을 보이고 올리면 이어 간다 | 브라우저 시험(가짜 codex) |
| AC-12 | v28 DB 가 v29 로 이행되고(행 보존, 옛 실행 NULL), 새 키 설정이 저장된다 | 이행 시험 |
| AC-13 | 기존 시험 전부 통과(`scripts\run-tests.ps1` 종료 코드 0), 웹 빌드·웹 단위 통과 | 전체 시험 |

## 5. 검증

- 제어부 시험 `tests/test_run_timeout.py`(새): AC-1·3·4·5·6 — `processing_harness` 의 가짜 실행기에 시간 초과 결과(`times_out`)를
  더한다. Runner 쪽 AC-2 는 같은 파일에서 `CliExecutor` 를 가짜 codex(`HADS_FAKE_SLEEP`)로 짧은 제한에 실제로 돌린다(Windows).
  이행 AC-12(v28 → v29, 옛 표를 실제로 재구성)도 이 파일에 둔다.
- 제어부 시험 `tests/test_remediation_cycle.py`(새): AC-7·8·9.
- 웹 단위 `web/src/lib/timeout.test.ts`(새): 제한 시간 표시·제안값·분 변환.
- 브라우저 `tests/test_web_shell.py` +2: AC-10(가짜 codex `HADS_FAKE_SLOW_VERIFY=<초>` — 그 작업공간의 첫 검증만 잔다; 시험이 Case
  제한을 짧게 두고 카드에서 늘린다), AC-11(가짜 codex `HADS_FAKE_VERIFY_NOT_MET` — 수정 구현이 표시 파일을 쓰기 전까지 C-01 `not_met`).
- 전체 `scripts\run-tests.ps1`(AC-13).
- 실제 codex 라이브(선택, 관찰): 시간이 되면 짧은 제한으로 실제 codex 실행이 시간 초과로 기록되는지만 본다. 가짜 CLI 시험이 제품
  규칙을 고정한다.

기준선(S-037 시작, 변경 전): `scripts\run-tests.ps1` → 웹 빌드 성공, 웹 단위 **37**, pytest **795 통과·0 실패·2 건너뜀**
(15분 19초), P1 계약 **18**, 종료 코드 0.

## 6. 경계

- 새 권한·동의·인수 없음. 제한 시간·수정 한도는 설정(권한이 아님)이고, 한도를 올리는 것은 결과의 인수·예외 수용이 아니다.
  수정 사이클은 기존 목적(구현·검증)의 실행이며 진입 검사를 그대로 거친다. 진행기가 더한 작업은 사람의 재계획이 아니므로 출처를
  나눈다(`progressor_remediation`).
- 시간 초과는 결과가 아니다 — `unknown` 그대로, 부분 결과는 판정에 쓰지 않는다. 시간 예산 hard 한도의 의미(D-88)는 바꾸지 않는다.
- 강제 축·게시 규칙(P5) 무변경. 기존 판정·기록 소급 없음(옛 실행의 제한·사유는 NULL = 기록 없음).

## 9. 알려진 한계·설계 선택

- 제한 시간 층은 Case·프로젝트·시스템 셋이다(작업 종류별 없음). 진행 중인 실행의 제한은 바꾸지 않는다(다음 실행부터).
- 제한 시간은 CLI 호출 하나의 벽시계다. 준비·보고 시간은 들지 않는다.
- 수정 사이클의 사용 수는 Case 전체다(기준별이 아니다). 여러 저장소면 저장소마다 수정 작업 하나, 재검증은 하나.
- 근거의 진위(명령·종료 코드)는 여전히 자기보고다(9절 기존 한계) — 명령이 있어야 사이클을 연다는 것은 형식 검사일 뿐이다.
- 남은 계획 작업이 있는데 기준이 모두 충족되면 자동 완료되는 기존 규칙(UI-05a 관찰 (1))은 바꾸지 않았다 — 완료 규칙의 제품
  판단이라 사람에게 알린다.
