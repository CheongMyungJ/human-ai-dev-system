# P3-03 작업공간·실행 — 실행 결과

수행일: 2026-09-21. 계획: [`P3-PLAN-03`](../../plans/P3-PLAN-03.md).

이 문서는 **실제로 실행한 것만** 적는다. 자동 시험(가짜 실행기)과 실제 코딩 CLI 실행을
구분하고, 검증하지 않은 항목은 9절에 미검증으로 남긴다.

## 1. 실행 환경

| 항목 | 값 | 확인 방법 |
|---|---|---|
| OS | Windows 11 Home 10.0.26200 | P3-02와 동일 |
| 셸 | PowerShell 7 | 〃 |
| Python(고정) | 3.12.10 — 저장소 로컬 `.venv` | `.venv\Scripts\python.exe --version` |
| Node / npm | v22.15.1 | `npm run build` 출력 |
| Git | 2.52.0.windows.1 | `git --version` |
| 제어부 스키마 | **v7** | `GET /api/health` → `schema_version=7` |
| Codex CLI | **codex-cli 0.154.0** | 실행마다 결과에 남은 관측 버전 |
| Claude Code | **2.1.278 (Claude Code)** | 〃 |
| 브라우저 | Microsoft Edge | Playwright `channel="msedge"` |
| OpenCode | **없음** | P1-04와 같음 |

두 CLI 모두 자동 업데이트가 켜져 있어 실행 시점의 관측 버전을 함께 남긴다.
시스템은 두 CLI의 **자격증명을 읽지도 주입하지도 않았다.**

브라우저는 **이 PC에 이미 있는 Edge 를 썼다.** 검증을 위해 브라우저를 내려받지 않았다.

라이브 실행 데이터는 `%LOCALAPPDATA%\Temp\hads-p3-03-live` 에 두어 저장소 `var\` 를
건드리지 않았다. CLI의 작업공간도 같은 곳의 별도 임시 git 저장소(`workspace\`, 파일
`reader.py` 와 `sample.log`)이며 **이 설계 저장소를 CLI에 쓰기로 노출하지 않았다.**

그 임시 저장소에는 **사용자의 미커밋 변경을 일부러 남겨 두었다** — `reader.py` 의 편집
한 줄과 미추적 파일 `user-scratch.txt`. P3-03이 지켜야 하는 첫 번째 기준이 그것을
건드리지 않는 것이기 때문이다.

## 2. 만든 것

**AI가 실제로 코드를 바꾸고, 바꾼 것이 증거로 보인다.**

P3-02까지 `workspace_write` 는 `permission_not_allowed_in_stage` 로 거부됐다. 이유는
"지원하지 않아서"가 아니라 **Case 전용 작업공간과 기준 커밋이 없으면 사용자의 미커밋
변경을 보호할 수단이 없어서**였다(FR-08·FR-26). P3-03은 둘을 함께 열었다.

| 새 이름 | 무엇인가 |
|---|---|
| `case_workspace` | 이 업무는 **어떤 코드 위에서** 어디에 만들어지는가. 준비됐는가 |
| `run_command` | 그 실행이 **무엇을 실제로 실행했고** 어떻게 끝났는가 |
| `run.workspace_effect_json` | v1부터 있던 컬럼. **이번에 처음 채운다** |
| `RunPurpose.VERIFICATION_RUN` | 빌드·테스트를 돌리는 실행. 완료 판정이 구현과 다르다 |
| `workspace_not_ready` · `workspace_failed` · `case_write_in_progress` | 새 거부 사유 |
| `ClaimDeferral.RUNNER_WRITE_SLOT_BUSY` | 거부가 아니라 **미룸** |

### 쓰기 권한은 목적별로, 그리고 조건부로 열린다

전역 목록 하나(`STAGE_ALLOWED_PERMISSIONS`)를 넓히지 않고 **목적별 표**
(`ALLOWED_PERMISSIONS`)로 바꿨다. 하나를 넓히면 의도 초안을 쓰는 실행에도 쓰기가
열리기 때문이다. 그리고 쓰기가 열린 목적이라도 `_check_workspace` 가 준비된 작업공간과
쓰기 경합을 따로 본다.

```text
목적이 구현·검증이 아니다            → permission_not_allowed_in_stage
권한이 explicit_escalated 다         → permission_not_allowed_in_stage
Case 작업공간이 없다/requested 다    → workspace_not_ready
Case 작업공간이 failed 다            → workspace_failed
같은 Case 에 미완료 쓰기 실행이 있다 → case_write_in_progress
```

### 바뀌지 않았으면 완료가 아니다

P3-02가 연 것은 "실행 결과에서 Task 완료를 도출한다"였다. P3-03이 구현 실행 경로를
만들면서 **그 규칙이 위험해지는 지점**이 생긴다 — 아무 것도 바꾸지 않은 실행 하나가
`completed` 로 기록되면 후속 Task 가 증거 없이 전부 열린다.

그래서 완료 판정을 목적별로 엄격하게 했다.

```text
feature_implementation   CLI 정상 종료 + workspace_effect.changed == true → completed
                         변경 없음 → failed (no_workspace_change)
                         관측 없음 → failed (no_workspace_observation)
