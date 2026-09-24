# UI-04b 실행 결과 — 프로젝트 설정·상세 설정 화면 + 알림

기준: [UI-PLAN-04b](../../plans/UI-PLAN-04b.md) / **D-72**(프로젝트 기본값과 명확한 확인 동작) · **D-82**(필요한 상황의 PC 알림)
· D-29 보충(진행 상한의 Project 층) · P4-04(인라인 한도의 Project 조정) / [autonomy-budget-policy](../../autonomy-budget-policy.md)
5절의 우선순위 / [대화 중심 UI](../../ui-conversation-design.md) 3·4·11절 / 스키마 **v25**. 세션 S-030. 선행 [UI-04a 결과](UI-04a-results.md)
· [P4-07b 결과](../../p4/evidence/P4-07b-results.md) · [P4-05b 결과](../../p4/evidence/P4-05b-results.md).

**제품 판단은 새로 내리지 않았다.** 범위는 사용자 동의(2026-09-24, S-028)이고 설정 층의 모양·적용 시점·화면의 자리·알림의
기술은 상세 설계 선택이다(plan 0·9절). S-029 인계가 사용자에게 물으라고 남긴 **참고 후보 자동 활성 조건의 Project 설정화**는
새 제품 판단이라 넣지 않았다(조건은 코드 고정 그대로) — 인계에 다시 적는다. 정책 문서 5절의 다섯 층 가운데 **Project 기본값**
층만 만들었다(Task 층·Profile 기본값 층 없음). 모델·깊이의 프로젝트 기본값은 없고(모델 설정이 없다, 깊이는 업무별 수준 판단)
화면이 그 사실을 그대로 보인다.

## 1. 구현 결과

- **순수 규칙**(`domain/project_settings.py`): 설정 키 `default_tool_id`·`default_autonomy`·`repair_limit`·`task_retry_limit`·
  `context_inline_limit_bytes`·`budget:{metric}:{threshold}` 와 `check_setting`(도구 id 비어 있지 않음·60자, Autonomy 값, 상한
  0~10(`work_flow.check_limit`), 양의 정수 바이트, 예산 > 0 이고 **강제 불가한 정확한 hard 한도는 거부**(`domain.budget.guarantee_for`,
  D-61 — Case 한도와 같은 규칙)), `resolve(case, project, system)` → `(값, 출처)`(`case_setting`·`project_setting`·`system_default`).
  `AutonomySource.PROJECT_DEFAULT`(`case_policy.autonomy_source` 에 CHECK 가 없어 표 재구성 없음), `ProgressLimits.sources` 의
  `project_setting`.
- **스키마 v25**(`controller/schema.sql`·`controller/db.py`): 새 표 하나 `project_setting`(키·`value_json`(≤200)·주체·사유·
  `current`/`superseded`·이력). 기존 표·CHECK 변경 없음, 데이터 이행 없음 — 옛 DB 의 프로젝트는 행이 없고 그것은 "설정 없음 =
  시스템 기본값" 이다.
- **저장 계층**(`controller/repository.py`): `project_settings_view`(값·출처·설정 행 = 적용 시점·시스템 기본값·이력, 도구를
  확인한 PC, 모델·깊이의 "기본값 없음" 문구, 기본 예산 목록·지표별 hard 보장), `set_project_settings`(키마다 검사 → 하나라도
  잘못되면 전부 거부(422), `None` = 현재 행 닫기, 도구는 `project.default_tool_id` 도 갱신), `project_setting_value`·
  `project_budget_defaults`·`inline_limit_for`. **적용 지점**: `_insert_default_policy(case_id, now, project_id)` — 프로젝트 기본
  Autonomy 가 있으면 첫 행이 그 값·`project_default`·`set_by = project`, 이어서 `_insert_project_budget_defaults`(같은 지표·경계 대체,
  `set_by = project_default`, 사유 "프로젝트 기본 예산") — `create_case`·`create_conversation` 둘 다; `effective_progress_limits`
  (Case 명시 → Project → 시스템, 조회 때 계산)·`progress_limits_view.project_default`; `plan_context_package` 가
  `inline_limit_for(case_id)` 를 써 새 실행의 `run.context_inline_limit` 에 기록; `effective_policy` 의 `default_autonomy`·
  `default_autonomy_source`(복귀하면 무엇이 되는가). **복귀**: `reset_autonomy`(새 리비전, 값·출처 = 프로젝트/시스템 기본값, 주체
  사람, `set_autonomy(source=)` 와 같은 경로 — controlled 확인 지점 규칙 그대로, 종료 Case 거부), `clear_progress_limit`(현재 Case
  행 닫기, 이력 보존, 종료 Case 거부, 모르는 키 409), `apply_project_budget_defaults`(다시 적용, `applied` 수, 종료 뒤에도 — D-87).
