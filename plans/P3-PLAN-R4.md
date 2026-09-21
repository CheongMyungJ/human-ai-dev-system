# P3-PLAN-R4

자동 실행·진입·완료 경로. 기준: 설계 v0.7 / D-01~67 / 2026-09-22.
선행: P3-R3 완료(스키마 v10, pytest 341 + P1 계약 18 통과). 다음: [P3-04 수직 통합](../DEVELOPMENT.md).

## 1. 이 작업이 답해야 하는 것

R1은 **Autonomy 를 기록**했다. 기록만 했다. 지금 조회의 `enforcement.autonomy` 와
`enforcement.controlled_checkpoint` 는 둘 다 `recorded_not_enforced / P3-R4` 이고,
`tests/test_policy.py::test_the_policy_view_says_who_enforces_each_axis` 가 그 사실을
시험으로 고정해 두었다. R2 가 `repository_selection` 을, R3 이 `budget` 을 강제로 바꿨고
남은 두 축이 R4 다.

**지금 코드가 실제로 하는 일은 v0.6 규칙이다.** 새 Case 도:

- 완료는 **사람 최종 확인**이 기본이다(`completion_mode` 행이 없으면 `human_acceptance`).
  v0.7 의 기본은 반대다 — ask-on-decision 은 조건을 충족하면 **자동 완료**한다(D-31).
- 설계·계획은 **사람 검토**가 기본이다(`stage_review_mode` 행이 없으면 `human_review`).
  v0.7 에서 그 검토는 **선택 사항**이다(D-16·D-21·D-65).
- QG-01 은 **독립 AI 의미 검토를 항상** 요구한다(`combine_verdicts` 가 `not_run` 을
  `pass` 로 올리지 않는다). v0.7 은 요청 정합성 확인을 항상 하되 명확·저위험에는
  **가벼운 확인**을 쓰고 독립 검토는 조건부다(D-25·intent-artifacts 9행).
- `controlled` 로 설정해도 **아무 실행도 막히지 않는다.** 확인 지점은 기록될 뿐이다.
- 기능 구현은 언제나 **설계 산출물 + 계획 산출물 두 건**을 요구한다. Fast Lane 은
  "별도 설계·계획 파일이나 실행 없이 최소 논리 기록으로" 진행한다(D-60·intent-artifacts 48행).

R4 는 그 위에 **사람을 언제 부르는가**를 붙인다. 여섯 가지다.

1. **Autonomy 가 진입을 정한다.** `controlled` 는 시작 확인 전에 설계·계획·구현·검증을
   배정하지 않는다. `ask_on_decision` 은 명확한 요청 자체를 그 범위의 실행 위임으로
   인정해 추가 승인 없이 진행한다(D-11·D-65).
2. **Autonomy 가 완료를 정한다.** ask-on-decision 은 조건 충족 시 자동 완료하고
   **사람 인수 기록을 만들지 않는다.** controlled 는 결과 후보 확인 뒤 종료한다.
3. **Fast Lane 이 산출물의 개수를 정한다.** 명확·저위험이면 결합 기록 하나로 충분하고,
   조건이 깨지면 **사람 확인이 아니라 준비를 추가**해 일반 자동 진행으로 전환한다.
4. **요청 정합성 확인은 항상 하되 방식이 둘이다.** 가벼운 확인과 독립 의미 검토를
   구분해 기록하고, **가벼운 확인을 독립 검토 완료로 표시하지 않는다.**
5. **누적 material delta 가 의존 작업을 막는다.** 마지막 유효 위임과 비교하고 AI 자신의
   직전 초안과 비교하지 않는다. 작은 변경을 연속 채택해 다른 결과로 이동하지 못한다.
6. **목적이 권한을 정한다.** 원인 분석만 요청한 Case 는 허용된 로컬 실험을 자동
   수행하지만 제품 수정으로 목적을 확대하지 않는다(D-66·FR-20).

가장 위험한 것은 2번과 4번이다.

**2번:** 자동 완료를 붙이면서 사람 인수 기록을 같이 만들면, 나중에 그 기록이 "사람이
결과를 확인했다"는 근거로 쓰인다. D-31 이 명시적으로 금지하는 일이다. 반대로 자동 완료가
미충족·미검증을 스스로 예외 수용하면 D-32 가 깨진다 — **어느 Autonomy 에서도 AI 는 예외를
수용하지 않는다.** 두 실수는 방향이 반대이고 둘 다 막아야 한다.

