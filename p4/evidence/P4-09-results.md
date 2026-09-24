# P4-09 실행 결과 — P5 전 정리 묶음 (S-035, 2026-09-24)

plan: [P4-PLAN-09](../../plans/P4-PLAN-09.md). 사용자 결정(2026-09-24): 이슈 #2~#6·후속 Case 시작 기준(D-77)·실제 codex 라이브를 **한
세션·한 plan** 에. 기준: 설계 v0.8 2차 / D-01~93(D-91·D-92·D-93 은 이 세션이 `decisions.md` 에 적었다). 결과 상태: **DONE_WITH_LIMITATIONS** —
(a)~(g) 전부 구현·검증, (d) 라이브는 3절(관찰). 스키마 **v27 → v28**.

## 1. 한 일 — 부분별

| 부분 | 무엇을 | 근거 |
|---|---|---|
| (a) 이슈 #2 이월 질문 답 전달 | `_compose_base_refs` 의 `WORKS_FROM_THE_PLAN` 분기(+ 계획의 조사 Task 의 `limited_analysis`)가 **그 Task 를 막던 답한 이월 질문의 답 원문**을 `question_answer`(핵심·인라인) 참조로 더한다(`answered_deferred_questions_for_task` — 현재 그래프의 `task_question_block` 연결 + 연결 없이 전부를 막던 질문; Task 키 없는 실행은 전부). `plan_context_package`·`compose_context` 가 `task_key` 를 받고 `create_run`·`check_admission`·최신성 계산이 Task 키를 넘긴다. 조회의 참조에 `question{key, summary, decide_at, raised_in_stage}` 가 붙고 Runner 가 지시문 머리에 "— … 질문 {key}: {summary} 에 대한 답 (계획서의 '사람이 정한다' 는 이 답으로 정해졌다)" 를 적는다(`question_head`). 재시도는 같은 Task 키라 같은 입력이다 | `tests/test_question_answers_to_tasks.py` 3건 — AC-1·2(진행기 경유: 계획 질문이 T1 을 막음 → 카드 답 → 두 구현 실행 모두 `question_answer` 핵심·`read` 영수증·지시문에 답 원문과 머리), AC-3·5(연결된 답은 그 Task 만·연결 없는 답은 모든 Task·키 없는 실행은 전부, 실제 실행의 참조 집합), AC-4(열린 질문은 여전히 막고 의도 단계 질문은 안 간다). [문맥 계약](../../review-context-contract.md) 2절 구현 기록 |
| (b) 이슈 #3 샌드박스 해제(D-91) | `PERMISSION_MAP` — codex `workspace_write` → `--sandbox danger-full-access`, claude → `--permission-mode bypassPermissions --permission-prompts none --strict-mcp-config`(유지는 상세 설계 선택), `read_only` 그대로. 능력 보고 `write_sandbox = unsupported` + `permission:workspace_write` 근거를 D-91 로(`WRITE_SANDBOX_NOTE`). 게시 규칙(P5)은 그대로다 | `tests/test_cli_adapter_permissions.py` 4건(AC-6·7 — 두 도구·두 권한의 정확한 인자, 확대 권한 거부 그대로, 능력 행). `decisions.md` D-91, [환경 계약](../../p1-environment-contract.md) 6절 `permission` 행·8절 새 행 |
| (c) 후속 Case 시작 기준(D-77 마지막 문장) | `StartBasis.PREVIOUS_RESULT`. 제어부가 후속 Case 의 작업공간 요청에 이전 Case(가장 최근 `follow_up_change`)의 같은 저장소 브랜치를 싣고(`previous_result_for_workspace`), **작업 PC 가 git 으로** 그 끝 커밋이 HEAD 에 없을 때만(`previous_result_tip` — 브랜치 있음 · `merge-base --is-ancestor` 아님) 트리가 깨끗해도 **만들지 않고 묻는다**(`NeedsBasis.previous_*`, `awaiting_basis` 그대로). 행에 `previous_case_id`·`previous_branch`·`previous_commit`(v28)이 남고(자기 이전 Case 가 아니면 409 `previous_result_unknown`), `decide_start_basis(previous_result)` 는 기록된 커밋이 있을 때만(아니면 409 `previous_result_unavailable`) `base_ref` 를 그 커밋으로 둔다; Runner 는 그 커밋에서 `worktree add`, `base_commit` = 그 커밋·`committed_base` = 그때의 HEAD, 미커밋 포함 없음. 카드(`StartBasisCard`)가 이전 대화 제목·브랜치·커밋과 `이전 업무 결과에서 시작` 버튼을 보이고 미커밋 수가 0 이면 목록·포함 버튼을 숨긴다(셋 다 해당하면 세 버튼). 작업공간 절의 시작 코드 줄 | `tests/test_start_basis.py` +6(AC-9~14 — 깨끗한 트리에서 묻고 이전 결과 선택 시 그 커밋에서 열림·원래 트리 무변경·경로 DB 에 없음, HEAD 가 포함하거나 브랜치가 없으면 안 묻고 `committed`, 더러운 트리 + 이전 결과의 세 선택지와 미커밋 미포함, `committed` 는 HEAD 에서·기록 없는 선택은 409, 자기 이전 Case 가 아닌 보고 409, v27 행 NULL 그대로) |
| (e) 이슈 #4 업무 취소(1단계) | `Repository.cancel_case`(사유 필수·행위자; `status ≠ finished` 실행이 있으면 409 `runs_unfinished`, 종료 Case 409 `case_already_closed`) — 한 트랜잭션에 `decision(case_cancellation)`·`closure_record(cancelled, candidate NULL, cancelled_by·cancel_reason·decision_id·snapshot_json)`·`status = cancelled`·`held` 예약 `unresolved`(`settle_source = case_cancelled`)·진행 `done/cancelled` + 이벤트, 뒤이어 처리 중 요청을 `failed`(`case_cancelled`)로. `POST /api/cases/{id}/cancel` → 대화 조회(`cancellation{by, reason, at, decision_id}`). 취소 뒤 훅 무반응: 진행기 `advance`·`on_run_finished` 와 지식 후보 등록(`_apply_report`)이 취소 Case 에서 아무 것도 만들지 않는다; `progress/resume` 은 종료·취소 Case 를 거부(`guard_open_case`). 화면: 머리 `업무 취소`(사유 입력·확정) → "취소됨 — 사유 (행위자)"·목록 배지 "취소됨". v28 `closure_record` 재구성(`candidate_id` 는 취소일 때만 NULL, CHECK 둘) | `tests/test_case_cancel.py` 5건(AC-15~19 — 대기 중 취소의 기록·요청·진행·예약·보존, 실행 중·사유 없음·종료 뒤 거부, 취소 뒤 새 실행·정책 변경·재개 거부와 설명 응답·후속 대화 허용, 훅 무반응, v27 행 보존·새 CHECK) + 브라우저 1건(AC-20) |
| (f) 이슈 #5 지식 후보의 거부·열람(D-92) | ① `KNOWLEDGE_EXTRACTION_RULE`·`KNOWLEDGE_REGISTRATION_RULE` 에 활동 여덟(뜻)·경로 규칙·"모르면 비워 둔다". ② `parse_report_item(lenient_scope=)` — AI 후보(추출·`proposal: true`)는 틀린 활동·경로를 `reported_scope{activities, paths, problem}` 로 남기고 비워 후보 등록(`knowledge_version.reported_scope_json`, v28); 사용자 말은 `invalid_scope`/`paths_without_repository` 거부 그대로. `select` 가 `Decision.SCOPE_UNREADABLE` 로 주입에서 뺀다(`run_knowledge.decision` CHECK 확장, 옛 DB 재구성). `adoption_check` 의 막는 항목 `scope_unreadable` — `requested.activities` 가 `None` 이 아니면(빈 목록 포함) 없음; `GET adoption-check?activities=` 지원; 활성화의 새 버전에 `reported_scope` 없음. ③ `GET /api/cases/{id}/knowledge-intake/{run_id}/{index}` — 보고 항목의 원래 값·본문(서버에 있으면)·사유 코드와 읽을 말(`REFUSAL_TEXT`); 조회의 등록 행에 `reported_scope`·`refusal_text`. 화면: 후보 카드·거부 카드·결정 사항 패널의 거부 행에 `내용 보기`(본문·AI 가 적은 범위·사유)와 `이 내용으로 수동 등록`(sessionStorage 의 채우기 한 벌 → 규칙 화면 수동 등록 폼이 읽고 지운다), 규칙 화면 후보 항목의 "범위 확인 필요 · AI 가 적은 값" 배지와 활성화 폼 안내, 사유 읽을 말은 `lib/knowledgeText.ts` 하나 | `tests/test_knowledge_scope.py` 6건(AC-21~25 — 지시문의 활동 여덟·경로 규칙, 순수 규칙(관대/엄격·막음 해소·주입 제외), 틀린 활동의 추출 후보 → 후보·원래 값·Manifest `scope_unreadable`·채택 확인 막음 → 활동 명시로 활성(v2, `reported_scope` 없음), 논의 응답의 제안은 후보·사용자 말은 거부, 거부 행 열람의 본문·범위·사유·404) + 브라우저 1건(AC-26). `project-knowledge.md` 구현 기록 |
| (g) 이슈 #6 대화 제목(D-93) | 해석 블록의 `title`(`normalize_title` — 공백 정리, 40자 초과는 자름, 형식 오류 아님) → `Interpretation.title` → `conversation_interpretation.title`(v28). 처리기가 응답마다 `apply_auto_title`: 출처 기본값(`default`, 또는 옛 행 NULL + "새 대화"/"… · 후속")이면 `ai:discussion`, 업무 요청 응답이면 한 번 더 `ai:work_start`, `user` 는 덮지 않음. `set_case_title`(1~200자, 종료·보관 허용, 직전 값·주체·시각) — `PUT /api/cases/{id}/title`. `case.title_source/title_set_by/title_set_at/title_previous`(v28; 새 대화 `default`, 사람 입력 Case `user`, 옛 행 NULL). 조회에 네 값. 지시문(`DISCUSSION_INTERPRETATION_RULE`)에 제목 규칙(40자·비밀값 금지·사람 제목 우선). 화면: 머리 제목 클릭 → 인라인 편집(`TitleEditor`), 목록 행의 ✎ → 인라인 입력(`Sidebar`), `＋ 새 대화` 그대로. 가짜 codex 표지 `HADS_FAKE_TITLE=` | `tests/test_case_title.py` 5건(AC-27~32 — 순수 규칙, 첫 응답·업무 요청 응답의 갱신과 그 뒤 불변, 사람 제목 불변·PUT 검사·이력, 종료·보관 뒤 변경과 검색 결과·규칙 화면 출처·후속 대화 제목, 옛 행 규칙) + 브라우저 1건(AC-33). `tests/test_request_processor.py` 의 컬럼 집합에 `title` 추가(본문이 아니다) |