verification_run         CLI 정상 종료 + 실행한 명령 1건 이상 → completed
                         명령 없음 → failed (no_command_executed)
```

**종료 코드가 0이 아닌 명령도 완료다.** "테스트가 실패했다"와 "검증을 수행하지
못했다"는 다른 것이고, 전자는 기준 판정의 입력이다.

그리고 골격 실행기(`local-echo`)는 구현·검증에 **배정되지 않는다**(`NEEDS_CODING_CLI`).
그것은 코드를 고치지도 명령을 실행하지도 않으면서 정상 종료하기 때문이다.

### 격리라고 하지 않는다

worktree 는 파일 배치의 분리이며 OS 격리가 아니다(D-44). 이 단계가 할 수 있는 것은
**감지해 드러내는 것**뿐이다.

| 능력 | 상태 |
|---|---|
| `os_level_isolation` | **`unsupported`** — "worktree 는 파일 배치 분리이며 OS 격리가 아니다" |
| `workspace_change_detection` | `verified` — 실행 전후 HEAD·작업 트리 대조 |

화면의 한계 문구도 **서버가 준 값**(`isolation_note`)을 그대로 보인다. 화면이 지어내면
언젠가 "격리됨"으로 바뀐다.

## 3. 자동 시험

`scripts\run-tests.ps1` → **pytest 242 passed** + P1 OpenCode 문서 계약 unittest 18 OK.

| 파일 | 건수 | 본다 |
|---|---|---|
| `tests/test_workspace.py` (신규) | 34 | 작업공간 생성·충돌·사용자 트리 보호·권한 개방 조건·완료 판정·경합·경계 밖 변경 |
| `tests/test_data_boundary.py` (추가 3) | — | diff·파일 경로·명령 원문·빌드 로그가 제어부 바이트에 없음 |
| `tests/test_ai_draft.py` (추가 1) | — | 지시문이 "이 실행의 제약"과 "산출물의 내용"을 갈라 적는가 |
| `tests/test_migration.py` (확장) | — | v6 → v7 이행에서 기존 행 보존, 없던 값 안 지어냄 |
| `tests/test_restart_recovery.py` (추가 1) | — | 작업공간·기준 커밋·실행 효과·명령 기록의 강제 종료 복원 |

**`tests/test_workspace.py` 는 git 을 진짜로 쓴다.** worktree 가 사용자의 원래 트리를
건드리지 않는다는 것은 흉내로 확인할 수 없기 때문이다. 다만 코딩 CLI 는 계속 가짜다
(`FakeCliExecutor`) — 자동 시험은 결정적이어야 하고 외부 계정을 쓰지 않는다.

P3-02까지 "쓰기는 거부된다"를 고정하던 시험 3건은 **새 경계로 옮겼다.** 사유가
`permission_not_allowed_in_stage` 에서 `workspace_not_ready` 로 바뀐다 — 권한은
열렸고 작업공간이 없을 뿐이다.

## 4. 라이브 검증 — 실제 CLI로 코드 변경

`%LOCALAPPDATA%\Temp\hads-p3-03-live` 에서 제어부(127.0.0.1:8773)와 Runner를 **별도
프로세스로** 띄우고 실제 CLI를 불렀다.

### 4.1 QG-01 이 AI 초안을 두 번 막고 세 번째에 통과시켰다

P3-03의 주제는 작업공간과 실행이지만, 거기 닿으려면 의도 동의를 지나야 한다.
**게이트는 라이브에서 실제로 막았다.**

| 회차 | 판정 | 무엇을 지적했나 |
|---|---|---|
| 1차 | `fail` (6건) | 접두사 매칭 해석을 **질문 없이 확정 기준으로** 적었다 / 실행 환경을 질문에 올리지 않았다 / **지시문의 제약("코드를 바꾸지 마라")을 의도의 `constraints` 에 `user_requirement` 로 적어 목표와 충돌한다** |
| 2차 | `fail` (5건) | 이번에는 반대로 **확인 가능한 사실까지 질문으로 넘겼다.** 그리고 1차의 제약 충돌이 그대로 남았다 |
| 3차 | **`pass`** (권고 2건) | — |

**게이트를 느슨하게 만들지 않았다.** 제품이 설계한 복구 경로(피드백 → 새 버전 →
재검토)를 그대로 세 번 돌았다.

1차 지적 중 하나는 **우리 지시문의 결함**이었다. `INTENT_AUTHORING_PROMPT` 는
"코드를 바꾸지 말고 파일도 만들지 마라"고 적는데, 그것은 **그 실행에만 걸린 규칙**이지
개발할 기능의 제약이 아니다. codex 가 그것을 의도 문서에 옮겨 적었고 별도 세션의
Claude 가 "함수를 추가한다는 목표와 정면으로 충돌한다"고 막았다. 지시문을 고쳐
둘을 갈라 적었다(10절 결함 1).

**이 과정에서 드러난 우리 검증 도구의 결함도 적어 둔다.** 처음 두 번의 재작성은
피드백이 접수되지 않은 채(요청에 대상 의도 버전이 빠져 422) 돌았고, 그래서 AI는
**무엇을 고치라는 것인지 모른 채** 다시 썼다. 드라이버가 응답 코드를 확인하지 않은
탓이며 제품의 문제가 아니다. 다만 **시스템도 그것을 알려 주지 않았다** — 게이트가
막은 직후의 재작성에 반영할 피드백이 하나도 없다는 사실은 어디에도 표시되지 않는다
(11절 위험 3).

### 4.2 실제로 실행한 CLI

| Run | 목적 | 도구 | 권한 | 결과 |
|---|---|---|---|---|
| `run-intent-1` · `-2` · `-3` | 의도 초안·재작성 | **codex-cli 0.154.0** | read_only | `completed` |
| `run-gate-1` · `-2` · `-3` | QG-01 의미 검토 (별도 세션) | **Claude Code 2.1.278** | read_only | `completed` |
| `run-intent-2-…` · `-3-…` | 피드백을 받은 재작성 | codex-cli | read_only | `completed` |
| `run-gate-2-…` · `-3-…` | 재검토 | Claude Code | read_only | `completed` — **3차에서 `pass`** |
| `run-design-…` | 설계안 작성 | Claude Code | read_only | `completed` |
| `run-plan-…` | 개발계획 작성 | codex-cli | read_only | `completed` — **그래프 6 Task** |
| `run-t1-…` | T1 조사 (제한 작업) | Claude Code | read_only | `completed` → T1 `done` |
| **`run-t2-impl-…`** | **T2 기능 구현** | **Claude Code** | **`workspace_write`** | **`completed` — 코드가 실제로 바뀌었다** |
| **`run-t3-verify-…`** | **T3 검증 실행** | **codex-cli** | **`workspace_write`** | **`completed` — 명령 12건** |
| `run-nochange-…` | 변경 없는 구현 시도 | Claude Code | `workspace_write` | **`failed`** — 아무 것도 바꾸지 않았다 |

합계 **16회**(codex 8, Claude Code 8). 전 구간 기록은 [P3-03-live.log](P3-03-live.log)에 있다.

### 4.3 Case 작업공간이 만들어졌다 (AC-1)

```text
[작업공간] 요청 status=201 state=requested
[작업공간] state=ready branch=hads/case-7398b5fb3ff31707
[작업공간] base_commit=95646c0d27db2d15d78122b96583a29a14c3b1ef
[작업공간] worktree=...\hads-p3-03-live\runner\worktrees\case-7398b5fb3ff31707
[작업공간] 사용자 미커밋=True (2건)
```

`requested` 와 `ready` 가 **다른 상태로 지나갔다.** 요청 직후에는 브랜치도
worktree 도 없었고, 저장소를 가진 Runner 가 만든 뒤에야 `ready` 가 됐다.

git 쪽에서도 등록이 확인된다.

```text
$ git worktree list
...\hads-p3-03-live\workspace                                   95646c0 [main]
...\runner\worktrees\case-7398b5fb3ff31707                      95646c0 [hads/case-7398b5fb3ff31707]
```

### 4.4 사용자의 원래 작업 트리를 건드리지 않았다 (AC-2)

라이브 저장소에는 **일부러 사용자의 미커밋 변경을 남겨 두었다** — `reader.py` 의
편집 한 줄과 미추적 `user-scratch.txt`.

```text
[사용자 트리] 시작 HEAD=95646c0d27 미커밋='M reader.py\n?? user-scratch.txt'
[사용자 트리] 준비 후 HEAD=95646c0d27 미커밋='M reader.py\n?? user-scratch.txt'
[사용자 트리] 최종  HEAD=95646c0d27 미커밋='M reader.py\n?? user-scratch.txt'
```

**시작·준비 후·전 과정이 끝난 뒤가 모두 같다.** 자동 커밋·stash·reset·삭제가
없었다. 그리고 worktree 에는 사용자의 편집이 따라오지 않았다.

```text
worktree/  reader.py  sample.log          ← 커밋된 상태만
저장소/    reader.py  sample.log  user-scratch.txt
worktree 의 reader.py 에 '사용자가 쓰던 중이던 줄' 이 없다
```

기준 커밋이 `HEAD` 의 **커밋된 상태**이기 때문이며, 선택되지 않은 변경을 복사하지도
폐기하지도 않았다.

### 4.5 실제 CLI가 코드를 바꿨다 (AC-5)

Claude Code 가 `workspace_write` 로 T2 를 구현했다. 실제 diff 는
[P3-03-implementation.diff](P3-03-implementation.diff) 에 있다.

```diff
+def read_error_lines(path):
+    """ERROR 로 시작하는 줄만 돌려준다."""
+    return [line for line in read_lines(path) if line.startswith("ERROR")]
```

제어부에 올라온 것은 **수와 SHA 뿐이다.**

```json
{"base_commit": "95646c0d…", "head_before": "95646c0d…", "head_after": "95646c0d…",
 "entries_before": 0, "entries_after": 1, "changed": true,
 "files_changed": 1, "insertions": 5, "deletions": 0,
 "isolation": "worktree_file_layout_only",
 "outside_workspace_observed": true, "outside_workspace_changed": false}
