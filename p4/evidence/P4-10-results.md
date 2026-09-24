# P4-10 결과 — 이슈 #8·#9 진행기 보강

세션 S-037(2026-09-24). plan: [P4-PLAN-10](../../plans/P4-PLAN-10.md). 범위: 사용자 결정(2026-09-24, S-036 — 다음 세션·UI-05b 앞·한 plan)과
D-95(실행 제한 시간 기본 1시간·시간 초과 구분·같은 제한으로 자동 재시도 않음·부분 결과 판정 제외), 이슈 #8·#9 본문의 완료 조건.
**새 제품 판단은 내리지 않았다** — 상세 설계 선택은 plan 0절(구현 중 더한 것 포함)에 있다.

## 1. 요약

| 이슈 | 지금 제품이 하는 일 |
|---|---|
| #8 실행 제한 시간 | 모든 실행의 CLI 제한 시간이 **설정**이다 — 업무(Case) 설정 → 프로젝트 기본값 → 시스템 기본값(`HADS_RUN_TIMEOUT_SECONDS`, **3600초**). 진행 상한과 같은 자리(이력·출처·복귀, 새 화면 설정 탭·프로젝트 설정). 실행을 만들 때 유효값을 `run.timeout_seconds` 에 적고 배정이 그 값을 싣는다 — 바꾼 값은 **다음 실행부터**. Runner 는 그 제한으로 CLI 트리를 끊고 결과에 `stop_reason = timeout`·적용 제한을 싣는다(결과는 `unknown` 그대로 — 실패가 아니다). 제어부가 `run.stop_reason` 에 적고, 끊긴 실행의 기준 보고는 판정에 쓰지 않는다(`run_timed_out`). 진행기는 같은 목적·작업의 마지막 실행이 시간 초과였고 지금 제한이 그보다 크지 않으면 다시 돌리지 않고 **`run_timed_out` 카드**("제한 시간 늘려 다시 시도" — 분 입력·사유, 끊긴 실행 상세 링크)에서 멈춘다. 시간 초과는 재시도 상한의 소비가 아니다. 트리 종료가 확인된 시간 초과 실행은 종료 보류(`unsettled_runs`)에서 빠진다 — 다시 시도해 통과하면 업무가 닫힌다 |
| #9 검증 미충족 → 수정 사이클 | 모든 작업이 끝났는데 검증이 **근거와 함께**(끝까지 돈 검증 실행·그 기준의 요약·명령 기록) `not_met` 을 보고한 기준이 있으면, 진행기가 사람 없이 작업 그래프 **새 리비전**(출처 `progressor_remediation`, 행위자 진행기, 사유 = 기준·차수·근거 실행)에 수정 구현 `FIX<n>`(그 기준을 implements, 출처 관측)과 재검증 `REVERIFY<n>`(원래 검증 작업이 보던 기준 전부, FIX 에 의존)을 더해 돌린다. 수정 실행은 근거 검증 실행의 출력을 핵심 참조 `verification_report` 로 받고 지시문에 "검증이 보고한 미충족" 블록(기준·요약·근거 실행, 기준·시험을 약하게 하지 말 것)을 받는다 — 사람이 작업 탭에서 더한 수정 작업도 같다. 한도 `remediation_limit`(기본 2, 0 = 끔, 진행 상한의 셋째 키) 뒤·`unverified`·근거 없음·원인/조사 결론 의무·고칠 구현 작업 없음은 `criteria_unresolved` 카드에 사이클 정보(사용/한도·출처·이력·열지 않은 이유)와 "수정 한도를 올리고 계속" 이 붙는다 |

스키마 **v29**: `run.timeout_seconds`·`run.stop_reason`(옛 행 NULL = 기록 없음), `progress_limit_setting` 재구성(키 넷, 키별 범위 CHECK — 재작성·재시도·
수정 사이클 0~10, 제한 시간 10~86400초; 행 보존).

## 2. 구현

- **순수 규칙** `domain/work_flow.py`: `LIMIT_KEYS` 넷·`LIMIT_RANGES`·`check_limit(system=)`·`ProgressLimits` 두 필드, `WaitReason.RUN_TIMED_OUT`,
  `run_timeout_step`(진행기가 게이트 치환 뒤 모든 실행 걸음에 적용), `_task_retries_used`(시간 초과 제외), `remediation_plan`·`_remediation_phase`
  (그래프 걸음과 완료 단계 사이)·`remediation_summary`(대기에 싣는 짧은 정보), `Step.remediation`, `finished_summary` 의 `stop_reason`·`timeout_seconds`.
