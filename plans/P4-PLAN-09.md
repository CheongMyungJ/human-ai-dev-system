# P4-PLAN-09

**P5 전 정리 묶음** — 사용자 결정(2026-09-24, S-034 보고 뒤 "저것들은 다 한번에 했으면 좋겠어" + "4,5,6번 이슈도 추가됐어 이것도 하나로
묶어서"): 한 세션·한 plan 에서 (a) 이슈 #2 이월 질문 답 전달, (b) 이슈 #3 쓰기 실행 샌드박스 해제(D-91), (c) 후속 Case 시작 기준(D-77
마지막 문장), (e) 이슈 #4 업무 취소, (f) 이슈 #5 지식 후보의 거부·열람(D-92), (g) 이슈 #6 대화 제목(D-93), (d) 실제 codex 라이브
(RCA·maintenance 의도 표본 + 실제 검증 `met`). 기준: 설계 v0.8 2차 / D-01~93 / [완료 수명 주기](../completion-lifecycle.md) 2절(취소) /
[문맥 계약](../review-context-contract.md) 2절 / [프로젝트 지식](../project-knowledge.md) / [대화 중심 UI](../ui-conversation-design.md) /
[P1 환경 계약](../p1-environment-contract.md) 6·8절 / [P4-ENV 결과](../p4/evidence/P4-ENV-results.md) / GitHub 이슈 #2~#6.
선행: P3-04(질문 답 고정 컨텍스트 `add_question_answers`), P3-02(작업 그래프·`task_question_block`), P4-04(문맥 등급), P4-05(진행기·
사람 대기 카드·후속 Case 이동), P4-06·07(지식 등록부·후보·채택 확인), UI-03(요청 처리기·AI 해석), UI-04d(시작 기준 카드·스냅샷 커밋).
세션 S-035.

기준선(S-035 시작, 변경 전, `scripts\run-tests.ps1`): 5절 끝에 있다. 시작 상태 `main`/`30c30c0`, 작업 트리 clean, `origin/main` 과 같음.

