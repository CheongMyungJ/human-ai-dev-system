# UI-04c 실행 결과 — 활성 목적·Profile 이행(D-86) + 실행시간 합계(D-88) + 외부 편집·작업 PC 열기(D-89)

기준: [UI-PLAN-04c](../../plans/UI-PLAN-04c.md) / **D-86**(미완료 업무의 목적 확장·유형 변경) · **D-88**(시간 한도 선택 시 실행시간
합계를 기본으로) · **D-89**(직접 파일 편집은 외부 편집기) / [대화 중심 UI](../../ui-conversation-design.md) 4.1·5.1·10.1절 /
[case-profiles](../../case-profiles.md) 5절 / 스키마 **v26**. 세션 S-031. 범위는 사용자 결정(2026-09-24, S-030: 남은 네 항목을 두
단계로 — 이것이 1단계). 선행 [UI-04b 결과](UI-04b-results.md) · [UI-04a 결과](UI-04a-results.md) · [P4-03 결과](../../p4/evidence/P4-03-results.md)
· [P4-05 결과](../../p4/evidence/P4-05-results.md).

**제품 판단은 새로 내리지 않았다.** S-030 인계가 물으라고 남긴 두 가지 — 새 의도 버전의 동의 규칙, 진행 중 실행의 처리 — 는
기존 정책을 그대로 적용했다(개정 뒤 새 버전은 P4-05 의 의도 단계(QG-01·material delta·사람의 동의)를 그대로 지난다; 끝나지
않은 실행이 있으면 개정을 거부한다 — "실행 사이 잠금 유지" 의 적용). 상세 설계 선택(개정 = 이력·되돌림 = 또 하나의 개정, 유지
항목·유지 목적, 소유 Profile 의 의무 도출, AI 해석 경로의 좁은 규칙, v1 Case 거부, D-88 은 지표를 바꾸지 않음, 열기 = Runner
명령·자기 worktree 만·확인한 지원만·60초 만료, 외부 변경 확인 = 쓰기 실행 직전 Runner)은 plan 0·9절.

## 1. 구현 결과

### D-86 — 같은 Case 의 Profile 개정

- **순수 규칙**: `domain/profiles.py` 의 `FIELD_OWNER`·`field_owner`(의미 항목 → 그 항목을 가진 Profile), `retained_fields`(이전
  Profile 들의 의미 항목 중 현재 Profile 에 없는 것을 이전 순서로 누적), `field_order`/`required_fields(retained=)`(공통 여섯 → 현재
  의미 항목 → 유지 항목). `domain/completion_meaning.derive_obligation(version=)` — 유지 항목의 기준은 **그 항목을 가진 Profile 의
  계약**으로 도출한다(`cause_questions` 는 defect_fix 아래서도 `cause`); 보고값 우선·공통/자기 항목은 현재 계약 그대로·판을 모르는
  옛 호출자는 현재 계약. `domain/intent_doc.py` **문서 v6** — `compose(retained_fields=)` 가 유지 항목을 항목 순서 뒤에 두고
  `retained_fields` 를 적으며 그 항목을 가리키는 기준을 받는다(유지 항목이 없으면 그 기준은 항목 밖이라 거부); `parse` 는 v1~5 를
  0건으로 읽고 `structure` 가 유지 항목을 그대로 올린다. `domain/conversation.py` — `Interpretation.objectives`, `parse_interpretation`
  의 `profile_change`(Profile 필수, 목적은 열거값 — 모르는 것은 `invalid`), `interpretation_refusal` 이 `profile_change` 도 시도.
  `domain/models.py` — `ProfileSource.REVISED`, `InterpretationKind.PROFILE_CHANGE`, `ConversationRefusal` 의 `case_not_in_work_stage`·
  `profile_definition_not_current`·`profile_revision_empty`·`runs_unfinished`. `domain/work_flow._intent_phase` — `intent.profile_stale`
  면 `intent_revision` 실행(`INTENT_AUTHORING`, 시도 키 `intent_revision`; 그 뒤는 기존 의도 단계).