```

`head_before == head_after` 다 — **커밋하지 않았다.** 변경은 Case 브랜치의 작업
트리에 있고, 무엇을 커밋할지는 사람이 정한다(P5).

### 4.6 바뀌지 않은 실행은 완료가 아니다 (AC-6)

같은 작업공간에서 **아무 것도 바꾸지 말라고 지시한 구현 실행**을 실제 Claude Code
로 한 번 더 돌렸다.

```text
[변경 없는 구현] status=201        ← 배정은 허용된다
[변경 없는 구현] outcome=failed
[변경 없는 구현] effect={... "changed": false, "files_changed": 1, ...}
[그래프] {'T1':'done','T2':'done','T3':'done','T4':'planned',...}
```

**`files_changed` 가 1인데 `changed` 는 false 다.** 수는 기준 커밋 대비 누적이고,
`changed` 는 이 실행이 바꾼 것이다. 이 구별이 없으면 앞선 실행이 남긴 변경 때문에
아무 것도 하지 않은 실행이 완료가 된다 — 화면을 보다 찾은 결함이며 10절 결함 2다.

### 4.7 빌드·테스트가 증거를 남겼다 (AC-7)

codex 가 T3 검증을 수행하며 **명령 12건**을 보고했고 그중 **4건의 종료 코드가
0이 아니다.** 그래도 실행은 `completed` 다.

```text
seq 1  exit 0  전용 작업공간 경로 확인
seq 2  exit 1  rg 명령이 없어 계획 파일 검색 실패
seq 7  exit 1  python 명령을 찾지 못해 함수 실행 실패
seq 8  exit 1  일반 설치 위치에서 Python 실행기를 찾지 못함
seq 11 exit 0  설치된 Python 실행기 발견
seq 12 exit 0  표본 로그로 새 함수를 실제 실행하여 기댓값 일치 검증 통과
```

**"테스트가 실패했다"와 "검증을 수행하지 못했다"는 다른 것이다.** 종료 코드는
기준 판정의 입력으로 그대로 남는다. 명령 원문과 출력은 제어부에 없다
([P3-03-verification-run.json](P3-03-verification-run.json)).

### 4.8 구현이 끝나자 후속 Task 가 열렸다 (AC-12)

codex 가 쓴 계획이 Task 6개를 낳았다([P3-03-work-graph.json](P3-03-work-graph.json)).

| Task | 종류 | 선행 |
|---|---|---|
| T1 | 조사 | — |
| T2 | **구현** | T1 |
| T3 | 검증 | T2 |
| T4 | 검증 | T2 |
| T5 | 검증 | T3, T4 |
| T6 | 통합 | T3, T4, T5 |

```text
(T1 실행 전)  T1 runnable=True   T2~T6 task_dependencies_unmet
(T1 완료 후)  T1 done  T2 runnable=True
(T2 완료 후)  T2 done  → T3·T4 가 열렸다
```

**P3-02는 조사 Task 로만 이것을 보였고 구현 Task 는 끝날 수 없었다.** 이제 끝난다.
그리고 끝나는 근거는 사람이 적은 완료가 아니라 **작업공간의 실제 변화**다.

### 4.9 경계 밖은 감지만 한다 (AC-10)

```text
[작업공간] 경계 밖 변경=False
[작업공간] 격리 한계=worktree_file_layout_only
```

이번 라이브에서 CLI 는 작업공간 밖을 건드리지 않았고, 그 사실을 **관측으로**
확인했다(`outside_workspace_observed=true`). 막은 것이 아니라 본 것이다 —
능력 보고의 `os_level_isolation` 은 `unsupported` 로 올라간다
([P3-03-runners.json](P3-03-runners.json)).

## 5. 화면 확인 (AC-15)

라이브가 남긴 DB 위에 제어부를 다시 띄워 **그 라이브가 만든 실제 상태**를 Edge 로
열었다([P3-03-ui-01-workspace.png](P3-03-ui-01-workspace.png),
[P3-03-ui-02-graph.png](P3-03-ui-02-graph.png)).

화면에서 그대로 확인한 것:

- 상태 `준비됨`, 브랜치 `hads/case-7398b5fb3ff31707`, 기준 커밋 `95646c0d27 (HEAD)`,
  worktree 경로와 저장소 경로
- **"준비 시점에 사용자의 원래 작업 트리에 변경 2건이 있었다. 시스템은 그것을
  커밋·stash·삭제하지 않았고 기준 커밋에도 담지 않았다."**
- **격리 한계**: "worktree 는 파일 배치의 분리다. 다른 경로·자격증명 접근을 막는
  OS 격리가 아니며, 경계 밖 변경은 감지해 드러낼 뿐 막지 못한다" — **서버가 준
  문장 그대로**다
- 실행이 바꾼 것: `run-t2-impl` `completed` **"이 실행이 작업공간을 바꿨다"**,
  `run-nochange` `failed` **"이 실행은 작업공간을 바꾸지 않았다"**, 둘 다 옆에
  "기준 커밋 대비 누적: 파일 1개"
- 실행한 명령 12건과 각 종료 코드(`exit 0` / `exit 1`)
- 작업 그래프에서 T5·T6 의 `선행 작업 미완료` 사유와 기준별 구현/검증 Task 대응

## 6. 재시작 복원 (AC-14)

제어부와 Runner 를 **강제 종료**한 뒤 같은 데이터 경로로 다시 띄웠다.

```text
workspace identical: True
graph identical: True
after: ws ready 95646c0d27 effects 2
after: tasks {'T1':'done','T2':'done','T3':'done','T4':'planned','T5':'planned','T6':'planned'}
```

작업공간·기준 커밋·실행 효과·명령 기록·Task 상태가 **바이트까지 같다**
([P3-03-workspace-after-restart.json](P3-03-workspace-after-restart.json),
[P3-03-work-graph-after-restart.json](P3-03-work-graph-after-restart.json)).

Task 상태는 저장된 값이 아니라 실행 결과에서 도출된 것이므로, 이 일치는 실행
기록이 온전히 복원됐다는 뜻이기도 하다.

## 7. 데이터 경계 (바이트 검사, AC-13)

라이브가 실제로 바꾼 코드와 사용자의 편집이 제어부 파일 바이트에 있는지 직접
찾았다([P3-03-boundary.log](P3-03-boundary.log)).

```text
제어부 바이트 5,456,531  Runner 바이트 725,183
  '구현이 넣은 코드 한 줄'    제어부=없음  Runner=있음
  '구현이 넣은 docstring'  제어부=없음  Runner=있음
  '사용자의 미커밋 편집'      제어부=없음  Runner=있음
  '표본 로그 본문'          제어부=없음  Runner=있음
  '브랜치 이름'            제어부=있음(정상: 식별자)
  '기준 커밋 SHA'         제어부=있음(정상: 식별자)
  구현 함수 이름(요약에 등장)   제어부=있음(정상: 작성자가 쓴 명령 요약)