경계(AC-37): 어느 부분도 권한·동의·인수를 만들지 않았다 — 강제 축 넷·진입 검사·게시 규칙(P5) 무변경. (b) 의 샌드박스 해제는 CLI 인자이며 제품의
게시 허용이 아니다(D-91 의 받아들인 손실로 적었다). 원문 경계: 질문 답은 참조로(Runner 가 읽는다), 후보 본문은 P4-06b 예외 그대로(새 저장 없음),
제목은 짧은 값. 옛 행의 새 컬럼은 전부 NULL/빈 값(기록 없음) — `tests/test_migration.py` 전부와 각 부분의 이행 시험이 확인.

## 2. 검증

- 기준선(변경 전, 2026-09-24 19:23): 웹 빌드 성공 · 웹 단위 37 · pytest **753 통과·0 실패·2 건너뜀**(14분 50초) · P1 계약 18 · 종료 코드 0.
- **최종**(모든 변경 뒤, `scripts\run-tests.ps1`, 20:15~20:31): 웹 빌드 성공 · 웹 단위 37 · pytest **785 통과·0 실패·2 건너뜀**(15분 25초, 실행 수
  **+32** = (a) 3 · (b) 4 · (c) 6 · (e) 5 · (f) 6 · (g) 5 · 브라우저 3) · P1 계약 18 · "전체 시험 통과" 종료 코드 0. 건너뜀 2건은 이행 시험의 옛 스키마
  커밋 창(9절 그대로). 기준선의 시계 해상도 흔들림 시험은 두 회차 모두 통과.
