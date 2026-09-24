# UI-04d 실행 결과 — 대화 검색(D-84) + 미커밋 포함 시작(D-77)

기준: [UI-PLAN-04d](../../plans/UI-PLAN-04d.md) / **D-84**(보관 포함 프로젝트 대화 검색) · **D-77**(작업 기준과 미커밋 변경) /
[대화 중심 UI](../../ui-conversation-design.md) 3.1·10절 / [데이터 경계](../../data-boundary-review.md) 1·3절 / [작업공간 검토](../../execution-workspace-review.md)
2절 / 스키마 **v27**. 세션 S-032. 범위는 사용자 결정(2026-09-24, S-030: 남은 네 항목을 두 단계로 — 이것이 2단계, UI-04 의 마지막
하위 plan). 선행 [UI-04c 결과](UI-04c-results.md) · [UI-04a 결과](UI-04a-results.md) · [UI-03 결과](UI-03-results.md) · [P3-R2 결과](../../p3/evidence/P3-R2-results.md).

**제품 판단은 새로 내리지 않았다.** 상세 설계 선택(검색어·발췌·목록은 제어부 메모리에만, 본문 검색에 색인 없음(후보 상한), 낱말
AND 일치, 선택 대기는 사람 대기 카드·이진 선택, 포함 = 스냅샷 커밋(`base_commit` = 스냅샷·`committed_base` = HEAD), 동시 편집
보호 = 지문 대조, 포함은 HEAD 기준에서만, 옛 행의 `start_basis` NULL = 기록 없음)은 plan 0·9절. 파일별 포함 선택·후속 Case 의
"이전 결과 기준" 제안·화면의 ref 변경 입력은 넣지 않았다(아래 5절 — 사용자가 원하면 별도 작업).

## 1. 구현 결과

### D-84 — 대화 검색

- **순수 규칙**(`domain/search.py`, 제어부·Runner 공용): `tokens`(공백 분리·소문자·중복 제거·8개 상한), `matches`(모든 낱말 포함, 대소문자
  무시 — 빈 검색은 전부 일치가 아니다), `snippet`(첫 일치 주변 160자·일치 수), 상한(`MAX_QUERY` 200·`MAX_CANDIDATES` 2,000·`MAX_ENTRIES` 500).
- **제어부 메모리**(`controller/transient.py` `TransientStore` — 값·TTL·프로세스 메모리; `controller/search.py` `SearchRegistry`): 검색 요청
  (검색어·후보·소유 PC 별 부분·결과)은 **DB 에 표가 없고** 메모리에만 있다(TTL 10분, PC 전달 뒤 60초 무응답은 `expired`, 재시작하면 404).
  `create` 가 `Repository.search_candidates`(제목·메시지 요약·업무화 요약·결정 종류 사람 말·Profile 개정 사유·이 대화에서 정한 규칙 요약
  + 본문 후보 = 메시지 원문 참조·소유 PC·가용성, 최신순 상한)로 서버 일치를 즉시 계산하고, 후보를 소유 PC 별로 묶어 연결된 PC 는 `pending`,
  미연결 PC 는 `excluded`(메시지 수)로 둔다. `view` 의 `scope`(`bodies` = none|pending|partial|relayed|expired|excluded, 후보·제외·만료·
  읽지 못한 수, `truncated`, PC 별 상태, `note` 문구)와 `matches`(서버 + 본문), `body`. `pending_for`(PC 에 한 번만 전달 — `claimed`),
  `record_results`(후보 밖 일치·다른 PC·끝난 부분 거부). 검색어·발췌는 로그에도 남지 않는다.
- **API**(`controller/api.py`): `POST /api/projects/{id}/conversation-searches {query, requested_by}` → 201 뷰, `GET /api/conversation-searches/{id}`
  (없으면 404), Runner `GET /api/runner/{id}/search-requests`·`POST /api/runner/search-requests/{id}/results`. `app.state.searches`·
  `app.state.uncommitted`(`controller/app.py`).
- **Runner**(`runner/agent.py` `serve_search_requests`, `runner/client.py`): 제어 루프에서 후보 원문만 `store.get` 으로 읽어(경로를 받지 않는다,
  후보 밖은 읽지 않는다) 같은 규칙으로 대조하고 일치(참조·발췌·수)·`scanned`·`unreadable`(이 PC 에 없는 원문 — 일치가 아니다)을 올린다.