- **API**(`controller/api.py`): `GET/PUT /api/projects/{id}/settings`(`{values, set_by, reason_summary}`, 422 = 사유 그대로),
  `POST /api/cases/{id}/autonomy/reset`, `DELETE /api/cases/{id}/progress/limits/{key}`(기록 뒤 진행기 호출 — `PUT` 과 같다),
  `POST /api/cases/{id}/budget/project-defaults`. 정책·진입 검사·권위·게시 규칙·`enforcement` 는 바꾸지 않았다.
- **화면**: 주소 `lib/address.ts`(`Screen` 에 `settings`·`repositories`, `rules` 는 설정 화면의 규칙 탭 — UI-04a 주소·카드 링크
  그대로; `settingsLink`·`settingsTabOf`·`screenOfTab`). `shell/ProjectSettings.tsx`(새 — 머리·탭·`settings-back`; 기본값 탭
  `settings-defaults`: 사유 칸, 행마다 `setting-{key}`(`data-source`·`data-value`·적용 시점·시스템 기본값)·변경 폼·`setting-reset-{key}`,
  도구 선택(연결된 PC 의 능력 보고에서 후보)·확인한 PC, 모델·깊이 절(기본값 없음), 기본 예산 추가·해제(`setting-budget-*`), 이력
  `settings-history`; 규칙 탭 = `ProjectRules`(`embedded` — 머리를 줄이고 `rules-screen`·`rules-back` 그대로); 저장소 탭
  `settings-repositories`(목록·기록 저장소 지정·등록)). `shell/CaseSettings.tsx`(새 — 오른쪽 패널 `설정` 탭 `case-settings`: Autonomy
  (`case-setting-autonomy` `data-source`, 두 버튼·사유·`case-autonomy-reset`), 예산(현재 한도·해제·추가·`case-budget-project-defaults`),
  진행 상한(`case-limit-{key}` `data-source`·변경·`case-limit-reset-{key}`), 수준(`case-level-none` 또는 현재 판단과 조정 폼 — 이유·남는
  위험 필수), 저장소 선택(`case-repo-{id}` `data-selected`, 코드 쓰기·게시 허용 체크 — 기본값 없음), QG-02~07(`case-gate-{gate}`
  `data-setting`·예약 표시·설정 폼 — 사유 없으면 비활성), 인라인 한도(읽기 전용), 종료 Case 안내). `ReviewPanel.tsx`(`PanelTab`
  `settings`, `panel-tab-settings`), `Composer.tsx`(적용 요약 `settings-summary-line`·출처를 사람 말로 `settings-summary-sources`·
  `상세 설정 열기` `open-case-settings` → `hads:open-panel` `settings`), `Sidebar.tsx`(`프로젝트 설정` `open-settings` 아래 `프로젝트
  규칙` `open-rules`; `PC 알림` `notify-toggle`·`notify-state`), `Shell.tsx`(설정 화면 셋·등록 저장소 조회·알림 전이 계산·기록·팝업
  클릭 → 대화 열기), `ProgressCards.tsx`(상한 대기 카드의 `project_setting` 출처), `api.ts`(`ProjectSettingsView`·`projectSettingsApi`·
  `repositoryApi`·`qualityGateApi`·`policyApi.resetAutonomy/applyProjectBudgetDefaults`·`progressApi.clearLimit`·라벨), `shell.css`.
