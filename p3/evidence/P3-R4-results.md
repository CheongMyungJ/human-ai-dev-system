# P3-R4 결과 — 자동 실행·진입·완료 경로

기준: [P3-PLAN-R4](../../plans/P3-PLAN-R4.md) / 설계 v0.7 / D-01~67 / 2026-09-22.
선행: P3-R3 완료(스키마 v10, pytest 341 + P1 계약 18). 이 단계 후 스키마 **v11**.

## 1. 한 줄 요약

R1이 기록만 하던 **Autonomy 가 진입과 완료를 실제로 정한다.** `controlled` 는 시작
확인 전에 설계·계획·구현·검증·실험을 배정하지 않고 결과 후보 확인 전에 종료하지
않는다. 기본 `ask-on-decision` 은 반대로 **연다** — 명확한 요청을 그 범위의 실행
위임으로 인정해 설계·계획의 사람 검토 없이 진행하고, 조건을 충족하면 **사람 인수
기록 없이** 자동 완료한다.

**R1~R3 의 강제는 전부 "막는" 방향이었고 R4 는 방향이 둘이다.** 여는 쪽이 더
위험하다 — 조건을 갖추지 않았는데 열리면 아무도 보지 않은 결과가 완료가 되고,
조건을 갖췄는데 사람 인수 기록을 함께 만들면 있지도 않은 확인이 근거로 남는다.

## 2. 검증 요약

| 항목 | 결과 |
|---|---|
| 자동 시험 | **pytest 395 + P1 계약 unittest 18 통과** (R3 시점 341 → +54) |
| 화면 빌드 | `npm run build` 성공 |
| 스키마 | **v11**. 커밋 이력의 v10 스키마로 만든 실제 DB의 이행 확인 |
| 실제 CLI | **실제 codex 실행 6회**(codex-cli 0.154.0). 그중 1회가 6.1의 결함을 드러냈고, 고친 뒤 재실행해 확인했다. 아래 5절 |
| 실제 강제 종료 | 제어부 강제 종료 후 확인 지점·정합성 방식·완료 도출이 그대로 복원 |
| 외부 반영 | 없음. push·PR·이슈는 이 단계에 없다(P5) |

라이브 원문은 [P3-R4-live.log](P3-R4-live.log)·[Fast Lane 원문](P3-R4-live-fastlane.log),
상태는 [정책](P3-R4-live-policy.json)·[정합성](P3-R4-live-conformance.json)·[controlled](P3-R4-controlled-policy.json)·[준비](P3-R4-fastlane-preparation.json)·[결과](P3-R4-fastlane-result.json).

## 3. 만든 것

### 3.1 Autonomy 의 취급 — 기록과 적용을 나눴다

`domain/progression.py` 에 **적용되는** Autonomy 를 도출하는 함수를 두었다. 저장된
값과 다를 수 있는 경우가 정확히 하나다 — `autonomy = NULL` 인 R1 이전 Case 다.

```
policy.autonomy           = null                     ← 기록. 지어내지 않는다
policy.autonomy_recorded  = false
policy.autonomy_source    = migrated_unknown
policy.effective_autonomy = controlled               ← R4 가 적용하는 값
policy.effective_source   = migrated_unknown_treated_as_controlled
```

**사용자 결정(2026-09-22)으로 controlled 취급을 골랐다.** 그러나 `controlled` 를
적어 넣지 않는다 — 있지도 않은 사람의 선택을 기록하는 일이 된다(D-14·FR-23). R1 의
시험(`test_a_pre_r1_case_is_never_reported_as_ask_on_decision`)은 **갱신 없이 그대로
통과한다.** 취급으로 생긴 확인 지점에는 `note_summary` 로 "미기록 Autonomy 를
controlled 로 취급(이행 정책)"이 남아 사람이 고른 설정과 구별된다.

그 요구는 **조회 시점에 도출하고 확인 시점에 행이 된다.** 조회가 쓰기를 하지 않으면서
"없음을 통과로 읽지 않는다"를 지키는 방법이다.

### 3.2 Autonomy 가 정하는 것 셋

| 축 | `ask_on_decision` | `controlled` | `NULL`(취급) |
|---|---|---|---|
| 진입 | 그대로 진행 | 시작 확인 전 설계·계획·구현·검증·실험 거부 | controlled 와 같다 |
| 완료 | `auto_on_conditions` (조건 충족 시 자동) | `human_acceptance` (결과 후보 확인 뒤) | `human_acceptance` |
| 단계 검토 기본값 | `auto_proceed` | `auto_proceed`(D-65) | **`human_review`** (v0.6 유지) |

