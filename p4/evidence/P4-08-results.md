# P4-08 실행 결과 — 여섯 Profile 대표 흐름의 진행기 경유 재현 + 혼합 목적의 완료

상태: **완료**
기준: [P4-PLAN-08](../../plans/P4-PLAN-08.md) / [P4 수용 확인](P4-ACCEPT-results.md) 1.1·1.2·4절(빠진 것) / [case-profiles](../../case-profiles.md)
4·5·6절 / 2026-09-24. 세션 S-034(같은 대화에서 S-033 push 뒤 사용자 지시 "P4-PLAN-08 먼저 하고 닫아줘" 로 이어서). 선행
[P4-03](P4-03-results.md)(완료 계약)·[P4-05](P4-05-results.md)(진행기)·[UI-04c](../../ui/evidence/UI-04c-results.md)(개정).

**제품 코드는 바꾸지 않았다.** 새 시험 파일 하나(`tests/test_profile_flows.py`, 13건)가 defect-fix·refactoring·maintenance 와 혼합 목적을
P4-05 의 진행기 경로(업무화 → 의도 초안 → 동의 → 결합 기록 → 작업공간 → 구현·검증 → 기준 판정 → 완료/미완료)로 지나며, 가짜 CLI 의
응답만 Profile 에 맞게 바꾼다. 시험이 드러낸 제품 결함은 **없다**(3절). 제품 판단도 새로 내리지 않았다 — 대표 흐름은 case-profiles
4절의 완료 의미와 6절 시나리오 6·7·8·10 그대로다.

## 1. 구현 결과 (시험)

| 시험 | 무엇을 지나는가 | 고정한 것 |
|---|---|---|
| `test_a_defect_fix_restores_the_behavior_through_the_progressor` | defect_fix 업무화 → 동의 → 결합 기록 → 구현 → 검증 → 자동 완료 | 기준 둘의 의무 `restoration`(`derived_from_field`)·`changed_and_verified`, 실행 순서 다섯, 사람 결정은 동의 하나, `completion_meaning` 의 `restoration` = `met`·`required_by = [profile]` |
| `test_an_already_fixed_defect_closes_from_a_verification_run_alone` | 계획에 **검증 Task 만** → 작업공간 → 검증(아무것도 쓰지 않음) → 자동 완료 | 구현 실행 없이 닫힘, 기준 둘 `already_satisfied`·근거 = 그 검증 실행, 검증 실행의 트리 변경 없음 |
| `test_a_failed_reproduction_records_nothing_and_waits` | 검증 명령이 exit 1(미재현) 인데 `met` 보고 | 아무 기준도 적히지 않고(`no_successful_command` 가 진행 이력에) `unverified` 그대로 → `criteria_unresolved` 대기·자동 완료 거부·종료 없음 |
| `test_a_refactoring_closes_when_improvement_and_preservation_are_each_verified` | refactoring — C-01 `improvement_target`·C-02 `preserved_contracts` → 구현 → 검증 → 자동 완료 | C-01 `improvement`/`changed_and_verified`, C-02 `preservation`/`preserved`(검증 실행 근거), 둘 다 `required_by = [profile]` |
| `test_a_refactoring_without_a_preservation_criterion_waits_instead_of_closing` | 개선 기준만 있는 refactoring → 검증이 개선을 충족 | `objective_without_criteria` 대기(`obligations = [preservation]`), `missing = [preservation]`, 자동 완료 거부, 종료 없음 |
| `test_a_refactoring_whose_preservation_fails_keeps_the_verdict_and_waits` | 보존 기준 `not_met` 보고 | `criteria_unresolved` 대기(C-02), 개선은 `met` 그대로·보존은 `not_met`·방식 없음, `preservation` = `open` |
| `test_maintenance_requires_preservation_only_when_conditions_are_written[conditions-both]` | `preserved_conditions` 를 적은 maintenance — C-01 `target_state`·C-02 `preserved_conditions` | `target_state`/`changed_and_verified` + `preservation`/`preserved`(`required_by = [profile_conditional]`) → 닫힘 |
| `…[conditions-target-only]` | 조건을 적었는데 보존 기준이 없음 | `objective_without_criteria` 대기·`missing = [preservation]`·종료 없음 |
| `…[no-conditions]` | 조건을 적지 않은 maintenance — 목표 상태 기준만 | `preservation` 행 없음·`missing = []` → 닫힘 |
| `test_a_revised_case_closes_only_when_the_cause_and_the_fix_are_both_proven[both-proven]` | RCA(분석 판단 불가 → `criteria_unresolved`) → defect_fix 개정 → 의도 재작성 → delta 확인 → 동의 → 결합 기록 → 구현 → 검증 | 검증 실행이 C-01·C-02(`cause`, 이전 `not_met` 승계)를 `met`·`investigated`·`determined` 로 적고(근거 = 검증 실행 — `INVESTIGATION_EVIDENCE_PURPOSES` 에 검증 실행이 있다) C-03(`restoration`)을 `changed_and_verified` 로 → `declared_objectives = [cause, restoration]` 둘 다 `met` → `completed` |
| `…[fix-only]` | 같은 경로, 검증이 C-03 만 충족하고 원인은 판단 불가 | `criteria_unresolved` 대기(C-01·C-02), 원인 `not_met`·`inconclusive`, `cause` = `open`·`restoration` = `met`, 자동 완료 거부·종료 없음 |
| `test_a_defect_fix_that_declared_the_cause_from_the_start_needs_both[both-proven]` | 처음부터 defect_fix + 선언 목적 `cause`(C-01 `obligation: cause` 보고값) | `cause` `required_by = [declared]`·`restoration` `[profile]`, 둘 다 충족 → 자동 완료 |
| `…[fix-only]` | 같은 Case, 원인 판단 불가 | `criteria_unresolved` 대기(C-01), `cause` = `open` |