- **제어부** `controller/repository.py`: `create_run` 의 `timeout_seconds`, `report_result(stop_reason=, timeout_seconds=)`(`timeout` 은 `unknown` 과만,
  `stop_requested` 는 `completed` 가 아닐 때만), `unsettled_runs`(확인된 시간 초과 제외), `apply_criteria_report`(시간 초과 → `run_timed_out`),
  `flow_state`(`verification_remediation_state`), `verification_remediation_state`·`open_remediation_cycle`(기준 리비전 대조 — 그 사이 그래프가 바뀌면 열지 않음)·
  `verification_reports_for_task`, `_replan(source=)`, `_compose_base_refs`(구현 실행의 `verification_report`), `task_for_assignment`(미충족 요약·근거 실행),
  `progress_limits_view`·`project_settings_view` 의 키별 범위. `controller/work_progressor.py`(`run_timeout_step`·`remediation` 걸음),
  `controller/api.py`(`ResultIn.stop_reason`·`timeout_seconds`, `ProgressLimitsIn` 두 키), `controller/config.py`(`HADS_REMEDIATION_LIMIT`·
  `HADS_RUN_TIMEOUT_SECONDS`), `controller/db.py`·`schema.sql`(v29), `domain/models.py`(`WorkGraphSource.PROGRESSOR_REMEDIATION`·
  `ContextRefRole.VERIFICATION_REPORT`).
- **Runner** `runner/cli_adapter.py`(`DEFAULT_TIMEOUT_SECONDS = 3600`, `execute(timeout=)`, `ExecutionOutput.timeout_seconds`, 출력 머리의
  `timeout_seconds`), `runner/agent.py`(배정의 제한을 넘김, 결과의 `stop_reason`·`timeout_seconds`, **시간 초과 실행은 산출물 검사 뒤에도 `unknown`
  그대로이고 부분 기준 보고를 싣지 않음**), `runner/prompts.py`(`verification_report` 설명·"검증이 보고한 미충족" 블록).
- **화면** `web/src/lib/timeout.ts`(새, 순수 — 표시·제안값·분 변환)·`timeout.test.ts`(새), `api.ts`(키·범위·이름표·`Run` 필드·대기·리비전 출처),
  `shell/ProgressCards.tsx`(`RunTimeoutCard`·`RemediationSection`), `shell/CaseSettings.tsx`(진행 상한 절에 두 키, 제한 시간은 분),
  `shell/ProjectSettings.tsx`(수정 사이클 한도·제한 시간 행), `shell/WorkPanel.tsx`(실행 목록·상세의 시간 초과·적용 제한), `PolicyPanel.tsx`
  (관리 화면은 옛 두 키만 — 타입 좁힘).
- **시험 도구** `tests/conftest.py`(`FakeCliExecutor.times_out`·`timeout` 인자), `tests/fake_cli/fake_codex.py`(`HADS_FAKE_SLOW_VERIFY=<초>`·
  `HADS_FAKE_VERIFY_NOT_MET`, 미충족 블록을 받은 구현이 `REMEDIATED.txt` 를 씀).

## 3. 검증