**4번:** 가벼운 확인을 도입하면서 그것을 게이트 `pass` 로 같은 모양으로 적으면, 독립
검토를 실제로 한 Case 와 하지 않은 Case 가 화면에서 구별되지 않는다. "미실행을 통과로
표시하지 않는다"(D-25)가 깨지는 자리가 정확히 여기다. 그리고 가벼운 확인을 고를 수 있는
조건을 AI 추천이나 preset 으로 넓히면 **필수 정합성 확인을 완화한 것**이 된다
(autonomy-budget-policy 5절 "필수 요청 정합성 확인은 일반 preset 이나 AI 추천으로
완화할 수 없다").

세 번째 위험은 **소급**이다. v0.6 기본값(사람 검토·사람 인수)으로 진행한 기존 Case 에
새 기본값을 얹으면, 사람이 확인하기로 하고 시작한 업무가 조용히 자동 완료 대상이 된다.
`autonomy = NULL` 인 R1 이전 Case 의 처리는 **사람에게 확인한다**(11절).

## 2. 범위

| 넣는 것 | 넣지 않는 것 (담당) |
|---|---|
| Autonomy 기반 진입 조건(`controlled` 시작 확인 강제) | 실제 push·PR·기록 이슈 게시 (P5) |
| Autonomy 기반 완료 모드 도출과 기본 자동 완료 | 외부 CI 대기·CI 수정 후 재확인 (P5) |
| controlled 결과 후보 확인의 종료 강제와 내용 변경 시 재확인 | `RemediationCycle`·repair 한도 (P4-01) |
| Fast Lane 판정과 **결합 준비 기록**(`combined` 단계) | QG-02~07 추가 게이트 (P4-01) |
| 단계 검토 기본값을 Autonomy 에서 도출(자동 진행 기본) | 지식 주입·추출 (P4-06·P4-07) |
| QG-01 의 가벼운 확인 / 독립 의미 검토 구분과 조건 | Project·Task 단위 정책 조정 (계층이 없다) |
| 누적 material delta 기록·차단과 위임 기준 갱신 | 실제 수직 통합 기능 개발 (P3-04) |
| 피드백 영향의 기준·검증 자동 연결(`needs_recheck`) | 여섯 Profile 대표 시나리오 전수 (P4-03) |
| 로컬 실험 목적(`local_experiment`)과 목적 밖 확대 차단 | 실행 중 안전 정지 (P6-03) |
| 무변경 목표 충족과 미재현의 구분 | 분산 환경의 예약·확인 조정 (P6) |
| 스키마 v11 과 v10→v11 이행 | |
| 화면의 위임 상태·정합성 방식·delta·Fast Lane 표시 | |
| **`tests/test_policy.py` 의 autonomy·controlled_checkpoint 축 시험 갱신** | |

**예산·저장소·게이트의 강제는 느슨해지지 않는다.** 자동 실행 경로도 **같은 예약을
지난다**(R3). Fast Lane 이 저장소 선택 검사(R2)나 hard 한도(R3)를 우회하는 경로를
만들지 않는다. 새 자동 경로가 `create_run()` 을 거치지 않는 일이 없어야 한다.

## 3. 여섯 축의 실제 규칙 — 이 작업의 중심 표

### 3.1 Autonomy → 진입

아래에서 `controlled` 는 **유효 Autonomy**다. `autonomy = NULL` 인 R1 이전 Case 도
11절의 결정에 따라 같은 칸을 쓴다.

| 목적 | `ask_on_decision` | `controlled` (시작 확인 전) | `controlled` (확인 후) |
|---|---|---|---|
| `intent_authoring` | 허용 | **허용** | 허용 |
| `intent_gate_review` | 허용 | **허용** | 허용 |
| `limited_analysis` | 허용 | **허용** | 허용 |
| `design_authoring` | 허용 | 거부 | 허용 |
| `plan_authoring` | 허용 | 거부 | 허용 |
| `feature_implementation` | 허용 | 거부 | 허용 |
| `verification_run` | 허용 | 거부 | 허용 |
| `local_experiment` | Profile 조건 | 거부 | Profile 조건 |

**초안 작성과 조사를 막지 않는 이유.** controlled 의 시작 확인 대상은 "목표·범위·기준·
허용 행동"이고, 사람이 그것을 확인하려면 **초안이 먼저 있어야 한다**(case-profiles 3절
"초안을 제시할 준비와 해당 작업을 실행할 준비를 구분한다"). 조사까지 막으면 확인에 필요한
사실을 모을 수 없고 "질문과 무관한 조사까지 모두 멈추지 않는다"(9절 2)에도 어긋난다.
`limited_analysis` 는 읽기 전용이며 R2 가 이미 대상 저장소를 고정한다.

새 거부 사유는 `controlled_start_not_confirmed` 하나다. 확인 지점이 `superseded` 되어
다시 `required` 가 되면 같은 사유로 다시 막힌다.

### 3.2 Autonomy → 완료

| Autonomy | 도출되는 완료 모드 | 종료 확정 | 사람 인수 기록 |
|---|---|---|---|
| `ask_on_decision` | `auto_on_conditions` | 조건 충족 즉시 | **만들지 않는다**(actor = 정책 식별자) |
| `controlled` | `human_acceptance` | 결과 후보 확인 뒤 | 실제 확인한 주체·시각 |
| `NULL`(R1 이전) | `human_acceptance` | 〃 (controlled 로 취급, 11절) | 〃 |

`completion_policy` 행이 **명시로 설정돼 있으면 그것이 이긴다.** 도출값이 사용자 명시
설정을 조용히 덮어쓰지 않는다(autonomy-budget-policy 5절). 조회는 세 출처를 구별한다 —
`case_explicit` / `autonomy_derived` / `system_default`.

controlled 의 종료에는 **결과 후보 확인이 선행 조건**이다. 세 가지를 거부한다.

- `controlled_result_not_confirmed` — 확인 지점이 아직 `required` 다.
- `controlled_confirmation_stale` — 확인한 후보의 `subject_hash` 가 지금 후보와 다르다.
  코드나 검토 내용이 달라졌으면 이전 확인을 새 후보에 쓰지 않는다(D-65·FR-23).
- `controlled_start_not_confirmed` — 시작 확인 없이 만들어진 결과는 종료 후보가 아니다.

**같은 내용의 재전송에는 재확인하지 않는다.** 후보 해시가 같으면 확인은 그대로 유효하다.