마지막 칸이 소급 금지의 자리다. 11절의 결정은 **진입·완료를 보수적으로** 하라는
것이지 옛 Case 의 단계 검토 설정을 새로 만들라는 것이 아니다 — 그 Case 들은 이미
사람 검토를 받고 있었다.

**명시 설정은 언제나 이긴다.** `completion_policy` 행이 있으면 도출하지 않고,
조회가 세 출처를 구별한다(`case_explicit` / `migrated_explicit` / `autonomy_derived`).

### 3.3 controlled 가 막는 것과 막지 않는 것

```
막는다      design_authoring · plan_authoring · feature_implementation
            verification_run · local_experiment
막지 않는다 intent_authoring · intent_gate_review · limited_analysis
```

**초안 작성·의미 검토·조사를 막지 않는 것이 설계다.** 시작 확인의 대상이 "목표·범위·
기준·허용 행동"인데 사람이 그것을 확인하려면 초안이 먼저 있어야 한다(case-profiles
3절). 조사까지 막으면 확인에 필요한 사실을 모을 수 없고 "질문과 무관한 조사까지 모두
멈추지 않는다"(autonomy-budget-policy 9절 2)에도 어긋난다.

종료 쪽은 셋으로 나눠 거부한다 — `controlled_start_not_confirmed`,
`controlled_result_not_confirmed`, `controlled_confirmation_stale`. 사람이 해야 할
일이 각각 다르기 때문이다. **같은 내용의 재전송은 셋 중 어느 것도 아니다** — 후보
해시가 같으면 이전 확인이 그대로 유효하다(D-65 마지막 문장).

결과 후보를 확인하면 **시스템이 종료를 확정한다**(D-65 "…→ 시스템 종료"). 사람이 또
한 번 "완료"를 눌러야 하면 같은 내용의 확인을 두 번 요구하는 것이다. 그 인수는
`mode = human`·actor = 확인한 사람이며 **정책 식별자로 적지 않는다** — 여기에는
실제 사람의 확인이 있었다.

### 3.4 기본 자동 완료

`maybe_auto_complete()` 를 기준 판정 기록과 실행 결과 보고 뒤에 부른다. 사람이
버튼을 눌러야 일어난다면 그것은 자동 완료가 아니다.

`auto_complete_if_allowed()` 와 다른 점 하나: **후보를 먼저 만들지 않는다.** 저쪽은
사람이 "지금 완료할 수 있는가"를 물은 것이라 못 하는 이유를 보여 주려고 후보를
만들지만, 이쪽은 시스템이 매번 부르는 자리라 조건이 안 갖춰졌는데 후보를 만들면
진행 중 Case 가 매번 `waiting_final_acceptance` 로 표시된다.

**고친 결함 하나.** `record_exception_decision()` 이 완료 모드가 자동이면 **사람의**
예외 수용까지 거부하고 있었다. v0.7 에서 자동이 기본이 되면 그 규칙은 "기본 Case
에서는 사람이 예외를 수용할 수 없다"가 되어 D-32 와 어긋난다. 막아야 하는 것은
"자동 정책이 **스스로** 수용하는 것" 하나이며 그 검사는 `check_acceptance(AUTO_POLICY)`
에 그대로 있다. 두 문장을 합치면 사람의 결정 경로가 정책 설정에 묶인다.

### 3.5 Fast Lane 과 결합 기록

Fast Lane 여부는 **저장하지 않고 도출한다**(R3 의 `stop` 과 같은 판단). 조건은 전부
이미 기록된 사실이다 — 간소 수준, 근거 부족 없음, 열린 질문 없음, 미확인 누적 변경
없음.

Fast Lane 이면 구현·검증의 준비 조건이 **설계+계획 두 건에서 결합 기록 한 건으로**
바뀐다. 없어지는 것이 아니다.

```
preparation_artifact.stage = 'combined'
  필수 항목 = change_summary · verifiability · tasks · verification
```

세 가지를 지켰다.

- **대체하는 선택지이지 강제가 아니다.** 설계·계획이 이미 있으면 Fast Lane 이어도
  그대로 통과한다.
- **이탈은 사람 확인 요구가 아니다.** 조건이 깨지면
  `fast_lane_left_needs_preparation` 과 함께 **무엇이 더 필요한지**를 말한다.
- **내용을 비우는 것이 아니다.** 필수 항목이 미정이면 그대로 거부된다.