- **스키마 v26**(`controller/schema.sql`·`controller/db.py`): 새 표 `case_profile_revision`(from/to Profile·판, 유지 항목·유지 목적·
  추가 목적(JSON, 짧음), 주체, 근거 메시지·해석 실행, 사유, 개정 시점의 최신 의도 버전)과 `workspace_open_request`(D-89);
  `intent_version.profile/profile_version/retained_fields_json`(**옛 행은 그 Case 의 Profile 로 채운다** — 개정 경로가 없었으므로
  만들 때의 값과 같다(당시 사실), Profile 미기록 Case 는 NULL); `conversation_interpretation` 재구성(`kind` 에 `profile_change`,
  `objectives_json`, `applied` CHECK — 행 보존, 멱등). 본문 컬럼 없음.
- **저장 계층**(`controller/repository.py`): `revise_profile`(종료 `case_already_closed`, 준비 단계 `case_not_in_work_stage`, v1/미기록
  `profile_definition_not_current`, 같은 Profile 에 추가 목적 없음 `profile_revision_empty`, 끝나지 않은 실행 `runs_unfinished`, AI 해석이면
  `start_work` 와 같은 메시지·요청·실행 검사; 한 트랜잭션에 Case 행(`kind`·`profile`·`profile_version = 현재판`·`profile_source =
  revised`)과 개정 행 — 유지 항목 = 이전 유지 ∪ 이전 Profile 의미 항목 − 새 Profile 항목, 유지 목적 = `keep` 이면 이전 유지 ∪ 이전
  Profile 의 무조건 필수 의무(새 Profile 이 이미 요구하는 것은 뺀다), 추가 목적; **바꾸지 않는 것** — 위임 근거·예산·`attempts`·확인
  지점·저장소 선택·의도 버전·기준·판정·결정), `_profile_revision_rows`·`retained_intent_fields`·`carried_objectives`, `profile_revisions_view`
  (개정마다 값 + 근거 메시지 순번 + `criteria_mapping` — 개정 직전 버전의 기준 → 개정 뒤 첫 버전의 같은 키 기준: `carried`/`recheck`/
  `no_target`/`pending`; 대응표를 저장하지 않는다 — 같은 키·같은 지문이 대응이고 `carried_from` 이 흔적), `_intent_revision_for_assignment`
  (의도 재작성 실행에 싣는 이전 Profile·유지 항목·유지 목적·직전 기준의 키·항목·의무·요약). **버전별 Profile**: `create_intent_version` 이
  버전 행에 Case 의 Profile·판·유지 항목을 적고 `_intent_version_profile`(NULL 이면 Case 값)을 `list_intent_fields`·`get_intent_detail`
  (`profile`·`profile_version`·`retained_fields`·`required_fields`)·`apply_success_criteria`(도출 판)가 쓴다 — 개정 뒤 옛 버전은 자기
  항목 집합으로 조회·게이트 검사된다. `required_intent_fields`(다음 구조 보고의 집합 = 현재 Profile + 유지 항목), `case_profile`
  (`retained_fields`·`carried_objectives`·`revision_count`), `apply_intent_structure` 가 `objectives_json` 에 유지 목적을 합친다(AI 가
  적지 않아도 사라지지 않는다), `intent_state.profile_stale`, `assignment_payload` 의 `intent_retained_fields`·`intent_revision`,
  `conversation_view.profile_revisions`, `_record_interpretation` 의 `objectives_json`.
- **처리기**(`controller/request_processor.py`): `apply_interpretation` 이 `profile_change` 면 `revise_profile(decided_by =
  AI_INTERPRETATION, keep_previous_objectives = True, request_message_id = 여는 메시지, interpretation_run_id = 응답 실행)` — 거부
  코드는 해석 행의 `refusal` 로. 그 다음 걸음(의도 개정 실행)은 기존대로 진행기가 잇는다.
