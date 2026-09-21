# P3-PLAN-R2

Repository·작업공간. 기준: 설계 v0.7 / D-01~67 / 2026-09-21.
선행: P3-R1 완료(스키마 v8, pytest 286 + P1 계약 18 통과). 다음: [P3-R3 예산](../DEVELOPMENT.md).

## 1. 이 작업이 답해야 하는 것

R1은 **Project 등록 저장소와 Case의 선택·쓰기허용·게시허용을 기록**했다. 기록만 했다.
지금 조회의 `enforcement.repository_selection` 은 `recorded_not_enforced / P3-R2` 이고,
`tests/test_policy.py` 가 그 사실을 시험으로 고정해 두었다. 실제 실행은 여전히
P3-03의 가정 위에서 돈다 — **Case당 작업공간 하나, 저장소 하나, 경로는
`project.repo_path`**.

R2는 그 위에 실행을 붙인다. 세 가지다.

1. **작업공간이 `Case × Repository` 가 된다.** 저장소마다 전용 브랜치·worktree·시작
   기준을 갖고, 저장소마다 사용자의 원래 dirty tree를 따로 보존한다(D-39).
2. **선택·쓰기허용이 실제로 무엇을 막는다.** 선택되지 않은 저장소, 명시 제외한
   저장소, 기록 저장소에는 작업공간이 만들어지지 않는다. 허용 안의 추가는 자동으로
   기록되고, 허용 **밖**은 자동으로 넓히지 않고 사람에게 되돌린다(D-38·D-63).
3. **증거가 코드 조합을 가리킨다.** `Repo ID → 정확한 스냅샷 참조`의 벡터를 고정하고,
   개별 Repo 통과를 통합 통과로 자동 승격하지 않는다(execution-workspace-review 2.1절).

가장 위험한 것은 1번의 **이행**이다. `case_workspace` 는 지금 `case_id` 가 기본 키이고
이미 준비된 작업공간 행이 거기 있다. 키를 바꾸면서 그 행을 잃거나, 그 행이 어느 저장소의
것인지 지어내면 "어떤 코드 위에서 시작했는가"의 답이 사라진다. 그래서 이 작업의 성공
기준에는 **기존 단일 저장소 Case가 이행 후에도 같은 worktree·같은 기준 커밋으로
계속 동작한다**가 들어간다.

두 번째로 위험한 것은 2번이 **소급**되는 것이다. P3-03까지의 Case는 선택 기록 없이
Project의 단일 저장소에서 실제로 작업했다. 그 Case에 "선택 기록이 없으니 쓰기 금지"를
적용하면 새 정책을 기존 권한에 소급하는 것이다(DEVELOPMENT 3절). 그 상태는 R1이
`implicit_single_repository` 로 이미 이름 붙여 두었고, R2는 **그 이름을 근거로 허용하되
허용의 출처를 기록에 남긴다.**

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| `case_workspace` 를 `(case_id, repository_id)` 로 재구성, 스키마 v9 이행 | Case를 여러 Runner에 분산 (P6) |
| 저장소별 브랜치·worktree·시작 기준·dirty tree 관측 | OS 수준 격리 보장 (하지 않는다. D-44) |
| 선택·쓰기허용의 강제 — 미선택·제외·기록 저장소의 작업공간 거부 | 게시 허용의 강제, 실제 push·PR (P5) |
| 허용 내 자동 추가(`auto_in_allowance`)와 허용 밖 거절 사유 | 자동 추가가 만든 질문의 대화·재평가 자동화 (R4) |
| 코드 조합(스냅샷 벡터)의 기록·조회와 근거 연결, 통합 미검증 표시 | 누적 material delta 계산 (R4) |
| 실행의 대상 저장소(`run.repository_id`)와 그 작업공간 배정 | Autonomy 기반 자동 실행 경로 (R4) |
| 부분 준비 실패·재시작·경합(같은 Case 직렬 쓰기, 같은 저장소 두 Case) | 예산 예약·정지 (R3) |
| `project_repository` 를 경로의 정본으로 사용, `repo_path` 불일치 표시 | `project.repo_path` 컬럼 삭제 (지우지 않는다) |
| 화면의 저장소별 작업공간·조합·허용 출처 표시 | 실제 수직 통합 기능 개발 (P3-04) |