| AC | 결과 | 근거 |
|---|---|---|
| AC-1 설정·적용 시점 | 충족 | `tests/test_run_timeout.py::test_the_run_timeout_is_a_setting_recorded_on_each_new_run` (기본 3600·Case 7200 은 다음 실행부터·이력·범위 밖 422·프로젝트 기본값 1800 은 새 대화에) |
| AC-2 Runner 의 실제 끊기 | 충족 | `test_the_adapter_cuts_the_cli_tree_at_the_given_limit` (가짜 codex 90초 → 제한 2초에 `unknown`·`timeout`·`job_terminated`, 손자까지 OS 에서 종료 확인, 기본 1시간) |
| AC-3 결과 기록의 경계 | 충족 | `test_a_stop_reason_must_match_the_outcome` + 진행기 시험의 `stop_reason`·`timeout_seconds` 기록 |
| AC-4 같은 제한으로 되풀이 않음 | 충족 | `test_a_timed_out_task_waits_for_a_longer_limit_instead_of_retrying_and_then_closes`(대기·다시 시도해도 새 실행 없음)·`test_a_second_timeout_after_raising_waits_again_not_as_a_failure`(늘린 뒤 또 끊기면 `task_failed` 가 아니라 `run_timed_out`, 2번째) |
| AC-5 늘리면 이어 가 닫힘 | 충족 | 같은 첫째 시험(7200 으로 다시 → 기준 충족 → 자동 완료, 끊긴 실행이 종료를 막지 않음) |
| AC-6 부분 결과 판정 제외 | 충족 | 같은 시험(끊긴 실행의 보고 → `run_timed_out`) + Runner 가 부분 기준 보고를 싣지 않음 |
| AC-7 근거 있는 미충족 → 사이클 | 충족 | `tests/test_remediation_cycle.py::test_a_not_met_with_evidence_opens_a_fix_and_reverify_cycle_that_closes_the_work`(리비전 출처·행위자·사유, FIX1·REVERIFY1 의 종류·출처·의존·기준, `verification_report`(핵심·읽음)·미충족 블록, 처음 T1 에는 없음, 자동 완료) |
| AC-8 한도·이력·올림·0 | 충족 | `test_the_cycle_repeats_within_the_limit_then_waits_with_its_history_and_raising_it_goes_on`(한도 1 → `exhausted` 1/1·이력 → 올리면 FIX2·REVERIFY2 → 완료)·`test_a_limit_of_zero_turns_the_cycle_off` |
| AC-9 근거 없으면 열지 않음 | 충족 | `test_unverified_or_command_less_not_met_does_not_open_a_cycle`(`unverified`·요약 없는 `not_met`) + `test_profile_flows` AC-5 수정만 충족(`investigation_obligation`) |
| AC-10 브라우저 — 시간 초과 카드 | 충족 | `tests/test_web_shell.py::test_a_timed_out_verification_waits_on_a_card_and_a_longer_limit_finishes_the_work`(실제 Edge·가짜 codex·실제 Runner — 20초 제한에 끊김 → 카드 → 실행 상세 "시간 초과" → 2분으로 늘려 완료) |
| AC-11 브라우저 — 수정 사이클 | 충족 | `test_a_not_met_verification_is_fixed_and_reverified_by_the_progressor_and_the_card_raises_a_zero_limit`(자동 FIX1·REVERIFY1 → 완료, 작업 탭 "진행기 수정 사이클"; 한도 0 업무의 카드 `off` 0/0 → 한도 올림 → 완료) |
| AC-12 이행 v28 → v29 | 충족 | `test_a_v28_limit_table_is_rebuilt_with_the_new_keys_and_old_rows_stay`(옛 표 실제 재구성·행 보존·키별 CHECK·멱등) |
| AC-13 전체 시험 | 충족 | 아래 "최종 전체 실행"(종료 코드 0) |

**기존 시험의 의미 검토(삭제 없음):** `test_work_progressor` AC-10·`test_profile_flows` AC-3 은 이제 **사이클을 끈 업무**의 예외 카드를 본다
(근거 있는 미충족은 먼저 사이클을 연다 — 의도한 변화). `test_profile_flows` AC-5 수정만 충족은 그대로 예외 카드이고 이유를 확인한다. 진행 상한
조회 셋은 키 넷을 반영했다. P4-05b 의 "DB 도 범위 밖을 받지 않는다" 단언은 키별 CHECK 로 그대로 성립한다.

늘어난 12건 = `tests/test_run_timeout.py` 6 · `tests/test_remediation_cycle.py` 4 · `tests/test_web_shell.py` +2. 웹 단위 +4(`timeout.test.ts`).

**첫 전체 실행이 드러낸 결함(고침):** 새 저장소 메서드 이름 `remediation_state` 가 P4-01 의 같은 이름 메서드(게이트 repair 조회 — `(case_id, gate,
subject_key)`)를 가려 게이트·예약·문맥 시험 여섯이 `TypeError` 로 깨졌다. `verification_remediation_state` 로 바꾸고 새로 더한 함수들에 다른 중복
정의가 없음을 확인했다. 관련 네 모듈(59건) 통과 뒤 최종 전체 실행.