- **화면**(`web/src/lib/search.ts` 순수 — 낱말·강조 조각·범위 문구·대화별 묶기·제목 일치; `shell/SearchScreen.tsx`; `Sidebar.tsx` 검색 폼
  `search-input`·`search-submit`; `Shell.tsx` — `screen=search`, 본문 `pending|partial` 이면 500ms 조회 최대 30초 → `expired` 표시; `lib/address.ts`
  `search` 화면·`searchLink`(검색어는 주소에 없다); `api.ts` `searchApi`·`SearchView`·`SEARCH_KIND_LABEL`). 검색 화면: 범위 줄 `search-scope`
  (`data-bodies`), 대화별 묶음 `search-case-{id}`(보관·종료 배지, 제목 일치 강조), 일치 행 `search-hit-{case}-{n}`(`data-kind`·`data-seq`·
  `data-source`, `<mark class="sh-hit">` 강조, 일치 수) → 메시지는 그 대화 + `focusSeq`, 결정·개정·업무화는 그 대화 + 결정 사항 패널, 규칙은
  규칙 화면의 항목. 빈 결과·만료·오류 문구.

### D-77 — 미커밋 포함 시작

- **모델·스키마 v27**(`domain/models.py` `WorkspaceState.AWAITING_BASIS`·`StartBasis`; `controller/schema.sql`·`db.py`): `case_workspace` 컬럼 여덟
  (`start_basis`·`basis_decided_by/at`·`committed_base`·`included_entries`·`included_tree_digest`·`basis_tree_digest`·`basis_entries`) —
  새 표·재구성·데이터 이행 없음. 옛 행은 NULL/기본값(= 기록 없음, `committed` 가 아니다).
- **Runner**(`runner/workspace.py`): `NeedsBasis`(만들지 않았다 — HEAD·항목·지문·`stale`), `snapshot_commit`(임시 인덱스 `GIT_INDEX_FILE` 로
  `read-tree HEAD` → `add -A`(`.gitignore` 존중) → `write-tree` → `commit-tree -p HEAD`, 작성자 `hads` — 원래 트리·인덱스·브랜치·HEAD 무변경,
  ref 를 옮기지 않음), `prepare(start_basis=, expected_tree_digest=)`: 더럽고 기준 미정 → `NeedsBasis`; `include_uncommitted` 는 기준 ref 가
  HEAD 커밋일 때만(아니면 `WorkspaceError`), 지문이 다르면 `NeedsBasis(stale=True)`, 같으면 스냅샷 커밋에서 worktree 를 편다;
  `PreparedWorkspace.start_basis/committed_base/included_entries/included_tree_digest`. `runner/agent.py` `prepare_workspaces` 가 요청의
  `start_basis`·`basis_tree_digest` 를 넘기고 `NeedsBasis` 면 목록(상태·경로, 500건 상한)을 `report_workspace_uncommitted` 로 올린다.
- **제어부**(`controller/repository.py`·`api.py`·`work_progressor.py`·`domain/work_flow.py`): `report_workspace_uncommitted`(행 → `awaiting_basis`,
  `committed_base`·`basis_tree_digest`·`basis_entries`·`user_tree_*`; `stale` 면 선택 기록을 지운다), `decide_start_basis`(`awaiting_basis` 가
  아니면 409 `workspace_not_awaiting_basis`, `seen_digest` ≠ 행의 지문이면 409 `basis_list_stale`, 기록 뒤 `requested`), `report_workspace_ready`
  의 새 값(포함이면 `committed_base`·지문 필수), `workspace_state` 의 기준·수·HEAD, `_task_phase` 의 `WaitReason.WORKSPACE_START_BASIS`
  (저장소·수·HEAD·작업 키), 진행기 `on_start_basis_decided`(대기 → `running`/`workspace_pending`, 이벤트 `decided`, 한 걸음). API `POST
  /api/runner/workspaces/{case_id}/uncommitted`(목록은 `app.state.uncommitted` 메모리, TTL 30분; 준비 보고가 지운다), `GET /api/cases/{id}/
  workspaces/{repo}/uncommitted`(`available`·`entries`·`digest`·`stale_choice`; 없으면 `available: false`), `POST .../start-basis {basis, actor,
  seen_digest}`. 진입 검사 `_check_workspace` 는 그대로(`awaiting_basis` = 준비되지 않음 → `workspace_not_ready`, 상태 이름이 사유에).
