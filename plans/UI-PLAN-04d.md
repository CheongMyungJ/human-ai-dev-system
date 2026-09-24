# UI-PLAN-04d

UI-04(남은 업무·화면 연결)의 **넷째(마지막) 하위 plan** — 대화 검색(D-84) + 미커밋 포함 시작(D-77). 범위는 **사용자
결정(2026-09-24, S-030): 남은 네 항목을 두 단계로 묶는다 — UI-04c = D-86 + D-88 + D-89(완료), UI-04d = D-84 + D-77**.
기준: 설계 v0.8 2차 / D-01~90 / **D-84**(보관 포함 프로젝트 대화 검색 — 제목·요약·본문·결정, PC 연결 시 본문, 미연결 시
서버의 제목·요약·결정 요약만 + 일부 제외 표시, 결과에서 메시지·결정으로 이동, 본문·본문 인덱스는 PC, 코드·파일 검색 아님) /
**D-77**(작업 기준과 미커밋 변경 — 현재 브랜치 마지막 커밋 기본, 미커밋 변경이 있으면 목록과 함께 포함/커밋된 코드만 선택,
포함해도 원래 폴더 보존·별도 작업공간에 정확한 시작 상태 기록, 자동 커밋·stash·삭제 없음) / [대화 중심 UI](../ui-conversation-design.md)
3.1·10절 / [데이터 경계](../data-boundary-review.md) 1·3절("검색용 발췌를 서버 영구 저장의 예외로 삼지 않는다") /
[작업공간 검토](../execution-workspace-review.md) 2절 / [review-acceptance-matrix](../review-acceptance-matrix.md) AC-45·49.
선행: UI-01(대화 메시지·원문 참조), UI-02(제어 루프·heartbeat·PC 연결 판정), UI-03(열람 중계·`seq` 이동·탭 메모리 본문),
UI-04a(결정 사항 패널·규칙 화면·`seq` 주소), P3-03/R2(작업공간·트리 지문·`user_tree` 관측), P4-05(진행기·사람 대기 카드).
세션 S-032.

기준선(S-032 시작, 변경 전, `scripts\run-tests.ps1`): 5절 끝에 있다. 시작 상태 `main`/`fae2af5`, 작업 트리 clean,
`git fetch` 뒤 `origin/main` 과 같음.

범위는 **UI-04d 하나**다. P5(GitHub)·P6·프로젝트 코드/파일 전체 검색·후속 Case 의 기준 제안(아래 9절)은 넣지 않는다.

## 0. 제품 판단 — 새로 내리지 않는다

이 plan 이 정하는 것은 D-84 의 **검색이 어디서 무엇을 읽는가와 결과를 어떻게 나르는가**(서버 필드 즉시, 본문은 소유 PC 가
읽어 제어부 메모리로만 중계), D-77 의 **선택 지점·기록 모양·포함 방식**(사람 대기 카드, 스냅샷 커밋, 원래 트리 무변경)이며
D-77·D-84·데이터 경계 1·3절·작업공간 검토 2절 안이다. 상세 설계 선택(제품 정책이 아니다, 9절에도 적는다):

- **서버는 검색어·발췌·목록을 저장하지 않는다.** 검색 요청·본문 일치 발췌·미커밋 변경의 파일 목록은 제어부 **프로세스
  메모리**에만 있고(열람 중계 `RelayBuffer` 와 같은 자리), 제어부가 재시작하면 사라진다(`expired` — 다시 요청한다). DB 에는
  수·해시·상태만 남는다. 데이터 경계 1·3절의 "검색용 발췌는 서버 영구 저장의 예외가 아니다", D-43 "파일 경로는 PC 에" 그대로다.
- **본문 검색에 색인이 없다(첫 버전).** 서버가 후보(이 프로젝트 대화들의 메시지 원문 참조 — `artifact_id/revision`·순번)를 소유
  PC 별로 묶어 주고, Runner 는 자기 `ArtifactStore` 에서 그 원문만 읽어 대조한다(경로를 받지 않는다 — 열람 중계와 같은 원칙).
  후보 상한(2,000건, 최신순)을 넘으면 `truncated` 로 드러낸다. 색인은 필요해지면 PC 쪽에 둔다(D-84 "본문 인덱스는 PC").
- **검색 범위는 값으로 온다.** 서버 필드(제목·메시지 요약·업무화 요약·결정·이 대화에서 정한 규칙·Profile 개정 사유)는 즉시,
  본문은 소유 PC 가 연결돼 있을 때만 — 미연결 PC 가 가진 메시지 수를 `excluded_message_count` 로 세고 화면이 "PC 미연결로
  본문 N건 검색 제외" 를 보인다. 메시지 요약은 본문 발췌가 아니다(UI-01 규칙 — `사용자 메시지 · N자`·`AI 응답 · run`)이므로
  요약 일치는 사실상 제목·규칙·결정 일치다 — 오프라인에서 본문을 검색했다고 표시하지 않는다.