- **알림**(D-82): `lib/notify.ts`(순수 — `diffConversations`: `needs_response` 거짓→참, `progress_state → waiting_human`(답변 필요가
  아닐 때)·`blocked`, `current_request_state → unknown`, 종료(`closed`/`cancelled`) 또는 `progress_state → done`; `running`·
  `processing`·`paused`·첫 조회·빈 새 대화는 아니다; `suppressed` = 문서 보임·포커스·같은 대화; `diffProjects`: 다른 프로젝트의
  `needs_response`/`request_unknown` 수가 **늘면** 한 건; `appendLog` 20건). **보충(사용자 결정 2026-09-24, plan 10절):** 목록 행
  `budget_stopped`(`_with_conversation_summary` — `budget_stop(...)["stopped"]`, hard 한도가 없으면 계산 없음)·`project_attention.budget_stopped`,
  종류 `budget_stop`(거짓→참 전이, 한도를 올리면 풀리고 다시 닿으면 다시), `diffProjects` 의 예산 도달 수 증가, 목록 행 배지 `예산 도달`,
  선택기의 다른 프로젝트 수. `shell/notifier.ts`(권한 상태·요청·`Notification`
  팝업, 클릭 → `onOpen`). `Prefs.notifications`(기본 꺼짐 — 브라우저 권한이 사람의 행동을 요구한다). 화면 안 알림 기록
  `notice-log`(`notice-{n}` `data-kind`·`data-case`·`data-project`·`data-suppressed`·`data-popped`, `열기`).
- **문서**: decisions D-72·D-82 구현 기록·D-29 보충, ui-conversation-design 3·4·11·12절, autonomy-budget-policy 5절 구현 상태,
  review-acceptance-matrix AC-46·47, README, DEVELOPMENT.

## 2. 성공 기준 근거