**구현 중 드러난 결함(고침):** 시간 초과로 끊긴 **검증** 실행은 최종 메시지가 없어 Runner 의 산출물 검사가 결과를 `failed` 로 바꿨다 — 그러면
`timeout`+`failed` 를 제어부가 거부해 결과가 영원히 들어가지 않는다. Runner 가 시간 초과 실행의 결과를 `unknown` 으로 되돌리고 부분 기준 보고를
싣지 않게 했다(브라우저 시험이 실제 Runner 로 이 경로를 지난다).

### 기준선과 최종 전체 실행

| 실행 | 웹 빌드 | 웹 단위 | pytest | P1 계약 | 종료 코드 |
|---|---|---|---|---|---|
| 기준선(S-037 시작, 변경 전) | 성공 | 37 | 795 통과·0 실패·2 건너뜀(15분 19초) | 18 | 0 |
| 첫 전체 실행(S-037, 이름 충돌 전) | 성공 | 41 | 801 통과·**6 실패**·2 건너뜀 | — | 1 |
| 최종(S-037, 모든 변경 뒤) | 성공 | **41** | **807 통과·0 실패·2 건너뜀**(16분 12초) | 18 | 0 "전체 시험 통과" |

## 4. 경계

- 새 권한·동의·인수 없음. 제한 시간·수정 사이클 한도는 설정이고 올리는 것은 결과의 인수·예외 수용이 아니다. 수정 사이클의 작업은 기존 목적
  (구현·검증)의 실행이며 진입 검사를 그대로 거친다. 진행기가 더한 작업은 사람의 재계획이 아니므로 리비전 출처를 나눴다.
- 시간 초과는 결과가 아니다 — `unknown` 그대로. 시간 예산 hard 한도의 의미(D-88, 절대 상한 아님)는 바꾸지 않았다 — 이것은 실행 하나의 CLI
  제한이다.
- 강제 축·게시 규칙(P5)·관리 화면(UI-05b 가 지운다) 그대로. 옛 실행·설정 소급 없음.

## 5. 알려진 한계와 사람에게 알릴 것

- 제한 시간 층은 Case·프로젝트·시스템 셋(작업 종류별 없음). 진행 중인 실행의 제한은 바꾸지 않는다(다음 실행부터). 같은 제한으로 한 번 더 시도하는
  버튼은 없다(D-95 — 제한을 늘린다). 진행기 밖의 논의 응답도 같은 제한을 받지만 시간 초과 카드는 진행기 걸음에만 있다.
- 수정 사이클의 사용 수는 Case 전체다. 여러 저장소면 저장소마다 수정 작업 하나·재검증 하나. 근거의 진위(명령·종료 코드)는 여전히 자기보고다.
- **이슈 #8 참고 항목(`blocked by policy`) 확인:** 그 실행(`wp-766d9fec98a7-task-T2-1`, 21:13 KST — D-91 커밋 `5db52a9` 20:59 뒤)의 Runner 원시 로그
  (읽기만 함)에서 거부된 것은 AI 가 만든 비교용 worktree 의 `Remove-Item -Recurse -Force` 이고 문구는 codex 자체의 `exec_command ... rejected: blocked
  by policy` 다 — **제품의 샌드박스가 아니라 codex 의 파괴적 명령 거부**다. D-91(쓰기 실행의 샌드박스 해제)과 어긋나지 않는다. 그 거부까지 풀지
  (codex 승인·샌드박스 전부 우회)는 새 안전 판단이라 바꾸지 않았다.
- **UI-05a 관찰 둘 확인:** (1) 남은 계획 작업(검증 T6)이 있는데 기준이 모두 충족되면 자동 완료되는 것은 기존 완료 규칙(기준 충족 = 완료 조건)
  이며 바꾸지 않았다 — 남은 작업까지 기다릴지는 완료 규칙의 제품 판단이다. (2) 출력 없이도 `met` 보고 — 명령·종료 코드 자기보고의 기존 한계.
- 실제 codex 라이브는 하지 않았다(가짜 codex·실제 Runner·실제 Edge 시험이 제품 규칙을 고정한다; 실제 CLI 트리의 끊기는 UI-02 가 중단 경로로
  실증했고 시간 초과는 같은 종료 경로다).