**진입 조건(FR-29) 판정 규칙은 이번에도 바꾸지 않는다.** 늘어나는 것은 "어느 저장소의
작업공간인가"를 해석하는 부분과 새 사유 하나(`workspace_target_not_recorded`)뿐이다.

## 3. 정책·데이터 영향

| 대상 | R2 이후 새 Case | R2 이전에 만들어진 Case·작업공간 |
|---|---|---|
| 작업공간 | 저장소마다 한 행. `repository_id` 필수 | 기존 행을 **Project의 이행된 저장소 행에 연결**한다. `branch`·`worktree_path`·`base_commit` 은 그대로 |
| worktree 경로 | `worktrees_dir/{case}/{repo}` | **기록된 경로를 그대로 쓴다.** 새 규칙으로 옮기지 않는다 — 옮기면 이미 한 작업이 떨어져 나간다 |
| 쓰기 허용 | `case_repository.code_write_allowed = 1` 필요 | 선택 기록이 하나도 없고 등록 저장소가 하나면 **허용**하고 출처를 `implicit_single_repository` 로 남긴다 |
| 등록 저장소가 둘 이상 + 선택 기록 없음 | **거부**(`repository_selection_required`) | 같음. 단 이미 `ready` 인 작업공간은 그대로 유지된다 |
| 실행의 대상 저장소 | `run.repository_id` | NULL(미기록). `ready` 작업공간이 하나뿐이면 그것으로 해석하고, 둘 이상이면 거부한다 |
| 코드 조합 | 실행 관측에서 만든다 | 관측이 없는 저장소는 `base_commit` 만으로 `snapshot_incomplete` 표시 |

`run.repository_id = NULL` 을 "주 저장소"로 읽지 않는다. 작업공간이 하나뿐일 때만
모호하지 않으며, 둘 이상이면 **지어내지 않고 거부한다**. 어느 저장소를 고쳤는지 모르는
채로 쓰기를 여는 것이 이 단계에서 가장 비싼 실수다.

## 4. 새 표·컬럼 (스키마 v9)

| 표·컬럼 | 답하는 질문 |
|---|---|
| `case_workspace.repository_id` (기본 키 일부) | 이 작업공간은 **어느 저장소**의 것인가 |
| `case_workspace.allowance_source` | 무엇을 근거로 이 작업공간을 만들었나 (`case_repository` / `implicit_single_repository`) |
| `run.repository_id` | 이 실행은 어느 저장소의 작업공간에서 도는가. NULL은 미기록 |
| `code_composition` | 이 시점 Case의 **코드 조합**은 무엇인가 (revision, hash, 생성 시점) |
| `code_composition_entry` | 저장소별 `base_commit` · `head` · 미커밋 수 · 트리 지문 · 관측 출처 |
| `criterion_result.composition_id` | 이 근거는 **어느 조합 위에서** 나왔나 |
| `completion_candidate.composition_id` | 이 후보는 어느 조합을 보여 줬나 |

`case_workspace` 는 SQLite에서 기본 키를 바꿀 수 없으므로 **표를 다시 만들어 옮긴다**
(`CREATE` → `INSERT ... SELECT` → `DROP` → `RENAME`). `migrate()` 는 매 연결마다 돌므로
옛 모양일 때만 수행하고 여러 번 불려도 같은 결과여야 한다.

조합 항목에 들어가는 **트리 지문은 해시**다. 본문이 아니며 `artifact_ref.content_hash`
와 같은 성격이다. 파일 경로·diff 본문은 여전히 Runner에 남는다(D-43·NFR-12).

## 5. 허용 판정 규칙

### 작업공간을 만들 수 있는가

1. 저장소가 이 Case의 Project에 등록돼 있는가 → 아니면 `repository_not_in_project`
2. 기록 저장소인가 → 맞으면 `journal_repository_not_a_code_target`
3. `case_repository` 현재 행이 있는가
   - 있고 `selection_source = excluded` → `repository_explicitly_excluded`
   - 있고 `code_write_allowed = 0` → `repository_not_selected_for_code`
   - 있고 `code_write_allowed = 1` → 허용, 출처 `case_repository`
