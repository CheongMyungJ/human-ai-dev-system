# P3-04 결과 — 수직 통합

기준: [P3-PLAN-04](../../plans/P3-PLAN-04.md) / 설계 v0.7 / D-01~67 / 2026-09-22.
선행: P3-R4 완료(스키마 v11, pytest 395 + P1 계약 18). 이 단계 후 스키마 **v12**.

## 1. 한 줄 요약

R1~R4 가 붙인 네 축의 강제를 **한 업무가 처음부터 끝까지** 지나가게 했다. 각 축은
자기 시험과 자기 라이브로 확인돼 있었지만 한 줄로 이어진 적이 없었고, 이어 보니
빈칸 하나가 드러났다 — **Task 는 자기 저장소를 모른다.**

설계는 처음부터 그것을 요구했다("Task·Run이 사용하는 Repo와 작업공간을 명시한다",
execution-workspace-review 19행). R2 가 실행 쪽(`run.repository_id`)을 채웠고 Task
쪽이 비어 있었다. 저장소가 하나인 동안에는 그 빈칸이 보이지 않지만, 두 저장소를
**함께 바꾸는** 업무에서는 "UI 작업을 한다면서 API 저장소를 고치는 실행"이 대상을
기록했다는 이유로 통과한다. 실행 전후 대조가 우리가 가진 유일한 증거인데 그 대조가
엉뚱한 Task 에 붙는다.

## 2. 검증 요약

| 항목 | 결과 |
|---|---|
| 자동 시험 | **pytest 415 + P1 계약 unittest 18 통과** (R4 시점 395 → +20) |
| 화면 빌드 | `npm run build` 성공 |
| 스키마 | **v12**. 커밋 이력의 v11 스키마로 만든 실제 DB 의 이행 확인 |
| 실제 CLI | *(아래 5절)* |
| 외부 반영 | 없음. push·PR·이슈는 이 단계에 없다(P5) |

## 3. 만든 것

### 3.1 Task 가 자기 저장소를 안다 (스키마 v12)

```
task.repository_id   TEXT NULL   해석된 저장소. NULL 은 **미기록**이다
task.repository_ref  TEXT ''     계획이 **적은 그대로**의 문자열
```

컬럼 둘이 전부이고 새 표는 없다. 두 컬럼을 함께 두는 이유는 조회의 소비자가 다른
것을 묻기 때문이다 — 진입 검사는 "무엇으로 해석됐는가"를 묻고 화면은 "계획이
무엇이라고 적었는가"를 묻는다. 해석 성공에 원문을 지우면 두 번째 물음에 답할 수
없고, "저장소를 말하지 않은 계획"과 "선택 밖을 가리킨 계획"이 같은 모양이 된다.

**해석 범위가 이 Case 의 선택이다.** Project 의 등록 저장소 전체에서 찾으면 계획이
선택 밖 저장소를 지목하는 것만으로 허용이 넓어진 것처럼 보인다 — R2 가 자동 추가의
세 경계로 막은 일이다(D-38·D-63·D-64).

### 3.2 새 거부 둘, 그리고 그 둘을 **좁힌** 조건

| 사유 | 언제 |
|---|---|
| `run_task_repository_mismatch` | 실행의 대상이 그 Task 가 기록한 저장소와 다르다 |
| `task_repository_not_recorded` | **저장소가 둘 이상인 Case** 에서 그 Task 가 저장소를 말하지 않았다 |

둘째의 조건이 소급을 막는 자리다. 모든 Case 에 걸면 단일 저장소 Case 와 R2 이전
Case 의 진행 중 업무가 멈춘다. 저장소가 둘 이상인 Case 는 R2 이후에만 있고, 그
안에서 저장소를 말하지 않는 계획은 **덜 된 계획**이다.

그리고 대조는 **실행이 밝힌 대상**으로 한다. 작업공간 상태에서 끌어내면 준비되지
않은 저장소를 대상으로 적은 요청이 "작업공간이 없다"는 이유로 대조를 건너뛴다.

### 3.3 계획이 저장소를 말하려면 그 목록을 알아야 한다

배정이 `case_repositories`(**이름과 식별자뿐**)를 싣고, 계획·결합 기록 지시문이 그
목록만 보여 준다. 경로도 본문도 들어가지 않는다 — 한 실행은 자기 작업공간 하나만
보며(D-39) 이 목록이 다른 저장소를 열어 주지 않는다.