- **검색은 현재 프로젝트, 보관 포함, 대화만이다.** 다른 프로젝트·프로젝트 파일·코드·산출물 본문(의도·설계·계획)은 대상이
  아니다(D-84 "코드·파일 전체 검색 아님"). 일치는 대소문자를 무시한 **모든 낱말 포함**(공백 분리, AND)이며 정규식·형태소 분석은
  없다.
- **결과에서의 이동은 기존 주소 규칙이다.** 메시지 일치 → 그 대화의 `seq` 로(UI-04a `messageLink`·`hads:focus-message`), 결정·
  개정·업무화 일치 → 그 대화 + 결정 사항 패널, 규칙 일치 → 규칙 화면의 그 항목(`rulesLink`). 본문은 그 뒤 열람 경로로 오며 PC
  미연결이면 "연결 필요" 그대로다(D-84 "원문을 열 수 없는 경우 연결 필요").
- **미커밋 변경의 선택은 사람 대기다(카드).** 진행기의 작업공간 걸음에서 Runner 가 사용자 원래 트리를 관측해 **더러우면 만들지
  않고** 목록(상태·경로)을 제어부 메모리로 올리고 행을 `awaiting_basis` 로 둔다 → 진행기가 `workspace_start_basis` 사람 대기로
  요청을 끝낸다 → 카드가 목록·기준 커밋과 `포함해서 시작 / 커밋된 코드에서 시작` 을 보인다 → 사람이 고르면 행이 `requested` 로
  돌아가 Runner 가 만든다. 깨끗한 트리는 지금처럼 묻지 않고 바로 만든다(D-77 "현재 브랜치 마지막 커밋을 기본"). 선택은 **이진**
  이다(전부 포함 / 전부 제외) — 파일별 선택은 경로가 브라우저→서버→PC 로 오가야 하므로 첫 버전에 넣지 않는다(9절).
- **포함은 스냅샷 커밋이다.** Runner 가 **임시 인덱스**(`GIT_INDEX_FILE`)로 사용자 트리를 `add -A`(`.gitignore` 존중) → `write-tree`
  → `commit-tree`(부모 = HEAD) 해 원래 저장소의 객체 저장소에 **스냅샷 커밋**을 만들고 그 커밋에서 worktree 를 편다. 원래
  트리·인덱스·브랜치·HEAD 는 건드리지 않는다(자동 커밋·stash·reset·삭제 없음 — 기존 AC-2 그대로). `base_commit` = 스냅샷 커밋
  (실행 전후 대조·누적 수·코드 조합의 기준이 "실제 시작 상태"가 된다), `committed_base` = 그때의 HEAD, `included_entries`·
  `included_tree_digest` 가 무엇을 포함했는지의 기록이다(정확한 시작 상태 = 커밋 SHA + 트리 지문 + 수). 브랜치의 첫 커밋으로
  남으므로 사람이 `git log` 에서 그 사실을 본다.
- **동시 편집 보호는 지문 대조다.** 목록을 올릴 때의 트리 지문(`basis_tree_digest`)을 사람의 선택이 `seen_digest` 로 되돌려
  주고(다르면 409 `basis_list_stale`), Runner 는 포함 직전에 다시 관측해 지문이 다르면 만들지 않고 **새 목록으로 다시 묻는다**
  (`start_basis` 를 지우고 `awaiting_basis`). 사람이 본 목록과 다른 것을 포함하지 않는다.
- **기준 변경 경로(다른 브랜치·커밋)는 기존 API 그대로다.** `POST /api/cases/{id}/workspace {base_ref}`·관리 화면(P3-03)이
  있고 새 화면에는 넣지 않는다. 미커밋 포함은 **HEAD 기준에서만** 뜻이 있다(사용자 트리는 HEAD 위의 변경이다) — 다른 ref 와
  포함이 함께 오면 Runner 가 거부한다(`failed`, 사유).
- **`start_basis` 미기록은 "정해지지 않음"이다.** 옛 행(v27 이전)은 NULL 이며 그것은 `committed` 가 아니라 기록 없음이다 —
  당시에는 선택 경로가 없었고 준비는 HEAD 였다는 사실은 `base_commit`·`user_tree_dirty` 가 이미 말한다. 지어 채우지 않는다.

## 1. 현재 구현과 차이 (코드 대조)

1. **검색이 없다.** 목록은 `list_cases`(`archived=include|exclude|only`)·`_with_conversation_summary`(단계·요청·진행·활동 시각),
   대화는 `conversation_view`(`messages` = `list_messages`, 요약은 호출자 문구). 본문은 열람 중계뿐(`open_read_request` →
   Runner `serve_read_requests`(`store.get(artifact_id, revision)`) → `RelayBuffer` → 브라우저 한 번 받음). 결정은 `decision`
   (종류·대상·주체, 글 없음)·`case_profile_revision.reason_summary`·`knowledge_intake/knowledge_version.summary`(규칙 글)·
   `case_work_start.summary`. 왼쪽 목록(`Sidebar.tsx`)에 검색 자리가 없고 주소(`lib/address.ts`)는 `conversation|rules|settings|
   repositories` 화면뿐이다. `seq` 이동(`focusSeq`·`hads:focus-message`)과 규칙 항목 이동(`rulesLink`)은 있다.