단계를 고르는 것은 **제어부**다(`Repository._authoring_stage`). 목적은 여전히
`plan_authoring` 하나이고 배정이 `preparation_stage` 를 실어 보낸다 — 새 목적을 만들면
진입 조건표·권한표·역할표·CLI 요구 표가 함께 늘고 한 곳만 빠지면 새 목적이 조용히
조건 없는 실행이 된다.

### 3.6 요청 정합성 확인 — 방식이 둘

QG-01 은 **끌 수 없다**. 달라지는 것은 방식이다.

| 방식 | 무엇을 하는가 | 게이트 |
|---|---|---|
| `light` | 제어부의 결정적 규칙 검사 + 위험 조건 없음의 기록 | 규칙이 허용할 때만 `pass` |
| `independent` | 작성과 **별도 세션**의 AI 의미 검토 | 지금까지와 같다 |

독립 검토가 **필수**인 조건: 수준이 `simple` 을 넘음, `evidence_gap` 이 있음, 미확인
누적 변경이 있음, Case 설정이 명시로 요구함. **Case 설정은 올릴 수만 있고 내릴 수
없다** — 낮추는 인자가 API 표면에 없는 것이 그 계약이다.

`conformance_check` 행에 `method`·`required_method`·`unverified_scope` 를 남긴다.
마지막 칸이 이 단계의 요점이다 — 그것이 없으면 두 방식이 같은 `pass` 로 보이고 그
순간 "미실행을 통과로 표시하지 않는다"(D-25)가 깨진다. 화면도 `통과(가벼운 확인)` 와
`통과(독립 의미 검토)` 를 구별하고 보지 않은 범위를 함께 적는다.

**확인한 원문이 지금 원문인지도 본다.** 내용이 바뀌면 그 확인은 다른 것을 본
결과이므로 게이트가 통과하지 않는다.

### 3.7 누적 material delta

비교 대상은 **마지막으로 동의된 의도**다. AI 자신의 직전 초안이 아니다(D-60) —
초안끼리 비교하면 작은 변경을 연속 채택해 원래 요청과 다른 결과로 이동할 수 있다.

제어부는 본문을 읽지 않으므로 **구조화된 사실만으로** 분류한다.

| 관측 | 분류 | 처리 |
|---|---|---|
| 이 버전이 사용자 피드백을 반영했고 바뀐 항목의 출처가 사용자 요구·프로젝트 규칙 | `user_directed` | **위임 기준을 갱신**하고 막지 않는다 |
| 동의된 항목이 AI 출처로 바뀌었다 | `material` | `pending` 으로 쌓이고 의존 작업을 막는다 |
| 성공 기준의 추가·삭제·요약 변경 | `material` | 〃 |
| 아직 동의되지 않은 항목의 변경 | `draft_work` | 기록하고 자동 진행 |

**과다 차단인 것을 알고 있다.** "문구만 정리"와 "의미 변경"을 본문 없이 구별할 수
없으므로 동의된 항목의 AI 출처 변경을 전부 `material` 로 본다. 방향이 안전한 쪽이고,
사용자 지시 경로가 정상 흐름을 연다.

**AI 의 평가는 근거가 아니다.** `record_delta_assessment()` 는 `state` 를 건드리지
않으며, 그 함수에 해소 분기가 하나라도 있으면 AI 가 자기 평가로 차단을 푼다.
해소되는 경로는 사람의 확인과 사용자 지시 둘뿐이고, **한 번의 확인은 한 건에만**
적용된다 — 누적 전체의 승인이 되면 누적을 세는 의미가 없다.

차단 범위는 그 변경이 가리키는 기준에 붙은 Task 다. 의도 항목·저장소 허용의 변경과
연결을 모르는 변경은 **전부 막는다** — 모르는 것을 안전한 쪽으로 읽으면 연결하지
않는 것만으로 차단이 사라진다.

### 3.8 피드백 영향의 자동 연결

v0.6 은 새 의도 버전이 생기는 순간 이전 판정을 **전부** `needs_recheck` 로 내렸다.
그 규칙은 "의도가 바뀌면 연결된 성공 기준을 재검토한다"를 지키지만 **한 항목을 고친
피드백 하나가 모든 검증을 무효로 만든다.** intent-artifacts 69행은 그 뒤에 "영향이
없는 기록은 유지한다"를 함께 요구한다.