| 기준 | 근거 |
|---|---|
| AC-1 | `tests/test_project_settings.py::test_project_defaults_apply_to_new_conversations_and_runs_but_not_to_existing_ones`(초기 view: Autonomy `system_default`·`setting = None`, 상한 (2, `system_default`), 인라인 한도 = 제어부 기본값, 도구 (`codex`, `registration`), 기본 예산·이력 없음, 모델·깊이 `value = None` + 문구, 확인한 PC `[(test-host, verified)]`; 변경 뒤 값·`project_setting`·설정 행(주체·사유·`current`·`created_at`)·기본 예산 두 건(보장 `absolute`/`display_only`)·이력 5행) · `::test_bad_project_settings_are_refused_atomically_and_reverting_closes_the_row`(복귀 `null` → `system_default`·`setting = None`, 이력 `superseded`+`superseded_at`, 다른 키 그대로; 도구 변경 → 컬럼·이력·확인 안 된 PC `not_reported`) · 브라우저 시험(3절: 기본값 탭의 출처·적용 시점·이력·강제 불가 hard 예산 거부 문구) |
| AC-2 | 같은 첫 시험(설정 **뒤** 대화: `autonomy_source = project_default`·`autonomy_recorded`·`effective_autonomy = controlled`, 예산 행 `set_by = project_default` 두 건; 설정 **전** 대화: 정책 행 `system_default` 그대로·예산 없음(`unlimited`)·`default_autonomy_source = project_default`(복귀하면 무엇이 되는가); 설정 전 실행 `run-b0` 의 `context_inline_limit` = 기본값 그대로, 설정 뒤 새 실행 `run-b1` = 4096, `run-b0` 재확인 그대로) · `::test_the_project_default_budget_does_not_admit_more_than_it_says`(기본 예산 `run_count hard 1` → 논의 응답 하나 뒤 예산 정지 `stop.stopped`·`enforcement.budget = enforced` — 설정이 R3 의 강제를 그대로 탄다) · 브라우저 시험(설정 뒤 대화의 요약·상세 설정 탭 출처 `project_default`·`project_setting`·`project_default` 예산 행; 설정 전 대화 `system_default`·예산 행 없음) |
| AC-3 | 순수 `::test_setting_keys_are_checked_and_unknown_or_bad_values_are_refused`·`::test_resolve_prefers_case_then_project_then_system`(0 은 값), 첫 시험(진행 상한: 두 대화 모두 `repair_limit (1, project_setting, setting None)`·`task_retry_limit (1, system_default)`·`project_default {1, None}`; Case 명시 4 → `case_setting`, 준 키만), `::test_bad_project_settings_…`(`fast`·11·강제 불가 hard·0·-1·모르는 키·빈 값 → 422, 이력 없음 — 함께 준 올바른 값도 저장되지 않음) |
| AC-4 | `::test_a_case_returns_to_its_defaults_with_new_records_and_closed_cases_keep_the_policy_refusal`(Autonomy: 명시 → 복귀 = r3 `controlled`·`project_default`·`owner`·사유, 이전 행 `superseded`, 확인 지점 `required` 둘; 프로젝트 기본값 지운 뒤 복귀 = r4 `ask_on_decision`·`system_default`·확인 지점 없음; 상한: Case 5 → 해제 → (0, `project_setting`, None)·이력 `[(5, superseded)]`·모르는 키 409·이미 상위 층이면 무변경; 예산: 다시 적용 `applied = 1`·`project_default` → 사람 20 → 다시 적용 대체, 이력 셋; 종료 Case: 복귀·해제 409 `case_already_closed`, 예산 복귀 200) · 브라우저 시험(복귀 뒤 리비전 셋, 상한 이력) |
| AC-5 | 브라우저 `tests/test_web_shell.py::test_project_defaults_reach_new_conversations_and_the_case_settings_tab_adjusts_and_reverts`(3절 — 상세 설정 탭의 출처·변경·복귀, 수준 판단 없음 문구, 저장소 선택 코드 쓰기 허용·게시 불허, QG-02 사유 없으면 비활성 → 켬 `case_explicit`). 검사 강도 낮추기 거부·예약은 서버 규칙 그대로(P4-01·02 기존 시험) — 화면은 409 문구를 그대로 보인다(코드 대조) |
| AC-6 | 같은 브라우저 시험(`settings-tab-rules`·`open-rules` → `rules-screen`·주소 `screen=rules`·`rules-back`) + UI-04a 브라우저 시험 둘·P4-07b 브라우저 시험 통과(카드 링크 `?project=…&screen=rules&item=`·한 번에 활성화 그대로) |
| AC-7 | 같은 브라우저 시험(저장소 탭: `primary`·"등록은 선택도 허용도 아니다"·주소 `screen=repositories`). 등록·기록 저장소 지정은 기존 API(P3-R1·R2 시험) |
| AC-8 | (a)(b) 웹 단위 `web/src/lib/notify.test.ts` 5건(첫 조회·진행 중·처리 중·멈춤·같은 상태 무알림; 답변 필요가 확인 필요를 대신함; 확인 필요·막힘·실행 상태 확인 필요·완료(종료/`done`) 각 한 번; 새로 나타난 대화; 보고 있는 대화 억제·기록, 창이 보이지 않으면 억제 아님; 다른 프로젝트의 수 증가만·지금 프로젝트 제외·감소·첫 조회 무알림; 기록 20건) · (c) 브라우저 `::test_pc_notifications_record_transitions_and_suppress_the_conversation_being_viewed`(3절) |
| AC-9 | `::test_a_v24_database_gets_no_project_setting_it_never_had`(v24 DB → 이행 → 표 생성·행 0·표식 25·멱등·본문 컬럼 없음·옛 프로젝트 조회 `system_default`·상한 `project_default {None, None}`) · `tests/test_data_boundary.py` 통과(관련 실행·전체 실행) |
| AC-10 | 코드 대조(진입 검사·정책·권위·`ENFORCEMENT`·DB CHECK 미변경; 새 끝점은 설정·복귀뿐), `::test_the_project_default_budget_…`(`enforcement.budget = enforced` 그대로), 기존 시험 전부 통과(3절), 기준선 대비 +N |
| AC-11 | 3절 — 순수 2 + 서버 4 + 이행 1(`test_project_settings.py` 7) · 웹 단위 +6(`notify.test.ts` 5, `address.test.ts` 1) · 브라우저 2 |
| AC-13(보충) | `::test_the_project_default_budget_does_not_admit_more_than_it_says`(도달 대화의 목록 행 `budget_stopped = True`, 한도 없는 새 대화 `False`, `project_attention.budget_stopped = 1`, 한도를 올리면 `False` — 도출값) · 웹 단위(`budget_stop` 한 번·같은 상태 무알림·풀렸다 다시 닿으면 다시; 다른 프로젝트의 예산 도달 수 증가) · 브라우저 알림 시험(프로젝트 기본 예산 `run_count hard 1` 을 다른 대화에 다시 적용 → `applied = 1`·`stop.stopped` → 기록 `budget_stop`·억제 0·팝업 1·행 배지 `예산 도달`, 보고 있는 대화에는 배지 없음) |
| AC-12 | **하지 않았다**(선택 사항). 이 작업의 규칙은 화면·설정·알림이며 AI 응답 내용에 의존하지 않는다 — 가짜 CLI·실제 Edge 시험이 같은 제품 경로(제어부·Runner 프로세스·브라우저 알림 권한)를 지난다 |

## 3. 검증

### 자동 시험