- **화면**(`shell/ProgressCards.tsx` `StartBasisCard` — `wait-card-workspace_start_basis`(`data-available`), 수 `basis-count`, 기준 커밋, 목록
  `basis-entries`/`basis-entry-{n}`, 만료 시 `basis-unavailable`·`basis-reload`(작업공간 재요청 → PC 가 다시 관측), 낡은 선택 `basis-stale`,
  버튼 `basis-committed`·`basis-include`(둘 다 원래 폴더를 바꾸지 않는다는 문구); `shell/ReviewPanel.tsx` `WorkspaceRow` 의 시작 코드 줄
  `ws-basis-{repo}`(`data-basis` — 커밋된 코드 / 포함 N건·스냅샷·커밋 기준 / 기록 없음 / 선택 대기)·상태 이름표; `api.ts` `StartBasis`·
  `START_BASIS_LABEL`·`UncommittedList`·`workspaceApi.uncommitted/decideBasis`·`WAIT_LABEL.workspace_start_basis`·`WORKSPACE_STATE_LABEL.awaiting_basis`).
- **시험 도구**: `tests/conftest.py` `FakeCliExecutor` 가 **쓰기 권한의 실행에서만** 파일을 쓴다(읽기 전용 실행이 사용자 원래 저장소에 쓰던
  것은 시험 도구의 특성이었고 D-77 아래서는 모든 진행기 시험을 선택 대기로 보냈다); `Harness.prepare_workspace(basis="committed")` 가 더러운
  저장소 시험에서 사람의 선택을 대신 보낸다(`basis=None` 이면 묻는 상태 그대로), `Harness.decide_start_basis`.

## 2. 성공 기준 대조