그래서 판단을 구조 보고 뒤로 옮겼다. 기준의 지문(요약·확인 방법·연결 항목)이 같고
**그 기준이 가리키는 의도 항목이 바뀌지 않았으면** 이전 판정을 잇고, 이어지지 않은
판정만 `needs_recheck` 가 된다. 이어진 판정에는 `recheck_source = carried_from:<id>`
가 남아 "이번 버전에서 다시 확인한 것이 아니다"가 드러난다.

### 3.9 목적의 경계와 로컬 실험

`root_cause_analysis`·`research` Case 에서 `feature_implementation` 은
`purpose_outside_case_objective` 로 거부된다(D-66·FR-20). 넓히는 방법은 **사용자의
명시 결정** 하나이며 Profile 재분류로는 넓혀지지 않는다(D-62).

새 목적 `local_experiment` 는 **쓰기를 받지만 기능 개발 pipeline 을 받지 않는다.**

- 요구하는 것: 준비된 작업공간, 대상 저장소 기록, 예산 예약, 쓰기 직렬화.
  **R2·R3 의 검사를 전부 지난다** — 사용자의 미커밋 변경을 보호하는 것은 실험이라고
  면제되지 않는다.
- 요구하지 않는 것: 설계·계획·결합 기록, 작업 그래프.
- **Profile 이 기록되지 않은 Case 에서는 열지 않는다.** 유도한 목적으로 쓰기를 여는
  것은 "유도해 채우지 않는다"(D-62)를 가장 비싼 방식으로 어기는 일이다.

실행 효과는 `run.is_experiment` 로 표시되며 **요청이 스스로 주장하지 못한다** —
목적에서 도출한다. 요청이 그 구별을 정하면 임시 변경을 실험으로 적어 검증을 건너뛸
수 있다. 지시문도 검증과 **반대 방향**이다(검증은 "제품 코드를 고치지 마라", 실험은
"재현에 필요한 만큼 임시로 고쳐도 된다") — 하나로 합치면 둘 중 하나가 거짓이 된다.

### 3.10 무변경 충족과 미재현

`criterion_result.satisfaction` 에 세 값을 둔다.

| 값 | `met` 가능 | 요구 |
|---|---|---|
| `changed_and_verified` | ○ | — |
| `already_satisfied` | ○ | **검증 실행의 증거**(`evidence_kind = run_output`) |
| `not_reproduced` | **×** | — |

마지막 줄을 **쓰기 경로에서** 막는다. 화면 문구로만 구별하면 API 직접 호출로
우회된다. `already_satisfied` 가 실행 증거를 요구하는 이유는 사람 판단만으로 적으면
미재현과 구별되지 않기 때문이다.

## 4. 성공 기준 대조