4. 행이 없다
   - 이 Case에 선택 기록이 **하나도** 없고 등록 저장소가 정확히 하나 → 허용, 출처
     `implicit_single_repository`
   - 그 밖 → `repository_selection_required`

4번의 첫 갈래가 **소급을 막는 지점**이다. 선택 기록이 하나라도 있으면 그 Case는 판단이
있었던 Case이므로 없던 가정을 씌우지 않는다 — R1이 `case_repository_state` 에서 쓰는
규칙과 같다.

### 허용 안에서 자동으로 추가할 수 있는가 (D-38·D-63)

자동 추가는 **이미 가진 것을 넓히지 않을 때만** 성립한다.

| 조건 | 결과 |
|---|---|
| 명시 제외된 저장소 | `repository_explicitly_excluded` — 자동 추가가 넘지 못하는 경계 |
| 기록 저장소 | `journal_repository_not_a_code_target` |
| 게시 허용을 함께 요청 | `auto_add_cannot_grant_publish` (D-64: 쓰기 허용 추가는 게시 허용 확대가 아니다) |
| 쓰기 허용을 요청했는데 이 Case에 쓰기 허용 저장소가 하나도 없다 | `auto_add_needs_new_permission` — 새 권한이다 |
| 이미 `explicit` 로 선택돼 있다 | 바꾸지 않는다. 사람의 선택을 자동 기록으로 덮지 않는다 |
| 그 밖 | `auto_in_allowance` 로 기록. 사유 요약과 주체가 함께 남는다 |

거절은 **거절로 끝난다.** 질문을 자동으로 만들지 않는다 — 질문 생성과 누적 material
delta 판단은 R4의 몫이고, 여기서 만들면 R4가 붙일 자리에 반쯤 된 것이 먼저 있게 된다.
대신 거절 응답에 `requires_human_confirmation` 과 사유를 실어 화면이 그대로 말한다.

## 6. 코드 조합과 근거

조합은 **기존 기록에서 만든다.** 저장소별로 `case_workspace.base_commit` 과 그 저장소에서
끝난 가장 최근 실행의 관측(`head_after` · `entries_after` · 트리 지문)을 합친다.

- 관측이 있는 저장소: `source = run_effect`. HEAD와 미커밋 상태까지 고정된다
- 관측이 없는 저장소: `source = workspace_base`, `snapshot_incomplete = true`.
  **기준 커밋만으로 실제 입력을 설명할 수 없다**는 사실을 값으로 남긴다

조합 해시는 항목을 저장소 순으로 정렬해 만든다. 같은 상태에서 다시 만들면 같은 조합을
돌려주고(새 revision을 만들지 않는다), 달라지면 새 revision이 생기고 이전 것은
`superseded` 가 된다.

근거(`criterion_result`)는 조합을 참조할 수 있다. 조회는 두 가지를 **도출**한다.

- `composition_stale`: 그 조합에 **들어 있는** 저장소의 현재 스냅샷이 달라졌는가.
  들어 있지 않은 저장소가 바뀐 것은 stale이 아니다 — 무관한 변경으로 모든 증거를
  폐기하지 않는다(2.1절)
- `integration_covered`: 그 조합이 이 Case의 쓰기 허용 저장소를 **전부** 담았는가.
  아니면 `integration_verified = false` 와 사유를 함께 돌려준다. 개별 통과를 통합
  통과로 자동 승격하지 않는다

저장하지 않고 도출하는 이유는 P3-03의 `unexpected_external_change` 와 같다 — 컬럼으로
두면 "누가 그 값을 적었는가"가 새 문제가 된다.

**후보 확인의 강제는 여기서 하지 않는다.** 후보가 어느 조합을 봤는지는 기록하고, 그 뒤
조합이 바뀌었다는 사실은 조회가 드러낸다. 그것으로 재확인을 **요구**하는 것은 controlled
경로이며 R4다.

## 7. 작업 순서

1. 스키마 v9와 이행 — `case_workspace` 재구성, `run.repository_id`, 조합 표, 근거 컬럼.
   v8 DB로 실제 이행 시험부터 만든다