- **API**(`controller/api.py`): `POST /api/cases/{id}/profile-revisions`(`{profile, added_objectives, keep_previous_objectives, actor,
  reason_summary(필수)}` → 409 코드·문구, 기록 뒤 `on_human_input` — 상한 변경과 같다), `GET /api/cases/{id}/profile-revisions`.
- **Runner**(`runner/prompts.py`·`runner/agent.py`): `WORK_STAGE_INTERPRETATION_RULE`(업무 단계 논의 응답 — `discussion` 기본,
  같은 문제의 명시적 목적 추가·유형 변경만 `profile_change` + `objectives`; 다른 문제·질문·동의·제한 표명·애매함은 `discussion`),
  `_produce_discussion_reply` 가 업무 단계 응답의 블록도 뗀다; 의도 지시문의 `_intent_field_list(retained)`("이전 목적에서 이어지는
  항목 — 잃지 말고 갱신") 와 `_intent_profile_note(revision)`("계속 충족해야 하는 목적", 직전 기준의 키·항목·의무 — 같은 키는 같은
  obligation), `parse_intent_draft(retained_fields=)`, `_produce_intent_draft` 가 배정의 유지 항목으로 파싱·작성한다. 가짜 codex
  `HADS_FAKE_PROFILE_CHANGE=<profile>[:<obligation,...>]`.
- **화면**: `web/src/api.ts`(`ProfileRevision`·`CriteriaMappingRow`·`ProfileRevisionsView`·`profileRevisionApi`·`obligationLabel`·
  `PROFILE_PRIMARY_OBLIGATION`·`PROFILE_SOURCE_LABEL`·`CRITERIA_MAPPING_LABEL`·거부 문구, `IntentVersion.profile/retained_fields`,
  `ConversationInterpretation.kind` 에 `profile_change`, `ConversationView.profile_revisions`). `shell/ReviewPanel.tsx` `WorkSection`
  (결정 사항 패널의 업무 절: 현재 Profile `decisions-current-profile`·출처·처음 Profile·주체, 계속 충족해야 하는 목적 `decisions-carried`,
  개정 목록 `profile-revision-{n}`(from → to·유지·추가·주체·근거 메시지 `#seq`·사유)과 대응 `revision-mapping-{n}`(승계/재검사/대상
  없음), 개정 폼 `profile-revision-form`(Profile `revision-profile`·추가 목적 `revision-objective-{o}`·이전 목적 유지 `revision-keep`·
  사유 `revision-reason`(필수)·`revision-submit`·`revision-refusal`·`revision-notice`), 종료 Case 는 안내만). `shell/ConversationView.tsx`
  `ProfileRevisionCard`(근거 메시지 뒤 또는 목록 끝의 표식 `profile-revision-marker-{n}`)와 해석 줄의 `profile_change`.

### D-88 — 시간 한도의 기본 지표

- **지표는 그대로다.** `execution_seconds` = 실행별 `assigned_at ~ finished_at` 의 Case 합계(논의·업무·재시도·종료 후 설명 실행 전부,
  병렬 각각; 실행 안에 사람 대기는 없고 대기열 대기는 밖이다; Runner 준비·보고 시간은 든다), `elapsed_seconds` = 대화 생성 후 벽시계.
  `RESERVATION_REASON` 두 줄에 그 정의와 "별도 선택"을 덧붙였다(기존 문구 유지).
- **계측 결함 수정**(`controller/repository.py`): `bump_generation` 이 옛 세대의 `HELD` 예약을 **재배정 시점까지 관측한 값**으로
  `unresolved`/`SettleSource.REASSIGNED` 로 닫는다(시간 = 옛 `assigned_at` ~ 지금, 정확 지표 = 예약값 — 풀지 않는다). 그 전에는 옛
  세대의 시간 행이 새 세대의 `assigned_at` 을 타고 벽시계로 영원히 자랐다(`_metric_exposure` 의 조인). `_metric_exposure` 는 옛 DB 에
  열린 채 남은 옛 세대 행(`generation < run.assignment_generation`)에 시간을 더하지 않고 "모른다" 로 센다(`complete = False`).
  재배정 자체의 정산 의미(옛 세대의 소비가 실제인가)는 P6-03 그대로다.