| # | 기준 | 근거 |
|---|---|---|
| AC-1 | controlled 는 시작 확인 전 작업을 거부하고 사유가 기록된다 | `test_controlled_refuses_work_before_the_start_is_confirmed`, **라이브** 409 `controlled_start_not_confirmed` |
| AC-2 | 초안·의미 검토·조사는 확인 전에도 배정된다 | `test_controlled_still_allows_the_draft_and_the_investigation` |
| AC-3 | 확인이 `superseded` 되면 다시 막히고 기록은 남는다 | `test_superseding_the_start_confirmation_blocks_again` |
| AC-4 | 기본 정책이 사람 인수 없이 완료한다 | `test_the_default_policy_completes_without_a_person`, **라이브** `mode=auto_policy actor=policy:auto_on_conditions` |
| AC-5 | 미충족·미정리 실행이 있으면 자동 완료하지 않는다 | `test_auto_completion_does_not_fire_while_something_is_unresolved`, `test_auto_completion_waits_for_an_unsettled_run`, `test_a_case_without_criteria_never_auto_completes` |
| AC-6 | 자동 완료 Case 에서도 **사람은** 예외를 수용할 수 있다 | `test_a_person_can_still_accept_an_exception_under_the_auto_policy` |
| AC-7 | controlled 는 결과 후보 확인 전 종료되지 않고 확인 뒤 종료된다 | `test_controlled_does_not_close_before_the_result_is_confirmed`, `test_confirming_the_result_closes_the_case` |
| AC-8 | 바뀐 후보에 이전 확인을 쓰지 않고, 같은 내용에는 재확인하지 않는다 | `test_a_changed_candidate_needs_a_new_confirmation`, `test_the_same_candidate_is_not_re_confirmed` |
| AC-9 | 명시 설정이 도출값을 이기고 출처가 구별된다 | `test_an_explicit_completion_setting_beats_the_derived_one` |
| AC-10 | Fast Lane 은 결합 기록 하나로 배정된다 | `test_a_fast_lane_case_needs_only_the_combined_record`, `test_the_two_stage_path_still_works_in_a_fast_lane_case` |
| AC-11 | 이탈은 준비 추가를 말하고 사람 확인을 요구하지 않는다 | `test_leaving_the_fast_lane_asks_for_preparation_not_for_a_person` |
| AC-12 | 결합 기록도 필수 항목이 미정이면 거부된다 | `test_a_combined_record_with_a_missing_section_is_refused` |
| AC-13 | 정합성 확인은 끌 수 없고 미기록은 `not_run` 이다 | `test_the_conformance_check_cannot_be_skipped` |
| AC-14 | 가벼운 확인이 독립 검토로 표시되지 않는다 | `test_a_light_check_passes_the_gate_but_says_what_it_did_not_see`, `test_an_independent_review_is_recorded_as_a_conformance_check`, **라이브** `verdict=pass ai=not_run` |
| AC-15 | 위험·불확실성에서는 가벼운 확인으로 통과하지 않고 설정으로 낮출 수 없다 | `test_risk_forces_the_independent_review`(2건), `test_a_case_setting_can_raise_but_not_lower_the_requirement`, **라이브** `required=independent` |
| AC-16 | 독립 검토는 여전히 별도 세션이다 | `test_the_independent_review_is_still_a_separate_session` |
| AC-17 | 검토 기본값이 도출되고 조건 충족 시 기록된다 | `test_the_stage_review_default_comes_from_autonomy`, `test_auto_proceed_is_recorded_as_soon_as_the_conditions_hold`, `test_auto_proceed_still_needs_its_condition_record` |
| AC-18 | AI 출처 변경이 `pending` 으로 쌓이고 의존 작업을 막는다 | `test_an_ai_change_to_an_agreed_intent_becomes_a_pending_delta`, `test_a_pending_delta_blocks_the_dependent_work` |
| AC-19 | 사용자 지시 변경은 위임 기준을 갱신한다 | `test_a_user_directed_change_updates_the_delegation_instead` |
| AC-20 | 누적 차이가 마지막 위임 기준과 비교된다 | `test_deltas_accumulate_against_the_last_delegation` |
| AC-21 | AI 평가만으로 `pending` 이 풀리지 않는다 | `test_an_ai_assessment_does_not_clear_a_pending_delta` |
| AC-22 | 영향받는 기준만 재검토가 되고 무관한 판정은 유지된다 | `test_an_unaffected_criterion_keeps_its_verdict`, `test_a_changed_criterion_does_not_keep_its_verdict` |
| AC-23 | 조사 Case 의 목적 확대가 막히고 사용자 결정으로만 넓어진다 | `test_an_analysis_case_cannot_widen_into_a_product_change`, `test_a_user_decision_widens_the_objective` |
| AC-24 | 실험은 pipeline 을 받지 않되 작업공간·Profile 은 요구한다 | `test_a_local_experiment_does_not_need_the_feature_pipeline`, `test_a_local_experiment_needs_a_recorded_profile` |
| AC-25 | 실험 변경이 제품 변경과 구별된다 | `test_an_experiment_run_is_marked_as_one` |
| AC-26 | 미재현은 `met` 이 되지 않고 무변경 충족은 실행 증거를 요구한다 | `test_not_reproducing_a_defect_is_not_a_met_criterion`, `test_an_already_satisfied_goal_needs_run_evidence` |
| AC-27 | 자동 경로가 R2·R3 의 검사를 우회하지 않는다 | `test_the_automatic_path_still_passes_the_repository_check`, `test_the_automatic_path_still_passes_the_budget_check` |
| AC-28 | 강제 종료 후 확인·delta·정합성이 복원된다 | `test_progression_records_survive_a_forced_kill`(**실제 프로세스 종료**), `test_the_progression_records_survive_a_reopened_database` |
| AC-29 | v10 DB 의 기본값이 바뀌지 않는다 | `test_a_v10_database_keeps_its_completion_and_review_defaults` |
| AC-29b | 취급은 적용될 뿐 기록되지 않는다 | `test_an_unrecorded_autonomy_is_treated_as_controlled`, `test_a_pre_r1_case_is_never_reported_as_ask_on_decision`(**갱신 없이 통과**) |
| AC-30 | 두 축이 강제로 바뀌고 게시만 남는다 | `test_the_policy_view_says_who_enforces_each_axis`, `test_budget_enforcement_did_not_spread_to_the_other_axes`, `test_the_enforcement_table_now_shows_four_enforced_axes` |
| AC-31 | 새 표에 본문이 없다 | `test_the_controller_keeps_no_bodies_in_the_new_tables` |
| AC-32 | 실제 CLI 로 자동 진행 경로가 동작한다 | **라이브** 5절 |