**고칠 결함 하나.** 지금 `record_exception_decision()` 은 완료 모드가 자동이면 사람의
예외 수용까지 거부하고 "사람 확인으로 되돌린 뒤 수용하라"고 답한다. v0.7 에서 자동이
기본이 되면 **기본 Case 에서 사람이 예외를 수용할 수 없게 된다** — D-32 와
completion-lifecycle 4절에 어긋난다. 막아야 하는 것은 "자동 정책이 **스스로** 예외를
수용하는 것"이고 그 검사는 `check_acceptance(AUTO_POLICY)` 에 이미 있다. 사람 경로의
거부를 걷어내고 대응 시험을 더한다.

### 3.3 Fast Lane 과 결합 준비 기록

Fast Lane 여부는 **저장하지 않고 도출한다**(R3 의 `stop` 과 같은 이유 — 저장하면 "누가
그 값을 적었는가"가 새 문제가 된다). 조건은 전부 이미 기록된 사실이다.

| 조건 | 근거 |
|---|---|
| 효과 수준이 `simple` | 높은 영향 축이 하나라도 있으면 `deep` 이다(sizing) |
| 수준 판단에 `evidence_gap` 이 없다 | 모르는 것을 저위험으로 읽지 않는다 |
| 열린 의도 질문·미연결 이월 질문이 없다 | 미위임 제품 결정이 남아 있지 않다 |
| 미확인 material delta 가 없다 | 원 요청과 차이가 없다(D-60) |
| 저장소 허용을 넓히는 요구가 없다 | R2 의 세 경계 |

Fast Lane 이면 `feature_implementation`·`verification_run` 의 준비 조건이 **설계+계획 두
건에서 결합 기록 한 건으로** 바뀐다. 없어지는 것이 아니다.

```
preparation_artifact.stage = 'combined'
  필수 항목 = 변경 이유·대상 + 작업·검증   (간소 수준이 요구하는 것의 합)
```

- 결합 기록은 **Fast Lane 일 때만** 선행 조건을 충족한다. 조건이 깨지면
  `fast_lane_left_needs_preparation` 으로 거부하고 **무엇이 더 필요한지**를 말한다.
  이것은 사람 확인 요구가 아니다 — 준비를 추가한 일반 자동 진행으로 전환하는 것이다
  (autonomy-budget-policy 4절 마지막 문단).
- 설계·계획이 이미 있으면 Fast Lane 이어도 그대로 통과한다. 결합 기록이 두 산출물을
  **대체하는 선택지**이지 강제가 아니다.
- 결합 기록도 **필수 항목이 미정이면 거부한다.** Fast Lane 은 기록을 줄이는 것이지
  내용을 비우는 것이 아니다(intent-artifacts 48행 "필수 기준과 증거는 남긴다").

### 3.4 단계 검토 기본값

`stage_review_mode()` 는 행이 없으면 지금 `human_review` 를 돌려준다. 그것은 v0.6
기본값이다. R4 에서 **Autonomy 에서 도출**한다.

| Autonomy | 도출 기본값 | 근거 |
|---|---|---|
| `ask_on_decision` | `auto_proceed` | 설계·계획의 사람 검토는 선택 사항(D-16) |
| `controlled` | `auto_proceed` | controlled 도 마찬가지다(D-65 "설계·계획의 사람 검토는 별도 선택") |
| `NULL` | `human_review` | v0.6 그대로. 옛 Case 의 검토 기본값을 소급해 바꾸지 않는다 |

`NULL` 만 `human_review` 로 두는 이유는 11절의 결정이 **진입·완료를 보수적으로** 하라는
것이지 옛 Case 의 단계 검토 설정까지 새로 만들라는 것이 아니기 때문이다. 그 Case 들은
v0.6 기본값으로 이미 사람 검토를 받고 있었다.

Case 명시 설정은 그대로 이긴다. 그리고 **자동 진행이 산출물의 생략을 뜻하지 않는다** —
`record_auto_proceed()` 의 기존 조건(산출물 존재·필수 항목·원문 가용)은 그대로다. 달라지는
것은 그 조건이 충족될 때 **자동으로 기록된다**는 점뿐이고, 그것이 "자동 실행 경로"다.
조건을 못 갖추면 `awaiting_auto_conditions` 로 남는다.

### 3.5 요청 정합성 확인 — 가벼운 확인과 독립 검토

QG-01 은 **끌 수 없다**(intent-artifacts 9행). 달라지는 것은 방식이다.

| 방식 | 무엇을 하는가 | 언제 쓸 수 있는가 |
|---|---|---|
| `light_check` | 제어부의 결정적 규칙 검사 + 위험 조건 없음의 기록 | **Fast Lane 조건과 같을 때만** |
| `independent_review` | 작성과 **별도 세션**의 AI 의미 검토(지금 구현) | 언제나. 아래 조건에서는 **필수** |

독립 검토가 필수인 조건: 효과 수준이 `standard`·`deep`, `evidence_gap` 이 있음,
미확인 material delta 가 있음, Case 설정이 명시로 요구함. **Case 설정은 올릴 수만 있고
내릴 수 없다** — 규칙이 독립 검토를 요구하면 설정으로 가벼운 확인으로 바꾸지 못한다.

게이트 판정은 `combine_verdicts(rule, conformance)` 로 바뀐다.

```
rule = fail|hold          → 그대로 (지금과 같다)
독립 검토 필수인데 not_run → not_run   (지금과 같다. 승격하지 않는다)
가벼운 확인 가능 + 기록됨  → pass       (새 경로)
가벼운 확인 가능 + 미기록  → not_run    (자동으로 통과시키지 않는다)
```

조회는 **방식과 남은 불확실성을 함께** 말한다: `conformance.method`,
`conformance.independent_review_required`, `conformance.unverified_scope`. 가벼운 확인의
`unverified_scope` 에는 "원문의 의미 대응을 AI 가 검토하지 않았다"가 값으로 남는다.
화면 문구도 `통과(가벼운 확인)` 와 `통과(독립 의미 검토)` 를 구별한다.

### 3.6 누적 material delta

비교 대상은 **마지막 유효 위임 기준**(`delegation_basis` 의 `current` 행)이다. AI 자신의
직전 초안이 아니다(D-60).

제어부는 본문을 읽지 않으므로 **구조화된 사실만으로** 분류한다.

| 관측 | 분류 | 처리 |
|---|---|---|
| 동의된 의도의 항목이 바뀌었고 그 항목의 출처가 `user_requirement`·`project_rule` 이며 기록된 피드백·결정에 연결됨 | 사용자 지시 | **위임 기준을 갱신**하고 delta 를 만들지 않는다 |
| 동의된 의도의 항목이 바뀌었고 출처가 `ai_proposal`·`ai_assumption` | **material** | `pending` 으로 쌓이고 의존 작업을 막는다 |
| 성공 기준의 삭제·완화(요약 해시 변경) | **material** | 〃 |
| 저장소 허용 확대·게시 허용 | **material** | 〃 (R2 가 이미 거부하는 것은 그대로) |
| 아직 동의되지 않은 항목의 변경 | 초안 작업 | 기록하고 자동 진행 |
| 해시가 같다 | 변경 없음 | delta 를 만들지 않는다 |

**AI 의 "의미가 같다"는 주장만으로 `pending` 이 풀리지 않는다**(autonomy-budget-policy
3절). AI 의 평가는 `ai_assessment` 로 기록되고 사람의 확인이나 사용자 지시로만 해소된다.
누적이므로 확인 전까지 delta 행이 쌓이고, 조회는 **마지막 위임 기준 대비 누적 차이**를
보여 준다. 해소는 `confirm`(사람) 또는 `superseded`(그 항목이 다시 원래대로)다.

차단 범위는 **그 delta 가 가리키는 기준·Task 에 의존하는 작업**이다. 연결을 모르면
R3·P3-02 와 같은 규칙으로 **전부 막는다** — 모르는 것을 안전한 쪽으로 읽지 않는다.

### 3.7 피드백 영향의 자동 연결

새 의도 버전이 피드백을 반영하면, **바뀐 항목을 가리키는 성공 기준의 판정**을
`needs_recheck` 로 내리고 그 피드백을 근거로 연결한다. 영향 없는 기준의 판정은 **그대로
둔다**(intent-artifacts 69행 "영향이 없는 기록은 유지한다").

이미 `CriterionVerdict.NEEDS_RECHECK` 가 있고 `criterion_result` 에 기록이 있다.
R4 가 더하는 것은 **자동 연결**과 그 출처(`recheck_source = feedback:<id>`)다.

### 3.8 목적 밖 확대와 로컬 실험

| Profile | `feature_implementation` | `local_experiment` |
|---|---|---|
| `feature`·`defect_fix`·`refactoring`·`maintenance` | 허용 | 허용 |
| `root_cause_analysis`·`research` | **거부**(`purpose_outside_case_objective`) | 허용 |
| 미기록(R1 이전) | 지금과 같다 | 거부 — Profile 을 모른다 |

`local_experiment` 는 **쓰기 권한을 받지만 기능 개발 pipeline 을 받지 않는다**
(D-66 "임시 코드가 있다는 이유만으로 기능 개발 전체 절차를 요구하지 않는다").

- 요구하는 것: 준비된 작업공간(사용자 트리 보호), 대상 저장소 기록, 예산 예약, 쓰기
  직렬화. **R2·R3 의 검사를 전부 지난다.**
- 요구하지 않는 것: 설계·계획·결합 기록, 작업 그래프.
- 실행 효과는 `is_experiment` 로 표시되고 **결과 후보에서 제품 변경과 구별**된다.
  "증거와 임시 변경을 구분한다"(D-66).

`root_cause_analysis`·`research` 가 제품 수정을 하려면 **사용자의 명시 결정**으로 목적을
넓혀야 한다(`delegation_basis` 의 `user_decision` 행 + 그 범위 기록). Profile 재분류만으로
넓히지 않는다(D-62 "분류 변경만으로 재승인·예산 초기화·기준 삭제를 하지 않는다").

### 3.9 무변경 목표 충족과 미재현

| 관측 | 판정 | 근거 |
|---|---|---|
| 대상 버전에서 요구 동작이 충족됨을 **검증 실행이 관측** | `met`, `satisfaction = already_satisfied` | 코드 변경 없이 완료할 수 있다(case-profiles 4절) |
| 재현하지 못했다 | **`met` 이 아니다.** `unverified`, `satisfaction = not_reproduced` | "미재현만으로 버그 해결을 선언하지 않는다" |
| 변경하고 검증했다 | `met`, `satisfaction = changed_and_verified` | 〃 |

`already_satisfied` 는 **실제 검증 실행의 증거를 요구한다**(`evidence_kind = run_output`).
사람 판단만으로는 적을 수 없다. `not_reproduced` 는 `met` 으로 저장되지 않게 **쓰기
경로에서** 막는다 — 화면 문구로만 구별하면 API 직접 호출로 우회된다.

## 4. 새 표·컬럼 (스키마 v11)

```
material_delta                     ← 새 표
  id, case_id
  basis_id          비교의 기준이 된 delegation_basis 행. **AI 초안이 아니다**
  detected_at
  change_class      intent_field | success_criterion | repository_allowance
  target_type, target_id, target_key
  from_hash, to_hash            무엇이 어떻게 바뀌었는가 (본문 아님)
  origin            바뀐 항목의 출처. ai_proposal 이면 material 이다
  materiality       material | draft_work | user_directed
  state             pending | confirmed | superseded | adopted
  ai_assessment     AI 의 의미 평가(요약 200자). **이것만으로 pending 이 풀리지 않는다**
  decision_id       사람이 확인했다면 그 결정
  resolved_at, resolution_source

conformance_check                  ← 새 표
  id, case_id, intent_version_id
  method            light | independent
  required_method   규칙이 요구한 방식. light 인데 required 가 independent 면 불충분
  verdict           pass | fail | hold | not_run
  run_id            독립 검토의 실행. light 는 NULL
  unverified_scope  무엇을 확인하지 않았는가 (요약)
  reasons_json      왜 그 방식이 가능/필요한가 (코드 목록)
  recorded_at
  UNIQUE (intent_version_id, method)

preparation_artifact.stage 에 'combined' 추가   ← CHECK 제약 확장
run.purpose        에 'local_experiment' 추가    ← 〃
run.is_experiment  INTEGER DEFAULT 0            ← 새 컬럼
criterion_result.satisfaction  TEXT             ← 새 컬럼
criterion_result.recheck_source TEXT            ← 새 컬럼
completion_policy.source TEXT                   ← 새 컬럼(case_explicit 표시)
```

**이행(v10→v11)에서 소급하지 않는 것.**

| 대상 | v11 이후 | v11 이전에 만들어진 것 |
|---|---|---|
| `autonomy = NULL` Case | — | **controlled 로 취급한다**(11절). 저장된 값은 `NULL`·`migrated_unknown` 그대로 두고 **도출만** 바꾼다 |
| 기존 `completion_policy` 행 | 명시 설정으로 존중 | `source = migrated_explicit` 로 남고 도출값이 덮지 않는다 |
| 기존 `stage_review_setting` 행 | 그대로 | 그대로. 행이 없는 **기존** Case 는 `human_review` 를 유지한다 |
| 기존 게이트 판정 | 새 방식 기록 | 옛 `pass` 는 `method = independent` 로 이행한다 — 실제로 AI 검토를 거쳤기 때문이다. 지어내지 않는다 |
| 기존 `criterion_result` | 새 컬럼 | `satisfaction = NULL`(미기록). **`changed_and_verified` 로 채우지 않는다** |
| 진행 중 Case | 새 규칙 | 종료 기록은 다시 쓰지 않는다. 진행 중 정책 변경의 영향만 조회에 드러낸다 |

**가장 조심할 이행.** `stage_review_setting` 행이 없는 **기존** Case 를 자동 진행으로
바꾸면, 사람이 검토하기로 하고 진행하던 업무가 조용히 통과한다. 그래서 도출은
`case_policy.revision >= 1 이고 autonomy 가 기록된` Case 에만 적용하고, 그 밖에는 v0.6
기본값을 유지한다. 같은 이유로 `completion_policy` 도 도출은 **행이 없을 때만** 한다.

## 5. 작업 순서

1. `domain/progression.py` — Fast Lane 판정, 정합성 방식 판정, 완료 모드·검토 모드
   도출, material delta 분류. **순수 함수로 두고** 제어부·화면·시험이 같은 것을 쓴다
2. 스키마 v11 + 이행. **v10 DB 로 실제 이행 시험부터 만든다**(R2·R3 와 같은 방식)
3. `effective_completion_mode()`·`stage_review_mode()` 의 도출과 출처 표시
4. `controlled` 진입 강제 — `controlled_start_not_confirmed` 와 그 기록
5. 자동 완료 경로 — 조건 충족 시 종료, 사람 인수 기록 없음, 예외는 사람만
6. controlled 종료 강제 — 결과 후보 확인, 해시 대조, 재확인·동일 내용 구분
7. `conformance_check` 와 `combine_verdicts` 개정. **가벼운 확인을 독립 검토로 적지 않음**
8. 결합 준비 기록(`combined`)과 Fast Lane 진입 조건. 이탈 시 준비 추가
9. `record_auto_proceed` 의 자동 기록(조건 충족 시)
10. `material_delta` 기록·누적·차단과 위임 기준 갱신
11. 피드백 영향의 `needs_recheck` 자동 연결
12. `local_experiment` 목적과 목적 밖 확대 차단, `is_experiment` 표시
13. `satisfaction` 세 값과 `not_reproduced` 의 쓰기 차단
14. 화면 — 위임 상태·정합성 방식·Fast Lane·delta·실험 변경 표시
15. **`tests/test_policy.py` 의 autonomy·controlled_checkpoint 축 시험 갱신.**
    `enforcement` 가 넷 다 `enforced` 로 바뀌어야 한다(publish 만 P5). 통과한 채로
    남으면 강제를 붙이지 않은 것이다
16. 전체 시험·빌드·재시작 복원·실제 CLI 라이브 확인

## 6. 성공 기준 (AC)

| # | 기준 | 검증 |
|---|---|---|
| AC-1 | `controlled` Case 는 시작 확인 전 설계·계획·구현·검증이 `controlled_start_not_confirmed` 로 거부되고 그 사유가 진입 검사에 기록된다 | 확인 전후 같은 요청 |
| AC-2 | 같은 Case 에서 의도 초안·의미 검토·조사는 시작 확인 전에도 배정된다 | 세 목적의 요청 |
| AC-3 | 시작 확인이 `superseded` 되면 다시 막힌다. 확인 기록은 남는다 | supersede 후 요청 |
| AC-4 | `ask_on_decision` Case 는 기준·검증·미해결이 정리되면 **사람 인수 없이** 완료되고 `final_acceptance.mode = auto_policy`·actor 가 정책 식별자다 | 종료 기록 |
| AC-5 | 자동 완료가 미충족·미검증을 스스로 예외 수용하지 않는다 | 미충족 기준이 있는 Case |
| AC-6 | **자동 완료 Case 에서도 사람이 예외를 수용할 수 있다.** 원래 판정은 남는다 | 예외 기록과 `criterion_result` 비교 |
| AC-7 | `controlled` 는 결과 후보 확인 전 종료되지 않고, 확인 뒤 종료된다 | `controlled_result_not_confirmed` |
| AC-8 | 확인한 후보의 내용이 바뀌면 이전 확인이 새 후보에 쓰이지 않는다. 같은 내용의 재전송에는 재확인하지 않는다 | 해시 변경·무변경 두 경우 |
| AC-9 | 명시 `completion_policy` 설정이 도출값을 이긴다. 조회가 출처를 구별한다 | 세 출처 |
| AC-10 | Fast Lane Case 는 결합 기록 하나로 구현·검증이 배정된다. 설계·계획 두 건을 요구하지 않는다 | 간소 수준 Case |
| AC-11 | Fast Lane 조건이 깨지면 결합 기록만으로 통과하지 않고 **무엇이 더 필요한지** 말한다. 그것만으로 사람 확인을 요구하지 않는다 | 수준 상향·delta 발생 |
| AC-12 | 결합 기록도 필수 항목이 미정이면 거부된다 | 빈 결합 기록 |
| AC-13 | 요청 정합성 확인은 끌 수 없다. 가벼운 확인이 기록되지 않으면 `not_run` 이고 자동으로 통과하지 않는다 | 게이트 판정 |
| AC-14 | 가벼운 확인이 **독립 검토 완료로 표시되지 않는다.** 방식·미확인 범위가 조회·화면에 남는다 | `conformance.method` 와 문구 |
| AC-15 | 독립 검토가 필수인 조건(표준·심층·근거 부족·미확인 delta)에서는 가벼운 확인으로 통과하지 않는다. Case 설정으로 낮출 수 없다 | 네 조건 각각 |
| AC-16 | 독립 검토는 여전히 **작성과 별도 세션**이다 | 기존 시험 유지 |
| AC-17 | 단계 검토 기본값이 Autonomy 에서 도출되고, 조건 충족 시 자동 진행이 **기록**된다. 산출물·필수 항목 없이 기록되지 않는다 | 자동·명시 두 경우 |
| AC-18 | AI 출처 변경이 동의된 의도를 바꾸면 `material_delta` 가 `pending` 으로 쌓이고 **그 기준에 의존하는 작업이 막힌다** | 차단 범위 |
| AC-19 | 사용자 지시에서 온 변경은 **위임 기준을 갱신**하고 delta 를 만들지 않는다 | 피드백 반영 버전 |
| AC-20 | 작은 변경을 연속 채택해도 **누적 차이가 마지막 위임 기준과 비교**되고 사라지지 않는다 | 3회 연속 변경 |
| AC-21 | AI 의 "의미가 같다" 평가만으로 `pending` 이 풀리지 않는다 | `ai_assessment` 기록 후 상태 |
| AC-22 | 피드백이 반영되면 영향받는 기준만 `needs_recheck` 가 되고 무관한 판정은 유지된다 | 두 기준 비교 |
| AC-23 | `root_cause_analysis`·`research` Case 는 로컬 실험을 수행하되 `feature_implementation` 은 `purpose_outside_case_objective` 로 거부된다 | 두 목적 |
| AC-24 | 로컬 실험도 작업공간·대상 저장소·예산 예약·쓰기 직렬화를 **전부 지난다** | R2·R3 검사 재확인 |
| AC-25 | 실험 변경이 결과 후보에서 제품 변경과 구별된다 | `is_experiment` 표시 |
| AC-26 | 무변경 목표 충족은 검증 실행 증거와 함께 `met` 이 되고, 미재현은 `met` 으로 저장되지 않는다 | 쓰기 경로 거부 |
| AC-27 | 자동 실행 경로가 R2 의 저장소 검사와 R3 의 예약을 우회하지 않는다 | 미선택 저장소·hard 한도에서 |
| AC-28 | 제어부를 강제 종료해도 확인·delta·정합성 기록이 복원된다 | 프로세스 종료 후 재기동 |
| AC-29 | v10 DB 를 올려도 기존 Case 의 단계 검토 기본값과 명시 설정이 **바뀌지 않는다** | 커밋 이력의 v10 스키마로 실제 DB 를 만들어 이행 |
| AC-29b | `autonomy = NULL` Case 는 controlled 로 **취급**되지만 `autonomy` 는 여전히 `null`·`migrated_unknown` 이다. 확인 지점에 이행 정책이 출처로 남는다 | 조회와 확인 지점 기록 |
| AC-30 | `enforcement` 의 `autonomy`·`controlled_checkpoint` 가 `enforced` 로 바뀌고 R1 이 고정한 "강제 없음" 시험이 갱신된다. `publish` 는 여전히 P5 | `tests/test_policy.py` |
| AC-31 | 제어부 DB 에 본문이 들어가지 않는다 | `tests/test_data_boundary.py` 바이트 검사 |
| AC-32 | 실제 CLI 실행으로 자동 진행 경로가 한 번 이상 동작한다 | 라이브 확인 |

## 7. 검증 방법

- **자동 시험:** 기존 341 + P1 계약 18 을 유지하면서 위 AC 마다 시험을 더한다. v0.6
  기본값을 고정한 기존 시험은 **지우지 않고** 의미를 검토해 바꾸고, 대응하는 v0.7
  거절·보존 시험을 짝으로 남긴다.
- **이행 시험:** 커밋 이력의 v10 스키마로 실제 DB 를 만들어 올린다(`_v10_schema()`).
- **재시작 복원:** 제어부 프로세스를 실제로 강제 종료하고 확인·delta·정합성 기록을 본다.
- **화면:** `npm run build` 와 실제 패널 확인.
- **라이브:** 실제 제어부·Runner 프로세스와 실제 CLI 로 자동 진행 경로를 한 번 돌린다.
  종료 코드만으로 판단하지 않고 실제 기록을 본다.

## 8. 복구·인계

- 이 작업은 **기존 컬럼을 바꾸지 않는다.** 새 표 둘, 새 컬럼 다섯, CHECK 제약 둘이며
  이행 전 DB 사본을 남긴다.
- 이행이 실패하면 `material_delta`·`conformance_check` 가 없고 R4 강제는 동작하지 않는다.
  **반쯤 적용된 강제를 "강제한다"로 표시하지 않는다.**
- 시험은 임시 경로에서만 돌고 저장소의 `var\` 는 건드리지 않는다.
- 외부 쓰기(push·PR·이슈)는 이 작업에 없다. 커밋·push 는 사용자 확인 뒤에만 한다.
- P3-04 는 READY 로 인계하고 착수하지 않는다. R1~R3 의 모델을 재설계하지 않는다.

## 9. 하지 않는 것과 그 이유

| 하지 않는 것 | 이유 |
|---|---|
| `autonomy` 에 세 번째 값 추가 | D-59 는 둘을 확정했다. `fast` 는 자율성 등급이 아니라 실행 경로다 |
| Fast Lane 여부를 컬럼에 저장 | 도출로 충분하고, 저장하면 "누가 적었는가"가 새 문제가 된다(R3 의 `stop` 과 같다) |
| AI 의 의미 평가로 delta 해소 | "의미가 같음"이라는 주장만으로 새 의미를 승인하지 않는다(D-60) |
| 가벼운 확인의 조건을 설정으로 넓히기 | 필수 정합성 확인은 preset·AI 추천으로 완화할 수 없다(5절) |
| 기존 Case 의 검토·완료 기본값 변경 | 소급하지 않는다. 사람이 확인하기로 한 업무를 자동으로 바꾸지 않는다 |
| 실행 중 안전 정지 | P6-03. R4 가 막는 것은 **배정**이다 |

## 10. 남은 위험

- **자동 완료가 너무 일찍 닫을 위험.** `check_acceptance` 가 이미 미해결 기준·질문·
  피드백·미정리 실행을 거부하지만, 자동 경로는 사람이 보지 않으므로 그 목록이 곧
  안전장치다. AC-5·AC-27 이 그것을 시험한다.
- **가벼운 확인의 범위.** 규칙 검사는 구조만 본다. `unverified_scope` 에 그 사실을 값으로
  남기지만, 그것이 의미 검토를 대신한다고 읽히지 않게 화면 문구까지 확인한다.
- **delta 분류의 한계.** 제어부는 본문을 읽지 않으므로 "문구만 정리"와 "의미 변경"을
  스스로 구별할 수 없다. 그래서 **동의된 항목의 AI 출처 변경을 전부 material 로 본다** —
  과다 차단이지만 방향이 안전한 쪽이고, 사용자 지시 경로(AC-19)가 정상 흐름을 연다.
- **진행 중 Case 의 정책 변경.** Autonomy 를 바꾸면 완료 모드·검토 기본값이 함께 바뀐다.
  종료 기록은 다시 쓰지 않으며 영향은 조회에 드러낸다(autonomy-budget-policy 5절).

## 11. 사람에게 물어야 할 것 — `autonomy = NULL` Case

R1 이전에 만들어진 Case 는 Autonomy 가 `NULL`·출처 `migrated_unknown`·정책 버전 `0.6`
이다. R4 가 Autonomy 로 진입·완료를 정하는 순간 **이 Case 들을 어떻게 진행할지가 실제
제품 선택**이 된다. 미기록을 기본값으로 올려 자동 진행 대상으로 삼지 않는다.

| 안 | 동작 | 위험 |
|---|---|---|
| A. v0.6 규칙 유지 | 완료는 사람 인수, controlled 확인은 요구하지 않음 | 옛 Case 가 새 자동화를 받지 못한다 |
| B. 진행 차단 | `autonomy_not_recorded` 로 새 실행을 거부 | 진행 중이던 업무가 멈춘다 |
| **C. controlled 로 취급** | 가장 보수적인 새 값으로 읽는다 | 사람이 확인해야 진행된다 |

D 안(기본값 `ask_on_decision` 으로 읽기)은 인계가 명시로 금지했으므로 제시하지 않았다.

### 결정 — C (2026-09-22, 사용자)

**`autonomy = NULL` Case 는 controlled 로 취급한다.** 시작 확인 전에는 설계·계획·구현·
검증이 배정되지 않고, 종료에는 결과 후보 확인이 필요하다.

**구현에서 분리하는 것 하나.** 저장된 값은 `autonomy = NULL`·`autonomy_source =
migrated_unknown`·`policy_version = 0.6` **그대로 둔다.** 바꾸는 것은 **도출된 유효
값**뿐이다.

```
policy.autonomy           = null                     ← 기록. 지어내지 않는다
policy.autonomy_recorded  = false
policy.autonomy_source    = migrated_unknown
policy.effective_autonomy = controlled               ← R4 가 적용하는 값
policy.effective_source   = migrated_unknown_treated_as_controlled
```

R1 의 시험(`test_a_pre_r1_case_is_never_reported_as_ask_on_decision`)이 고정한 사실 —
"`autonomy` 는 `null` 이고 기본값으로 읽지 않는다" — 은 **그대로 통과해야 한다.** 그
Case 에 `controlled` 를 적었다면 없는 사람의 선택을 기록한 것이다(D-14·FR-23).

확인 지점도 같은 규칙으로 만든다. `controlled_checkpoint` 행의 `note_summary` 에
"미기록 Autonomy 를 controlled 로 취급(이행 정책)" 을 남겨 **사람이 고른 설정과 구별**한다.
그 Case 의 Autonomy 를 사람이 실제로 기록하면 그때부터 정상 경로를 탄다.

---

*이 계획은 구현 전에 기록·공유한다. 구현 중 범위·기준이 바뀌면 이유를 함께 남긴다(12절).*

## 12. 수정 기록

### 결합 기록을 **새 목적이 아니라 새 단계**로 만들었다 (4절)

계획 4절은 `preparation_artifact.stage` 에 `combined` 을 더한다고만 적었고, 그것을
**누가 고르는가**는 정하지 않았다. 구현하면서 선택지가 둘로 갈렸다.

- 새 `RunPurpose.COMBINED_AUTHORING` 을 만든다 — 진입 조건표·권한표·역할표·CLI 요구
  표가 전부 목적별이므로 **네 표가 함께 늘어난다.** 한 곳만 빠지면 새 목적이 조용히
  조건 없는 실행이 된다.
- 같은 `plan_authoring` 목적이 **제어부가 정한 단계**를 받는다 — 표가 늘지 않는다.

둘째를 골랐다. `Repository._authoring_stage()` 가 Fast Lane 여부와 설계 유무로 단계를
정해 배정에 실어 보내고, `runner/prompts.py` 가 그 값으로 지시문을 고른다.
**Runner 가 스스로 판단하지 않는다** — 그것이 진입 조건과 같은 판단이기 때문이며,
두 곳에서 각각 계산하면 "Runner 는 결합 기록을 썼는데 진입 검사는 계획을 요구하는"
상태가 조용히 생긴다(R2 가 실제로 한 실수다).

### `needs_recheck` 의 시점을 **구조 보고 뒤로** 옮겼다 (3.7절)

계획 3.7절은 "바뀐 항목을 가리키는 성공 기준의 판정을 `needs_recheck` 로 내린다"를
더하는 일로 적었다. 구현해 보니 **그 전에 걷어내야 하는 것이 있었다** —
`create_intent_version()` 이 새 버전이 생기는 순간 이전 판정을 **전부**
`needs_recheck` 로 내리고 있었다(v0.6 규칙). 그 상태에서는 "영향받은 것만"을 붙일
입력 자체가 이미 지워진다.

그래서 재검토 표시를 `_carry_unaffected_results()` 안으로 옮겼다. 새 버전의 구조가
보고돼야 무엇이 영향을 받았는지 알 수 있고, 그때 **이어지지 않은 판정만** 내린다.
구조가 끝내 보고되지 않으면 이전 판정이 남지만 그 기준들은 이미 `superseded` 라
현재 판정에 쓰이지 않는다(`current_criteria`·`record_criterion_result` 가 막는다).

이어 가는 조건도 계획보다 좁혔다. 기준의 지문이 같아도 **그 기준이 가리키는 의도
항목이 바뀌었으면 잇지 않는다** — 문구가 그대로여도 검증하는 대상이 달라졌으면 옛
판정은 다른 것을 확인한 결과다.

### 사람 검토가 자동 기록을 **덮어쓰게** 했다 (3.4절)

자동 진행을 조건 충족 시점에 기록하도록 바꾸자 새 상태가 생겼다 — **자동 조건이
기록된 뒤에 사람이 실제로 검토하는 경우.** `record_stage_review()` 는 기존 기록이
있으면 그대로 돌려주므로, 그대로 두면 **실제로 있었던 사람의 검토가 사라진다.**

`UNIQUE (preparation_id)` 는 "이 산출물의 검토 상태는 하나"를 지키므로 풀지 않았다.
대신 사람 검토가 자동 조건 충족보다 **강한 사실**이므로 그쪽이 남게 했다. 없는 사람의
검토를 만드는 방향이 아니라 있었던 검토를 적는 방향이다.

### 결합 기록의 지시문에 **출력 형식을 빠뜨렸다** (라이브가 찾음)

계획 5절 8번은 결합 기록의 지시문을 만들라고만 적었고, 처음 구현은 "출력 형태는
개발계획과 같다"는 한 줄로 끝냈다. 설계·계획 지시문은 **실제 JSON 형태를 그대로**
보여 주는데 그 블록을 옮기지 않은 것이다.

라이브에서 실제 codex 가 `{"doc_type": "hads.combined-record", "sections": [{"key":
..., "content": {...}}]}` 처럼 **자기 나름의 형식**을 냈고 구조 보고가 실패했다.
자동 시험은 `FakeCliExecutor` 가 올바른 형식을 내므로 이 구멍을 볼 수 없었다.

고침: 결합 기록 지시문에 설계·계획과 같은 JSON 템플릿을 넣고, `sections` 가 객체이며
키가 항목 이름 그대로여야 한다는 것을 명시했다. 상세는 결과 문서 6절.