시험 도우미(제품 아님): `_draft`(기본 초안의 기준 연결 항목·의무·항목·선언 목적만 바꾼다), `_tasks`/`_plan`(구현 하나 + 기준 전부를
`verifies` 로 잇는 검증 하나, 또는 검증만), `_verification`(명령 하나 + 기준별 판정 — **방식은 적지 않는다**, 진행기가 의무에서 정한다).
기존 시험·도구는 바꾸지 않았다.

## 2. 성공 기준 대조

| AC | 근거 | 결과 |
|---|---|---|
| AC-1 defect-fix 복원 | `test_a_defect_fix_restores_the_behavior_through_the_progressor` | 통과 |
| AC-2 무변경 완료·미재현 | `test_an_already_fixed_defect_closes_from_a_verification_run_alone`(구현 실행 없이 `already_satisfied`), `test_a_failed_reproduction_records_nothing_and_waits`(exit 1 → 적지 않음). `not_reproduced` 는 보고 형식에 없다 — 진행기 경로의 방식은 `decide_criteria` 가 의무·변경 관측에서 정하므로 보고가 그것을 고를 수 없다(P4-03 의 API 거부 규칙은 그대로) | 통과 |
| AC-3 refactoring | 위 refactoring 시험 셋(각각 충족·보존 기준 없음·보존 미충족) | 통과 |
| AC-4 maintenance | 매개변수 시험 셋(조건+둘·조건+목표만·조건 없음) | 통과 |
| AC-5 혼합 목적 | 개정 경로 둘(both/fix-only) + 처음부터 선언 경로 둘 | 통과 |
| AC-6 강제 축·진입 검사 그대로 | 제품 코드 diff 없음(`git status` 가 새 시험 파일뿐), 기존 시험 전부 통과(3절), 조사 Profile 의 쓰기 가드·controlled·예산 시험 그대로 | 통과 |
| AC-7 전체 통과·근거 표 갱신 | 3절 최종 실행, [P4 수용 확인](P4-ACCEPT-results.md) 1.1·1.2·4절 갱신 | 통과 |
| AC-8 실제 codex 의도 작성(maintenance·RCA) | **선택 사항 — 미수행**(사용자에게 그 뜻을 설명하고 판단을 기다린다, S-034 인계) | 미수행 |