## 5. 라이브 확인 원문 요약

실제 제어부·Runner 프로세스와 실제 git 저장소 하나, 실제 codex 실행 6회
(codex-cli 0.154.0). 두 벌로 나눈 이유는 **한 Case 가 두 경로를 동시에 탈 수 없기**
때문이다 — controlled 와 기본 자율 진행은 서로 다른 Case 다. 아래 값은 **고친 뒤
재실행한** 실행의 것이며, 고치기 전 실행이 드러낸 것은 6.1에 있다.

### 5.1 controlled 가 실제로 막고 실제로 열린다

```
강제 표시: autonomy=enforced, controlled_checkpoint=enforced, budget=enforced,
          repository_selection=enforced, publish=not_implemented
확인 지점: start_scope=required, result_candidate=required
완료 모드: human_acceptance (autonomy_derived)

시작 확인 전 설계 요청: HTTP 409
  ['intent_not_agreed', 'intent_gate_not_passed', 'controlled_start_not_confirmed']
시작 확인 뒤 같은 요청: HTTP 409
  ['intent_not_agreed', 'intent_gate_not_passed']
```

**확인 뒤에도 409 인 것이 정상이다.** 이 Case 는 의도 동의와 QG-01 을 아직 거치지
않았고, 그 둘은 Autonomy 와 **다른 조건**이다. 사라진 것은
`controlled_start_not_confirmed` 하나이며 그것이 이 축이 실제로 막았다가 열렸다는
증거다. 축이 서로를 대신하지 않는다는 사실이 같은 줄에 함께 보인다.

### 5.2 위험이 있으면 가벼운 확인으로 통과하지 않는다

실제 codex 가 쓴 초안의 수준 판단이 `standard` 였고 근거 부족 축이 있었다.

```
수준: standard · Fast Lane: False
      ['level_not_simple', 'evidence_gap', 'open_intent_questions']
정합성 요구: independent 이유=['level_above_simple', 'evidence_gap']
독립 검토 종료: outcome=completed
정합성 결과: method=independent verdict=pass
QG-01: verdict=pass rule=pass ai=pass
단계 검토 기본값: design=auto_proceed(autonomy_derived) plan=auto_proceed
```

**규칙이 가벼운 확인을 허용하지 않았고, 그래서 독립 검토가 돌았다.** 이 경로는
사람이 고른 것이 아니라 기록된 사실(수준·근거 부족)에서 도출됐다.

### 5.3 Fast Lane 은 결합 기록 하나로 돌고 가벼운 확인이 통과시킨다

같은 저장소에 **명확하고 저위험인 요청**을 주자 실제 codex 의 수준 판단이 `simple`
로 나왔고 열린 질문이 없었다.

```
수준: simple (도출 simple)
Fast Lane: True []
가벼운 확인: method=light verdict=pass
확인하지 않은 범위: 원문의 의미 대응을 AI 가 검토하지 않았다.
                    구조·참조·버전·필수 항목의 결정적 검사만 수행했다
QG-01: verdict=pass ai=not_run          ← **AI 검토는 실제로 돌지 않았다**

결합 기록 실행: outcome=completed
결합 기록: 있음 · 상태=auto_conditions_met
설계 산출물: 없음
계획 산출물: 없음
작업 그래프: present=True tasks=['T1', 'T2']
```

**`ai=not_run` 인 채로 `verdict=pass` 인 것이 이 단계의 요점이다.** 가벼운 확인이
게이트를 통과시키되 **독립 검토를 한 것으로 적지 않았고**, 무엇을 보지 않았는지가
값으로 남았다. 그리고 설계·계획 산출물이 **하나도 없는 채로** 작업 그래프가 섰다 —
결합 기록 한 건이 두 산출물의 자리를 실제로 대신했다.

자동 진행 기록도 사람 승인이 아니다(`auto_conditions_met`).

### 5.4 기본 자동 완료가 사람 인수 없이 닫는다

```
완료 모드: auto_on_conditions (autonomy_derived)
  C-01..C-04 판정 기록 → HTTP 200
Case 상태: closed
종료 기록: completed
인수 기록: mode=auto_policy actor=policy:auto_on_conditions
사람 인수 결정 행: ['policy:auto_on_conditions']
```