**Runner 가 저장소를 찾아 나서지 않는다.** 찾아 나서면 이 Case 가 고르지 않은
저장소를 계획에 적게 되고 그것은 허용을 넓히는 요구가 된다. 그리고 **고를 것이
하나뿐이면 규칙을 아예 넣지 않는다** — 고를 것이 없는데 고르라고 하면 이름을
지어내고, 지어낸 이름은 해석되지 않아 그 작업이 막힌다.

이것이 필요하다는 것은 라이브 준비에서 드러났다. Project 를 만들면 등록 저장소가
`primary` 라는 이름으로 자동 생성되는데, 사람이 부르는 이름(디렉터리 `repo-core`)과
다르고 요청 원문에는 후자가 적혀 있다. 목록을 주지 않으면 계획이 요청 원문의 이름을
그대로 적게 되고 **새 검사가 계획을 실수로 몰아간다.**

## 4. 성공 기준 대조

| # | 기준 | 근거 |
|---|---|---|
| AC-5 | 계획이 적은 저장소가 그래프에 해석돼 남는다 | `test_a_plan_records_which_repository_each_task_changes` |
| AC-6 | 대상이 틀린 구현 실행이 거부된다 | `test_implementing_a_task_in_another_repository_is_refused`, `test_the_mismatch_is_caught_even_without_a_prepared_workspace` |
| AC-7 | 저장소 둘인 Case 의 미기록 Task 가 막히고, 단일 저장소 Case 는 그대로다 | `test_a_task_without_a_repository_blocks_when_there_are_two`, `test_a_single_repository_case_never_needs_the_task_repository`, `test_the_investigation_of_an_unrecorded_task_is_not_blocked` |
| AC-8 | 선택 밖 저장소는 해석되지 않고 버려지지도 않는다 | `test_a_repository_outside_the_selection_is_not_resolved_and_not_dropped` |
| AC-20 | v11 DB 를 올려도 기존 Task 가 미기록 그대로이고 실행이 계속 배정된다 | `test_a_v11_database_keeps_its_tasks_without_inventing_a_repository`(**커밋 이력의 v11 스키마로 실제 DB**) |
| AC-21 | 제어부에 경로·본문이 들어가지 않는다 | `test_the_task_repository_is_an_identifier_not_a_path`, `test_a_second_repository_diff_body_also_stays_on_the_runner` |
| — | 계획 지시문이 선택한 저장소만 보여 주고, 하나뿐이면 묻지 않는다 | `test_the_plan_prompt_names_only_the_repositories_the_case_chose`, `test_the_plan_prompt_says_nothing_when_there_is_one_repository` |
| — | 배정이 이름·식별자만 싣는다 | `test_the_assignment_carries_the_repositories_the_plan_may_choose` |
| — | 사람이 더한 Task 도 저장소를 적고, 재계획이 기존 기록을 지우지 않는다 | `test_a_person_added_task_can_name_its_repository` |

| AC-1 | 저장소별 worktree 가 따로 준비되고 두 저장소의 사용자 미커밋 변경이 전 과정 뒤에도 같다 | **라이브** 5.1·5.6 |
| AC-2 | `deep` 인 Case 가 `ask_on_decision` 인 채로 설계·계획의 사람 검토 없이 진행된다 | **라이브** 5.1 (`auto_proceed / autonomy_derived`) |
| AC-3 | 결합 기록 하나로는 통과하지 않고 설계+계획 두 건이 요구된다 | **라이브** 5.1 (Fast Lane False, 결합 기록 없음) |
| AC-4 | QG-01 이 `required_method = independent` 이고 가벼운 확인으로 통과하지 않는다 | **라이브** 5.1 |
| AC-9 | 실제 codex 가 두 저장소 각각에서 코드를 바꾸고 `workspace_effect` 로 관측된다 | **라이브** 5.2·5.3 (두 항목 `run_effect`) |
| AC-10 | 검증 실행이 각 저장소에서 실제 명령을 돌리고 `run_command` 에 남는다 | **라이브** 5.5 — 명령은 남았고 **전부 실패했다**(환경 제약). 종료 코드로 판정하지 않았다 |
| AC-11 | 조합이 두 저장소를 모두 담고 `covers_all = true` 다 | **라이브** 5.3 |
| AC-12 | outcome 이 `completed` 가 아닌 실행을 근거로 한 `met` 은 거부된다 | 기존 시험 유지. **라이브에서는 그 앞 단계에서 막았다** — 시험을 돌리지 못한 검증은 근거로 쓰지 않았다(5.5) |
| AC-13 | 사람의 입력이 의도 단계에만 있다 | **라이브** 5.4 (결정 3건, 확인 지점 0건) |
| AC-14 | 조건이 충족되면 사람 인수 없이 종료된다 | **미확인.** 검증이 돌지 않아 조건이 충족되지 않았다. 대신 **닫히지 않는 쪽**이 확인됐다(5.5). 앞선 R4 라이브에 `mode=auto_policy` 종료의 증거가 있다 |
| AC-15~17 | controlled·예산 대표 경로 | **미수행.** 8절 |
| AC-18 | AI 출처 변경이 의존 작업을 막는다 | **라이브** — 다시 쓴 초안이 `material_delta_unconfirmed` 로 다음 실행을 막았고 사람 확인으로 풀렸다(6.5·5.4) |
| AC-19 | 강제 종료 후 복원 | **미수행.** 8절 |
| AC-22 | 외부 push·PR·이슈가 없다 | 시험 저장소에 **원격을 붙이지 않았다**. `enforcement.publish = not_implemented` |