2. **작업공간은 항상 HEAD 에서 바로 만든다.** 진행기 `_task_phase` → `Step("workspace")` → `request_workspace(base_ref=HEAD)`
   → Runner `prepare_workspaces` → `workspace.prepare`(사용자 트리 `observe` 만 — 더러워도 그대로 만든다, 수만 보고) →
   `report_workspace_ready(user_tree_dirty, user_tree_entries)`. `case_workspace` 상태는 `requested|ready|failed`(CHECK 없음).
   진입 검사 `_check_workspace` 는 `ready` 만 연다. 파일 목록은 Runner 에 남고(`TreeState.entries`) 어디에도 올라가지 않는다.
   `WaitReason` 에 작업공간 선택 대기가 없고 카드도 없다. `WorkspaceRow` 는 브랜치·상태·PC·경로·열기만 보인다.
3. **Runner 제어 루프**는 heartbeat → 원문 저장 → 열람 → 지식 올림 → 제어(중단·잔류·열기) 순이며(`control_tick`) 검색 자리가
   없다. `ControllerClient` 에 검색·미커밋 보고가 없다.
4. **제어부 메모리**는 `RelayBuffer`(바이트, 키 하나) 하나다. TTL 있는 값 저장소가 없다.

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| **D-84 순수**: `domain/search.py` — 낱말 분해(`tokens`), 일치(`matches`), 발췌(`snippet`, 160자·첫 일치·일치 수), 후보 상한 | 정규식·형태소·유사도(없음). 색인(없음 — 필요해지면 PC) |
| **D-84 제어부**: `controller/transient.py`(메모리 값 저장소, TTL), `SearchRegistry`(요청·후보·결과 — 메모리), `conversation_search` 뷰(서버 필드 일치 즉시 + 소유 PC 별 후보·연결 판정·제외 수), API `POST /api/projects/{id}/conversation-searches`·`GET /api/conversation-searches/{id}`·Runner `GET /api/runner/{id}/search-requests`·`POST /api/runner/search-requests/{id}/results`, 만료(요청 10분·PC 전달 뒤 60초 무응답) | 검색 표·발췌 저장(없음). 다른 프로젝트·산출물 본문·코드(없음). 서버 푸시(없음 — 화면이 조회) |
| **D-84 Runner**: `serve_search_requests`(제어 루프, 후보 원문만 `store.get` → 대조 → 결과 올림; 없는 원문은 `unreadable` 로 셈), `ControllerClient.pending_search_requests/send_search_results` | Runner 의 임의 경로·전체 저장소 스캔(없음) |
| **D-84 화면**: `lib/search.ts`(순수 — 강조 조각·범위 문구·묶기), 왼쪽 목록의 검색 입력(`search-input`·`search-submit`), 가운데 검색 화면(`screen=search`, 주소에 검색어 없음)·범위 줄·결과(대화별 묶음, 보관 표시, 일치 종류, 발췌 강조)·이동(메시지 `seq`/결정 패널/규칙 항목), 본문 결과 대기·만료 표시 | 검색 이력 저장(없음). 결과 안에서 원문 열기(없음 — 이동 뒤 기존 열람) |
| **D-77 순수·Runner**: `workspace.prepare(start_basis=, expected_tree_digest=)` — `NeedsBasis`(더러움·기준 미정 또는 지문 불일치) / 스냅샷 커밋(`snapshot_commit`, 임시 인덱스) / `PreparedWorkspace.committed_base·start_basis·included_entries·included_tree_digest`; `prepare_workspaces` 가 목록 보고(`report_workspace_uncommitted`) | 파일별 선택(없음 — 9절). 다른 ref 와 포함의 조합(거부). 원래 트리의 어떤 변경(없음) |
| **D-77 제어부**: 스키마 **v27** — `case_workspace` 컬럼(`start_basis`·`basis_decided_by/at`·`committed_base`·`included_entries`·`included_tree_digest`·`basis_tree_digest`·`basis_entries`), `WorkspaceState.AWAITING_BASIS`, `StartBasis`, `report_workspace_uncommitted`(상태·수·지문; 목록은 메모리), `decide_start_basis`(`seen_digest` 대조, 409 `workspace_not_awaiting_basis`·`basis_list_stale`), `claim_workspace_requests` 가 기준·지문을 실음, `report_workspace_ready` 가 새 값을 받음, `workspace_state`/`workspace_view` 확장, `WaitReason.WORKSPACE_START_BASIS`(`_task_phase`), 진행기 `on_start_basis_decided`, API `POST /api/runner/workspaces/{case_id}/uncommitted`·`GET /api/cases/{id}/workspaces/{repo}/uncommitted`·`POST /api/cases/{id}/workspaces/{repo}/start-basis` | 진입 검사 규칙 변경(없음 — `ready` 만 연다). 후속 Case 의 기준 제안(9절). 화면의 ref 변경(기존 API·관리 화면) |
| **D-77 화면**: 대기 카드 `StartBasisCard`(목록·기준 커밋·두 버튼·목록 만료 시 다시 불러오기), `WorkspaceRow` 의 시작 기준 줄(커밋된 코드 / 미커밋 N건 포함 · 스냅샷 · 커밋 기준), 상태 이름표 | 입력창 근처의 기준 표시(9절 — 작업공간 절이 보인다) |
| 자동 시험(순수·서버·Runner·이행·웹 단위·브라우저 2), 문서 | 실제 codex 라이브는 선택 사항(3·5절 — 두 기능 모두 AI 응답 내용에 의존하지 않는다) |