| AC | 근거 | 결과 |
|---|---|---|
| AC-1 서버 필드 검색 | `tests/test_conversation_search.py::test_server_fields_are_searched_at_once_and_a_disconnected_pc_is_excluded_by_count` — 제목(`quokka`)·규칙 요약(`lint 규칙` → `K-001`, 규칙 화면 대상)·결정(`의도 동의` → 업무 Case, 결정 사항 대상)·보관된 대화(`archived: true`) 일치, 다른 프로젝트의 같은 제목·결정은 없음, 본문 낱말(`wombat`)은 서버에서 0건(요약은 본문이 아니다), 낱말 전부 요구, 빈 검색 422; 순수 `::test_words_match_all_case_insensitively_and_the_snippet_sits_on_the_first_hit` | 통과 |
| AC-2 범위 표시 | 같은 시험 — 미연결(`age_heartbeat`)이면 `body.state = excluded`·`excluded_message_count = 4`·`runners[].state = excluded`·"PC 미연결로 본문 4건 검색 제외"; `::test_a_project_without_bodies_says_none_and_the_candidate_cap_is_reported` — 후보 0 → `none`, 상한(2) 초과 → `truncated`·후보 2·문구 | 통과 |
| AC-3 본문 검색(PC) | `::test_the_owning_pc_searches_the_bodies_and_the_excerpt_stays_out_of_the_db` — `pending` → `control_tick` 이 후보 4건을 읽어 2건 일치(첫 대화 #1·보관된 대화 #1, 발췌에 낱말·수) → `relayed`; AI 응답 본문(`numbat` → #2 assistant); 두 번째 루프는 다시 하지 않음; 후보 밖 일치 0건 수용, 다른 PC 409, 끝난 부분 409, 모르는 검색 404; `::test_missing_originals_are_counted_and_late_or_expired_searches_say_so` — 지운 원문은 `unreadable = 1` 이고 일치 아님 | 통과 |
| AC-4 경계 | 같은 시험들 — 검색 뒤 DB 의 모든 표·모든 글 칸에 검색어(`WOMBAT`·`quokka 없는낱말`)·발췌(`첫 대화의 본문에는 wombat`)가 없고 검색 표가 없다; PC 무응답 → `expired`(`expired_message_count`·문구·결과 보고 409), TTL 뒤 조회 404. `tests/test_start_basis.py` — 미커밋 목록의 경로(`scratch.txt`·`reader.py`)가 DB 에 없다 | 통과 |
| AC-5 화면(D-84) | `tests/test_web_shell.py::test_search_finds_titles_rules_and_pc_bodies_and_leads_to_the_message` — 왼쪽 검색 → 검색 화면(`screen=search`, 검색어는 주소에 없음, 오른쪽 패널 닫힘) → 범위 줄 `relayed`·"본문(PC)" → 첫 대화 묶음·보관된 대화 묶음("보관됨") → 본문 일치(`data-seq = 1`, `<mark>quokka</mark>`) 클릭 → `message-1` 강조·주소 `case=`; 규칙 검색 → 규칙 일치 클릭 → 규칙 화면(`screen=rules`)·`rule-K-001`; DB 에 검색어 없음 | 통과(실제 Edge·가짜 codex) |
| AC-6 깨끗한 트리 | `tests/test_start_basis.py::test_a_clean_tree_starts_at_head_without_asking` — 묻지 않고 `ready`·`committed`·`committed_base = base_commit = HEAD`·포함 0·목록 `available: false`; 순수 `::test_prepare_asks_when_the_tree_is_dirty_and_builds_only_with_a_basis`(깨끗하면 기준 없이 `committed`); 기존 `test_workspace.py`·`test_repositories.py` 전부 통과 | 통과 |
| AC-7 선택 대기 | `::test_a_dirty_tree_waits_for_the_basis_and_the_list_stays_out_of_the_db` — `awaiting_basis`·수 2·지문 64자·`committed_base = HEAD`·`base_commit`/경로 빈 값, 원래 폴더·브랜치 그대로, 목록 조회(`?? scratch.txt`·`M reader.py`, `available`), DB 에 경로 없음, 구현 실행 409 `workspace_not_ready`(사유에 `awaiting_basis`), 두 번째 준비 요청도 묻기만; 진행기 `::test_the_progressor_waits_at_the_basis_card_and_continues_after_the_choice` — 동의 뒤 `workspace_start_basis` 대기(수 2·HEAD·저장소), 요청 종료(전송 열림), 이벤트 `waiting_human` | 통과 |
| AC-8 커밋된 코드에서 시작 | `::test_starting_from_committed_code_leaves_the_changes_in_the_original_folder` — 선택 기록(`committed`·`owner`·시각) → `requested` → 준비: `base_commit = committed_base = HEAD`, worktree 에 사용자 변경 없음, 원래 폴더 그대로(`scratch.txt` 남음), 목록은 메모리에서 지워짐, 구현 실행 201; 기존 `test_workspace.py::test_the_users_own_working_tree_is_left_alone` 을 "선택 없이 만들어지지 않음 + 커밋된 코드 선택 뒤 같은 단언" 으로 고침 | 통과 |
| AC-9 포함해서 시작 | `::test_including_uncommitted_changes_starts_from_a_snapshot_and_keeps_the_original` — worktree 에 수정 `reader.py`·미추적 `scratch.txt`, 원래 폴더(상태·HEAD·브랜치·인덱스) 그대로·stash 없음, `base_commit` = 스냅샷(부모 = HEAD = `committed_base`, Case 브랜치가 가리킴), 포함 2·지문 = 목록 때 지문, 구현 실행의 효과가 스냅샷 기준(`files_changed = 1`·`entries_before = 0`)·코드 조합 `base_commit` = 스냅샷, 사용자 변경 보존; 순수 `::test_a_snapshot_commit_captures_the_dirty_tree_without_touching_it`(`.gitignore` 제외·ref 무변경·임시 인덱스 삭제) | 통과 |
| AC-10 동시 편집 보호 | `::test_a_changed_list_is_asked_again_and_a_stale_choice_is_refused` — 옛 지문 선택 409 `basis_list_stale`; 선택 뒤 파일을 더하면 Runner 가 만들지 않고 새 목록(3건·새 지문·`stale_choice`)으로 다시 묻고 `start_basis` 를 지움; 새 목록으로 고르면 3건 포함; 준비된 행의 선택 409 `workspace_not_awaiting_basis`, 모르는 기준 422; 순수 — 다른 ref 와 포함은 `WorkspaceError`, 지문 불일치는 `stale` | 통과 |
| AC-11 화면(D-77) | `tests/test_web_shell.py::test_a_dirty_repository_asks_for_the_start_basis_and_including_keeps_the_original` — 더러운 실제 git 저장소에서 동의 뒤 카드(수 2·목록 `wip-note.txt`·`reader.py`·HEAD, 진행 `waiting_human`, 행 `awaiting_basis`, 원래 폴더 그대로, DB 에 경로 없음) → 포함 → 완료(`done`), 행 `ready`/`include_uncommitted`/2/`owner`, `committed_base = HEAD`·스냅샷, 원래 폴더 그대로·worktree 에 사용자 변경, 작업공간 절 `ws-basis-*`(`data-basis`·"포함해 시작"·"2건"·스냅샷); 구현 실행이 스냅샷 위에서 `reader.py` 를 고쳤고 스냅샷 커밋에는 사용자 버전이 있다 | 통과(실제 Edge·가짜 codex) |
| AC-12 스키마 v27·경계 | `::test_a_v26_database_gets_the_basis_columns_and_old_rows_stay_unrecorded` — v26 DB 이행 뒤 옛 행 `start_basis` NULL·기본값·옛 사실 그대로, 판 ≥ 27, 멱등, 새 표 없음(검색 표 없음); `test_migration.py`·`test_data_boundary.py` 전부 통과; 진입 검사·`enforcement` 변경 없음(코드 대조 — `admission.py` 무변경) | 통과 |
| AC-13 실제 codex·Edge | **선택 사항 — 실제 codex 라이브 미수행.** 실제 Edge 는 브라우저 시험이 열었다(가짜 codex). 두 기능 모두 AI 응답 내용에 의존하지 않는다 | 미수행 |

## 3. 검증

- **기준선**(S-032 시작, 변경 전, `scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **31**, pytest **723 통과·1 실패·2 건너뜀**(13분 50초), P1 계약
  **18**(따로 실행). 실패 1건은 DEVELOPMENT 9절의 기존 시계 해상도 흔들림 시험(`test_quality_changes.py::test_the_reservation_lands_…`) — 이
  변경과 무관. 건너뜀 2건은 이행 시험의 옛 스키마 커밋 창.
- **최종**: 아래 "최종 전체 실행" 에 적는다.
- **기존 시험의 의미 검토** — 검사를 지운 것은 없다. 뜻을 고친 것 하나: `test_workspace.py::test_the_users_own_working_tree_is_left_alone`(더러운
  트리를 선택 없이 준비하던 것 → 선택 없이는 `awaiting_basis` 이고 "커밋된 코드" 선택 뒤 같은 단언 + 기준 기록). 도우미 둘: `Harness.prepare_workspace`
  가 더러운 저장소에서 사람의 선택(`committed` 기본)을 대신 보내므로 `test_repositories.py::test_each_repository_keeps_its_own_uncommitted_user_changes`
  등은 본문 그대로 통과한다; `FakeCliExecutor` 가 읽기 전용 실행에서 파일을 쓰지 않는다(위 1절 — 시험 도구의 특성, 제품 규칙 아님). 수치 고정
  하나: `test_profile_revision.py::test_a_v25_database_…`(`== 26` → 현재 판 이상). 브라우저 시험 결함 둘도 첫 회차에 고쳤다(구현 실행이
  고친 파일에 사용자 버전을 기대한 단언 → 스냅샷 커밋을 본다; `open-results` 가 토글이라 이미 열린 결과물 패널을 닫던 것).
- **새 시험의 첫 회차** — 제품 결함은 없었고 시험·구현 결함을 고쳤다: (1) 검색의 **제목 일치를 서버 필드에 넣지 않았던 것**(구현 누락 —
  `search_candidates` 에 `title` 필드 추가), (2) TTL 0 에서 생성 응답이 `None` 이 되던 것(`create` 가 항목에서 바로 뷰를 만든다), (3) 규칙 검색이
  `knowledge_intake`(실행 보고)만 봐 수동 등록 규칙을 못 찾던 것(`knowledge_version.source_case_id` 로), (4) 순수 시험의 "다른 ref" 가 같은 커밋을
  가리켰던 것(시험 자료), (5) 결정 검색이 다른 프로젝트의 업무 Case 를 같은 프로젝트에서 찾던 것(시험 자료), (6) 진행기 시험에서 가짜 CLI 가
  읽기 전용 실행마다 원래 저장소를 써 구현 실행이 "변경 없음" 으로 실패하던 것(시험 도구 — 위), (7) 이행 시험 고정 자료의 `project_repository`
  컬럼(시험 자료).
- **실제 CLI(codex) 라이브**: 하지 않았다(선택 사항). 실제 Edge 는 브라우저 시험이 열었다(시험 Runner 는 `HADS_RUNNER_DESKTOP=off`).

### 최종 전체 실행

`scripts\run-tests.ps1`(모든 변경 뒤): 웹 빌드 성공, 웹 단위 **37**(+6 — `search.test.ts` 5·`address.test.ts` 1), pytest **740 통과·0 실패·2
건너뜀**(15분 29초 — 기준선의 실행 수 724 에서 **+16** = `tests/test_conversation_search.py` 5(순수 1·서버 4) + `tests/test_start_basis.py` 9
(순수 2·서버 5·진행기 1·이행 1) + 브라우저 2; 기준선의 흔들림 시험은 이 회차에 통과), P1 계약 **18**, "전체 시험 통과". 건너뜀 2건은 이행
시험의 옛 스키마 커밋 창(DEVELOPMENT 9절). AC-5·AC-11 의 브라우저 시험(실제 Edge·가짜 codex)은 이 실행 안에서 통과했다(분리 실행에서도
4/4 — 새 둘 + 자동 진행 + 작업 PC 절).

## 4. 경계

- 검색·선택은 **권한·동의·인수·준수가 아니다.** 진입 검사·예산 강제·확인 지점·게시 규칙·저장소 쓰기 허용은 그대로다(강제 축 넷,
  `publish` 는 P5). `awaiting_basis` 는 준비되지 않음이며 쓰기 실행은 `workspace_not_ready` 로 거부된다(`admission.py` 무변경).
- 원문 경계 그대로 — 검색어·발췌·미커밋 파일 목록은 제어부 메모리에만 있고 DB·로그에 없다(시험이 DB 의 모든 표를 읽어 확인). 서버 필드
  일치는 이미 서버에 있던 짧은 값이고 본문 검색은 소유 PC 가 후보 원문만 읽는다(색인 없음). 행에는 수·해시만 남는다.
- 원래 폴더는 어떤 경로에서도 바뀌지 않는다 — 스냅샷 커밋은 객체 저장소에 더해질 뿐 브랜치·HEAD·인덱스·작업 트리는 그대로다(시험이 전후
  대조). 사람이 본 목록과 다른 것은 포함하지 않는다.
- 소급 없음 — 옛 작업공간 행은 `start_basis` NULL(기록 없음)이고 이미 준비된 작업공간은 다시 묻지 않는다. 스키마 v27 은 컬럼 여덟뿐이다.

## 5. 알려진 한계

- **본문 검색에 색인이 없다**(후보 상한 2,000건까지 선형, 넘으면 `truncated`). 낱말 AND 부분 문자열 일치뿐이다(정규식·형태소 없음).
- **서버 필드의 "요약" 은 본문이 아니다** — 오프라인 검색은 제목·규칙 요약·개정 사유·업무화 요약·결정 종류에서만 찾는다.
- **여러 PC**: 소유 PC 별로 나눠 연결된 PC 만 검색하고 나머지는 제외 수로 보인다(지금 운영은 한 Runner).
- **검색·목록은 메모리다.** 제어부 재시작·TTL 뒤에는 404/`available: false` 로 드러나고 사람이 다시 검색·다시 불러온다.
- **선택은 이진이다**(전부 포함 / 전부 제외). 파일별 포함은 경로가 브라우저→서버→PC 로 오가야 해 넣지 않았다. **사용자 확인(2026-09-24): 이진 선택 그대로 둔다.**
- **포함은 HEAD 기준에서만.** 다른 브랜치·커밋(`base_ref`)은 기존 API·관리 화면으로 고르고 그때는 커밋된 코드에서만 시작한다. 새 화면에 ref
  변경 입력은 없다.
- **후속 Case 의 "이전 결과 기준" 제안(D-77)은 넣지 않았다** — 후속 대화(P4-05)의 작업공간도 HEAD 기준이다(별도 작업).
- **스냅샷 커밋은 Case 브랜치의 첫 커밋으로 남는다**(P5 의 push·PR 에 따라간다). `.gitignore` 된 파일은 목록에도 포함에도 없다.
- 시작은 `main`/`fae2af5` clean·`origin/main` 과 같음. 이 결과는 **사용자 지시로 커밋·push** 했다(작업 커밋 뒤 인계 기록 커밋 — 해시는 DEVELOPMENT.md). 그 허용은 이 변경에만 적용된다. 라이브 데이터 없음. 저장소 `var\` 는 건드리지
  않았다. 시험이 띄운 제어부·Runner·Edge 는 pytest 가 내렸다.