## 5. 라이브 확인 — 경로 A(기본 자율)

실제 제어부·Runner 프로세스, **실제 git 저장소 둘**(`repo-core`·`repo-report`,
둘 다 사용자의 미커밋 변경을 남긴 채 시작), **실제 codex**(codex-cli 0.154.0).
원문은 [P3-04-A-live.log](P3-04-A-live.log), 상태는
[정책](P3-04-A-policy.json)·[작업공간](P3-04-A-workspaces.json)·[정합성](P3-04-A-conformance.json)·[게이트](P3-04-A-gate.json)·[준비](P3-04-A-preparation.json)·[작업 그래프](P3-04-A-work-graph.json)·[조합](P3-04-A-composition.json)·[결과](P3-04-A-result.json).

### 5.1 `deep` 과 `ask_on_decision` 이 섞이지 않았다

```
수준: AI 제안 standard → 사람이 deep 으로 조정(P3-01 의 설계된 축)
Fast Lane: False  ['level_not_simple']
정합성 요구: independent  ['level_above_simple']
설계 산출물: 있음 · 계획 산출물: 있음 · 결합 기록: 없음
단계 검토: design=auto_proceed(autonomy_derived) plan=auto_proceed
완료 모드: auto_on_conditions (autonomy_derived)
```

**깊이는 준비를 늘렸고 Autonomy 는 확인 지점을 정했다.** `deep` 이라서 결합 기록이
아니라 설계+계획 두 건이 요구됐고 독립 검토가 필수가 됐지만, 그 어느 것도 사람
검토를 부르지 않았다 — 단계 검토 기본값은 `auto_proceed` 그대로다. R1 이 분리를
주장하고 R4 가 가능하게 만든 조합이 **실제로 그렇게 돌았다.**

### 5.2 두 저장소를 함께 바꾸고, Task 가 자기 저장소를 안다

계획이 Task 마다 저장소를 **등록된 이름 그대로** 적었다.

```
T1 investigation  repo=repo-report    T5 verification   repo=repo-report
T2 implementation repo=primary        T6 verification   repo=primary
T3 verification   repo=primary        T7 integration    repo=repo-report
T4 implementation repo=repo-report
```

일곱 Task 가 **계획이 정한 순서대로** 전부 실행됐고, 각 실행은 그 Task 의 저장소
worktree 안에서 돌았다. 실제 코드 변경은 두 저장소 모두에서 일어났다.

```
repo-core   summarize() → {"lines":…, "words":…, "chars": len(text)}
repo-report render()    → "{lines}줄 {words}단어 {chars}자"
```

**대상이 틀린 실행은 막혔다.** 같은 Task 를 반대쪽 저장소로 보내자:

```
[wrong-repo-T2] 409 ['run_task_repository_mismatch']
```

사유가 **그것 하나**인 것이 요점이다. 다른 조건은 전부 갖춰져 있었고 틀린 것은
대상 저장소뿐이었다 — v12 의 검사가 단독으로 막았다는 증거다.

### 5.3 조합이 두 저장소를 **관측으로** 담았다