## 3. 설계

### 3.1 D-84 — 순수 (`domain/search.py`, `web/src/lib/search.ts`)

- `tokens(query) -> tuple[str, ...]`: 공백 분리·소문자·중복 제거·빈 낱말 제거(최대 8개). `matches(text, tokens)`: 소문자 본문에
  모든 낱말이 있는가. `snippet(text, tokens, width=160) -> {snippet, match_count}`: 첫 일치 낱말 주변 `width` 자(줄바꿈은 공백),
  일치 수는 낱말별 등장 수의 합. `MAX_CANDIDATES = 2000`, `SNIPPET_WIDTH = 160`, `MAX_QUERY = 200`.
- `lib/search.ts`: 같은 `tokens`, `highlight(text, tokens) -> {text, hit}[]`, `scopeText(scope)`("제목·요약·결정 + 본문(PC 연결)"/
  "PC 미연결로 본문 N건 검색 제외"/"본문 검색 중(PC)…"/"본문 검색 만료 — 다시 검색"), `groupByCase(matches)`.

### 3.2 D-84 — 제어부 (`controller/transient.py`·`controller/search.py`·`controller/repository.py`·`controller/api.py`)

- `transient.TransientStore`: `put(key, value, ttl)`·`get`·`drop`·`items(prefix)`·`sweep()`. 프로세스 메모리·잠금. `app.state.searches`·
  `app.state.uncommitted` 두 개(`controller/app.py`).
- `repository.search_candidates(project_id)`: 이 프로젝트 모든 대화(보관 포함)의 서버 필드 행과 본문 후보 —
  `cases`(id·title·archived·status·stage), `summaries`(메시지 요약 — 종류·순번), `work_starts`(요약), `decisions`(종류·대상 버전·주체·
  근거 메시지 순번), `revisions`(개정 사유·근거 메시지 순번), `rules`(등록 규칙 요약·키·순번), `bodies`(메시지 원문 참조 — case·seq·
  author·artifact·revision·owner_runner_id·availability, 최신순 상한). 본문은 없다.
- `controller/search.py`: `build_search(repo, store, project_id, query, requested_by)` — 서버 일치(`ServerMatch`)를 즉시 계산, 후보를
  소유 PC 별로 묶어 `runner_connection_state` 로 연결 판정 → 연결된 PC 마다 `SearchRegistry` 항목(`id`·`runner_id`·검색어·후보)을
  `pending` 으로, 미연결 PC 는 `excluded`(메시지 수). `available != available` 인 원문은 `unreadable_pending` 으로 센다.
  `view(id)`: `{id, project_id, requested_at, query_length, scope, matches, body}`; `body.state` = `none`(후보 0) | `pending` |
  `partial`(여럿 중 일부 도착) | `relayed` | `expired` | `excluded`. 만료: 요청 10분, PC 에 전달 뒤 60초 무응답.
- API: `POST /api/projects/{project_id}/conversation-searches {query(1~200), requested_by}` → 201 뷰; `GET /api/conversation-searches/{id}`
  → 뷰(없으면 404 — 재시작·만료); `GET /api/runner/{runner_id}/search-requests` → 그 PC 의 `pending`(전달 표시·`claimed_at`);
  `POST /api/runner/search-requests/{id}/results {runner_id, matches: [{case_id, seq, artifact_id, revision, snippet, match_count}],
  scanned, unreadable}` → 등록(다른 PC·끝난 요청 409). 검색어·발췌는 **로그에도 남기지 않는다**.

### 3.3 D-84 — Runner (`runner/agent.py`·`runner/client.py`)

- `serve_search_requests()`: `control_client.pending_search_requests(runner_id)` 마다 후보 원문을 `store.get` 으로 읽고(없으면
  `unreadable += 1`) `domain.search` 로 대조, 일치마다 발췌·수 → `send_search_results`. `control_tick` 에서 열람 다음에 돈다.
  경로를 받지 않고 후보 밖은 읽지 않는다.

### 3.4 D-84 — 화면 (`web/src/shell/Sidebar.tsx`·`Shell.tsx`·`SearchScreen.tsx`(새)·`lib/address.ts`)

- 주소: `Screen` 에 `search` 추가(`?screen=search`, 검색어는 주소에 넣지 않는다). `Sidebar` 상단 "새 대화" 아래 검색 폼
  (`search-form`·`search-input`·`search-submit`) — 제출하면 `onSearch(query)` → `Shell` 이 `screen=search` 로 두고
  `searchApi.start(projectId, query)`, 본문이 `pending|partial` 이면 500ms 마다 `searchApi.get(id)` 를 최대 30초.