```

**Runner 에 있어야 경계를 지킨 증거가 된다** — 넷 다 없으면 애초에 저장되지 않은
것이다. 마지막 두 줄을 따로 적은 이유는, 브랜치·SHA 는 식별자이고 함수 이름은
작성자가 직접 쓴 짧은 요약에 나온 것이기 때문이다. 그것을 위반으로 읽으면 요약을
쓸 수 없게 된다.

## 8. 성공 기준별 결과 (AC-1~15)

| AC | 결과 | 근거 |
|---|---|---|
| AC-1 작업공간 기록 | **통과** | 라이브 4.3 + 자동 시험 3건(요청·준비·없는 저장소) |
| AC-2 사용자 트리 보호 | **통과** | 라이브 4.4(시작·준비 후·최종이 모두 동일) + 자동 시험(진짜 git 저장소) |
| AC-3 덮어쓰지 않음 | **통과** | 자동 시험 3건(브랜치 충돌·경로 충돌·재사용 시 기준 커밋 유지) |
| AC-4 조건부 쓰기 개방 | **통과** | 라이브(구현·검증만 `workspace_write` 허용) + 자동 시험 6건 |
| AC-5 실제 코드 변경 | **통과** | 라이브 4.5(실제 diff) + 자동 시험 |
| AC-6 변경 없으면 미완료 | **통과** | 라이브 4.6(실제 CLI가 아무 것도 바꾸지 않자 `failed`) + 자동 시험 4건 |
| AC-7 명령 증거 | **통과** | 라이브 4.7(명령 12건, 종료 코드 0/1 보존) + 자동 시험 3건 |
| AC-8 Case 쓰기 직렬화 | **통과** | 자동 시험 3건(두 번째 쓰기 거부, 읽기는 허용, 끝나면 해제) |
| AC-9 Runner 쓰기 1개 | **통과** | 자동 시험 2건(claim 에서 미룸 + 권고 잠금) |
| AC-10 경계 밖 감지·비주장 | **통과** | 라이브 4.9 + 자동 시험 3건(감지·한계 문구·능력 보고) |
| AC-11 외부 편집 보존 | **통과** | 자동 시험 1건(`unexpected_external_change` 표시, 되돌리지 않음) |
| AC-12 구현이 후속을 연다 | **통과** | 라이브 4.8 + 자동 시험 2건 |
| AC-13 데이터 경계 | **통과** | 7절 바이트 검사 + 자동 시험 3건 |
| AC-14 재시작·이행 | **통과** | 6절 + 자동 시험(마이그레이션 v6→v7, 강제 종료 복원) |
| AC-15 화면 한 바퀴 | **통과** | 5절 |

## 9. 라이브로 하지 않은 것

**자동 시험으로만 확인했고 실제 CLI로는 보지 않은 것**을 적는다.

- **브랜치·경로 충돌 거부와 재사용.** 라이브에서는 충돌을 만들지 않았다
- **같은 Case 의 두 번째 쓰기 거부와 Runner 쓰기 자리 미룸.** 라이브는 한 번에
  하나씩만 돌렸다
- **권고 잠금.** 같은 호스트에 두 번째 Runner 프로세스를 띄우지 않았다
- **예상하지 못한 외부 편집의 표시.** 라이브 중 사람이 worktree 를 직접 고치지 않았다
- **경계 밖 변경의 감지.** 라이브에서는 실제로 밖을 건드리는 일이 없었다 —
  `outside_workspace_changed=false` 는 "감지 경로가 돌았고 변화가 없었다"이지
  "감지가 동작함을 보였다"가 아니다. 감지 자체는 자동 시험으로 확인했다
- **없는 저장소에서의 준비 실패.** 자동 시험으로만 봤다
- **OpenCode.** 설치 흔적이 없어 이번에도 제외다(P1-04)

그리고 **커밋·push 는 하지 않았다.** Case 브랜치의 작업 트리에 변경이 남아 있을
뿐이며 무엇을 커밋할지는 P5의 문제다.

## 10. 검토·시험 중 발견해 고친 것

**결함 1 — 지시문의 제약이 산출물의 제약으로 새어 나갔다.**
`INTENT_AUTHORING_PROMPT` 는 "코드를 바꾸지 말고 파일도 만들지 마라"고 적는다.
그것은 **그 실행에만 걸린 규칙**인데 codex 가 의도 문서의 `constraints` 에
`user_requirement` 로 옮겨 적었고, 별도 세션의 Claude 가 "함수를 추가한다는 목표와
정면으로 충돌한다"고 막았다. 라이브가 아니었으면 드러나지 않았을 것이다 —
가짜 응답은 그런 실수를 하지 않는다. 의도·설계·계획 세 지시문에서 둘을 갈라 적고,
**지시문의 문장 자체를 시험으로 고정**했다(`tests/test_ai_draft.py`).

**결함 2 — "바뀌었는가"를 누적 수로 판정하고 있었다.**
화면을 보다 찾았다. 검증 실행의 줄에 "파일 1개 · +5 / −0" 이 떠 있었는데, 그
실행은 파일을 바꾸지 않았다. `files_changed` 는 **기준 커밋 대비 누적**이고
`changed` 판정이 그 수를 보고 있었다. 그대로 두면 "바뀌지 않았으면 완료가 아니다"가
**첫 실행에만 적용되는 규칙**이 된다 — 두 번째 구현 Task 부터는 빈 실행으로 의존이
풀린다. 판정을 **이 실행의 작업 트리 내용 지문 비교**로 바꿨다. 상태 줄 목록만으로는
부족하다(이미 `M reader.py` 인 파일을 또 고쳐도 줄은 그대로다). 자동 시험 둘을 더해
양쪽을 고정했고, **실제 CLI로 다시 확인했다**(4.6절).

**결함 3 — 골격 실행기가 구현·검증을 맡을 수 있었다.**
`local-echo` 는 코드를 고치지도 명령을 실행하지도 않으면서 `completed` 로 끝난다.
그 실행이 구현으로 기록되면 아무 것도 하지 않은 실행 하나로 후속 Task 가 전부
열린다. 진입 검사에서 `tool_is_not_a_coding_cli` 로 막았다.

**결함 4 — 권고 잠금이 관측 대상을 바꾸고 있었다.**
잠금 파일을 worktree 안에 두었더니 그 파일 자체가 미추적 변경으로 잡혀 "이 실행이
무엇을 바꿨는가"의 답에 섞였다. worktree **옆**으로 옮겼다. 관측 수단이 관측
대상을 바꾸면 안 된다.

**결함 5 — 잠금이 잡혀 있으면 실행이 `assigned` 로 멈춘 채 남았다.**
예외로 죽으면 그 Case 의 쓰기 자리도 영영 비지 않는다. 원장을 잡기 전에 잠금을
**보고** 사유와 함께 끝내도록 고쳤다(P3-01 라이브에서 배운 것과 같은 교훈이다).

**검증 도구의 결함도 적어 둔다.** 라이브 드라이버가 피드백 요청의 응답 코드를
확인하지 않아, 처음 두 번의 재작성이 **지적을 보지 못한 채** 돌았다. 제품의 문제는
아니지만 그 사실을 모르고 "AI가 게이트를 넘지 못한다"고 적었으면 틀린 결론이
됐을 것이다.

## 11. 남은 위험

1. **`changed` 는 파일 내용의 변화이지 "옳은 변화"가 아니다.** 시스템은 무엇이
   바뀌었는지 세고 비교할 뿐, 그 변경이 Task 의 완료 조건을 충족하는지 판정하지
   않는다. 그것은 사람 검토와 (P4의) 게이트의 몫이다. 공백 한 줄을 넣어도
   `changed` 는 true 다.
2. **OS 격리는 없다.** worktree 는 파일 배치의 분리다(D-44). 경계 밖 변경은
   실행 전후 대조로 **감지**할 뿐이며, 실행 중에 일어나는 일을 막지 못하고
   되돌리지도 않는다. 원래 저장소 밖(다른 디스크, 네트워크)은 아예 관측하지 않는다.
3. **게이트가 막은 뒤의 재작성에 반영할 피드백이 없어도 시스템이 알려 주지 않는다.**
   이번 검증에서 실제로 그 상태가 만들어졌고(드라이버 결함), 화면에도 기록에도
   "무엇을 고치라는 것인지가 없다"는 표시가 없었다. 수정 주기의 관리는 P4-01이다.
4. **검증 실행의 명령 기록은 AI의 자기 보고다.** 시스템은 명령이 **있는지**를
   보지만, 보고된 명령이 실제로 실행된 그것인지는 확인하지 않는다. Runner 가
   셸을 직접 잡는 구조가 아니기 때문이며, 원문(CLI 스트림)은 남아 있으므로 사람이
   대조할 수 있다.
5. **같은 Runner 의 쓰기 자리는 1개로 고정돼 있다.** 설정으로 바꿀 수 없다.
   FR-26의 "기본 1개"에는 맞지만 조정 경로는 없다.
6. **재사용 시 기준 커밋 복구는 merge-base 에 기댄다.** 기록이 남아 있으면 그것을
   쓰고, 없으면 갈라진 지점으로 되찾는다. 둘 다 안 되면 현재 HEAD 를 쓰며 그 경우
   이미 한 변경이 기준에 포함된다 — 지어낸 값을 쓰지 않을 뿐이다.
7. P1·P2·P3-01·02에서 넘어온 위험(`residual_activity` 는 항상 `unknown`, 안전
   중지 미연결, 열람 요청의 만료·크기 한도 없음, 산출물 내용 판정 안 함, 수준 도출
   규칙은 구현 제안, AI가 낳는 질문이 많음, `blocks` 가 자유 문자열, Task·기준
   연결의 적절성 미판정)은 **그대로다.**

## 12. 외부 전송·남은 자원

- **외부 AI 전송이 있었다.** 사용자 계정의 codex 8회·Claude Code 8회를 실행했고
  각 CLI의 기존 사용자 설정을 따랐다. 시스템은 자격증명을 읽지도 주입하지도 않았다.
- 작업 저장소는 `%LOCALAPPDATA%\Temp\hads-p3-03-live\workspace` 의 **임시 git
  저장소**다. 이 설계 저장소를 CLI에 쓰기로 노출하지 않았다.
- **GitHub 이슈·PR·push 등 외부 게시는 없다.**
- 라이브 시험 데이터 `%LOCALAPPDATA%\Temp\hads-p3-03-live` 는 지워도 된다(저장소 밖).
  그 안의 worktree 와 `hads/case-…` 브랜치도 그 임시 저장소 안에만 있다.