```
covers_all_code_repositories = True   integration_verified = True
snapshot_complete = True
  primary     base=0b234ff40b head=0b234ff40b… dirty=2 source=run_effect
  repo-report base=233b922947 head=233b922947… dirty=2 source=run_effect
```

두 항목 모두 `run_effect` 다 — 기준 커밋만 있는 `workspace_base` 가 아니라 실행이
**실제로 관측한** HEAD 와 미커밋 수가 들어 있다.

### 5.4 사람은 의도 단계에서만 불렸다

Case 전체의 사람 결정은 **셋**이다.

```
intent_agreement            owner   (rev 1)
material_delta_confirmation owner   (다시 쓴 초안의 AI 출처 변경 확인)
intent_agreement            owner   (rev 2)
확인 지점: []               (ask_on_decision 이므로 controlled 확인 없음)
```

그 밖에 사람이 한 것은 미정 질문 답변과 이월 질문 답변, 수준 조정이다. **설계·계획·
구현·검증·완료에는 사람 호출이 하나도 없다.** 일곱 Task 가 전부 사람 없이 배정되고
실행됐다.

### 5.5 검증이 돌지 않았고, **그래서 닫히지 않았다**

이 호스트의 CLI sandbox 는 Python 인터프리터에 닿지 못한다. 네 검증 실행이 모두
명령을 실행하고 실패를 보고했다.

```
검증 실행 run-verification-T3…: 명령 2건, 종료 코드 0 인 것 0건
검증 실행 run-verification-T5…: 명령 2건, 종료 코드 0 인 것 0건
검증 실행 run-verification-T6…: 명령 2건, 종료 코드 0 인 것 0건
검증 실행 run-integration-T7…:  명령 1건, 종료 코드 0 인 것 0건
```

**그 상태에서 기준을 `met` 으로 적지 않았다.**

```
C-01~C-04 → unverified  (evidence_kind = none)
완료 모드  → auto_on_conditions
Case 상태  → 열린 채  (결과 후보 없음, 종료 기록 없음)
```

**이것이 이 라이브의 가장 중요한 결과다.** R4 는 "여는 쪽이 더 위험하다"고 적었고 —
조건을 갖추지 않았는데 열리면 아무도 보지 않은 결과가 완료가 된다 — 여기서 그
반대가 확인됐다. 자동 완료는 **기본값이지 무조건이 아니다.** 검증이 돌지 않았으므로
기준이 충족되지 않았고, 충족되지 않았으므로 닫히지 않았다.

**이 세션의 앞선 시도 하나는 정확히 그 반대로 끝났다.** 검증이 시험을 한 줄도 돌리지
못했는데 기준을 `met` 으로 적었고 Case 가 `mode = auto_policy` 로 닫혔다. 제품이
그것을 막지 못한 것이 아니라 **하네스가 거짓 근거를 먹였기** 때문이다(6.6). 근거의
진위는 여전히 시스템이 판정하지 못한다 — 그것이 남는 한계다(9절).

### 5.6 사용자의 미커밋 변경은 그대로다

```
repo-core   : 동일=True
repo-report : 동일=True
```

worktree 준비부터 일곱 Task 실행까지 지나고도 두 저장소의 `git status --porcelain`
이 시작 때와 **완전히 같다.**

## 6. 구현·라이브가 찾은 결함

### 6.1 질문에 답해도 그 답이 **다시 쓰는 실행에 닿지 않았다** (라이브가 찾음)

AI 가 미정 질문을 냈고 사람이 답했다. 그 답은 `intent_question.answer_artifact_id`
로 기록됐다. 그런데 **어떤 실행의 입력도 아니었다** —
`compose_context_refs(INTENT_AUTHORING)` 는 직전 초안과 미해결 **피드백**만 고정하고,
질문 답변은 `feedback` 표에 행을 만들지 않는다(`answer_question()` 은 질문 행만
갱신한다).

그 상태에서는 "필요한 질문의 답변을 반영하면 자동 진행한다"(intent-artifacts
104행)가 성립하지 않는다. 반영할 입력이 없기 때문이다.

**라이브에서 결과가 나왔다.** 답이 있는데도 다음 초안이 같은 모순을 그대로 두었고
QG-01 의 독립 검토가 그것을 잡았다.

```
지적: request_missing_or_contradictory [required/confirmed] constraints
      — 기존 출력 기대값을 유지하면서 출력 계약을 변경하는 요구가 서로 충돌한다
지적: important_open_question_unlisted [required/confirmed] sizing.axes
      — 다른 호출자·외부 출력 소비자 존재 여부가 중요 미정 사항이지만 질문 목록에 없다
```