- `SearchScreen`: 머리(검색어·프로젝트), 범위 줄 `search-scope`(`data-bodies`), 결과 `search-results` — 대화별 묶음
  `search-case-{case_id}`(제목·보관·종료 배지) 아래 일치 행 `search-hit-{n}`(종류 이름표·발췌(`<mark>`)·`#seq`). 클릭 → 메시지면
  `selectCase` + `focusSeq`, 결정·개정·업무화면 `selectCase` + 결정 사항 패널, 규칙이면 규칙 화면 항목. 결과 없음·만료·오류 문구.
- `api.ts`: `SearchView`·`SearchMatch`·`searchApi`·`SEARCH_KIND_LABEL`.

### 3.5 D-77 — Runner (`runner/workspace.py`·`runner/agent.py`·`runner/client.py`)

- `StartBasis`(`domain/models.py`): `COMMITTED = "committed"`, `INCLUDE_UNCOMMITTED = "include_uncommitted"`.
- `workspace.NeedsBasis(head, entries, digest, stale: bool)` — 만들지 않았다. `prepare(..., start_basis=None, expected_tree_digest="")`:
  저장소 확인 → 사용자 트리 관측 → 재사용(`SYSTEM_OWNED`)이면 그대로(기준은 처음 것) → **더럽고 기준 미정이면 `NeedsBasis`** →
  `include_uncommitted` 면 `base_ref` 가 HEAD 커밋과 같아야 하고(아니면 `WorkspaceError`) 지문이 `expected_tree_digest` 와 같아야
  한다(아니면 `NeedsBasis(stale=True)`) → `snapshot_commit(repo, head, message)`(임시 인덱스: `read-tree HEAD` → `add -A` →
  `write-tree` → `commit-tree -p HEAD`, 작성자는 `hads`) → `worktree add -b branch path <snapshot>` → `PreparedWorkspace(base_commit=
  snapshot, committed_base=head, start_basis, included_entries=len(entries), included_tree_digest=digest)`; `committed`(또는 깨끗함)면
  지금처럼 `base_commit = base_ref^{commit}`, `committed_base = 같은 값`, `included_entries = 0`.
- `prepare_workspaces`: 요청의 `start_basis`·`basis_tree_digest` 를 넘기고 `NeedsBasis` 면 `client.report_workspace_uncommitted(case_id,
  {runner_id, repository_id, head, user_tree_digest, entries: [{status, path}](상한 500·`truncated`), stale})`; 준비면 새 값을
  `report_workspace_ready` 에 더한다.

### 3.6 D-77 — 제어부 (`controller/schema.sql` v27·`db.py`·`repository.py`·`admission.py`·`domain/work_flow.py`·`work_progressor.py`·`api.py`)

```
case_workspace + start_basis TEXT (NULL | committed | include_uncommitted), basis_decided_by TEXT, basis_decided_at TEXT,
                committed_base TEXT NOT NULL DEFAULT '', included_entries INTEGER, included_tree_digest TEXT NOT NULL DEFAULT '',
                basis_tree_digest TEXT NOT NULL DEFAULT '', basis_entries INTEGER
```

- `SCHEMA_VERSION = 27`(컬럼만, `_add_column_if_missing`; 옛 행 NULL/기본값 — "기록 없음"). `WorkspaceState.AWAITING_BASIS`.
- `claim_workspace_requests` 가 `start_basis`·`basis_tree_digest` 를 싣는다. `report_workspace_uncommitted(case_id, runner_id,
  repository_id, head, digest, entry_count, stale)`: 행 → `awaiting_basis`, `runner_id`, `committed_base = head`, `basis_tree_digest`,
  `basis_entries`, `user_tree_dirty = 1`, `user_tree_entries`; `stale` 면 `start_basis`·결정 기록을 지운다. API 가 목록을
  `app.state.uncommitted` 에 `(case_id, repository_id)` 키로 넣는다(TTL 30분).
- `decide_start_basis(case_id, repository_id, basis, actor, seen_digest)`: 상태가 `awaiting_basis` 가 아니면 409
  `workspace_not_awaiting_basis`; `seen_digest != basis_tree_digest` 면 409 `basis_list_stale`; 기록 뒤 상태 `requested`(Runner 가 다음
  회차에 만든다). API 는 기록 뒤 `progressor.on_start_basis_decided` 를 부른다(P4-05b 의 상한 변경과 같은 자리).
- `report_workspace_ready(..., start_basis, committed_base, included_entries, included_tree_digest)`; `workspace_state()` 에 `user_tree_entries`·
  `basis_entries`·`start_basis`; `workspace_view` 의 작업공간마다 새 컬럼 그대로. `WORKSPACE_STATE_LABEL.awaiting_basis`.