- **화면**: `web/src/lib/budget.ts`(순수 — `BUDGET_METRIC_LABEL`(여덟 지표 전부)·`BUDGET_METRIC_NOTE`·`DEFAULT_TIME_METRIC =
  execution_seconds`·`orderMetrics`·`formatSeconds`·`timeSummary`), `shell/CaseSettings.tsx` 예산 절의 시간 절 `case-time`
  (`case-time-execution` — 합계·진행 중·미확정·"전부가 아니다", `data-complete`; `case-time-elapsed`), `시간 한도 추가` `case-budget-add-time`
  (지표 = 실행시간 합계·hard·1800), 지표 select 의 이름표·순서(실행 수 → 실행시간 합계 → 경과시간 → …)·선택 지표 설명 `case-budget-metric-note`,
  한도 행의 이름표; `shell/ProjectSettings.tsx`·`PolicyPanel.tsx`·`shell/Composer.tsx` 의 이름표·설명.

### D-89 — 외부 편집·작업 PC 열기

- **Runner**(`runner/desktop.py` 새): `detect()` — `open_folder` 는 Windows 의 `os.startfile` 을, `open_editor` 는 PATH 의 `code` 를
  이 PC 에서 실제로 찾았을 때만 `verified`(근거 문자열), 아니면 `unsupported`(사유); `HADS_RUNNER_DESKTOP=off` 면 둘 다 `unsupported`
  (사유는 그 설정 — 자동 시험이 창을 띄우지 않는다). 능력 행 `runner-host/desktop` 을 `default_capabilities()` 가 더한다. `open_path`.
  `runner/agent.py` — `RunnerAgent(opener=)`(시험은 기록만 하는 것), `handle_controls` 의 `open_requests` → `handle_open_request`: 경로가
  **이 Runner 가 그 (Case, 저장소)에 쓰는 자리**(`worktree_for`, 옛 자리 포함)와 같을 때만 열고(`path_not_owned`), 없으면 `path_missing`,
  지원이 없으면 `unsupported:…`, 예외는 사유로; 결과를 `client.send_open_result`. `_execute_with_cli` 가 배정의 `workspace.last_tree_digest`
  로 `compose_effect(last_tree_digest=, last_effect_run_id=)` → 효과 JSON 의 `external_change_before_run`(직전 지문과 다르면 참, 직전
  실행이 없으면 `null`)·`external_change_basis_run_id`.
- **제어부**(`controller/repository.py`·`api.py`): `request_workspace_open`(준비된 작업공간·소유 Runner·연결(`guard_runner_connected`)·
  그 PC 의 `verified` 능력 — 아니면 409 `open_unsupported: … — <사유>`; 경로는 받지 않는다) → `workspace_open_request` `pending`;
  `runner_controls()` 의 `open_requests`(`pending_open_requests_for` — TTL 60초 지난 것은 `expired`/`not_delivered_in_time`, 전달
  시각 기록, 경로는 `case_workspace` 행의 것); `report_open_result`(다른 PC·이미 끝난 요청 거부); `workspace_view` 의 workspace 마다
  `runner{runner_id, host, connection}`·`open_support`(보고 없음 = `unknown`)·`open_requests`(최근 5), 실행 효과 행의
  `external_change_before_run`·`external_change_basis_run_id`, `unexpected_external_change` 가 **트리 지문**도 비교(HEAD·항목 수가 같은
  채 내용만 바뀐 경우를 잡는다; 지문 없는 옛 효과는 옛 규칙); `_last_workspace_effect`; `assignment_payload` 의 `workspace.last_tree_digest`·
  `last_effect_run_id`. API `POST /api/cases/{id}/workspaces/{repository_id}/open`(`{target: folder|editor, requested_by}` → 202 요청 행),
  `POST /api/runner/open-requests/{id}/result`.
