# P3-R2 Repository·작업공간 — 실행 결과

수행일: 2026-09-21. 계획: [`P3-PLAN-R2`](../../plans/P3-PLAN-R2.md).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험과 실제 코딩 CLI 실행을 구분하고,
검증하지 않은 항목은 10절에 미검증으로 남긴다. R1이 만든 기록 모델 위에 **실행과
강제**를 붙인 단계이며, 무엇이 강제로 바뀌고 무엇이 여전히 기록뿐인지를 5절에
명시한다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P3-R1과 동일 |
| 셸 | PowerShell 7 / Git Bash | 〃 |
| Python(고정) | 3.12.10 — 저장소 로컬 `.venv` | `.venv\Scripts\python.exe --version` |
| Node / npm | v22.15.1 / 10.9.2 | `npm run build` 출력 |
| Git | 2.52.0.windows.1 | `git --version` |
| 제어부 스키마 | **v9** | `GET /api/health` → `schema_version=9` |
| Codex CLI | **codex-cli 0.154.0** | Runner 기동 시 능력 보고 |
| Claude Code | 설치돼 있으나 **이번 작업에서 실행하지 않음** | 10절 |
| OpenCode | **없음** | P1-04와 같음 |

라이브 실행 데이터는 `%LOCALAPPDATA%\Temp\hads-p3-r2-live` 에 두어 저장소 `var\` 와
기존 증거를 건드리지 않았다. CLI에 노출한 작업공간도 같은 곳의 **별도 임시 git 저장소
두 개**이며 **이 설계 저장소를 CLI에 쓰기로 노출하지 않았다.** 실행 권한은
`read_only` 였다.

## 2. 만든 것

R1은 저장소 선택·쓰기 허용·게시 허용을 **기록**했다. 실행은 여전히 P3-03의 가정 위에서
돌았다 — Case당 작업공간 하나, 저장소 하나, 경로는 `project.repo_path`.

R2는 그 위에 실행을 붙였다.

| 만든 것 | 무엇이 달라졌나 |
|---|---|
| `case_workspace` 를 `(case_id, repository_id)` 키로 재구성 (스키마 v9) | 한 Case 가 저장소마다 브랜치·worktree·시작 기준·사용자 트리 관측을 따로 갖는다(D-39) |
| 허용 판정(`resolve_code_repository`) | 미선택·명시 제외·쓰기 미허용·기록 저장소에 **작업공간이 만들어지지 않는다** |
| 허용 내 자동 추가(`auto_select_repository`) | 이미 가진 범위 안이면 자동 기록, 넓히면 사유와 함께 거절(D-38·D-63·D-64) |
| `run.repository_id` 와 배정 해석 | 실행이 **자기 저장소의** worktree 에서 돈다. 모호하면 고르지 않고 거부한다 |
| 코드 조합(`code_composition`) | `Repo ID → 정확한 스냅샷 참조` 의 벡터로 검증 대상을 고정한다(2.1절) |
| 근거·후보의 조합 참조 | 그 근거가 아직 유효한지를 **저장소별로** 도출한다 |
| Runner 의 저장소별 worktree 경로 | `worktrees/{case}/{repo}`. 기록된 경로가 있으면 그 자리를 다시 쓴다 |
| 실행 효과의 트리 지문 | HEAD 가 같은 두 시점의 미커밋 상태를 구별한다. **해시이며 본문이 아니다** |
| 화면 | 저장소별 작업공간·허용 출처·부분 준비·조합·통합 미검증 표시 |

### 저장소별로 따로 세는 이유

사용자의 미커밋 변경 관측(`user_tree_dirty` · `user_tree_entries`)은 저장소마다
따로 남는다. 합쳐서 세면 "두 저장소 중 어느 쪽을 보존했는가"를 답할 수 없고, 한
저장소만 확인하는 시험은 "두 번째 저장소는 정리해도 된다"를 조용히 통과시킨다.

### 허용 출처를 기록에 남기는 이유

P3-03까지의 Case 는 선택 기록 없이 Project 의 단일 저장소에서 실제로 작업했다. 거기에
"선택 기록이 없으니 쓰기 금지"를 적용하면 **새 정책을 기존 권한에 소급 적용하는 것**
이다(DEVELOPMENT.md 3절). 그래서 허용하되 `allowance_source` 에 그 사실을 남긴다 —
`implicit_single_repository` 는 "선택했다"가 아니라 "선택 기록 없이 이행된 Case 다".
선택 기록이 **하나라도** 있으면 판단이 있었던 Case 이므로 없던 가정을 씌우지 않는다.

### 자동 추가가 넘지 못하는 세 경계

D-38의 "허용 안의 저장소는 자동 선택"과 "명시 제외·새 권한·제품/데이터 영향은
재판단"은 같은 문장의 앞뒤다. 앞만 구현하면 자동 추가가 권한 확대 경로가 된다.

| 경계 | 사유 코드 |
|---|---|
| 명시 제외한 저장소 | `repository_explicitly_excluded` |
| 쓰기 허용이 하나도 없는 Case 에 쓰기 부여 | `auto_add_needs_new_permission` |
| 게시 허용을 함께 부여 | `auto_add_cannot_grant_publish` (D-64) |

거절은 **거절로 끝난다.** 질문을 자동으로 만들지 않는다 — 질문 생성과 누적 material
delta 판단은 R4의 몫이고, 여기서 반쯤 만들면 R4가 붙일 자리가 이미 차 있게 된다.
그리고 `auto_in_allowance` 를 **명시 선택 경로로 적을 수 없다**. 출처만 바꿔 쓸 수
있으면 허용 검사를 우회해 자동 추가가 새 권한을 만든다.

## 3. 스키마 v9와 이행

`case_workspace` 는 SQLite 에서 기본 키를 바꿀 수 없어 표를 다시 만들어 옮겼다. 그
과정에서 셋 중 하나라도 어기면 기록이 거짓이 된다.

| 지킨 것 | 어겼을 때 |
|---|---|
| 기존 행을 잃지 않는다 | "어떤 코드 위에서 시작했는가"의 답이 사라진다 |
| worktree 경로를 새 규칙으로 바꾸지 않는다 | 이미 그 worktree 에서 한 작업이 떨어져 나가고, 남은 브랜치는 다음 준비에서 남의 것으로 보인다 |
| 어느 저장소인지 지어내지 않는다 | 한 저장소의 기준 커밋이 다른 저장소의 것으로 기록된다 |

이행은 등록 저장소가 **정확히 하나**일 때 그것에 연결하고, 여럿이면 Runner 가 보고한
`repo_path` 가 일치하는 것만 쓴다. 둘 다 아니면 **이행을 멈춘다** — 반쯤 옮긴 상태를
준비됨으로 표시하지 않는다.

새 축은 미기록으로 남는다. `run.repository_id` 는 NULL 이고 그것은 "주 저장소"가 아니라
**기록되지 않음**이며, 작업공간이 하나뿐일 때만 모호하지 않아 해석한다.

## 4. 코드 조합

조합은 **이미 있는 기록에서 만든다.** 새 관측을 요구하지 않는다.

- 실행이 관측한 저장소: `source = run_effect`. HEAD·미커밋 수·트리 지문까지 고정된다
- 관측이 없는 저장소: `source = workspace_base`, `snapshot_incomplete = true`.
  **기준 커밋만으로 실제 입력을 설명할 수 없다**는 사실을 빈칸이 아니라 값으로 남긴다

같은 상태에서 다시 고정하면 새 revision 을 만들지 않는다. 달라지면 새 revision 이
생기고 이전 것은 `superseded` 로 남는다 — 지우지 않는 이유는 "그때 무엇을 검증했는가"가
남아야 하기 때문이다.

유효성은 **저장하지 않고 도출한다**(P3-03의 `unexpected_external_change` 와 같은 이유).
그리고 **저장소별로** 본다 — 조합에 들어 있지 않은 저장소가 바뀐 것은 이 근거와
무관하며, 그것으로 증거를 폐기하면 두 저장소 Project 에서 어느 근거도 오래 살아남지
못한다(2.1절 "무관한 Repo 변경으로 모든 증거를 폐기하지 않는다").

조합이 이 Case 의 코드 대상을 전부 담지 않으면 `integration_verified = false` 다.
**개별 저장소 검사가 모두 통과해도 통합 조건을 충족했다고 자동 추정하지 않는다.**

## 5. 무엇이 강제가 되고 무엇이 아직 기록인가

R1 결과 문서의 같은 표가 여기서 한 줄 바뀐다.

```
autonomy               recorded_not_enforced  → P3-R4
controlled_checkpoint  recorded_not_enforced  → P3-R4
budget                 recorded_not_enforced  → P3-R3
repository_selection   enforced               → P3-R2   ← 이 단계에서 바뀌었다
publish                not_implemented        → P5
```

`repository_selection` 이 `enforced` 다. 선택과 쓰기 허용이 작업공간을 만들 수 있는지를
실제로 정한다. **게시 허용은 여전히 기록일 뿐이고** 실제 push·PR·기록 이슈는 P5 다 —
쓰기 허용이 게시 허용으로 번지지 않는다(D-64).

R1이 "강제가 없다"를 고정해 둔 시험(`tests/test_policy.py`)을 **갱신했다.** 그 시험이
갱신되지 않은 채 통과했다면 강제를 붙이지 않은 것이며, 실제로 처음 전체 시험을 돌렸을
때 그 시험은 `enforced_by` 만 보고 있어서 통과했다 — 그래서 `state` 를 함께 보도록
고쳤다.

## 6. 자동 시험

`scripts\run-tests.ps1` 기준.

| 묶음 | 결과 |
|---|---|
| 제품 시험 (pytest) | **313 통과** (P3-R1 시점 286 → +27) |
| P1 OpenCode 문서 계약 (unittest, CLI 미실행) | **18 통과** |
| 화면 빌드 (`npm run build`) | 성공 (tsc + vite) |

새로 더한 시험.

| 파일 | 무엇을 본다 |
|---|---|
| `tests/test_repositories.py` (23건) | 저장소별 작업공간·dirty 보존, 네 가지 거부 사유, 자동 추가와 세 경계, 대상 저장소 해석, 부분 준비 실패, 경합, 조합·통합·stale |
| `tests/test_migration.py` (+1건) | v8 → v9. 브랜치·기준 커밋·worktree 경로·사용자 트리 관측 보존, 허용 출처 표시, 반복 실행 |
| `tests/test_data_boundary.py` (+2건) | 조합 표의 본문 컬럼 없음, **두 번째 저장소의** 변경 본문이 제어부에 오지 않음 |
| `tests/test_restart_recovery.py` (+1건) | 저장소별 작업공간과 조합이 강제 종료 후 복원 |

갱신한 시험.

| 파일 | 왜 |
|---|---|
| `tests/test_policy.py` | `repository_selection` 이 `enforced` 로 바뀌었다. **이 갱신이 R2가 실제로 강제를 붙였다는 증거다** |
| `tests/test_workspace.py` | worktree 경로가 `{case}/{repo}` 가 됐다. 시험이 옛 자리를 붙잡으면 실제 대상 경로가 비어 준비가 성공하고 "덮어쓰지 않는다"가 확인되지 않는다 |
| `tests/test_restart_recovery.py` | 작업공간 조회가 저장소별 목록이 됐다 |
| `tests/conftest.py`·`tests/test_preparation.py` | 작업공간이 둘 이상인 Case 에서는 읽기 전용 실행도 대상을 밝혀야 한다(9절) |

## 7. 라이브 검증 — 실제 Runner 프로세스와 실제 git 저장소 두 개

제어부와 Runner 를 **별도 프로세스로** 띄우고, 실제 git 저장소 두 개(`repo-api`·
`repo-ui`)를 만들어 확인했다. 두 저장소 모두 **사용자의 미커밋 변경을 남겨 둔 채**
시작했다.

근거: [`P3-R2-live.log`](P3-R2-live.log) · [`P3-R2-workspaces.json`](P3-R2-workspaces.json)
· [`P3-R2-composition.json`](P3-R2-composition.json)

| 확인한 것 | 결과 |
|---|---|
| 선택 기록 없이 요청 (등록 저장소 3개) | 409 `repository_selection_required` |
| 기록 저장소에 작업공간 요청 | 409 `journal_repository_not_a_code_target` |
| 선택했으나 쓰기 미허용 | 409 `repository_not_selected_for_code` |
| 쓰기 허용 후 요청 | 201, 허용 출처 `case_repository` |
| 허용 안의 UI 저장소 자동 추가 | 201, 출처 `auto_in_allowance`, 쓰기 1 / **게시 0** |
| 실제 Runner 가 만든 worktree | 두 저장소가 **서로 다른 경로**, 각각 `reader.py` / `view.py` |
| 기준 커밋 | 각 저장소의 **실제 HEAD** 와 일치 (`78f0b3ded3` / `9fb1e5ceb4`) |
| 사용자 dirty tree | 두 저장소 모두 `git status --porcelain` 이 시작 때와 **완전히 동일** |
| 코드 조합 | 두 저장소의 실제 SHA 를 담고 기록 저장소는 들어가지 않음. 같은 상태 재고정 시 같은 revision |
| 제외 + 기록 저장소 자동 추가 | 409 |
| 정책 조회의 강제 표시 | `repository_selection: enforced (P3-R2)`, `publish: not_implemented (P5)` |

`user_tree_dirty` 는 API 저장소 2건 · UI 저장소 1건으로 **따로** 관측됐고, 준비 뒤에도
`reader.py` 의 사용자 수정과 두 저장소의 미추적 메모 파일이 그대로 있었다.

### 7.1 실제 codex 실행이 지정한 저장소에서 도는가

자동 시험은 가짜 실행기로 배정 경로를 본다. 여기서 확인한 것은 그것이 아니라
**실제 CLI 프로세스가 어느 디렉터리 안에서 돌았는가** 다.

근거: [`P3-R2-live-run.log`](P3-R2-live-run.log) ·
[`P3-R2-run-ledger.json`](P3-R2-run-ledger.json) ·
[`P3-R2-cli-answer.txt`](P3-R2-cli-answer.txt)

두 저장소에 작업공간을 만든 Case 에서, "이 작업 디렉터리에 어떤 파일이 있는지 한 줄로
알려 달라"는 지시로 `read_only` 실행을 두 번 요청했다.

| 요청 | 결과 |
|---|---|
| 대상 저장소를 **밝히지 않은** 읽기 실행 | 409 `workspace_target_not_recorded` — 실행이 만들어지지 않았다 |
| 대상을 **UI 저장소로 밝힌** 읽기 실행 | 201 → `outcome=completed`, `exit=0`, `repository_id` 가 UI 저장소, 관측 버전 `codex-cli 0.154.0` |

**결정적 증거는 CLI 자신의 답이다.**

```
작업 디렉터리에는 `.git` 폴더와 `view.py` 파일이 있습니다.
```

`view.py` 는 **UI 저장소**의 파일이다. API 저장소에는 `reader.py` 가 있다. 실제 codex
프로세스가 지정한 저장소의 worktree 안에서 돌았다는 뜻이며, 경로 문자열 비교가 아니라
CLI 가 실제로 본 파일 목록이 그것을 말한다.

실행 뒤에도 두 저장소의 사용자 작업 트리는 시작 때와 동일했다.

**읽기 전용 실행은 `workspace_effect` 를 남기지 않는다.** 그래서 이 실행 뒤에도 조합의
UI 항목은 `workspace_base` · `snapshot_incomplete = true` 로 남았다 — 읽기만 한 실행을
"관측했다"로 올리지 않는 것이 맞다. 조합이 `run_effect` 로 채워지는 경로는 자동
시험(`tests/test_repositories.py`)이 실제 git 저장소와 변경을 만들어 확인한다.

## 8. 데이터 경계 (바이트 검사)

`tests/test_data_boundary.py` 가 제어부 DB·로그의 **바이트 전체**를 훑어 표식 문자열이
없는지 본다. R2에서 새로 확인한 것 둘.

- `code_composition`·`code_composition_entry` 에 본문 컬럼이 없다
- **두 번째 저장소의** 변경 본문·파일 경로가 제어부에 오지 않는다. 대신 올라오는 것은
  트리 지문(sha256 64자)과 수다

트리 지문이 경계에 가장 가깝다. 그것은 작업 트리 내용의 **해시**이며
`artifact_ref.content_hash` 와 같은 성격이다 — 파일 경로도 diff 본문도 아니다. 지문이
없으면 HEAD 가 같은 두 시점의 미커밋 상태를 구별할 수 없어 "무엇을 검증했는가"를 커밋
하나로만 말하게 된다.

## 9. 검토·시험 중 발견해 고친 것

| 무엇 | 왜 문제인가 | 어떻게 고쳤나 |
|---|---|---|
| **강제를 붙였는데 "강제가 없다" 시험이 그대로 통과했다** | `tests/test_policy.py` 가 `enforced_by` 만 보고 `state` 를 보지 않았다. R1이 "R2가 붙일 때 갱신해야 한다"고 남긴 시험이 **갱신 없이 통과**했고, 그러면 그 시험은 경계를 지키지 못한다 | 네 축 모두 `state` 를 함께 보도록 고쳤다. `repository_selection` 은 `enforced`, `publish` 는 `not_implemented` |
| **읽기 전용 실행이 조용히 사용자의 원래 저장소로 떨어졌다** | 대상 저장소 검사를 쓰기에만 걸었더니, 작업공간이 둘인 Case 에서 대상을 밝히지 않은 읽기 실행의 배정이 `project.repo_path` 로 내려갔다. 설계·검토를 쓰는 실행이 이 Case 가 만들고 있는 코드가 아니라 **사용자의 다른 작업**을 읽는다 — 틀린 코드를 읽은 검토는 거부된 검토보다 나쁘다 | 대상 검사를 권한과 무관하게 적용했다. 작업공간이 하나뿐이면 모호하지 않으므로 아무 것도 하지 않는다 — 이 검사가 무는 것은 저장소가 둘 이상인 Case 뿐이고 그런 Case 는 R2 이전에 없었다. 시험 1건 추가 |
| 준비 실패 후 재요청이 worktree 자리를 옮겼다 | Runner 가 경로를 매번 새로 계산하면 이행된 작업공간(P3-03 자리)이 다음 준비에서 새 자리로 옮겨지고, 남은 브랜치는 `FOREIGN` 으로 보여 거부된다 | 요청 payload 에 기록된 `worktree_path` 를 실어 보내고 비어 있지 않으면 그 자리를 다시 쓴다 |
| 두 저장소 실행이 서로를 "예상 못한 외부 편집"으로 보았다 | `workspace_view` 가 실행 효과를 한 줄로 이어 비교했다. A 저장소 실행 뒤에 온 B 저장소 실행이 전부 `unexpected_external_change` 가 된다 | 저장소별로 나눠 직전 상태를 비교한다. 대상이 기록되지 않은 실행은 **아무 저장소에도 붙이지 않고** 따로 보인다 |
| 조합 조회가 새 조합을 만들 뻔했다 | 조회가 상태를 고정하면 근거가 가리키는 조합이 손 없이 바뀐다 | 조회는 `matches_current_state` 로 다르다는 사실만 말하고, 고정은 명시적 POST 로만 한다 |
| **코드 대상이 늘어도 옛 조합이 `integration_verified = true` 로 남았다** | 같음의 기준을 항목 지문으로만 두었다. 작업공간이 늘지 않고 **선택만** 늘면 항목도 지문도 그대로여서 같은 조합이 돌아오는데, 그때 이 Case 의 코드 대상은 이미 늘어 있다 — 담지도 않은 저장소의 통합이 검증됐다고 말하게 된다 | 통합 범위(`covers_all_code_repositories`)를 같음의 기준에 넣었다. 범위가 달라지면 같은 지문이어도 새 revision 이 생기고 이전 것은 `superseded` 로 남는다. 시험 1건 추가 |

## 10. 라이브로 하지 않은 것

- **쓰기 실행의 라이브 전 과정.** 라이브에서는 읽기 전용 실행까지 확인했다. 쓰기를
  여는 데 필요한 설계·계획·작업 그래프 전체는 P3-03·R1이 라이브로 확인한 경로이며,
  R2가 새로 바꾼 것은 **어느 디렉터리에서 CLI 가 도는가** 다. 두 저장소의 쓰기 실행
  전 과정은 P3-04의 몫이다.
- **Claude Code 실행.** 이번 작업에 의미 검토 실행이 없었다. 라이브 게이트는
  `not_run` 으로 남았다.
- **브라우저 조작·화면 캡처.** `npm run build` 와 화면 문구 검토까지만 했다. P3-03에
  쓴 Playwright 환경을 이 세션에서 다시 설치하지 않았고, 화면 없이도 같은 검사를
  서버가 한다는 것은 자동 시험이 본다.
- **기존 v8 DB의 실제 사용자 데이터 이행.** 시험이 만든 v8 DB로 확인했다. 이 저장소에는
  라이브용 임시 DB만 있었고 보존해야 할 운영 DB가 없었다.
- **실제 push·PR·기록 이슈 게시.** P5 이며 이 단계에서 구현하지 않았다. 게시 허용은
  기록일 뿐이라는 표시가 그대로 남아 있다.
- **두 Case 가 같은 원격 ref 를 갱신하는 경합.** 원격이 없으므로 확인할 수 없다(P5).

## 11. 남은 위험

- **한 실행은 작업공간 하나에서 돈다.** 여러 저장소를 **함께 읽어야** 하는 실행
  (예: 두 저장소를 아우르는 설계 작성)은 지금 한쪽을 골라야 한다. 조합은 여러 저장소를
  담지만 실행의 작업 디렉터리는 하나다. 이 한계는 R4/P3-04에서 다시 본다.
- **조합의 변화는 관측으로만 안다.** 제어부는 git 을 보지 않으므로, 실행이 없는
  저장소의 작업 트리가 움직여도 조합은 그것을 모른다. 그 상태는
  `snapshot_incomplete` 로 표시되지만 "모른다"이지 "안 바뀌었다"가 아니다.
- **`run.repository_id = NULL` 인 옛 실행.** 작업공간이 하나뿐인 Case 에서는 그것으로
  해석하지만, 저장소가 나중에 늘어나면 그 옛 실행들은 조합의 어느 항목에도 붙지
  않는다. 화면이 `unattributed_run_effects` 로 드러내며 지어내지 않는다.
- **worktree 는 여전히 OS 격리가 아니다**(D-44). 저장소가 늘어도 그대로다. 경계 밖
  변경은 감지해 드러낼 뿐 막지 못한다.
- **게시 허용은 아직 아무 것도 막지 않는다.** `publish_allowed` 는 기록이고 실제
  push·PR 은 P5 다. 쓰기가 강제로 바뀌었다고 게시도 그런 것처럼 읽지 않는다.
- **예산·Autonomy 는 그대로 기록뿐이다.** R3·R4 가 붙인다. `tests/test_policy.py` 의
  나머지 세 축 시험이 그 경계를 계속 고정한다.
- **`project.repo_path` 가 아직 남아 있다.** 정본은 `project_repository` 이며 조회가
  불일치를 드러내지만, 컬럼 자체를 지우는 것은 이 단계의 범위가 아니다.

## 12. 외부 전송·남은 자원

- 외부로 보낸 것은 **codex 실행**이며 그 전송은 codex 의 기존 사용자 설정을 따른다.
  노출한 작업공간은 임시 저장소의 worktree 이고 권한은 `read_only` 였다.
  **이 설계 저장소를 CLI 에 쓰기로 노출하지 않았다.**
- push·PR·이슈 게시는 하지 않았다. 이 단계에 그 기능이 없다.
- 라이브 제어부·Runner 프로세스는 종료했다. 라이브 데이터는
  `%LOCALAPPDATA%\Temp\hads-p3-r2-live` 에 남아 있고 저장소 `var\` 는 건드리지 않았다.
  증거 사본은 `p3/evidence/P3-R2-*` 에 있다.