- 브라우저(가짜 codex·실제 Edge, `tests/test_web_shell.py` +3): 제목(첫 응답의 자동 제목 → 머리 편집 → 다음 응답이 덮지 않음 → 목록 ✎), 취소(동의 카드에서
  사유·확정 → 취소됨·버튼 사라짐·후보 없는 종료 기록), 거부 후보(사용자 말의 틀린 활동 → 거부 카드의 읽을 말 → 내용 보기(본문·활동) → 수동 등록 폼 채우기
  → 활동을 고쳐 등록). 기존 브라우저 시험 전부 통과(가짜 codex 의 "사용자의 마지막 메시지" 추출을 고쳤다 — 첫 메시지에는 고정 컨텍스트가 없어 지시문 전체를
  규칙 본문으로 옮기던 시험 도구의 결함, 9절).
- 스키마 v28: 새 DB 는 재구성 없음(`test_a_new_database_needs_no_rebuild` 그대로), v27 DB 는 `closure_record`·`run_knowledge` 재구성(행 보존)과 컬럼 추가.

## 3. 실제 codex 라이브 (d) — 관찰

실제 `codex-cli 0.156.1`, 제품 경유, 이 PC(Windows 11, Python 프로젝트). 판정은 "AI 가 지시를 따랐는가" 의 관찰이며 제품 규칙 위반만 실패다.