고침: `ContextRefRole.QUESTION_ANSWER` 를 두고 답한 질문의 원문을 작성 실행에
고정한다. **피드백과 합치지 않았다** — 피드백은 초안 전체에 대한 의견이고 이것은
그 질문에 대한 답이며, 한 역할로 묶으면 지시문이 "무엇에 답한 것인지"를 말할 수
없다. 짝이 되는 시험 둘을 더했다(답한 질문은 고정되고 **실제로 읽히며**, 답하지
않은 질문은 고정되지 않는다 — 없는 답을 빈 참조로 실어 보내면 그 자리가 미정이
아니라 빈칸이 된다).

### 6.2 사람이 답한 것을 **AI 가정으로 적었다** (라이브가 찾음)

6.1 을 고치고 다시 돌리자 앞의 두 지적은 사라졌다 — 답이 실제로 반영됐다. 대신
한 단계 아래의 같은 종류가 드러났다.

```
지적: assumption_presented_as_requirement [required/confirmed] sizing.axes[2].evidence
      — 두 저장소 밖에 호출자가 없다는 근거 없는 가정을 확정된 사실로 서술했다
```

그 문장은 **사람의 답에서 나온 것**이다. 다시 쓰는 AI 가 그것을 `ai_assumption`
으로 적었고, 검토자는 정확히 그 표시를 보고 "근거 없는 가정"이라고 판정했다.
검토자가 틀린 것이 아니라 출처가 잘못 적힌 것이다(FR-04 "기록되지 않은 것과 확인된
것을 구별한다").

고침: 의도 작성 지시문의 origin 규칙에 반대 방향을 더했다. "가정을
`user_requirement` 로 적지 마라"만 있고 **"사람이 답한 것을 `ai_assumption` 으로
적지 마라"가 없었다.** `question_answer` 역할 설명에도 같은 것을 적었다.

### 6.3 라이브가 **요청 자체의 빈 곳**을 세 번에 걸쳐 찾았다

세 번째 시도에서 검토는 `hold` 로 끝났다(`suspected` 두 건).

```
지적: assumption_presented_as_requirement [required/suspected] desired_behavior
      — chars=len(text) 가 문자 수의 기준이라고 단정했지만 유니코드 문자 단위
        정의가 정해지지 않았다
지적: important_open_question_unlisted [required/suspected] open_questions
      — 기존 호출자나 저장된 요약 데이터의 호환성 처리 결정이 필요하지만
        질문으로 제시되지 않았다
```

**이것은 제품 결함이 아니다.** 요청이 `deep` 수준의 독립 검토를 견딜 만큼 구체적이지
않았다. P3-04 가 확인하려는 것은 "**명확한** 기능의 추가 사람 호출 없음"이고,
명확함은 전제이지 결과가 아니다. 그래서 검토가 찾은 것을 요청 안으로 옮겼다 —
`chars` 의 단위 정의, 기존 키 보존, 형식 테스트 갱신 범위, 다른 호출자 없음.

**남는 사실:** 두 저장소에 걸친 계약 변경을 `deep` 으로 올리면 독립 검토가
**세 번에 걸쳐** 요청의 빈 곳을 찾았고, 그 셋은 모두 실제 빈 곳이었다. QG-01 이
장식이 아니라는 증거이며, 동시에 "명확한 요청"이 사람이 생각하는 것보다 비싸다는
관측이다.

### 6.4 공유 연결의 동시 쓰기가 요청 하나를 죽였다 (라이브가 찾음, **가장 무거움**)

두 저장소 흐름을 실제로 돌리자 실행 생성이 **HTTP 500** 으로 죽었다.

```
sqlite3.OperationalError: cannot start a transaction within a transaction
  controller/repository.py  record_admission → db.transaction → BEGIN IMMEDIATE
```

제어부는 연결 하나를 `check_same_thread=False` 로 만들어 **모든 요청이 공유**하고,
FastAPI 는 동기 엔드포인트를 **스레드풀**에서 돌린다. P3-R3 이 `BEGIN IMMEDIATE`
를 쓰기 시작하면서 요청 둘이 같은 연결에 동시에 `BEGIN` 을 보내는 순간이 생겼고,
SQLite 가 그것을 거부한다.

**한 축만 찌르는 시험으로는 나오지 않는다.** Runner 가 실행 결과를 보고하는 **동안**
다음 실행을 만들어야 겹치며, 그 동시성은 실제 흐름에서만 생긴다. R3·R4 의 라이브는
조건 하나를 확인하고 멈췄기 때문에 이 자리를 지나가지 않았다.

그리고 이 실패는 **사람이 볼 수 있는 사유가 없다.** 진입 검사의 어느 거부도 아니고
요청 자체는 정상이다. "왜 실행이 시작되지 않았는가"에 답할 수 없는 실패이며 그것이
이 결함이 무거운 이유다.

고침: `db.transaction` 이 프로세스 안에서 쓰기 트랜잭션을 **직렬화**한다(`RLock`).
재진입으로 둔 이유는 같은 스레드의 중첩이 **설계 문제로 드러나야지** 스레드 경합으로
가려지면 안 되기 때문이다. 여러 제어부 프로세스의 조정은 P6-03 이며 이 잠금은 그
범위를 넓히지 않는다.

짝이 되는 시험(`test_two_threads_on_the_shared_connection_do_not_collide`)은 잠금을
지우면 **같은 예외로 실패한다** — 그것을 확인하고 넣었다.

### 6.5 재작성 버전의 검토에 **후속 지시**를 요청으로 줬다 (라이브가 찾음)

6.3 의 고침(`original_request`) 뒤에도 검토가 권고 하나를 남겼다.

```
지적: other [advisory/confirmed] fixed_context
      — 요청 원문 내용이 제공되지 않아 초안과의 전체 대조를 수행할 수 없다
```

원인은 **무엇을 요청으로 볼 것인가**였다. 처음 구현은 "그 초안을 쓴 실행이 받은
지시"를 요청으로 삼았는데, 다시 쓴 버전의 그 지시는 "이 지적을 고쳐라"라는 **후속
지시**다. 검토자는 그것을 원래 요청으로 받았고 대조가 되지 않는다고 말했다.

고침: 이 Case 에서 **처음 초안을 쓴 실행**의 지시를 요청으로 삼는다. 재작성은
요청이 아니라 다듬기다. 짝이 되는 시험이 후속 지시가 아니라 첫 요청이 가는 것을
고정한다.

### 6.6 하네스가 찾은 것 (제품 결함 아님)

| 무엇 | 왜 |
|---|---|
| 의미 검토의 지시 원문은 **의도 문서 자체**여야 한다 | 제어부가 지시 원문에서 검토 대상 버전을 끌어낸다. 따로 쓴 안내문을 주면 "검토할 의도 버전을 찾지 못했다"로 실행이 **실패한다** — 없는 대상을 지어내지 않는 것이 맞다 |
| 실행은 **그래프가 정한 순서**로 요청해야 한다 | 구현을 먼저 늘어놓으면 `task_dependencies_unmet` 으로 막힌다. 계획이 순서를 정하고 하네스는 지금 배정 가능한 것을 그래프에 묻는다 |
| 설계·계획이 **이월한 질문**에 사람이 답해야 배정이 열린다 | 이월 질문은 의존 Task 를 막고, 무엇을 막는지 모르는 질문은 전부 막는다(P3-02). 답하면 그대로 열렸다 |
| 통합 Task 는 **검증 목적**으로 돌린다 | 구현 목적으로 돌리면 바꿀 것이 없어 실패한다. 두 저장소가 맞는지 보는 것은 확인이지 변경이 아니다 |
| 한 Task 의 지시에 **요청 전체**를 붙이면 안 된다 | AI 가 다음 작업까지 미리 하고, 그 다음 실행은 바꿀 것이 없어 실패한다. 실제로 그렇게 됐다 |
| 검토 실행 id 는 **회차마다 달라야 한다** | 같은 `run_id` 는 멱등하게 이전 실행을 돌려주므로 새 버전이 검토되지 않고 게이트가 `not_run` 으로 남는다(P3-R4 6.5와 같은 함정) |

## 7. 수행하지 못한 것 — **P3-04 는 완료가 아니다**

| 범위 | 상태 | 이유 |
|---|---|---|
| **경로 B — controlled 대표 경로** | **미수행** | 스크립트는 있다(`p3/live/path_bc.py --path b`). 경로 A 가 결함 여섯을 드러내며 여덟 번 재실행됐고 이 세션의 시간을 다 썼다 |
| **경로 C — 예산 도달 대표 경로** | **미수행** | 〃 (`--path c`) |
| 제어부 강제 종료 후 복원(AC-19) | **미수행** | 자동 시험의 복원 시험은 그대로 통과하지만 **v12 기록의 라이브 복원은 보지 않았다** |
| 검증 실행이 실제로 시험을 돌리는 것 | **환경 제약으로 불가** | 이 호스트의 CLI sandbox 가 Python 에 닿지 못한다(P3-03 도 같은 것을 관측했다). 그래서 `met` 판정의 라이브 증거가 없다 |

**완료로 표시하지 않는다.** 위 넷 중 앞의 셋은 시간이고 넷째는 환경이며, 어느 것도
"확인했다"로 바꿀 수 없다.

## 8. 하지 않은 것 · 미검증

| 항목 | 위치 |
|---|---|
| 게시 허용·실제 push·PR·기록 이슈 | **P5** |
| 외부 CI 대기와 CI 수정 후 재확인 | **P5** |
| 다중 Repo 통합 증거의 **강제** | **P4-01**. R2 의 `covers_all_code_repositories` 는 드러내기만 한다 |
| QG-02~07 추가 게이트·repair 한도 | **P4-01** |
| 여섯 Profile 대표 시나리오 전수 | **P4-03**. 여기서는 `feature` 하나를 끝까지 봤다 |
| 지식 주입·추출 | **P4-06·P4-07** |
| 한 실행이 **여러** 작업공간을 보게 하기 | 바꾸지 않았다. 관측 결과는 6절 |
| 실행 중 안전 정지 | **P6-03** |
| Task 저장소를 작업공간에서 유도해 채우기 | **하지 않는다.** 없는 계획의 판단을 만드는 일이다(D-62) |

## 9. 이 단계가 만든 새 사실

- **`task` 가 저장소를 안다.** `repository_id`(해석)와 `repository_ref`(계획이 적은
  그대로) 둘이며, 미기록은 NULL·빈 문자열이고 **유도해 채우지 않는다**.
- **새 거부 둘:** `run_task_repository_mismatch`, `task_repository_not_recorded`.
  둘째는 **저장소가 둘 이상인 Case** 에서만 문다 — 조건을 좁힌 것이 소급을 막는다.
- **배정이 `case_repositories` 를 싣는다.** 이름과 식별자뿐이며, 계획을 쓰는 실행이
  고를 수 있는 이름을 알게 하기 위한 것이다. 경로·본문은 들어가지 않는다.
- **강제 축은 늘지 않았다.** `enforcement` 는 여전히 넷이 `enforced` 이고 `publish`
  만 `not_implemented` 다(P5). Task↔Repo 는 새 축이 아니라 `repository_selection`
  축이 이미 강제하던 것의 **대조 대상**을 정확히 한 것이다.
- **계획 지시문이 저장소를 묻는다.** 고를 것이 둘 이상일 때만이며, 하나뿐이면 그
  규칙을 아예 넣지 않는다.
- **고정 컨텍스트가 세 자리 늘었다.** `question_answer`(사람이 답한 것),
  `original_request`(검토가 대조할 것), `current_plan`(구현이 따라야 할 것). 셋 다
  **없던 참조를 지어내지 않는다** — 답하지 않은 질문, 사람이 직접 쓴 초안, 계획이
  없는 Case 에서는 참조가 만들어지지 않는다.
- **쓰기 트랜잭션이 프로세스 안에서 직렬화된다.** 공유 연결에 동시 `BEGIN` 이
  들어가 요청 하나가 500 으로 죽던 자리다. 여러 제어부의 조정은 P6-03 이며 이
  잠금은 그 범위를 넓히지 않는다.
- **자동 완료가 실제로 열리지 않는 것을 봤다.** 검증이 돌지 않아 기준이 `unverified`
  로 남자 Case 가 닫히지 않았다. R4 가 "여는 쪽이 더 위험하다"고 적은 것의 반대편
  증거이며, `auto_on_conditions` 가 **조건을 지난다**는 뜻이다.
- **QG-01 의 판정은 실행마다 다르다.** 같은 수준·같은 요청에서 pass·hold·fail 이
  모두 나왔다. 통과할 때까지 돌리지 않고 **지적을 피드백으로 넣어 다시 쓰는** 경로를
  썼으며, 상한(2회)을 넘으면 막힌 채로 끝낸다.