**마지막 기준을 기록하는 순간 시스템이 닫았다.** 사람이 "완료"를 부른 적이 없고,
`decision` 표의 인수 행 주체도 정책 식별자다 — 있지도 않은 사람의 확인이 만들어지지
않았다(D-31).

## 6. 구현·라이브가 찾은 결함

### 6.1 결합 기록의 지시문에 출력 형식을 빠뜨렸다 (라이브가 찾음, AC-10)

첫 Fast Lane 라이브에서 결합 기록 실행이 `outcome = failed` 로 끝났다. 실제 codex 가
낸 것은 이런 모양이었다.

```json
{"doc_type": "hads.combined-record", "doc_version": 1,
 "sections": [{"key": "change_summary", "content": {"location": "reader.py", ...}}],
 "tasks": [{"id": "T-01", "title": "...", "completion_conditions": [...]}]}
```

기대한 것은 `sections` 가 **객체**이고 키가 항목 이름 그대로이며 `tasks` 가
`key`/`purpose`/`deliverable`/`completion` 을 갖는 모양이다.

원인: 새로 쓴 결합 기록 지시문이 "출력 형태는 개발계획과 같다"는 **한 줄**로
끝났다. 설계·계획 지시문은 실제 JSON 템플릿을 그대로 보여 주는데 그 블록을 옮기지
않았다.

**자동 시험은 이 구멍을 볼 수 없다.** `FakeCliExecutor` 는 `fake_preparation_response`
로 언제나 올바른 형식을 내므로, 지시문이 형식을 말하든 말든 시험은 통과한다.

고침: 결합 기록 지시문에 같은 JSON 템플릿을 넣고 "**sections 는 객체이고 키는 위
항목 이름 그대로다** — 목록으로 내거나 이름을 바꾸면 시스템이 읽지 못해 이 실행은
실패한다"를 명시했다. 재실행에서 `outcome = completed` 와 작업 그래프 생성을 확인했다.

**남는 사실:** 지시문의 정확성은 자동 시험이 보장하지 못한다. 새 지시문을 만들면
실제 CLI 로 한 번 돌려 봐야 한다.

### 6.2 자동 완료가 사람의 예외 수용까지 막고 있었다 (구현 중)

`record_exception_decision()` 이 완료 모드가 `auto_on_conditions` 이면 **사람의** 예외
수용을 거부하고 "사람 확인으로 되돌린 뒤 수용하라"고 답하고 있었다. v0.6 에서는 그
모드가 사람이 일부러 고른 것이라 큰 문제가 아니었다.

**v0.7 에서 자동이 기본이 되면 그 규칙은 "기본 Case 에서는 사람이 예외를 수용할 수
없다"가 된다** — D-32 와 completion-lifecycle 4절에 정면으로 어긋난다.

막아야 하는 것은 "자동 정책이 **스스로** 예외를 수용하는 것" 하나이며 그 검사는
`check_acceptance(AUTO_POLICY)` 에 그대로 있다. 두 문장을 한 곳에서 처리하고 있었던
것이고, 합치면 사람의 결정 경로가 정책 설정에 묶인다. 요청 경로의 거부를 걷어내고
짝이 되는 시험을 더했다
(`test_a_person_can_still_accept_an_exception_under_the_auto_policy`).

### 6.3 자동 진행 기록이 그 뒤의 사람 검토를 삼켰다 (구현 중)

자동 진행을 **조건 충족 시점에** 기록하도록 바꾸자 R4 이전에는 있을 수 없던 상태가
생겼다 — 자동 조건이 기록된 뒤에 사람이 실제로 검토하는 경우다.
`record_stage_review()` 는 기존 기록이 있으면 그대로 돌려주므로 **실제로 있었던
사람의 검토가 사라진다.**

`UNIQUE (preparation_id)` 는 "이 산출물의 검토 상태는 하나"를 지키므로 풀지 않았다.
대신 사람 검토가 자동 조건 충족보다 **강한 사실**이므로 그쪽이 남게 했다. 방향이
중요하다 — 없는 사람의 검토를 만드는 것이 아니라 있었던 검토를 적는 것이다.

### 6.4 "영향받은 것만"을 붙일 입력이 이미 지워지고 있었다 (구현 중)

계획 3.7절은 피드백 영향을 **더하는** 일로 적었다. 구현해 보니 그 전에 걷어내야 하는
것이 있었다 — `create_intent_version()` 이 새 버전이 생기는 순간 이전 판정을 **전부**
`needs_recheck` 로 내리고 있었다. 그 상태에서는 무엇이 영향을 받았는지 비교할 입력
자체가 없다.