### 3.1 RCA·maintenance 의도 작성 표본 (`p4/live/profile_intents.py --prefix P4-09-live-intents --only D,E`, 태그 203057259)

| 표본 | 결과 | 관찰 |
|---|---|---|
| D `root_cause_analysis` "저장 직후 목록이 옛 값을 보이는 원인" | 실행 `completed`, 문서 v6, `objectives: ["cause"]`, 기준 C-01(`conclusion_requirement`, 의무 `cause` **reported**, 결론 요구 `definitive_required` = 기대), 목적별 완료 의미에 빠진 목적 없음, 질문 0 | Profile 항목(설명할 현상·관찰 근거·원인 질문·결론 요구·분석 종료조건)을 전부 `user_requirement` 출처로 채웠다. 기준이 하나뿐이다(현상·관찰을 따로 기준으로 두지 않았다) — 규칙 위반은 아니다 |
| E `maintenance` "저장 경로를 설정으로 옮기기" | 실행 `completed`, 문서 v6, **최상위 `objectives` 는 빈 목록**, 기준 셋(C-01 `target_state`/`target_state`, C-02·C-03 `preserved_conditions`/`preservation`, 전부 **reported**), 목적별 완료 의미: `target_state`·`preservation` 둘 다 Profile 필수로 도출돼 기준이 있음(빠진 목적 없음), 질문 1(빈 `STORE_PATH` 처리) | 유지 대상·현재 상태·목표 상태·작업 이유·보존 조건을 채웠고 현재 상태·이유는 `observation` 출처로 적었다. 최상위 `objectives` 를 비운 것은 지시(혼합 목적 선언)와 다르지만 P4-03 계약은 기준의 의무로 목적을 도출해 완료 의미가 성립한다 — 지시문이 Profile 기본 목적도 적으라고 요구할지 → **사용자 결정(2026-09-24): 지금대로 둔다** |

라이브 스크립트의 `doc_version_5` 확인은 UI-04c 이후 문서 판이 6 이라 낡은 것이었다 — `doc_version_known`(5·6)으로 고쳤다(시험 도구 수정, 제품 무관).
증거: `P4-09-live-intents.log`·`P4-09-live-intents-results.json`·`P4-09-live-intents-{D,E}-intent-original.json`.

### 3.2 샌드박스 해제 뒤 진행 라이브 (`ui/live/p405_progress.py`, `HADS_LIVE_PREFIX=P4-09-live-progress`, 태그 203311030, 실제 Edge)