## 3. 검증

- **기준선**(S-033, 코드 변경 없음, `scripts\run-tests.ps1`): 웹 빌드 성공, 웹 단위 **37**, pytest **740 통과·0 실패·2 건너뜀**(15분 7초), P1 계약 **18**.
- **새 시험의 첫 회차**: 13건 중 10 통과·3 실패 — 전부 **시험 결함**이었다. (1) 무변경 완료 시험이 검증 실행의 트리 변경 없음을 단언했는데
  가짜 CLI 가 쓰기 권한 실행(검증도 `workspace_write`)마다 `write_files` 를 쓴다 → 시험이 검증 전에 `write_files = {}` 로 둔다(이미 고쳐진
  코드를 관측만 하는 시나리오). 그 전에도 제품은 `already_satisfied` 로 닫았다 — `_product_change_observed` 는 **구현 실행**의 변경만
  본다(관찰, 4절). (2)(3) 개정 경로 시험이 동의 **뒤에** 실행 수를 셌는데 동의 자체가 진행기의 다음 실행(결합 기록)을 동기적으로 만든다
  → 동의 전에 센다. 고친 뒤 **13/13 통과**.
- **최종**(`scripts\run-tests.ps1`, 새 시험 추가 뒤): 웹 빌드 성공, 웹 단위 **37**, pytest **752 통과·1 실패·2 건너뜀**(15분 28초 — 기준선 740 에서
  **+13** = 이 파일 13건). 실패 1건은 DEVELOPMENT 9절의 기존 시계 해상도 흔들림 시험(`tests/test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure`,
  `applied_at == requested_at` 한 틱)이며 이 변경과 무관하다 — 단독 3회 전부 통과. 스크립트가 pytest 실패로 멈춰 P1 계약은 따로 실행: **18** 통과.
  건너뜀 2건은 이행 시험의 옛 스키마 커밋 창. 이 파일 13건은 전체 실행 안에서 통과했다.
- 제품 결함: **없음.** 제품 코드·스키마·정책·지시문 무변경.

## 4. 관찰·경계

- **검증 실행의 트리 변경은 제품 변경으로 세지 않는다.** `_product_change_observed` 는 완료된 구현 실행의 `workspace_effect.changed` 만
  본다(P4-05). 검증 실행이 쓰기 권한으로 돌아 파일을 바꿔도 `already_satisfied` 판정에는 영향이 없다 — 검증이 제품을 고치는 것은
  예상 밖의 일이며 `workspace_effect` 에 관측으로 남는다. 바꾸지 않았다(P4-05 의 규칙).
- **혼합 목적의 원인 결론은 검증 실행도 근거가 된다**(`INVESTIGATION_EVIDENCE_PURPOSES` 에 `verification_run`). 제품 변경 Profile 은
  분석 단계를 지나지 않으므로 개정 뒤 `cause` 기준은 검증 실행의 보고(`conclusion`)로 닫힌다 — 그것이 P4-03 계약의 뜻이며 바꾸지 않았다.
- 강제 축 넷·`enforcement`·진입 검사·정책·스키마 v27 그대로. 사람의 결정은 어느 시험에서도 동의 하나(또는 개정 폼)뿐이다.
- 실제 codex 의 maintenance·RCA 의도 작성 표본은 여전히 없다(AC-8 선택 사항). 검증 환경(실제 codex 가 시험을 돌리는가)은 별도 실험
  [P4-ENV 결과](P4-ENV-results.md).