기준선(S-030 시작, 변경 전, `pwsh -File scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **21**, pytest **696 통과·2 건너뜀·0 실패**
(11분 39초), P1 계약 **18**, "전체 시험 통과". S-029 인계의 수치와 같다.

전체 실행(`pwsh -File scripts\run-tests.ps1`) 세 번:

보충 전 1차 전체 실행: 웹 빌드 성공, 웹 단위 **27**(+6), pytest **705 통과·2 건너뜀·0 실패**(12분 3초, 기준선 696 에서 +9 = 서버 7 +
브라우저 2), P1 계약 **18**, "전체 시험 통과". **예산 도달 알림 보충 뒤 2차** 전체 실행: 703 통과·**2 실패**·2 건너뜀(12분 19초) — (a)
`tests/test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure` 는 DEVELOPMENT 9절에
적힌 시계 해상도 흔들림(S-022 관찰)이며 이번 변경과 무관하다(단독 재실행 통과), (b) `tests/test_request_processor.py::
test_lists_carry_activity_attention_and_derived_connection` 은 프로젝트 주의 수의 정확한 모양을 단언하는 시험이라 보충이 더한
`budget_stopped: 0` 을 기대값에 더했다(검사 삭제 없음, 그 파일은 작업 트리가 CRLF 여서 LF 로 되돌렸다). 두 파일 재실행 46 통과.
**3차(최종) 전체 실행:** 웹 빌드 성공, 웹 단위 **27**, pytest **704 통과·1 실패·2 건너뜀(12분 29초)** — 실패 1은 같은 시계 해상도
시험(`test_quality_changes.py`, 9절의 기존 한계)이며 단독 재실행에서 다시 통과했다. 스크립트가 pytest 실패로 멈춰 P1 계약 unittest 는
따로 실행해 **18** 통과(이 실행에는 "전체 시험 통과" 줄이 없다 — 세 번째 실행에서도 그 시험 하나만 실패했고 UI-04b 시험은 세 번 다
통과했다). 경고 2건은 기존 deprecation 이다. 건너뜀 2건은 `tests/test_migration.py` 의 v1·v2 이행 시험(옛 스키마 커밋 창 — 제품 무관).

새 시험은 첫 회차에 전부 통과했다 — 서버 7(`tests/test_project_settings.py`), 웹 단위 6, 브라우저 2. 다만 서버 시험을 처음 돌릴
때 `domain/project_settings.py` 의 import 가 틀려(`BudgetGuarantee` 는 `domain.budget` 에 있다) 수집 단계에서 멈췄고 import 만
고쳤다(제품 규칙 무관). 브라우저 시험 회차(`-k` 여섯: 새 둘 + UI-04a 둘 + P4-07b 하나 + UI-03 기본 화면)는 6/6, 1분 35초.
관련 서버 묶음(정책·상한·예산·대화·이행·데이터 경계·문맥·진행기·지식·결정 사항 — 216)은 2 건너뜀(이행 시험의 옛 스키마 커밋 창)
외 전부 통과.

브라우저 시험 둘(실제 제어부·실제 Runner 프로세스·가짜 codex·설치된 Edge):

- **설정 화면·상세 설정** — 설정 전 대화 → 설정 화면 기본값 탭(모델 "CLI 가 스스로 정한다"·깊이 "수준 판단"·Autonomy `system_default`·
  도구 확인 PC `verified`·"이 뒤에 만드는 대화" 안내) → 사유 + controlled(`project_setting`·값·출처 문구·적용 시점) → 재작성 상한 1
  → 기본 예산 `input_tokens hard 5` 거부 문구 "cannot be enforced" → `run_count hard 3` "절대 상한" → 이력(controlled·사유) → 서버
  이력 3행 → 저장소 탭(`primary`·등록≠선택≠허용·주소) → 규칙 탭(`rules-screen`·주소 `screen=rules`·왼쪽 `open-rules`·`rules-back` →
  대화·주소에 `screen` 없음) → 설정 뒤 새 대화: 요약에 controlled·펼침의 "프로젝트 기본값"·`상세 설정 열기` → 탭: Autonomy
  `project_default`·상한 `project_setting` 1·예산 행 `project_default`·"수준 판단 없음"·서버 정책 일치 → 자율로(`case_explicit`) →
  복귀(`project_default`, 리비전 셋) → 상한 4(`case_setting`) → 복귀(`project_setting`, 이력 `[(4, superseded)]`) → 저장소 선택(코드
  쓰기 허용·게시 불허) → QG-02 사유 없으면 비활성 → 켬(`on`·`case_explicit`) → 설정 전 대화: `system_default`·예산 행 없음·서버
  `unlimited`.
- **알림** — 권한 허용 문맥, 기록 0 → 켬("켜짐"·`granted`) → 빈 새 대화 뒤 6초 기록 0(첫 조회·빈 대화 무알림) → API 로 만든 다른
  대화의 업무 요청(질문 하나) → 기록 1: `needs_response`·그 대화·억제 0·팝업 1·"답변 필요"·제목, 보고 있는 대화 그대로(자동 전환
  없음) → 보고 있는 대화에 같은 요청 → 질문 카드 → 기록: 억제 1·팝업 0·"보고 있는 대화라 팝업 없음" → 다른 프로젝트의 대화에 요청
  → 기록 `project_attention`·"답변 필요 1"·"자동으로 옮기지 않는다"·선택기 그대로 → (보충) 프로젝트 기본 예산 `run_count hard 1`
  → 다른 대화에 다시 적용(`applied = 1`·도달) → 기록 `budget_stop`·억제 0·팝업 1·행 배지 → 기록의 `열기` → 그 대화가 열림(제목).

### 실제 CLI·브라우저

하지 않았다(AC-12 선택 사항). 실제 codex 가 바꾸는 것은 응답 내용뿐이며 이 작업의 규칙(설정 층·적용 시점·복귀·알림 전이·억제)은
그것에 의존하지 않는다. 실제 브라우저 팝업의 모양·클릭은 헤드리스 Edge 밖이라 시험이 보지 못한다 — 화면 안 기록(`data-popped`)이
`new Notification` 이 예외 없이 만들어졌다는 것까지만 말한다.

## 4. 경계·한계

- **설정은 권한·동의·인수·준수가 아니다.** 진입 검사·예산 강제(R3)·확인 지점(R4)·게시 규칙은 그대로이고 `enforcement` 넷이
  `enforced`, `publish` 는 P5 다. 새 끝점은 값을 기록·닫을 뿐이다.
- **소급 없음.** 프로젝트 기본값은 그 뒤에 만든 대화(정책·예산 행)·실행(인라인 한도)에만 적용된다. 진행 상한만 조회 때
  계산되는 유효값이라 Case 설정이 없는 기존 Case 에도 지금의 프로젝트 기본값이 보인다(저장된 값이 없었다). 화면이 출처를 보인다.
- **Project 층만 있다.** Task 층·Profile 기본값 층은 없고 조회에 그 출처가 나타나지 않는다. 모델·깊이의 프로젝트 기본값은 없다.
- **도구 변경은 확인이 아니다.** 어느 PC 도 확인하지 않은 도구를 기본값으로 두면 그 뒤 실행이 진입 검사에서 `tool_not_available`
  로 거부된다 — 화면이 확인 상태를 보이지만 막지 않는다. 진행 중 실행은 그대로다.
- **알림은 조회 위의 전이다.** 5초 조회 간격 안의 두 전이는 마지막 것만 보이고, 탭이 닫혀 있으면 알림이 없다(서버 푸시 없음).
  예산 hard 도달은 보충(사용자 결정)으로 알린다 — 목록 행의 도출값이며 R3 판정 그대로다. 실행 실패 자체는 별도 알림이 없고 막힘·확인
  필요·요청 상태로 드러난다. 권한이 없으면
  기록만 남는다. 기록은 알림이 아니다.
- **참고 후보 자동 활성 조건의 설정화는 넣지 않았다** — 사용자 결정(2026-09-24, 작업 보고 뒤): **나중에 필요하면 한다**(코드 고정 그대로).
- **원문 경계 그대로.** 설정 값은 짧은 값(도구 id·Autonomy·정수·지표 한도)이고 알림 본문은 제목·상태의 사람 말이다. 본문 표는
  `knowledge_body` 하나 그대로다(데이터 경계 시험).
- **스키마 v25** — 새 표 하나. 기존 표·CHECK 변경 없음.

## 5. 다음

사용자 결정(2026-09-24, 작업 보고 뒤): 남은 네 항목은 **두 단계** — **UI-04c** = D-86 활성 목적·Profile 이행 + D-88 실행시간 합계
계측 + D-89 외부 편집·작업 PC 열기, **UI-04d** = D-84 대화 검색 + D-77 미커밋 포함 시작(DEVELOPMENT 1.11절). 참고 후보 자동 활성
조건의 Project 설정화는 나중에 필요하면. 예산 도달 알림은 이 문서의 보충(AC-13)으로 넣었다. 커밋·push 는 사용자 지시 대기.