- **화면**(`shell/ReviewPanel.tsx` `WorkspaceRow`, 결과물 목록의 작업공간 절 `workspaces` — 작업공간이 있으면 항상): 저장소·브랜치·
  작업 PC `ws-runner-{repo}`(**작업공간을 만든 Runner** 의 호스트·연결 — 대화의 연결 PC 가 아니다; 옛 작업공간은 목록에서 같은 id),
  경로 `ws-path-{repo}`·`경로 복사` `ws-copy-{repo}`, `작업 PC 에서 폴더 열기` `ws-open-folder-{repo}`·`편집기(VS Code) 열기`
  `ws-open-editor-{repo}`(지원 `verified` 이고 연결일 때만 활성), 지원 문구 `ws-open-support-{repo}`, 요청 결과 `ws-open-result-{repo}`
  (`data-state`), 거부 문구 `ws-open-error-{repo}`; 코드 변경 행 `effect-{run}`(`data-external` true/false/null, "직전 실행 뒤 외부 변경이
  있었다 — 보존됨(되돌리지 않음)"). 안내 문구를 D-89 대로 바꿨다. `api.ts` 의 `WorkspaceOpenRequest`·`OPEN_STATE_LABEL`·
  `OPEN_SUPPORT_LABEL`·`workspaceApi.open`·`RepositoryWorkspace.runner/open_support/open_requests`·`WorkspaceEffect/RunEffectRow` 의 외부 변경 칸.

## 2. 성공 기준 대조

| AC | 근거 | 결과 |
|---|---|---|
| AC-1 개정 기록·보존 | `tests/test_profile_revision.py::test_a_revision_records_history_keeps_everything_else_and_carries_the_criteria` — RCA(분석 뒤 `criteria_unresolved` 대기)에 defect_fix+유지 개정: Case 행 `defect_fix`/`bug`/`revised`, 개정 행 from/to·유지 항목(RCA 다섯)·유지 목적 `["cause"]`·추가 목적 `[]`(restoration 은 새 계약이 요구)·주체·사유·개정 전 버전; 위임 근거·Autonomy·결정·이전 버전·기준·판정 값 그대로, 예약·시도 수는 새 의도 개정 실행의 것만 더해짐 | 통과 |
| AC-2 거부 | `::test_revisions_are_refused_where_they_would_lie` — 준비 단계 `case_not_in_work_stage`, 같은 Profile·추가 목적 없음 `profile_revision_empty`(추가 목적이 있으면 개정), v1 `profile_definition_not_current`, 배정 전 실행 `runs_unfinished`, 종료 `case_already_closed`; 거부된 Case 는 개정 0건·출처 그대로 | 통과 |
| AC-3 항목 유지 | 순수 `::test_retained_fields_keep_the_previous_profile_items_after_the_current_ones`·`::test_the_document_keeps_retained_fields_and_their_criteria`(v6, 유지 항목 없으면 그 기준 거부, v5 읽기 0건); 서버 — 새 버전의 항목 = 공통+defect_fix+RCA, 옛 버전은 `root_cause_analysis`/공통+RCA 로 조회 | 통과 |
| AC-4 기준 승계·의무 | 순수 `::test_a_retained_field_criterion_keeps_the_owner_profiles_obligation`; 서버 — C-01·C-02(`cause`, 보고값)의 `not_met` 이 `carried_from` 으로 승계, C-03(`restoration`) `unverified`, 대응 목록 `carried`×2, 옛 행 `superseded`·판정 그대로 | 통과 |
| AC-5 완료 의미 | 서버 — 새 버전 `objectives_json = ["cause","restoration"]`, `completion_meaning` 의 요구 목적 `{cause, restoration}`(수정만 충족하면 닫히지 않는다 — P4-03 계약); 유지를 끄는 경로는 API 의 `keep_previous_objectives`(폼의 체크)이며 시험은 켠 경우와 같은 Profile 의 목적 추가(`carried []`)를 본다. 기존 P4-03 시험 전부 통과 | 통과 |
| AC-6 쓰기 가드 | `::test_a_revision_does_not_open_product_writes_by_itself` — RCA 에서 구현 실행 `purpose_outside_case_objective`; 개정 뒤에도 409(다른 진입 거부), 실행 생성 없음. `test_profile_completion.py::test_declaring_a_product_objective_does_not_open_implementation_in_an_rca` 그대로 | 통과 |
| AC-7 진행기 | 서버 — 개정 직후 진행 `running`/`intent_revision`, 의도 개정 실행의 지시문에 유지 항목·"계속 충족해야 한다"·직전 기준(`C-01 · expected_outcome · cause`)·`root_cause_analysis → 지금 defect_fix`, 분석 재실행 없음, 새 버전 → material delta 확인 → `intent_agreement`(새 버전 id), `attempts` 보존 + `intent_revision = 1` | 통과 |
| AC-8 AI 해석 | 순수 `::test_a_profile_change_interpretation_needs_a_profile_and_known_objectives`; 서버 `::test_an_ai_profile_change_revises_with_the_user_message_as_basis` — 업무 단계 응답의 `profile_change` 가 사용자 메시지(id·순번)·해석 실행을 근거로 개정(`ai_interpretation`, 유지 `["cause"]`), 블록은 떼어지고 글만 대화에, 진행기가 의도 개정 실행; 모르는 목적은 `invalid`·`not_reported`·개정 없음. 기존 시험 셋의 뜻을 고쳤다(3절) | 통과 |
| AC-9 화면(D-86) | `tests/test_web_shell.py::test_a_purpose_change_in_the_work_stage_revises_the_profile_and_reauthors_the_intent` — 업무 절의 현재 Profile·개정 폼(사유 없으면 비활성) → 개정 → 업무 절·머리·타임라인 표식·개정 목록(유지 목적) → 의도 v2(defect_fix, 유지 항목) → 동의 카드가 v2 를 가리킴, 대응 목록 표시; 준비 단계 대화는 폼 없음 + 서버 409 | 통과(실제 Edge·가짜 codex) |
| AC-10 D-88 표시·기본값 | 웹 단위 `web/src/lib/budget.test.ts`(여덟 지표 이름표·시간 설명·기본 지표·순서·초 표시·요약); 브라우저 `::test_time_limits_default_to_execution_time_and_the_workspace_row_names_the_work_pc` — 시간 절 값·"시간 한도 추가" → `execution_seconds`/hard·설명(병렬) → 한도 행 "실행시간 합계 … 새 배정만 차단", 서버 한도 `no_absolute_cap`, 요약 이름표; `test_budget_time.py::test_the_reason_texts_say_what_the_time_metrics_are` | 통과 |
| AC-11 D-88 계측 | `tests/test_budget_time.py::test_a_reassigned_generation_stops_growing_and_stays_unresolved`(옛 세대 `unresolved`/`reassigned`·관측값 고정, 새 세대만 자람·정산, `run_count` 노출 2 그대로), `::test_a_stale_generation_left_open_by_an_old_database_does_not_add_wall_clock`. 기존 `test_budget.py` 전부 통과 | 통과 |
| AC-12 D-89 지원·열기 | `tests/test_workspace_open.py::test_desktop_support_is_reported_only_when_found`(off·OS·PATH), `::test_open_is_refused_without_a_verified_pc_and_a_connection`(보고 없음/`unsupported` → 409 `open_unsupported`, 미연결 → 409 `runner_disconnected`, 요청 행 없음, 모르는 대상 422), `::test_a_verified_pc_opens_only_its_own_worktree_and_reports_the_result`(`pending` → 제어 전달 → 기록 opener 가 worktree 경로로 호출 → `done`; 재전달 없음; 편집기; 경로가 이 Runner 자리가 아니면 `failed`/`path_not_owned`·opener 미호출; 저장소 선택·허용 그대로; 다른 PC·끝난 요청의 결과 보고 409), `::test_an_undelivered_open_request_expires` | 통과 |
| AC-13 D-89 외부 변경 | `::test_an_external_edit_between_write_runs_is_seen_before_the_next_run_and_kept` — A 뒤 사람이 **내용만** 고치고 B 가 다른 파일을 쓰면 B 의 `external_change_before_run = true`(근거 A), `unexpected_external_change` 참(항목 수·HEAD 는 같다), 사람의 편집 보존, A 는 `null`, C 는 `false`(근거 B). 기존 `test_workspace.py::test_an_unexpected_external_edit_is_surfaced_and_kept` 그대로 | 통과 |
| AC-14 화면(D-88·89) | 브라우저 위 시험 — 작업공간 절의 작업 PC(작업공간을 만든 Runner 의 호스트, 연결됨)·경로·복사·열기 버튼 비활성(`HADS_RUNNER_DESKTOP=off` 사유)·서버도 409 `open_unsupported`·첫 쓰기 실행의 외부 변경 `null` | 통과(실제 Edge) |
| AC-15 스키마 v26·경계 | `test_profile_revision.py::test_a_v25_database_gets_per_version_profiles_and_the_new_tables`(옛 버전 행에 Case 의 Profile 채움·미기록 NULL, 표 둘 0건, 해석 표 DDL·행 보존, 멱등, 본문 컬럼 없음); 기존 `test_request_processor.py::test_the_interpretation_record_keeps_no_body`(컬럼 집합 + 본문 없음) 갱신; 기존 시험 전부 통과, +19 | 통과 |
| AC-16 실제 codex·Edge | **선택 사항 — 미수행.** Edge 는 브라우저 시험(가짜 codex)에서 실제로 열었다. 실제 codex 가 업무 단계 메시지를 `profile_change` 로 읽는 판단은 라이브에서만 보인다 | 미수행 |

## 3. 검증

- **기준선**(S-031 시작, 변경 전, `scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **27**, pytest **704 통과·1 실패·2 건너뜀**(12분 31초),
  P1 계약 **18**(따로 실행). 실패 1건은 DEVELOPMENT 9절의 기존 시계 해상도 흔들림 시험(`test_quality_changes.py::test_the_reservation_lands_…`,
  단독 3회 중 2회 통과) — 이 변경과 무관.
- **최종**(`scripts\run-tests.ps1`, 모든 변경 뒤): 웹 빌드 성공, 웹 단위 **31**(+4 — `budget.test.ts`), pytest **724 통과·0 실패·2 건너뜀**
  (13분 27초, **+19** = 순수 4 + 서버 4 + 이행 1(`test_profile_revision.py` 9) + `test_workspace_open.py` 5 + `test_budget_time.py` 3 + 브라우저 2),
  P1 계약 **18**, "전체 시험 통과". 건너뜀 2건은 이행 시험의 옛 스키마 커밋 창(9절). 흔들림 시험은 이 회차에 통과했다.
- **기존 시험의 의미 검토** — 검사를 지운 것은 없다. 뜻을 고친 것 넷: `test_request_processor.py::test_the_rule_is_added_only_to_discussion_stage_replies`
  (업무 단계 응답은 **다른** 규칙 — `profile_change` 만, 업무화 규칙은 아님; 단계 없는 응답은 규칙 없음), `::test_work_stage_replies_get_no_rule_and_no_interpretation`
  (업무 단계 응답의 `work_request` 블록은 기록만 되고 `case_not_in_discussion_stage` 로 적용되지 않으며 `discussion` 은 아무것도 바꾸지
  않는다 — 규칙을 받았으므로 블록은 떼어진다), `test_work_progressor.py::test_a_work_stage_message_gets_a_read_only_reply_and_nothing_else_moves`
  (같은 뜻), `::test_the_interpretation_record_keeps_no_body`(컬럼 집합에 `objectives_json`). 수치 고정 둘: `test_profile_completion.py::
  test_the_v5_document_reports_enumerations_only`(`doc_version` 5 고정 → 현재 판(6) 이상 + 유지 항목 0건), `test_project_settings.py::
  test_a_v24_database_…`(`== 25` → 현재 판 이상). `test_policy.py::test_a_profile_change_does_not_reset_history` 는 `PUT /profile` 이 없음을
  보는 것이라 그대로 통과한다(개정 경로는 `POST /profile-revisions`).
- **새 시험의 첫 회차** — 제품 결함은 없었고 시험 결함 여섯을 고쳤다: 개정 직후 스냅샷 비교가 진행기가 만든 새 실행의 예약·시도를
  "바뀜" 으로 본 것(새 실행의 것만 더해진다고 고침), 실행 목록이 최신순인 것, 진입 거부 응답의 모양(`_refusals` 도우미), 이행 시험의
  고정 자료가 재구성 뒤 외래 키 검사·CHECK(요청 종료 시각, 메시지의 전송 id·접수 id)에 걸린 것, `implicit_single_repository` 가 dict 인 것,
  브라우저 시험이 동의 때 연 의도 원문 뷰어 뒤에서 목록을 찾은 것. 분리 실행은 Bash 배경 실행으로 띄웠다.
- **실제 CLI(codex) 라이브**: 하지 않았다(선택 사항). 실제 Edge 는 브라우저 시험이 열었다(시험 Runner 는 `HADS_RUNNER_DESKTOP=off`).

## 4. 경계

- 개정·해석·열기는 **권한·동의·인수·준수가 아니다.** 진입 검사·예산 강제·확인 지점·게시 규칙·저장소 쓰기 허용은 그대로다(강제 축
  넷, `publish` 는 P5). 목적 선언·개정만으로 조사 Profile 의 제품 쓰기가 열리지 않는다(AC-6).
- 소급 없음 — 개정은 그 뒤의 의도 버전·실행에 적용된다. 이전 버전·기준·판정·결정·예약·시도 수는 그대로이고 옛 버전은 자기 항목
  집합으로 읽힌다. 이행이 채우는 옛 버전의 Profile 은 당시 사실이다. 시간 지표의 뜻·보장은 그대로다.
- 원문 경계 그대로 — 개정 행은 열거값·짧은 사유·메시지 참조, 열기 요청은 경로를 받지 않고 결과 사유는 짧은 코드, 트리 지문은 해시다.
- 스키마 v26 — 새 표 둘, 컬럼 셋, 해석 표 재구성(행 보존).

## 5. 알려진 한계

- 개정은 정의판 v2 Case 만(v1·미기록 거부, D-62). 같은 조사 Profile 안의 목적 추가는 분석을 다시 돌리지 않는다. 개정 뒤 더한 기준은
  material delta 로 확인 대상(기존 규칙)이고 그 뒤 동의다. 끝나지 않은 실행이 있으면 거부한다.
- AI 해석 `profile_change` 는 이전 목적을 항상 유지한다(유형 정정은 사람의 폼). 되돌림은 또 하나의 개정이다(삭제·되감기 없음).
  유지 항목은 개정마다 누적된다(항목별 화면 표시는 뒤 작업). 실제 codex 의 판단은 라이브에서만 보인다(미수행).
- D-88 은 지표를 바꾸지 않았다 — Runner 준비·보고 시간 포함, 대기열 대기 제외, 절대 상한 아님. 재배정의 정산 의미는 P6-03.
- D-89 열기는 Windows 폴더·PATH 의 `code` 만 확인하고 `done` 은 호출 성공이다. 외부 변경 관측은 쓰기 실행 전뿐이며 제어부는 트리를
  보지 못한다(화면의 "지금" 상태 없음). 시험 Runner 는 열기를 끈다.
- 시작은 `main`/`84252ce` clean·`origin/main` 과 같음. **이 결과는 커밋·push 하지 않았다**(사용자 지시 대기). 라이브 데이터 없음.
  저장소 `var\` 는 건드리지 않았다. 시험이 띄운 제어부·Runner·Edge 는 pytest 가 내렸다.