- `work_flow._task_phase`: `space.state == awaiting_basis` → `_wait(WaitReason.WORKSPACE_START_BASIS, repository_id=, repository_name=,
  entries=basis_entries, head=committed_base)`; `WAIT_DETAIL` 문구. `_check_workspace` 는 그대로(`awaiting_basis` 는 준비되지 않음 →
  `workspace_not_ready`, 상태 이름이 사유에 든다).
- `work_progressor.on_start_basis_decided(case_id, *, actor, basis)`: 진행 행이 있으면 `RUNNING`/`workspace_pending` 으로 두고 이벤트를
  적은 뒤 `on_workspace_reported` 와 같이 한 걸음 본다.
- API: `POST /api/runner/workspaces/{case_id}/uncommitted`(Runner), `GET /api/cases/{case_id}/workspaces/{repository_id}/uncommitted`
  → `{available, head, digest, entry_count, truncated, entries: [{status, path}]|null, state}`(메모리에 없으면 `available: false` —
  화면이 "목록을 PC 에서 다시 불러온다" = 기존 `POST /api/cases/{id}/workspace {repository_id}` 로 다시 요청),
  `POST /api/cases/{case_id}/workspaces/{repository_id}/start-basis {basis, actor, seen_digest}` → 행(409 코드·문구).

### 3.7 D-77 — 화면 (`web/src/shell/ProgressCards.tsx`·`ReviewPanel.tsx`·`api.ts`)