2. 저장소 정본 이전 — 경로 해석을 `project_repository` 로 옮기고 `project.repo_path` 와의
   불일치를 조회에 표시. 컬럼은 지우지 않는다
3. 허용 판정(5절)과 `request_workspace(case_id, repository_id)` — 거부 사유와 허용 출처
4. 허용 내 자동 추가 API와 거절 사유
5. Runner — 저장소별 worktree 경로, 기록된 경로 재사용, 저장소별 준비 결과 보고,
   실행 효과에 트리 지문 추가
6. 배정·진입 — 실행의 대상 저장소 해석, `workspace_target_not_recorded`, 같은 Case
   직렬 쓰기 유지
7. 코드 조합 만들기·조회와 근거 연결, 통합 미검증 표시
8. 화면 — 저장소별 작업공간·허용 출처·조합·통합 표시
9. **`tests/test_policy.py` 의 "아직 강제하지 않는다" 시험 갱신.** `repository_selection`
   이 강제로 바뀌어야 하고, 바뀌지 않으면 시험이 실패한다
10. 전체 시험·빌드·재시작 복원·실제 git 저장소 두 개로 라이브 확인

## 8. 성공 기준 (AC)

| # | 기준 | 검증 |
|---|---|---|
| AC-1 | v8 DB를 올리면 기존 `case_workspace` 행이 저장소에 연결된 채 남고 브랜치·기준 커밋·worktree 경로가 그대로다 | 커밋 이력의 v8 스키마로 실제 DB를 만들어 이행 |
| AC-2 | 같은 Case가 두 저장소에 각각 브랜치·worktree·기준 커밋을 갖는다 | 실제 git 저장소 2개로 준비 |
| AC-3 | 저장소마다 사용자의 원래 dirty tree를 따로 관측·보존하고 커밋·stash·삭제하지 않는다 | 두 저장소를 서로 다른 dirty 상태로 만들고 준비 후 파일 내용 비교 |
| AC-4 | 미선택·명시 제외·쓰기 미허용·기록 저장소의 작업공간 요청이 각각의 사유로 거부된다 | 네 경우 각각 |
| AC-5 | 선택 기록이 없는 단일 저장소 Case는 계속 동작하고 허용 출처가 `implicit_single_repository` 로 남는다 | 이행된 Case로 요청 |
| AC-6 | 등록 저장소가 둘 이상인데 선택 기록이 없으면 거부한다 | `repository_selection_required` |
| AC-7 | 허용 안의 저장소는 자동 추가되고 `auto_in_allowance` 와 사유가 남는다 | 쓰기 허용이 이미 있는 Case |
| AC-8 | 명시 제외·새 권한·게시 허용 요구는 자동 추가되지 않고 사람 확인을 요구한다 | 세 경우 각각, 사유 코드 확인 |
| AC-9 | 기록 저장소는 지정만으로 어떤 Case의 코드 대상·작업공간에도 들어가지 않는다 | 지정 후 선택·자동 추가·작업공간 요청 모두 거부 |
| AC-10 | 실행이 대상 저장소의 작업공간에서 돈다. 작업공간이 둘 이상인데 대상이 미기록이면 거부한다 | 배정 payload와 진입 검사 |
| AC-11 | 한 저장소의 준비가 실패해도 다른 저장소의 준비는 유지되고, 실패가 준비됨으로 바뀌지 않는다 | 저장소 하나를 없는 경로로 |
| AC-12 | 코드 조합이 저장소별 스냅샷을 고정하고, 관측 없는 저장소를 `snapshot_incomplete` 로 표시한다 | 조합 조회 |
| AC-13 | 조합에 든 저장소가 바뀌면 그 근거가 stale로 드러나고, 들어 있지 않은 저장소의 변경은 근거를 무효로 만들지 않는다 | 두 저장소 중 하나만 변경 |
| AC-14 | 개별 저장소 통과가 통합 통과로 자동 승격되지 않는다 | 일부 저장소만 담은 조합의 `integration_verified = false` |
| AC-15 | 같은 Case의 두 저장소 쓰기가 동시에 배정되지 않고, 서로 다른 Case는 같은 저장소의 각자 worktree를 쓴다 | 기존 `case_write_in_progress` 유지 + 두 Case 준비 |
| AC-16 | 제어부를 강제 종료해도 저장소별 작업공간·조합 기록이 복원된다 | 프로세스 종료 후 재기동 |
| AC-17 | `enforcement.repository_selection` 이 강제로 바뀌고 R1이 고정한 "강제 없음" 시험이 갱신된다. `publish` 는 여전히 `not_implemented` | `tests/test_policy.py` |
| AC-18 | 제어부 DB에 코드·diff·파일 경로 본문이 들어가지 않는다 | `tests/test_data_boundary.py` 바이트 검사 |
| AC-19 | 실제 git 저장소 두 개에서 Runner가 작업공간을 만들고 실행 효과·조합이 관측된다 | 라이브 확인 |