**passed · 제품 규칙 18/18 · 관찰 16.** 새 대화 → 기능 요청 → AI 해석 업무화 → 의도 초안(질문 둘 → 카드 답 → 재작성 → QG-01 독립 검토 pass → repair) → 동의 → 설계·계획 → **계획의 이월 질문(`plan:p1` "개발계획 승인") 답** → T1·T2 구현 → T3·T4 검증 → 자동 완료(사람 인수 없음) → 종료 뒤 설명 응답(종료 뒤 소비 분리) → 수정 요청이 연결된 새 대화로. 실행 15(입력 토큰 895k·실행시간 790초).

- **처음으로 기준 다섯이 전부 `met`** — C-01·C-02·C-04 `changed_and_verified`, C-03·C-05 `preserved`, 전부 `policy:work_progressor` 가 검증 실행의 명령(종료 코드 0 다섯 + 하나)을 근거로 적었다. 그 전 라이브(P4-05·P4-ENV 이전)는 검증 실행이 샌드박스 때문에 시험을 돌리지 못해 `unverified` → 예외 수용이었다. **(b) 의 효과가 제품 경유로 확인됐다**(이 PC 의 Python 프로젝트; Gradle·JDK 는 보지 않았다).
- **(a) 가 실제로 걸렸다** — 라이브 DB 의 `run_context_ref` 에서 T1·T2 구현 실행이 `question_answer`(핵심) 참조를 가진다(`plan:p1` 의 답). 답이 "승인" 이라 결정의 내용은 얇았다(되묻는 답의 한계 그대로).
- **(g) 가 실제 codex 로 확인됐다** — 첫 대화의 제목 "로그 출력에 INFO·ERROR 수준 추가"(출처 `ai`, `ai:work_start` 로 갱신됨), 후속 대화 "log()에 호출 함수 출처 기록"(옮겨진 첫 메시지의 응답이 냈다; 처음 기본 제목은 "… · 후속"). 실제 codex 가 지시대로 40자 이하 제목을 냈다.
- (c) 의 이전 결과 카드와 (e) 의 취소는 이 라이브의 경로에 없다 — 가짜 codex·실제 Edge 의 브라우저 시험과 서버 시험이 확인한다. 후속 대화는 여기서 작업공간까지 가지 않았다.

증거: `P4-09-live-progress.log`·`P4-09-live-progress-results.json`·`P4-09-live-progress-*.png`. 라이브 데이터 `%LOCALAPPDATA%/Temp/hads-p4-05-live/203311030`.

## 4. 남은 것·알려진 한계

- **실행 중 Case 의 취소(2단계)는 없다** — 먼저 요청 중단(대화 화면)·실행 중단(관리 화면) 뒤 취소한다. "취소 요청됨 · 종료 확인 대기" 표시는 없다.
- **되묻는 답은 그대로 전달된다** — 그 Task 가 결정을 얻지 못할 수 있다(이슈 #2 관련 관찰). 설계 단계 답이 계획 작성 입력에 가는지는 관찰만 남았다(별도).
- 후속 Case 카드는 **직전 이전 Case 하나**의 같은 저장소 브랜치만 본다. 이전 브랜치 끝 커밋과 HEAD 가 갈라졌으면(둘 다 앞섬) 이전 결과에서 시작하면 HEAD 의
  새 커밋은 없다 — 카드가 "그때의 커밋된 코드" 를 함께 적는다. "다른 커밋에서 시작" 입력은 UI-05b.
- 범위를 읽지 못한 후보의 주입 제외는 상세 설계 선택이다. 자동 제목은 해석 블록을 받는 응답(준비 단계·종료 Case 의 논의 응답)에서만 온다.
- Claude 쓰기 실행의 `--strict-mcp-config` 유지는 상세 설계 선택(이슈 #3 권고). Claude 의 실제 `bypassPermissions` 실행은 해 보지 않았다.
- 읽기 전용 실행의 도구 문제(이슈 #3 "남는 제약")는 남는다 — P4-ENV 의 ACL 조치는 그대로 둔다.