- `StartBasisCard`(`wait-card-workspace_start_basis`): "이 저장소에 커밋하지 않은 변경 N건이 있다 — 어느 코드에서 시작할까" · 기준
  `커밋된 코드 = 현재 브랜치 마지막 커밋 <head7>` · 목록 `basis-entries`(행 `basis-entry-{n}`: 상태·경로, `truncated` 안내) 또는
  "목록이 이 서버에 없다(재시작·만료) — PC 에서 다시 불러온다" `basis-reload` · 버튼 `basis-include`("포함해서 시작 — 별도
  작업공간에 이 변경을 스냅샷으로 반영한다. 원래 폴더는 그대로다")·`basis-committed`("커밋된 코드에서 시작 — 이 변경은 원래
  폴더에만 남는다") · 거부 문구 `basis-refusal`. 두 경로 모두 원래 폴더를 바꾸지 않는다는 문구.
- `WorkspaceRow`: 시작 기준 줄 `ws-basis-{repo}`(`data-basis`): `커밋된 코드 <sha7>` / `미커밋 변경 N건 포함 — 스냅샷 <sha7>(커밋 기준
  <sha7>)` / `기록 없음(옛 작업공간)` / `awaiting_basis` 면 "시작 기준 선택 대기(대화의 카드)". `WORKSPACE_STATE_LABEL`·`WAIT_LABEL`.

### 3.8 문서

ui-conversation-design 3.1·10·12절(구현 기록), decisions D-77·D-84(구현 기록), data-boundary-review(검색 구현 기록 한 줄),
execution-workspace-review 2절(포함 경로 구현 기록), README, DEVELOPMENT(1절 요약 표·1.1·1.11절·3절·4절·9절·인계),
review-acceptance-matrix AC-45·49.

## 4. 성공 기준

| AC | 기준 |
|---|---|
| AC-1 | **서버 필드 검색**: 제목·규칙 요약·개정 사유·업무화 요약·결정이 낱말(AND, 대소문자 무시)로 일치하고 보관된 대화도 포함되며 다른 프로젝트의 대화는 나오지 않는다; 메시지 요약은 본문이 아니므로 본문 낱말로는 일치하지 않는다(오프라인에서 본문을 찾았다고 표시하지 않음) |
| AC-2 | **범위 표시**: 소유 PC 미연결이면 `body.state = excluded`·`excluded_message_count = N`·`runners[].state = excluded` 이고 서버 일치는 그대로 온다; 후보가 없으면 `none`; 후보 상한을 넘으면 `truncated` |
| AC-3 | **본문 검색(PC)**: 연결된 소유 PC 가 제어 루프에서 후보 원문만 읽어 일치(대화·순번·발췌·일치 수)를 올리고 조회의 `body.state = relayed` 에 온다; 이 PC 에 없는 원문은 `unreadable` 로 세고 일치로 적지 않는다; 후보 밖 원문은 읽지 않는다 |
| AC-4 | **경계**: 검색어·발췌·미커밋 파일 목록이 제어부 DB 파일 어디에도 없다(바이트 검사); 요청은 10분·PC 무응답 60초에 만료되고 제어부 재시작 뒤 조회는 404; 스키마에 검색 표가 없다 |
| AC-5 | **화면(D-84)**: 왼쪽 검색 → 가운데 결과(범위 줄·대화별 묶음·발췌 강조) → 메시지 일치 클릭이 그 대화의 그 메시지로 이동(`message-{seq}` 강조), 규칙 일치 클릭이 규칙 화면의 그 항목으로; 본문 대기·도착이 화면에 그대로(브라우저 시험, 실제 Edge·가짜 codex) |
| AC-6 | **깨끗한 트리**: 미커밋 변경이 없으면 지금처럼 묻지 않고 HEAD 에서 만들며 `start_basis = committed`·`committed_base = base_commit`·`included_entries = 0` 이다; 기존 작업공간 시험 전부 통과 |
| AC-7 | **더러운 트리의 선택 대기**: Runner 가 만들지 않고 목록(상태·경로)을 올리며 행이 `awaiting_basis`(수·지문·`committed_base` 기록), 목록은 메모리 조회에만 있고 DB 에 경로가 없다; 진행기가 `workspace_start_basis` 사람 대기로 요청을 끝내고 카드 값(저장소·수·HEAD)을 싣는다; 그 사이 쓰기 실행은 `workspace_not_ready` 로 거부된다; 원래 폴더는 그대로다 |
| AC-8 | **커밋된 코드에서 시작**: 선택 뒤 Runner 가 HEAD 에서 만들고 worktree 에 사용자 변경이 없으며 원래 폴더(상태·HEAD·내용)는 그대로, 행에 `start_basis = committed`·주체·시각이 남고 진행기가 이어 간다 |
| AC-9 | **포함해서 시작**: worktree 에 사용자의 수정·미추적 파일이 있고 원래 폴더(상태·HEAD·인덱스·브랜치)는 그대로(stash·커밋 없음); `base_commit` = 스냅샷 커밋(부모 = 그때의 HEAD = `committed_base`, 브랜치가 그것을 가리킴), `included_entries = N`·`included_tree_digest` = 목록 때 지문; 그 뒤 구현 실행의 효과·누적 수·코드 조합이 스냅샷을 기준으로 한다(사용자 변경을 AI 변경으로 세지 않음) |
| AC-10 | **동시 편집 보호**: 목록 뒤 사용자가 또 고치면 (a) 옛 `seen_digest` 의 선택은 409 `basis_list_stale`, (b) 선택 뒤 포함 직전에 트리가 바뀌었으면 Runner 가 만들지 않고 새 목록으로 다시 묻는다(`start_basis` 지움·`awaiting_basis`·수 갱신); 다른 ref 와 포함의 조합은 `failed` 사유로 거부; `awaiting_basis` 가 아닌 행의 선택은 409 |
| AC-11 | **화면(D-77)**: 카드가 목록·HEAD·두 버튼을 보이고 선택 뒤 진행이 이어져 완료되며 작업공간 절이 시작 기준(포함 N건·스냅샷·커밋 기준)을 서버 값 그대로 보인다(브라우저 시험, 더러운 실제 git 저장소) |
| AC-12 | **스키마 v27·경계**: v26 DB 이행 뒤 옛 작업공간 행의 `start_basis` NULL(기록 없음)·기본값, 멱등, 새 표 없음; 강제 축 넷·`enforcement`·진입 검사 규칙 그대로; 기존 시험 전부 통과, 시험 수는 늘기만 한다 |
| AC-13 | 실제 codex·Edge 라이브: **선택 사항** — 하지 않으면 미수행으로 적는다 |

## 5. 검증

- 순수·서버·Runner(`tests/test_conversation_search.py` 새): `domain.search` 셋(낱말·일치·발췌), AC-1~4 서버(`harness` — 대화 셋(하나
  보관, 하나 다른 프로젝트), 규칙 등록·개정·결정, `age_heartbeat` 로 미연결, `agent.control_tick` 으로 본문 검색, DB 바이트 검사,
  만료).
- D-77(`tests/test_start_basis.py` 새): 순수 `snapshot_commit`·`prepare(NeedsBasis)`; 서버 AC-6~10(`harness` 의 `create_git_project(dirty=
  True)` + `_agreed_git_case`; 진행기 대기는 `flow_state`/`next_step` 과 `processing_harness` 의 실제 진행); 이행 AC-12(`test_migration`
  방식으로 v26 자료 → v27).
- 기존 시험의 의미 검토: `test_workspace.py::test_the_users_uncommitted_changes_are_left_alone`(AC-2 — 더러운 트리를 **선택 없이**
  준비하던 것) 은 새 규칙에서 선택 대기가 되므로 "커밋된 코드" 선택 뒤 같은 단언으로 고친다(검사를 지우지 않는다);
  `test_repositories.py::test_each_repository_keeps_its_own_uncommitted_user_changes` 같은 방식. `harness.prepare_workspace` 에
  `basis="committed"` 기본 인자를 두어 더러운 저장소 시험이 선택을 지나게 한다(선택 없이 만들어지지 않음을 따로 단언).
- 웹 단위: `web/src/lib/search.test.ts`(낱말·강조·범위 문구·묶기), `address.test.ts` 에 `search` 화면.
- 브라우저(`tests/test_web_shell.py` 끝의 UI-04d 절 2건): (1) D-84 — 대화 둘(하나 보관)에 메시지 → 검색 → 범위 줄·결과 → 클릭 →
  `message-{seq}` 강조; 규칙 일치 → 규칙 화면; (2) D-77 — 더러운 git 저장소 프로젝트에서 업무 → 카드(목록·버튼) → 포함 → 완료 →
  작업공간 절의 시작 기준.
- 전체 `scripts\run-tests.ps1`.

기준선(S-032 시작, 변경 전, `pwsh -File scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **31**, pytest **723 통과·1 실패·2
건너뜀**(13분 50초), P1 계약 **18**(스크립트가 pytest 실패로 멈춰 따로 실행). 실패 1건은 DEVELOPMENT 9절의 기존 시계 해상도
흔들림 시험(`test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure` — `applied_at ==
requested_at` 한 틱)이며 이 세션의 변경 전이고 무관하다. 건너뜀 2건은 이행 시험의 옛 스키마 커밋 창. S-031 최종 수치(724·0·2)와
통과 수가 하나 다른 것은 그 흔들림 시험 하나다.

**최종**(모든 변경 뒤, 같은 스크립트): 웹 빌드 성공, 웹 단위 **37**(+6 — `search.test.ts` 5·`address.test.ts` 1), pytest **740 통과·0 실패·2
건너뜀**(15분 29초, 기준선의 실행 수 724 에서 **+16** = `test_conversation_search.py` 5 + `test_start_basis.py` 9 + 브라우저 2; 흔들림 시험은
이 회차에 통과), P1 계약 **18**, "전체 시험 통과". 근거·AC 대조는 [UI-04d 결과](../ui/evidence/UI-04d-results.md) 2·3절.

## 6. 경계

- 검색·선택은 **권한·동의·인수·준수가 아니다.** 진입 검사·예산 강제·확인 지점·게시 규칙·저장소 쓰기 허용은 그대로다
  (`enforcement` 넷 `enforced`, `publish` 는 P5). 포함 선택은 그 저장소의 쓰기 허용을 만들지 않는다 — 작업공간은 여전히 선택·허용
  검사(`request_workspace`)를 지나고 실행은 `_check_workspace` 그대로다.
- 원문 경계 그대로 — 검색어·발췌·파일 목록은 제어부 메모리에만 있고 DB·로그에 없다. 서버 필드 일치는 이미 서버에 있던 짧은
  값(제목·요약·사유·규칙 요약)이다. 본문·본문 인덱스는 PC 에 남는다(색인 없음).
- 원래 폴더는 어떤 경로에서도 바뀌지 않는다 — 스냅샷 커밋은 객체 저장소에 더해질 뿐 브랜치·HEAD·인덱스·작업 트리는 그대로다.
- 소급 없음 — 옛 작업공간 행은 `start_basis` NULL(기록 없음)이며 이미 준비된 작업공간은 다시 묻지 않는다.
- 스키마 v27 — 컬럼 여덟, 새 표 없음, 재구성 없음.

## 9. 알려진 한계·설계 선택

- **본문 검색에 색인이 없다.** 후보 상한(2,000건)까지 선형으로 읽는다. 큰 프로젝트에서 느리면 PC 쪽 색인을 그때 둔다.
- **낱말 AND 일치뿐이다.** 정규식·형태소·유사어는 없다. 한글 조사가 붙은 낱말은 부분 문자열로 잡힌다(`검색을` 은 `검색` 에 잡힌다).
- **서버 필드의 "요약" 은 본문이 아니다**(UI-01 규칙). 오프라인 검색은 제목·규칙·개정 사유·업무화 요약·결정 종류에서만 찾는다.
- **여러 PC**: 소유 PC 별로 후보를 나눠 연결된 PC 만 검색하고 나머지는 제외 수로 보인다. 지금 운영은 한 Runner 다(DEVELOPMENT 9절).
- **선택은 이진이다.** 파일별 포함은 경로가 브라우저→서버→PC 로 오가야 해 첫 버전에 없다 — 필요해지면 그 경로의 경계를 정한다.
  **사용자 확인(2026-09-24, 작업 보고 뒤): 이진 선택 그대로 둔다.**
- **포함은 HEAD 기준에서만.** 다른 브랜치·커밋 기준(`base_ref`)은 기존 API·관리 화면으로 고르고 그때는 커밋된 코드에서만 시작한다.
  새 화면에 ref 변경 입력은 없다(작업공간 절이 기준을 보인다).
- **후속 Case 의 기준 제안(D-77 "이전 업무 결과를 기준으로")은 넣지 않았다.** 후속 대화(P4-05)의 작업공간도 HEAD 기준이다 — 이전
  Case 브랜치를 기준으로 제안하려면 그 브랜치의 미커밋 포함 여부·경로 규칙을 함께 정해야 해 별도 작업이다(인계에 적는다).
- **목록은 메모리다.** 제어부 재시작·30분 뒤에는 카드가 "다시 불러온다" 를 보이고 사람이 누르면 PC 가 다시 관측한다.
- **스냅샷 커밋은 브랜치의 첫 커밋으로 남는다.** 이후 push·PR(P5)에 그대로 따라간다 — 감추지 않는다.
- **`.gitignore` 된 파일은 포함되지 않는다**(`add -A` 규칙). 그것은 사용자의 미커밋 변경 목록에도 없다(`status --porcelain` 규칙 그대로).