## 9. 복구·인계

- 이 작업은 **기존 작업공간 행을 옮긴다.** 되돌려야 하면 v9 이행 전 DB 사본이 필요하다.
  시험은 임시 경로에서만 돌고 저장소의 `var\` 는 건드리지 않는다
- 이행이 실패하면 `case_workspace` 는 옛 모양으로 남고 R2 기능은 동작하지 않는다.
  **반쯤 옮긴 상태를 준비됨으로 표시하지 않는다**
- 외부 쓰기(push·PR·이슈)는 이 작업에 없다. 커밋·push는 사용자 확인 뒤에만 한다
- R3는 READY로 인계하고 착수하지 않는다

## 10. 수정 기록

**대상 저장소 검사를 쓰기에서 모든 권한으로 넓혔다** (구현 중, AC-10).

계획 5절은 대상 저장소를 "실행의 작업공간 배정" 문제로만 적었고 진입 검사는 쓰기에만
걸 생각이었다. 구현하고 보니 그러면 작업공간이 둘인 Case 에서 **대상을 밝히지 않은
읽기 실행의 배정이 조용히 `project.repo_path` — 사용자의 원래 저장소 — 로 떨어진다.**
설계·검토를 쓰는 실행이 이 Case 가 만들고 있는 코드가 아니라 사용자의 다른 작업을
읽게 되고, 틀린 코드를 읽은 검토는 거부된 검토보다 나쁘다.

그래서 `workspace_target_not_recorded` 를 권한과 무관하게 적용한다. 작업공간이
하나뿐이면 모호하지 않으므로 아무 것도 하지 않으며, 이 검사가 무는 것은 저장소가 둘
이상인 Case 뿐이고 그런 Case 는 R2 이전에 없었다 — 기존 동작의 회귀가 아니다.

딸린 결과: 시험 도우미(`ai_prepare`·`create_run`·`complete_task`·`_prepare_both`)가
`repository_id` 를 받아 넘긴다. 제품 API 는 이미 받고 있었다.

**조합의 "같음"에 통합 범위를 넣었다** (구현 중, AC-14).

6절은 조합 해시를 "항목을 저장소 순으로 정렬해 만든다"로만 적었다. 그러면 작업공간이
늘지 않고 **선택만** 늘었을 때 — 코드 대상 저장소가 추가됐지만 아직 준비되지 않은
상태 — 항목도 지문도 그대로여서 같은 조합이 돌아오고, 그 조합은
`integration_verified = true` 를 단 채 살아남는다. 담지도 않은 저장소의 통합이
검증됐다고 말하는 것이며 AC-14가 막으려던 바로 그 일이다.

그래서 `covers_all_code_repositories` 를 같음의 기준에 넣는다. 범위가 달라지면 같은
지문이어도 새 revision 이 생기고 이전 것은 `superseded` 로 남는다.

**한 실행이 여러 저장소를 함께 읽는 경로는 만들지 않았다.**

조합은 여러 저장소를 담지만 실행의 작업 디렉터리는 하나이며 CLI 도 하나를 받는다.
두 저장소를 아우르는 설계를 쓰려면 지금은 한쪽을 골라야 한다. 이것을 R2에서 풀면
실행 모델 자체를 바꾸게 되므로 한계로 남기고 R4/P3-04에서 다시 본다
([결과 문서 11절](../p3/evidence/P3-R2-results.md)).