재검토 표시를 `_carry_unaffected_results()` 안으로 옮겨 **구조가 보고된 뒤** 판단하게
했다. 이어지지 않은 판정만 `needs_recheck` 가 된다. 이어 가는 조건도 좁혔다 —
기준의 지문이 같아도 **그 기준이 가리키는 의도 항목이 바뀌었으면 잇지 않는다.**

이 변경은 `test_results.py` 의 "새 버전은 판정을 승계하지 않는다" 시험이 고정하던
v0.6 규칙을 바꾼다. **지우지 않고** 영향을 받는 경우를 확인하도록 고쳤고, 받지 않는
경우는 `test_progression.py` 가 짝으로 확인한다.

### 6.5 라이브 스크립트가 같은 `run_id` 를 재사용했다 (시험 환경)

두 번째 라이브 시도에서 아무 일도 일어나지 않았다. 제어부 DB 를 그대로 둔 채 같은
`run_id` 로 요청했고, `create_run()` 이 **멱등하게 기존 실행을 돌려준** 것이다. 그
실행은 이전 시도의 것이고 다른 Case 에 속한다.

**제품 결함이 아니라 P2-01이 일부러 만든 멱등성이 제대로 동작한 것이다.** 기록으로
남기는 이유는 라이브 스크립트를 다시 쓰는 사람이 같은 곳에 빠지기 때문이다 — 실행
id 에 시도마다 달라지는 값을 붙였다.

## 7. 하지 않은 것 · 미검증

| 항목 | 위치 |
|---|---|
| 게시 허용·실제 push·PR·기록 이슈 | **P5**. 네 축이 강제로 바뀐 것이 게시 권한을 만들지 않는다 |
| 외부 CI 대기와 CI 수정 후 재확인 | **P5**. controlled 의 순서에서 게시 뒤 부분이다 |
| `RemediationCycle`·repair 한도 | **P4-01** |
| QG-02~07 추가 게이트 | **P4-01** |
| 지식 주입·추출 | **P4-06·P4-07**. 생기면 같은 예약·같은 진입 경로를 탄다 |
| 여섯 Profile 대표 시나리오 전수 | **P4-03**. R4 는 목적의 **경계**만 강제한다 |
| 실행 중 안전 정지 | **P6-03**. R4 가 막는 것은 배정이다 |
| Project·Task 단위 정책 조정 | 계층이 없다. **만들지 않았다** |
| 본문 의미의 delta 판정 | 하지 않는다. 제어부는 본문을 읽지 않으며 과다 차단 쪽을 골랐다 |
| 가벼운 확인의 의미 검증 | **하지 않는다.** 그것이 `unverified_scope` 에 값으로 남는 이유다 |

## 8. 이 단계가 만든 새 사실

- `enforcement.autonomy` 와 `enforcement.controlled_checkpoint` 가
  `recorded_not_enforced` → **`enforced`** 로 바뀌었다. R1이 "강제 없음"을 고정한
  시험을 갱신했다(`test_policy.py`·`test_budget.py`). **통과한 채로 남았다면 강제를
  붙이지 않은 것이다.** 이제 `publish` 만 남는다(P5).
- `RunPurpose.LOCAL_EXPERIMENT` 와 `PreparationStage.COMBINED` 가 생겼다. 둘 다
  **기존 목적·단계의 조건을 느슨하게 만들지 않는다** — 각각 자기 조건표를 갖는다.
- 새 거부 사유 아홉: `controlled_start_not_confirmed`,
  `purpose_outside_case_objective`, `material_delta_unconfirmed`,
  `fast_lane_left_needs_preparation`, `combined_record_{missing,stale,
  incomplete_for_level,review_missing}`, `profile_not_recorded`. 인수 쪽에 넷:
  `controlled_{start,result}_not_confirmed`, `controlled_confirmation_stale`,
  `material_delta_unconfirmed`.
- **v0.6 기본값 둘이 뒤집혔다.** 완료(사람 인수 → 조건 충족 자동)와 단계 검토(사람
  검토 → 자동 진행). 둘 다 **기존 Case 에는 소급하지 않는다** — 명시 설정 행과
  Autonomy 미기록 Case 가 그 경계다.
- `criterion_result` 의 판정이 **버전을 넘어 이어질 수 있다.** 이어진 것과 다시
  확인한 것은 `recheck_source` 로 구별된다.