범위는 **일곱 부분**이며 **부분별 성공 기준이 따로 있다**(4절) — 한 부분이 막혀도 나머지를 끝내고 막힌 것을 인계에 적는다. UI-05a(이슈
#7 관리 화면 정리)·P5(GitHub push·PR)·QG-02~07 자동 실행·파일별 포함 선택은 넣지 않는다. 실제 외부 쓰기(push·PR)는 하지 않는다.

## 0. 제품 판단 — 사용자 결정을 D-91·D-92·D-93 으로 적고, 나머지는 상세 설계 선택이다

사용자가 이미 내린 결정(이슈 본문·S-034 보고의 답)을 `decisions.md` 에 **먼저** 적는다: **D-91**(쓰기 실행의 CLI 샌드박스 해제 —
기능 동작 우선, 읽기 전용만 유지, 받아들인 손실), **D-92**(AI 지식 후보는 범위가 틀려도 받고 채택 확인에서 막는다 — 사용자 말의 자동
등록은 거부 유지, 거부된 것도 내용을 본다), **D-93**(대화 제목 — AI 자동 제목은 사람이 정한 제목을 덮지 않고 사람이 바꿀 수 있다).
(a)·(c)·(e) 는 기존 결정(FR-03 질문 처리·D-77·완료 수명 주기 2절)의 빠진 경로를 채우는 것이며 새 결정이 아니다.

아래는 이 plan 의 **상세 설계 선택**(제품 정책이 아니다, 9절에도 적는다):

- **(a)** 답한 이월 질문의 원문은 그 질문이 **막던 Task 의 실행**에만 간다(현재 작업 그래프의 `task_question_block` 이 이 Task 를 가리키는
  질문 + 연결이 없어 전부를 막던 질문). Task 키 없이 만든 작업 실행(직접 API)은 답한 이월 질문 **전부**를 받는다. 등급은 핵심(`tier_for`
  의 기본 — 빠지면 같은 실패가 재발한다). 지시문 머리에 질문 키·요약을 붙여 "무엇에 대한 답인지" 를 말한다(P4-06 의 `knowledge_head` 와
  같은 자리). 답이 되묻는 말이면 그대로 전달된다 — 판정하지 않는다(관찰만, 이슈 #2 관련 관찰).
- **(b)** Claude 쓰기 실행의 `--strict-mcp-config` 는 **유지**한다(이슈 #3 "남는 제약" 의 권고 — 로컬 환경이 아니라 외부 서비스 MCP 를 막는
  것이고 이번 문제와 무관). 능력 보고에 `write_sandbox = unsupported`(사실 그대로: 쓰기 실행에는 CLI 샌드박스가 없다)를 더하고
  `permission:workspace_write` 의 근거 문구를 D-91 로 바꾼다. P4-ENV 의 ACL 조치는 읽기 전용 실행을 위해 그대로 둔다.
- **(c)** 이전 결과의 판단은 **작업 PC 가 git 으로** 한다(제어부는 git 을 부르지 않는다, D-43): 후속 Case 의 작업공간 요청에 제어부가
  이전 Case 의 브랜치 이름을 실어 내리고, Runner 가 그 브랜치가 있고 그 끝 커밋이 HEAD 에 포함되지 않았을 때만 **만들지 않고 묻는다**
  (`awaiting_basis` 그대로 — 새 상태를 만들지 않는다). 카드의 선택지는 해당하는 것만: `이전 업무 결과에서 시작`(이전 브랜치 끝 커밋) /
  `포함해서 시작`(더러운 트리일 때만) / `커밋된 코드에서 시작`. 이전 결과를 고르면 미커밋 변경은 **포함하지 않는다**(포함은 HEAD 기준에서만
  뜻이 있다 — UI-04d 규칙 그대로). 기본 선택·자동 없음. 기록은 `start_basis = previous_result` + 이전 Case id·브랜치·끝 커밋(스키마 v28).
- **(e)** 1단계만 구현한다 — **끝나지 않은 실행이 없는 Case** 를 사람의 결정(사유 필수·행위자)으로 취소한다. 실행이 남아 있으면 409
  `runs_unfinished`("먼저 중단" — UI-02 의 중단 버튼은 관리 화면에 있고 요청 중단은 대화 화면에 있다). 2단계(중단 연결·종료 확인 대기)는
  **하지 않는다** — 다만 "취소 뒤 도착한 결과가 재시도·repair·후보·진행기를 일으키지 않는다" 는 훅 경계에서 고정한다(취소된 Case 의 결과
  뒤 훅은 아무 것도 만들지 않는다). 취소는 되돌리지 않는다(이어서 하려면 연결된 새 Case — 종료 Case 의 수정 요청 경로 그대로).
  부분 결과·변경·미검증·사용량·작업공간(브랜치·worktree)은 보존한다. 종료 기록은 `closure_record`(후보 없음, `cancelled`)이며 `case.status
  = cancelled` 다. 예산 예약 중 열린 것(`held`)은 `unresolved` 로 닫는다(끝나지 않은 실행이 없으므로 보통 0건).
- **(f)** 범위를 읽지 못한 AI 후보는 **주입하지 않는다**(`select` 가 `scope_unreadable` 로 건너뛴다) — 범위를 모르는 후보를 모든 실행에
  넣지 않는다. 채택 확인의 막는 항목 `scope_unreadable` 은 활성화 요청이 활동을 **명시**(빈 목록 포함 — "모든 작업" 도 사람의 확인이다)하면
  풀린다. AI 가 적은 원래 값은 `knowledge_version.reported_scope_json`(v28) 에 그대로 남는다(활성화의 새 버전에는 없다 — 사람이 정했다).
  거부된 행의 열람은 새 저장이 없다 — `run.knowledge_report_json` 의 항목과 `knowledge_body` 의 본문(있을 때)을 읽는다.
- **(g)** 자동 제목은 **해석 블록**(`hads-interpretation`)의 `title`(40자 이하) 로 온다 — 논의 응답의 글이 아니라 구조로, 본문 경계 그대로
  (서버에 짧은 값만). 적용 규칙: 제목 출처가 `default`(또는 옛 행 — 출처 미기록이고 제목이 기본 문구 "새 대화" / "… · 후속" 그대로)일 때
  첫 논의 응답의 제목을 쓰고, 업무 요청 응답(`work_request`)의 제목으로 **한 번 더** 갱신한다(출처 `ai`, `title_set_by` 가
  `ai:discussion` / `ai:work_start` 로 어느 갱신인지 남는다). 출처 `user` 는 어떤 자동 제목도 덮지 않는다. 옛 행의 출처는 NULL(기록 없음)로
  두고 지어 채우지 않는다. 이력은 가볍게 — 직전 값·시각·주체 한 벌(표 없음).
- **(d)** 라이브는 코드 변경 없이 관찰이다. `p4/live/profile_intents.py` 에 RCA(D)·maintenance(E) 요청 둘과 `--only` 선택 인자를 더해
  D·E 만 돌리고, `ui/live/p405_progress.py` 를 (b) 뒤에 그대로 돌려 검증 실행이 실제 시험을 돌려 `met` 을 적는지 본다. 가능하면 같은 라이브에서
  (g) 의 자동 제목·(c) 의 카드·(e) 의 취소를 관찰한다(못 하면 그 사실을 적는다).

## 1. 현재 구현과 차이 (코드 대조, S-035 시작 시)

| 항목 | 지금 | 이 plan 뒤 |
|---|---|---|
| (a) 작업 실행의 고정 컨텍스트 | `_compose_base_refs` 의 `WORKS_FROM_THE_PLAN` 분기는 동의된 의도·현재 계획 둘뿐. `add_question_answers` 는 의도 작성·검토에만 연결. 답한 이월 질문은 `task_question_block` 을 풀 뿐 어떤 작업 실행의 입력도 아니다(이슈 #2 의 관측 — T8 이 `blocked` "결정이 필요하다") | 그 Task 를 막던 답한 이월 질문의 `answer_artifact_id` 가 `question_answer` 참조(핵심)로 붙고, 지시문 머리에 질문 키·요약이 적히며, 재시도도 같은 입력 |
| (b) 권한 매핑 | `PERMISSION_MAP` codex `workspace_write → --sandbox workspace-write`, claude `acceptEdits`. 능력 보고는 P1-02 근거 그대로 | codex `danger-full-access`, claude `bypassPermissions`(+`--permission-prompts none --strict-mcp-config`), `read_only` 그대로. 능력 `write_sandbox = unsupported`. 환경 계약 6·8절·D-91 |
| (c) 후속 Case 의 시작 기준 | 후속 대화(`create_successor_conversation`)의 작업공간도 HEAD 기준. `StartBasis` 는 둘, 카드는 더러운 트리에서만 | 이전 Case 의 브랜치 끝 커밋이 HEAD 에 없으면 카드가 `이전 업무 결과에서 시작` 을 함께 묻고 `previous_result` 로 기록(v28) |
| (e) 취소 | `CaseStatus.CANCELLED`·`ClosureKind.CANCELLED` 만 있고 경로 없음. `closure_record.candidate_id NOT NULL` | `POST /api/cases/{id}/cancel`, 종료 기록(후보 없음)·상태·요청·진행·예약 정리, 화면 버튼·표시, 취소 뒤 훅 무반응 |
| (f) 후보 받기·거부 열람 | `parse_report_item` 이 활동·경로가 틀리면 `invalid_scope` 거부(사용자 말·AI 후보 구분 없음). 지시문은 활동 값을 말하지 않음. 거부 행은 제목·사유 코드뿐 | 지시문에 활동·경로 규칙. AI 후보는 원래 값을 보존한 채 후보 등록 + 채택 확인 `scope_unreadable`(활동 명시로 해소) + 주입 제외. 거부 행 열람 API·카드 펼침·수동 등록 채우기 |
| (g) 제목 | 새 화면은 "새 대화" 고정, 변경 API 없음, 해석 블록에 제목 없음 | 해석 블록 `title` → 자동 제목(출처 `ai`, 사람 제목 불변), `PUT /api/cases/{id}/title`, 머리 편집·목록 이름 바꾸기, 출처·직전 값 기록(v28) |
| 스키마 | v27 | **v28** — `closure_record` 재구성(`candidate_id` NULL 은 취소만, `cancelled_by`·`cancel_reason`·`decision_id`), `case_workspace` +3(`previous_case_id`·`previous_branch`·`previous_commit`), `knowledge_version` +1(`reported_scope_json`), `case` +4(`title_source`·`title_set_by`·`title_set_at`·`title_previous`), `conversation_interpretation` +1(`title`). 데이터 이행 없음(옛 행 NULL = 기록 없음) |

## 2. 범위

넣는 것: 위 표의 "이 plan 뒤" 전부, 시험(순수·서버·진행기·이행·브라우저), 문서(`decisions.md` D-91~93, `p1-environment-contract.md`,
`project-knowledge.md`, `completion-lifecycle.md` 구현 기록 한 줄, `ui-conversation-design.md` 제목·취소 한 줄, `DEVELOPMENT.md`·`README.md`),
라이브 관찰 문서(`p4/evidence/P4-09-results.md` 에 함께). 끝나면 이슈 #2~#6 을 닫는다(사용자 요청).

넣지 않는 것: 실행 중 Case 의 취소(2단계 — 중단 연결·종료 확인 대기·"취소 요청됨" 표시), 작업공간 정리(브랜치·worktree 삭제), 되묻는 답의
판정, 설계 단계 답이 계획 작성 입력에 들어가는지(이슈 #2 관련 관찰 — 별도), 후속 Case 의 "다른 커밋에서 시작" 입력(UI-05b), 관리 화면
정리(UI-05a·b), 검증 인터프리터 경로 설정(P4-ENV 4절 (b)), Runner 기동 시 샌드박스 능력 점검, 제목의 전체 이력 표, 파일별 포함 선택.

## 3. 설계

### 3.1 (a) 이월 질문 답 전달 — `controller/repository.py`·`runner/prompts.py`·`runner/agent.py`

- `plan_context_package`·`compose_context`·`compose_context_refs`·`_compose_base_refs` 에 `task_key: str | None = None` 을 더한다.
  `create_run` 은 `task_id` 를, `_context_freshness` 는 `run["task_id"]` 를 넘긴다(`check_admission` 은 생성이 세운 같은 계획을 받는다).
- `_compose_base_refs` 의 `WORKS_FROM_THE_PLAN` 분기 끝에 `add_task_question_answers(latest, task_key)`:
  최신 의도 버전의 `intent_question` 중 `state = answered`·`decide_at ∈ {design, plan}`·`answer_artifact_id` 있음을 `created_at` 순으로 보고,
  `task_key` 가 있으면 현재 그래프의 `task_question_block` 이 그 질문을 이 Task 에 연결했거나 **연결 행이 하나도 없는**(전부 막던, 해석
  안 된 참조 포함) 질문만, 없으면 전부를 `QUESTION_ANSWER` 로 더한다(같은 산출물은 한 번). 의도 단계 질문(`decide_at = intent`)은 이미
  의도 버전에 반영됐으므로 넣지 않는다.
- `list_context_refs` 가 역할 `question_answer` 참조에 `question = {key, summary, decide_at, raised_in_stage}` 를 붙인다
  (`intent_question` 을 `answer_artifact_id` 로 찾는다 — 스키마 변경 없음). Runner `_load_context` 가 `question` 을 그대로 나르고
  `build_context_block` 이 머리에 ` — 질문 {key}: {summary}` 를 적는다(`knowledge_head` 옆).
- 재시도·repair 실행은 진행기가 같은 `task_key` 로 만들므로 같은 입력이다(시험으로 고정).

### 3.2 (b) 쓰기 실행 샌드박스 해제 — `runner/cli_adapter.py`·문서

- `PERMISSION_MAP["codex"][workspace_write] = ["--sandbox", "danger-full-access"]`, `["claude"][workspace_write] = ["--permission-mode",
  "bypassPermissions", "--permission-prompts", "none", "--strict-mcp-config"]`. `read_only` 는 그대로. 주석에 D-91 과 손실을 적는다.
- `capabilities_for`: `permission:workspace_write` 의 근거를 "D-91(2026-09-24): CLI 샌드박스 없음 — 사용자 계정 권한으로 돈다" 로,
  새 행 `write_sandbox = unsupported`(같은 근거). `read_only` 행은 P1-02 근거 그대로.
- `p1-environment-contract.md` 6절 `permission` 행과 8절 "쓰기 범위 제한" 행에 D-91 기록을 더한다. `decisions.md` D-91.
- 시험 `tests/test_cli_adapter_permissions.py`(새): `build_command` 가 두 도구·두 권한에서 내는 인자(정확한 목록), `capabilities_for`
  의 `write_sandbox` 행(설치된 도구가 없어도 매핑은 검사할 수 있다 — `resolve_executable` 을 monkeypatch).

### 3.3 (c) 후속 Case 시작 기준 — `runner/workspace.py`·`runner/agent.py`·`controller/repository.py`·`api.py`·`domain/work_flow.py`·화면

- `StartBasis.PREVIOUS_RESULT = "previous_result"`. v28 `case_workspace.previous_case_id`·`previous_branch`·`previous_commit`.
- `claim_workspace_requests`: 요청 행에 `previous_result = {case_id, title, branch}` 를 싣는다 — 이 Case 의 `case_relation(follow_up_change,
  to = 이 Case)` 중 가장 최근 이전 Case 의 **같은 저장소** 작업공간이 `ready` 이고 브랜치가 있을 때, `base_ref = HEAD` 일 때만. 이미
  `previous_result` 를 골랐으면 행의 `previous_commit` 도 싣는다.
- `workspace.prepare(..., previous_branch="", previous_commit="")`: 새로 만들 때(재사용 아님) `start_basis` 가 없으면 이전 브랜치가 있고
  (`rev-parse --verify`) 그 끝 커밋이 HEAD 의 조상이 아니면(`merge-base --is-ancestor` 실패) `NeedsBasis(previous_branch, previous_commit)`
  — 트리가 깨끗해도 묻는다. 더러운 트리면 지금처럼 묻되 `previous_*` 를 함께 싣는다. `start_basis = previous_result` 면 `previous_commit`
  (제어부가 기록한 값)에서 `worktree add`; `base_commit = previous_commit`, `committed_base = HEAD`, 미커밋 포함 없음. `previous_result`
  인데 `previous_commit` 이 비면 `WorkspaceError`(조용히 HEAD 로 바꾸지 않는다).
- Runner `prepare_workspaces`: `NeedsBasis` 보고에 `previous_case_id`·`previous_branch`·`previous_commit` 을 싣는다. 요청의
  `previous_result` 를 `prepare` 에 넘긴다.
- 제어부 `report_workspace_uncommitted(... previous_case_id, previous_branch, previous_commit)` 가 행에 남긴다(빈 목록도 받는다 — `head`·
  지문은 그대로 필요). `decide_start_basis`: `previous_result` 는 행에 `previous_commit` 이 있을 때만(아니면 409 `previous_result_unavailable`);
  고르면 `base_ref` 를 그 커밋 SHA 로 둔다(Runner 가 그 커밋에서 해석). `report_workspace_ready(start_basis="previous_result")` 는
  `committed_base` 가 있어야 받는다. `workspace_state`·`get_uncommitted_list` 조회에 `previous_case_id`·`previous_case_title`·
  `previous_branch`·`previous_commit` 을 더한다. `work_flow._task_phase` 의 대기 항목에 같은 값을 싣고 `WaitReason.WORKSPACE_START_BASIS`
  설명을 넓힌다. `StartBasisIn.basis` 패턴에 `previous_result`.
- 화면 `StartBasisCard`: `previous_commit` 이 있으면 머리를 "어느 코드에서 시작할까 — 이전 업무 결과가 아직 커밋된 코드에 없다" 로, 버튼
  `이전 업무 결과에서 시작`(이전 대화 제목·커밋 앞 10자) 을 더한다. 파일 목록은 수가 0 이면 보이지 않고 `포함해서 시작` 도 숨긴다.
  `ReviewPanel` 작업공간 절의 시작 코드 줄에 `previous_result` 표시. `api.ts` `StartBasis`·`START_BASIS_LABEL` 확장.
- 시험 `tests/test_start_basis.py` 새 절(진행기 경유 — 종료 Case → 후속 대화 → 업무화 → 구현 전 카드): 이전 브랜치 끝 커밋이 HEAD 에 없음 →
  `awaiting_basis` + `previous_commit`; `previous_result` 선택 → worktree 의 `base_commit` = 이전 끝 커밋, 원래 트리·HEAD·브랜치 무변경,
  행 기록(v28); HEAD 가 그 커밋을 포함(fast-forward 뒤) → 묻지 않고 바로 `ready`; 이전 브랜치 없음 → 묻지 않음; 더러운 트리 + 이전 결과
  → 세 선택지·`previous_result` 는 미커밋 미포함; `committed` 선택은 HEAD 에서; `previous_result` 인데 커밋 기록 없음 → 409.
  순수: `prepare` 의 `previous_*` 분기(`tests/test_workspace.py` 절). 이행: v27 DB 의 옛 행이 NULL 로 남는다(`tests/test_migration.py`).

### 3.4 (e) 업무 취소 — `controller/schema.sql` v28·`db.py`·`repository.py`·`api.py`·`work_progressor.py`·화면

- v28 `closure_record` 재구성(`_rebuild_table`, 행 보존): `candidate_id TEXT REFERENCES completion_candidate(id)`(NULL 허용),
  `cancelled_by TEXT`, `cancel_reason TEXT`(≤200), `decision_id TEXT REFERENCES decision(id)`, `CHECK (candidate_id IS NOT NULL OR
  closure_kind = 'cancelled')`, `CHECK ((closure_kind = 'cancelled') = (cancelled_by IS NOT NULL))`. `DecisionKind.CASE_CANCELLATION`.
- `Repository.cancel_case(case_id, *, actor, reason)`: `guard_open_case`(409 `case_already_closed`); 사유 비면 409 `reason_required`;
  `status ≠ finished` 인 실행이 하나라도 있으면 409 `runs_unfinished`(실행 id 목록). 한 트랜잭션: `decision(case_cancellation, subject
  case)`, `closure_record(candidate NULL, cancelled, exception_count 0, snapshot_json = 종료 시점 소비, cancelled_by, cancel_reason,
  decision_id)`, `case.status = cancelled`, 처리 중 요청 → `failed`(note `case_cancelled`; 실행이 없으니 `decide_settle` 이 받는다 — `unknown`
  요청은 그대로 둔다: 확인되지 않은 것을 확인됐다고 적지 않는다), `case_progress` → `done`/`cancelled` + 진행 이벤트, `held` 예약 →
  `unresolved`(`settle_source = case_cancelled`). 작업공간·결과·판정은 건드리지 않는다.
- 취소 뒤 훅 무반응: `WorkProgressor.on_run_finished`·`on_human_input`·`on_workspace_reported`·`on_start_basis_decided` 와
  `RequestProcessor.finish` 의 진행기 위임, `apply_extraction_report`·`apply_knowledge_report` 는 **취소된 Case 에서 아무 것도 만들지 않는다**
  (`case_is_cancelled`). 결과 기록·정산(`report_result`)은 그대로다(부분 결과 보존).
- `POST /api/cases/{case_id}/cancel` `{actor, reason}` → 200 `conversation_view`(`cancellation = {by, reason, at}` 포함). `conversation_view`
  와 `list_cases` 행에 `cancelled`(status 로 이미 드러남) + `cancellation`.
- 화면: `ConversationView` 머리에 `업무 취소`(준비·업무 단계 모두, 종료 아님일 때; 사유 입력 + 확인) → 취소됨 표시(머리·목록 배지
  "취소됨"). 종료 Case 의 설명 전용 진입은 취소 Case 에도 같다(`guard_open_case` 는 이미 `cancelled` 를 종료로 본다).
- 시험 `tests/test_case_cancel.py`(새): 대기 중 취소(종료 기록·상태·요청·진행·예약·작업공간 보존·결과 보존), 실행 중 409, 종료 Case 409,
  사유 없음 422/409, 취소 뒤 배정 거부(`case_already_closed`)·정책 변경 거부·설명 응답 허용, 취소 뒤 훅(진행기·후보 등록)이 아무 것도
  만들지 않음, 되돌리기 없음, 후속 대화 생성 가능. 이행: v27 DB 의 옛 `closure_record` 행 보존(`test_migration.py`). 브라우저: 버튼 →
  확인 → 취소됨(`test_web_shell.py`).

### 3.5 (f) 지식 후보의 거부·열람 — `runner/prompts.py`·`domain/knowledge.py`·`controller/repository.py`·`api.py`·화면

- ① `KNOWLEDGE_EXTRACTION_RULE`·`KNOWLEDGE_REGISTRATION_RULE`: activities 허용 값 여덟과 뜻, "모르면 비워 둔다(빈 목록 = 논의를 뺀 모든
  작업)", paths 규칙(저장소 안 짧은 상대 경로·패턴, 최대 20, 저장소 없이 경로 없음).
- ② `parse_report_item(raw, *, lenient_scope=False)`: `lenient_scope` 이고 활동·경로 검사가 실패하면(또는 경로만 있고 저장소 없음) 거부
  대신 `activities=[]`·`paths=[]` 로 두고 `reported_scope = {"activities": [...원래 값], "paths": [...], "problem": "..."}` 를 항목에 싣는다.
  `_apply_report` 는 `lenient_scope = extraction or raw_item.get("proposal") is True`(사용자 말의 자동 등록은 엄격 그대로 → `invalid_scope`).
  `_register_candidate`→`register_knowledge(reported_scope=)` → v28 `knowledge_version.reported_scope_json`(≤1000). `_knowledge_version_row`
  가 `reported_scope`·`scope_unreadable` 을 낸다. `knowmod.select` 는 `scope_unreadable` 후보를 `Decision.SCOPE_UNREADABLE` 로 건너뛴다.
  `adoption_check` 에 막는 항목 `ADOPTION_SCOPE_UNREADABLE`("AI 가 적은 범위를 읽지 못했다 — 활동을 확인한다"), `requested["activities"]
  is not None` 이면 없음. `activate_knowledge` 의 새 버전은 `reported_scope` 없음.
- ③ `GET /api/cases/{case_id}/knowledge-intake/{run_id}/{index}`: 그 행(`knowledge_intake`)과 `run.knowledge_report_json[index]`(종류·효력·
  저장소·경로·활동·근거·관계·제안 표지 — AI 가 적은 원래 값)·본문(`knowledge_body` 에 있으면 `content`, 없으면 `content = null` 과 이유)·
  사유 코드와 읽을 말(`domain.knowledge.REFUSAL_TEXT`). 등록·근거 행에도 같은 조회가 된다(내용 보기).
- 화면: 후보 카드·결정 사항 패널의 거부 행에 `내용 보기`(펼침: 본문·AI 가 적은 범위·사유 읽을 말) + `이 내용으로 수동 등록`(규칙 화면의
  수동 등록 폼을 그 내용·제목·종류·효력·저장소로 채워 연다 — `sessionStorage` 의 채우기 값 한 벌, 폼이 읽고 지운다; 권위는 등록하는
  사람의 선택 그대로: 후보 체크). 결정 사항 패널의 사유 코드를 카드와 같은 읽을 말로(`lib/labels.ts` 로 옮긴다). 규칙 화면 후보 항목에
  "범위 확인 필요" 배지와 AI 가 적은 값, 활성화 폼의 안내.
- 시험(`tests/test_knowledge_extraction.py`·`test_knowledge.py` 새 절): 지시문에 활동 여덟 전부; 틀린 활동의 추출 후보 → `registered`
  후보 + `reported_scope` 보존 + 주입 제외 + 채택 확인 `scope_unreadable` 막음 → 활동 명시 활성화 통과(새 버전에 `reported_scope` 없음);
  논의 응답의 `proposal: true` 도 같음; 사용자 말 항목은 여전히 `invalid_scope` 거부; 거부 행 열람 API 가 본문·범위·사유를 낸다(본문 없으면
  `content = null`). 브라우저: 거부 행 펼침·수동 등록 폼 채우기(`test_web_shell.py`).

### 3.6 (g) 대화 제목 — `domain/conversation.py`·`runner/prompts.py`·`controller/repository.py`·`request_processor.py`·`api.py`·화면

- `Interpretation.title: str | None`(공백 정리 뒤 40자 초과는 자른다 — 형식 오류로 만들지 않는다; 비면 없음). `parse_interpretation` 이
  `title` 을 읽고 `to_dict` 가 싣는다. `DISCUSSION_INTERPRETATION_RULE` 에 `"title"` 규칙(첫 응답·업무 요청 응답에서 40자 이하, 비밀값 금지,
  이미 사람이 정한 제목이 있으면 시스템이 무시한다는 사실). v28 `conversation_interpretation.title`(≤80), `_record_interpretation` 저장.
- v28 `case.title_source`(`default`|`ai`|`user`, 옛 행 NULL)·`title_set_by`·`title_set_at`·`title_previous`. `create_conversation`·
  `create_successor_conversation` → `default`; `create_case`(관리 화면·API 의 사람 입력) → `user`.
- `Repository.apply_auto_title(run_id)`: 해석 행에 제목이 있고 `title_source ∈ {default, NULL+기본 문구}` 이면 적용(`ai:discussion`),
  해석이 `work_request` 이고 `title_source ≠ user` 이고 `title_set_by ≠ ai:work_start` 면 적용(`ai:work_start`). `RequestProcessor.finish`
  가 응답마다 `apply_knowledge_report` 앞에 부른다. 옛 행 판정: `title_source IS NULL AND title IN ('새 대화') OR title LIKE '% · 후속'`.
- `set_case_title(case_id, title, actor)`: 1~200자(공백 정리), 종료·보관 대화도 허용(`guard_open_case` 없음 — 제목은 판정이 아니다), 같은
  값은 무변경, `title_previous`·`title_set_by = actor`·`title_set_at`·`title_source = user`. `PUT /api/cases/{case_id}/title` `{title, actor}`
  → 200 `conversation_view`. 조회(`conversation_view`·`list_cases`)에 `title_source`·`title_set_by`·`title_set_at`·`title_previous`.
- 화면: `ConversationView` 머리 제목 클릭 → 인라인 편집(저장/취소, 빈 값 거부); `Sidebar` 행의 이름 바꾸기(행 위 `✎` 버튼 → 인라인 입력);
  목록·검색 결과·규칙 화면 출처는 서버 제목을 그대로 보이므로 자동 반영(시험으로 확인). `＋ 새 대화` 는 그대로.
- 가짜: `FakeCliExecutor` 는 시험이 `discussion_response` 에 블록을 넣는다(도우미 상수 `TITLED_DISCUSSION_BLOCK`). `fake_codex.py` 는
  지시문 꼬리의 표지 `HADS_FAKE_TITLE=<제목>` 이 있으면 블록에 `title` 을 넣는다(표지 없으면 없음 — 기존 브라우저 시험의 "새 대화" 유지).
- 시험 `tests/test_case_title.py`(새): 첫 응답의 제목 적용(출처 `ai`), 업무 요청 응답의 한 번 갱신, 사람이 바꾼 뒤 응답·업무화가 덮지 않음,
  `PUT` 의 1~200자·종료·보관 허용·이력, 목록·검색(`conversation-searches` 서버 필드)·규칙 화면 출처(`knowledge_view` 의 `source_case_title`)
  반영, 40자 초과 자르기, 옛 행(출처 NULL) 규칙, 후속 대화 기본 제목 갱신. 브라우저: 머리 편집·목록 반영(`test_web_shell.py`).

### 3.7 (d) 실제 codex 라이브 — `p4/live/profile_intents.py`·`ui/live/p405_progress.py`

- `profile_intents.py` 에 D(`root_cause_analysis` — 설명할 현상·관찰 근거·원인 질문·`cause` 의무·결론 요구 `definitive_required` 기대)와
  E(`maintenance` — 유지 대상·현재/목표 상태·`target_state`·`preservation` 의무 기대)를 더하고 `--only D,E` 로 골라 돈다. 결과는
  `P4-03-live-results.json` 을 덮지 않도록 `P4-09-live-intents-results.json`·`.log` 로 낸다(파일 이름 인자).
- `p405_progress.py` 는 그대로 돌린다 — (b) 뒤 검증 실행이 `met` 을 적는지, 자동 제목(`HADS_FAKE_TITLE` 없이 실제 codex 의 `title`)이
  생기는지 관찰로 적는다. 결과 파일은 기존 `P4-05-live-*` 를 덮지 않게 접미사를 준다.
- 판정은 "AI 가 지시를 따랐는가" 의 관찰이며 제품 규칙 위반만 실패다. 결과는 `p4/evidence/P4-09-results.md` 3절.

### 3.8 문서

`decisions.md` D-91·D-92·D-93(각각 사용자 결정 원문 뜻 + 구현 기록), `p1-environment-contract.md` 6·8절, `project-knowledge.md`(받기 규칙 —
AI 후보의 범위 미확정), `completion-lifecycle.md` 2절 구현 기록 한 줄(취소 경로·1단계), `ui-conversation-design.md`(제목·취소·이전 결과
카드 한 줄씩), `review-context-contract.md`(작업 실행의 질문 답 참조), `DEVELOPMENT.md`(1절 요약 표·현재 상태·1.11절·3절 표·4절·9절·10절
인계), `README.md`, `p4/evidence/P4-09-results.md`(결과·라이브·남은 것).

## 4. 성공 기준

**(a)** AC-1 계획 질문이 T 를 막음 → 답 → T 의 구현 실행 `run_context_ref` 에 `question_answer`(핵심·인라인) 가 있고 Runner 지시문에 답
원문과 "질문 {key}: {summary}" 가 보인다. AC-2 실패 뒤 재시도 실행도 같은 참조를 갖는다. AC-3 다른 Task 만 막던 질문의 답은 그 Task 에
가지 않고, 연결 없이 전부를 막던 질문의 답은 모든 Task 에 간다. AC-4 의도 단계 질문의 답은 작업 실행에 가지 않는다(기존 규칙 유지). AC-5
Task 키 없는 작업 실행(직접 API)은 답한 이월 질문 전부를 받는다.

**(b)** AC-6 `build_command("codex", …, WORKSPACE_WRITE)` 가 `--sandbox danger-full-access`, `read_only` 는 `--sandbox read-only`; claude
쓰기는 `bypassPermissions` + `--strict-mcp-config`. AC-7 능력 보고에 `write_sandbox = unsupported` 와 D-91 근거. AC-8 문서(D-91·환경
계약 6·8절)가 손실·남는 제약을 사실대로 적고 게시 규칙(P5)이 그대로임을 말한다.

**(c)** AC-9 후속 Case 의 첫 쓰기 실행 전 이전 브랜치 끝 커밋이 HEAD 에 없으면 카드가 `이전 업무 결과에서 시작 / 커밋된 코드에서 시작`
을 묻고(더러우면 포함도) 기본 선택·자동 없음. AC-10 `previous_result` 선택 → worktree 가 그 커밋에서 열리고 `base_commit` = 그 커밋,
`committed_base` = HEAD, 행에 이전 Case·브랜치·커밋; 원래 트리·인덱스·HEAD·브랜치 무변경. AC-11 HEAD 가 그 커밋을 포함하거나 이전
브랜치가 없으면 묻지 않는다(깨끗하면 바로 `ready`). AC-12 `previous_result` 는 미커밋을 포함하지 않으며, 기록 없는 `previous_result`
선택은 409. AC-13 옛 행(v27)은 NULL 그대로. AC-14 선택은 권한이 아니다(쓰기 실행의 진입 검사·저장소 허용 그대로).

**(e)** AC-15 끝나지 않은 실행이 없는 Case 를 사유·행위자로 취소 → `closure_record(cancelled, 후보 없음)`·`decision`·`status =
cancelled`·처리 중 요청 종료·진행 `done`·`held` 예약 `unresolved`; 결과·판정·사용량·작업공간(브랜치·worktree)은 그대로. AC-16 실행이
남아 있으면 409 `runs_unfinished`, 종료 Case 는 409 `case_already_closed`, 사유 없음은 거부. AC-17 취소 뒤 새 실행·정책 변경은 거부, 설명
응답은 허용, 후속 대화 생성 가능, 되돌리기 경로 없음. AC-18 취소된 Case 에서 결과 뒤 훅(진행기·후보 등록·재시도)이 아무 것도 만들지
않는다. AC-19 옛 `closure_record` 행이 v28 이행 뒤 보존된다. AC-20 화면: 버튼 → 사유·확인 → "취소됨"(머리·목록).

**(f)** AC-21 후보 규칙·등록 규칙 지시문에 활동 코드 여덟과 경로 규칙·"모르면 비워 둔다". AC-22 틀린 활동·경로의 AI 후보(추출·논의
제안)는 후보로 등록되고 원래 값이 `reported_scope` 에 남으며 주입되지 않는다. AC-23 그 후보의 채택 확인은 `scope_unreadable` 로 막고,
활성화 요청이 활동을 명시하면 통과하며 새 버전에 `reported_scope` 가 없다. AC-24 사용자 말의 자동 등록은 여전히 `invalid_scope` 거부.
AC-25 거부 행 열람 API 가 본문(있으면)·AI 가 적은 범위·사유 코드와 읽을 말을 낸다. AC-26 화면: 거부 행 펼침에 본문·범위·사유가 보이고
"이 내용으로 수동 등록" 이 규칙 화면의 폼을 채운다; 결정 사항 패널의 사유가 읽을 말이다.

**(g)** AC-27 새 대화의 첫 응답이 제목을 내면 제목이 바뀐다(출처 `ai`, 40자 초과는 잘림). AC-28 업무 요청 응답의 제목으로 한 번 더
갱신되고 그 뒤 응답은 덮지 않는다. AC-29 사람이 바꾼 제목은 이후 응답·업무화가 덮지 않는다. AC-30 `PUT` 은 1~200자만 받고 종료·보관
대화도 되며 직전 값·주체·시각이 남는다. AC-31 목록·검색 결과·규칙 화면 출처·후속 대화 제목에 반영된다. AC-32 옛 행(출처 NULL)은 기본
문구일 때만 자동 제목을 받는다. AC-33 화면: 머리 편집·목록 이름 바꾸기가 목록에 반영된다.

**(d)** AC-34 실제 codex 로 RCA·maintenance 의도 작성 표본 둘을 돌리고 관찰(항목·의무·결론 요구)을 적는다. AC-35 (b) 뒤 실제 codex 의
검증 실행이 시험을 돌려 `met` 을 적는지 관찰한다(못 적으면 그 사실). 선택: (g) 자동 제목·(c)·(e) 관찰.

공통: AC-36 기존 시험 전부 통과(기준선 대비 실패 증가 없음), 스키마 v28 이행이 옛 DB(v19·v27 스냅샷)에서 돌고 옛 행을 지어 채우지 않는다.
AC-37 강제 축 넷·진입 검사·게시 규칙(P5) 무변경 — 어느 부분도 권한·동의·인수를 만들지 않는다.

## 5. 검증

- 순수: `tests/test_workspace.py`(prepare 의 `previous_*`), `tests/test_knowledge.py`(`parse_report_item` lenient·`adoption_check`·`select`),
  `tests/test_conversation.py`(해석 `title`), 새 `tests/test_cli_adapter_permissions.py`.
- 서버·진행기: 새 `tests/test_question_answers_to_tasks.py`(a), `tests/test_start_basis.py` 새 절(c), 새 `tests/test_case_cancel.py`(e),
  `tests/test_knowledge_extraction.py`·`test_knowledge_server.py` 새 절(f), 새 `tests/test_case_title.py`(g).
- 이행: `tests/test_migration.py` v28(closure_record 재구성·새 컬럼·옛 행 NULL·v19 스냅샷).
- 브라우저: `tests/test_web_shell.py` 새 시험 셋(취소, 거부 행 열람·수동 등록 채우기, 제목 편집) + 이전 결과 카드는 서버 시험으로(브라우저는
  카드 버튼 라벨만 — 가짜 codex 로 후속 흐름을 끝까지 만드는 비용이 크면 서버 시험으로 대신하고 그 사실을 적는다).
- 전체: `scripts\run-tests.ps1`(웹 빌드·웹 단위·pytest·P1 계약). 라이브: 3.7절.

**최종**(모든 변경 뒤, 같은 스크립트, 2026-09-24 20:15~20:31): 웹 빌드 성공, 웹 단위 **37**, pytest **785 통과·0 실패·2 건너뜀**(15분 25초, 실행 수 +32 — `test_question_answers_to_tasks.py` 3 · `test_cli_adapter_permissions.py` 4 · `test_start_basis.py` +6 · `test_case_cancel.py` 5 · `test_knowledge_scope.py` 6 · `test_case_title.py` 5 · `test_web_shell.py` +3), P1 계약 **18**, 종료 코드 0. 라이브 둘의 결과는 [P4-09 결과](../p4/evidence/P4-09-results.md) 3절. **상태: 완료(DONE_WITH_LIMITATIONS — 라이브는 관찰, 남은 것은 결과 4절).**

기준선(S-035 시작, 변경 전, `scripts
un-tests.ps1`, 2026-09-24 19:23~19:38): 웹 빌드 성공, 웹 단위 **37**, pytest **753 통과·0 실패·2 건너뜀**(14분 50초 — S-034 최종의 752·1·2 와 같은 실행 수 755; 그때의 실패 1(시계 해상도 흔들림 시험)은 이번 회차에서 통과), P1 계약 unittest **18** 통과, 스크립트 종료 코드 0("전체 시험 통과"). 로그는 세션 스크래치 폴더의 `baseline.out`.

## 6. 경계

- 어느 부분도 새 권한·동의·인수를 만들지 않는다. (a) 는 입력 전달, (b) 는 CLI 인자, (c) 는 시작 코드의 선택, (e) 는 사람의 종료 결정,
  (f) 는 후보 받기·열람, (g) 는 표시값이다. 게시(push·PR)는 P5 다 — (b) 의 샌드박스 해제가 AI 의 직접 push 를 막지 못한다는 사실은 D-91
  의 받아들인 손실로 적되 제품의 게시 허용이 아니다.
- 원문 경계: 질문 답 원문은 참조로만(Runner 가 읽는다), 후보 본문은 P4-06b 예외 그대로(새 저장 없음), 제목은 짧은 값(본문 아님).
- 기존 기록 소급 없음: 옛 `closure_record`·`case_workspace`·`case`·`knowledge_version` 행의 새 컬럼은 NULL(기록 없음).

## 9. 알려진 한계·설계 선택

- 되묻는 답은 그대로 전달된다 — 그 Task 가 결정을 얻지 못할 수 있다(이슈 #2 관련 관찰, 별도). 설계 단계 답이 계획 작성 입력에 가는지는
  이 plan 밖(관찰만).
- 실행 중 Case 의 취소(2단계)는 없다 — 먼저 요청 중단(대화 화면)·실행 중단(관리 화면) 뒤 취소한다.
- 후속 Case 카드는 **직전 이전 Case 하나**(가장 최근 `follow_up_change`)의 같은 저장소 브랜치만 본다. 이전 Case 가 저장소를 둘 썼으면 저장소
  마다 따로 묻는다(작업공간이 저장소별이므로 자연히 그렇다).
- 자동 제목은 해석 블록을 받는 응답(준비 단계·종료 Case 의 논의 응답)에서만 온다 — 업무 단계 논의 응답은 제목을 내지 않는다.
- 범위를 읽지 못한 후보의 주입 제외는 상세 설계 선택이다(넣는 쪽이 낫다고 판단되면 `select` 한 줄이다).
- Claude 쓰기 실행의 `--strict-mcp-config` 유지는 상세 설계 선택(이슈 #3 권고)이다.
