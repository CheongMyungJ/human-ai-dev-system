# P4-03 실행 결과 — 여섯 Profile

상태: **완료**  
기준: 설계 v0.7 / D-01~67 / 2026-09-23  
계획: [P4-PLAN-03](../../plans/P4-PLAN-03.md)

## 1. 구현 결과

- **완료 판정이 Profile 을 본다.** 지금까지 여섯 Profile 모두 "현재 기준이 전부 `met`"
  하나였다. Profile 정의 **v2** 가 목적별 **완료 계약**(`CompletionContract`)을 갖고,
  새 Case 는 v2 를 받는다(`CURRENT_PROFILE_VERSION = "2"`). 의미 항목·문장은 v1 과 같고
  계약만 더했다. **기존 Case 는 기록된 v1 그대로이며 계약이 없다** — 새 완료 규칙을
  소급하지 않는다(D-62).
- **기준이 무엇을 입증하는가가 값이 됐다.** 목적 의무(`obligation`) 일곱 —
  `behavior`·`restoration`·`cause`·`answer`·`improvement`·`preservation`·`target_state`.
  원문이 적으면 `reported`, 아니면 연결 항목에 정의의 대응표를 적용해
  `derived_from_field` 로 남긴다. 본문을 읽은 것이 아니라 공개된 정의의 적용이다.
- **Profile 별 필수 의무.** feature=behavior, defect-fix=restoration, RCA=cause,
  research=answer, refactoring=improvement **와** preservation, maintenance=target_state
  (+ `preserved_conditions` 가 채워졌으면 preservation). 요구된 의무에 기준이 하나도
  없으면 후보의 미해결 항목 `objective_without_criteria` 이고 자동·사람 인수 모두
  거부된다. 기준이 아니므로 **예외 수용 대상도 아니다**.
- **충족 방식 생략 우회를 막았다.** P3-R4 는 `not_reproduced` 로 적은 `met` 만 거부했고
  **아무것도 적지 않은** `met` 은 받았다 — 미재현을 해결로 만드는 데 필요한 것은 방식을
  비워 두는 것 하나였다. v2 기준의 `met` 은 방식이 필수이고 의무마다 허용 방식이 다르다
  (`investigated` 는 원인·조사, `preserved` 는 보존만).
- **판단 불가를 구별한다.** 원인·조사 기준은 결론 요구(`conclusion_rule`)를 갖고 결과는
  결론(`determined`/`inconclusive`)을 적는다. 결론 요구가 **없으면 확정 필수로 취급**한다.
  확정 필수 기준의 판단 불가는 `not_met` 이며 사람이 예외로 수용해야 닫힌다(원래 판정
  보존). 판단 불가 허용 기준은 근거 있는 판단 불가로 `met` 이 되어 정상 완료한다.
- **무변경 성공의 근거를 좁혔다.** `already_satisfied`·`preserved` 는 **검증 실행**의
  관측이어야 한다. 구현 실행의 관측은 "바꿨다"는 기록 위의 관측이고, 실험은 임시 변경
  위의 관측이다. 구현 실행 없이 검증 실행의 관측만으로 결함 Case 가 닫힌다. 구현 실행
  자체의 판정("변경도 명령도 없으면 실패")은 바꾸지 않았다.
- **혼합 목적.** 의도 문서가 요청이 명시한 목적(`objectives`)을 적는다. 요구 의무 =
  Profile 필수 ∪ 조건부 ∪ 선언. "원인 확정과 수정"은 restoration 과 cause 기준이 각각
  충족돼야 닫힌다. **선언은 Profile 이 아니라 의도에 있다** — 대표 Profile 이 다른 목적을
  지우지 않는다. 조사 Profile 의 제품 수정 차단(D-66)은 선언으로 풀리지 않는다.
- **실험과 제품 증거를 나눴다.** 모델 주석만 있고 쓰이지 않던 `run.is_experiment` 가 이제
  판정에 쓰인다. 실험 실행은 `investigated` 의 근거로만 쓰이고 제품 의무의 근거가 되지
  않는다. 실험마다 실행 전후 트리 지문으로 **정리 상태를 도출**한다(`restored_in_run`·
  `restored_later`·`left_changes`·`unobserved`·`no_write_permission`·`not_finished`).
  제품 의무가 있는 Case 에 잔여(`left_changes`·`unobserved`)가 있으면 자동 완료하지 않고
  (`experiment_residue_unresolved`), 사람은 후보에 드러난 잔여를 보고 닫을 수 있다.
  조사 목적만인 Case 는 표시만 한다. 실험 지시문에 "끝나기 전에 되돌린다"를 더했다.
- **누적 변경.** 기준 지문에 의무·결론 요구를 **값이 있을 때만** 더했다. 결론 요구를
  확정 필수 → 판단 불가 허용으로 바꾸면 material delta 이고, v1 기준의 지문은 그대로다.
- 의도 문서 **v5**, AI 지시문·파서, 결과 조회의 `completion_meaning`, 후보의 `meaning`,
  화면(목적별 완료 의미·의무별 충족 방식 선택·결론·실험 정리), 스키마 **v15**.

## 2. 성공 기준 근거

시험 이름은 `tests/test_profile_completion.py`(표시 없음)와 `tests/test_migration.py` 의 것이다.

| 성공 기준 | 결과·근거 |
|---|---|
| AC-1 v1 Case 는 v1 규칙 | `test_a_v1_case_keeps_the_old_completion_rules` — 정의판 "1" Case 가 방식 없는 `met` 을 받고 보존 기준 없이 닫히며 후보 `meaning` 이 `None`(해시 모양 불변). `test_a_v1_case_does_not_accept_objectives` — 목적 선언 400 |
| AC-2 여섯 계약 | `test_every_current_profile_has_its_own_completion_contract` — 필수·조건부 의무, 현재 정의판 "2", v1 에 계약 없음·의미 항목 동일. `test_a_feature_closes_on_changed_and_verified_behavior` 가 feature 대표 흐름 |
| AC-3 의무와 출처 | `test_a_criterion_obligation_is_reported_or_derived_and_says_which` — `derived_from_field`/`reported` |
| AC-4 방식 필수·의무별 허용 | `test_met_without_saying_how_is_refused_on_a_v2_criterion`(`satisfaction_required`), `test_met_satisfaction_differs_by_obligation` |
| AC-5 defect-fix 무변경·미재현 | `test_a_defect_already_fixed_closes_without_any_code_change` — 검증 실행 하나로 완료, 구현 실행 0건. `test_already_satisfied_must_be_observed_by_a_verification_run` — 구현·실험 실행 근거 거부. 미재현 `met` 거부는 위 AC-4 시험 |
| AC-6 RCA 확정 필수 | `test_an_inconclusive_cause_is_not_success_when_the_cause_must_be_found` — 명시·미기록 둘 다 `inconclusive_not_allowed`, 결론 없는 `met` 거부, 자동 완료 없음, 예외 종료 뒤에도 `not_met`·`inconclusive` 보존 |
| AC-7 research 판단 불가 정상 | `test_a_bounded_research_can_close_with_an_inconclusive_answer_and_no_code`, `test_an_investigation_answer_needs_an_investigation_run`(초안 실행 거부, 실험 실행 허용) |
| AC-8 refactoring 개선+보존 | `test_a_refactoring_without_a_preservation_criterion_does_not_close`, `test_a_refactoring_closes_when_improvement_and_preservation_are_each_proven`(보존의 구현·실험 근거 거부, 검증 실행으로 완료) |
| AC-9 maintenance 조건부 보존 | `test_maintenance_asks_for_preservation_only_when_conditions_were_written` — `required_by = profile_conditional` |
| AC-10 혼합 목적 | `test_a_fix_that_also_asked_for_the_cause_needs_both`, `test_a_declared_objective_without_a_criterion_blocks_completion` |
| AC-11 목적 누락은 예외 불가 | 위 refactoring 시험 — 후보 미해결 `objective_without_criteria`, 사람 인수 409 |
| AC-12 실험 근거 제한 | feature·defect·refactoring 시험의 `experiment_evidence_not_product`, research 시험의 실험 근거 허용 |
| AC-13 정리 상태 도출 | `test_experiment_cleanup_is_derived_from_what_was_observed`(여섯 상태), `test_a_real_experiment_that_leaves_a_file_is_seen_as_residue` — **실제 git worktree** 에서 파일을 남긴 실험은 `left_changes`, 아무것도 쓰지 않은 실험은 `restored_in_run`, 원래 저장소 관측 `outside_workspace_changed = False` |
| AC-14 잔여와 자동 완료 | `test_experiment_residue_blocks_auto_completion_of_a_product_case_only` — 결함 Case 는 `experiment_residue_unresolved` 로 자동 완료 거부·사람 인수로 종료, RCA Case 는 잔여를 보이되 자동 완료 |
| AC-15 결론 요구 약화 | `test_weakening_a_conclusion_rule_is_a_material_change`(pending `material`), `test_a_v1_criterion_keeps_its_old_fingerprint` |
| AC-16 의도 문서 v5 | `test_the_v5_document_reports_enumerations_only`, `test_a_conclusion_rule_only_belongs_to_cause_and_answer_criteria` |
| AC-17 지시문·파서·실제 CLI | `test_the_intent_prompt_asks_for_the_contract_only_where_there_is_one`, `test_an_ai_draft_reports_objectives_and_obligations`, 그리고 3절의 실제 codex 3건 |
| AC-18 조회·후보·화면 | 결과 조회 `completion_meaning`·기준의 의무/결론 요구(적용값)/결론, 후보 `meaning`. `ResultPanel` 의 목적별 완료 의미·의무별 방식·결론 선택·실험 정리. 프로덕션 빌드 |
| AC-19 v14→v15 이행 | `test_a_v14_database_keeps_its_criteria_and_invents_no_obligation` — 의무·결론·목적 NULL, 정의판 "1" 유지, 판정 보존, 열거형 `CHECK`, 반복 이행 멱등 |
| AC-20 재시작 | `test_obligations_conclusions_and_meaning_survive_a_reopened_database` — 파일 DB 재개 |
| AC-21 기존 경계 | `test_declaring_a_product_objective_does_not_open_implementation_in_an_rca`, 전체 회귀 481 통과. `enforcement` 네 축·게시 미강제 그대로 |

## 3. 검증

| 검증 | 결과 |
|---|---|
| 기준선(시작 시) | `scripts\run-tests.ps1` — pytest **451**, unittest **18** 통과. 인계 수치와 일치 |
| P4-03 집중 시험 | `pytest tests/test_profile_completion.py` — **29 통과** |
| 이행 집중 시험 | `pytest tests/test_migration.py` — **10 통과**(v14→v15 신규 1건) |
| 전체 제품 시험 | `scripts\run-tests.ps1` — **pytest 481 통과**, 알려진 deprecation warning 2건 |
| P1 문서 계약 | 같은 스크립트 — **unittest 18 통과** |
| 웹 | `web`에서 `npm run build` — TypeScript/Vite 프로덕션 빌드 성공 |
| 재시작 | 파일 DB 를 닫고 다시 열어 의무·결론 요구·결론·선언 목적·후보 `meaning` 이 같음을 확인 |
| 실제 CLI | **수행.** `p4/live/profile_intents.py`, `codex-cli 0.154.0`, read-only 의도 작성 **3회**. 아래 |

실제 CLI 는 실제 제어부·Runner 프로세스(스키마 v15)와 합성 git 저장소(`store.py` 한 파일)로
돌렸다. 세 Case 모두 정의판 "2" 를 받았고, 세 실행 모두 `completed`, 구조 보고가 받아들여졌다.

| Case | 요청의 핵심 | codex 가 쓴 것 | 판정 |
|---|---|---|---|
| A defect-fix | "원인을 확정해 주시고 고쳐 주세요. 원인을 확정하지 못하면 완료가 아닙니다" | `objectives: ["cause"]`. C-01 `cause`+`definitive_required`, C-02 `restoration`, C-03 `preservation` | 지시대로. 선언 목적 cause 가 `required_by = declared` 로 요구됐다 |
| B research | "우열을 가리지 못하면 근거와 한계를 보고하는 것으로 충분합니다. 제품 코드는 바꾸지 마세요" | `objectives: []`. C-01~03 `answer`+`bounded_report_allowed`, C-04 `preservation`("제품 코드 상태 보존") | 지시대로 |
| C refactoring | "공개 함수 이름과 반환 형식은 그대로, 호출하는 쪽을 고치지 않아야" | C-01 `improvement`, C-02·C-03 `preservation`(둘 다 `preserved_contracts`) | 지시대로. 보존이 개선과 **별도 기준 둘**로 적혔다 |

모든 기준의 의무가 `reported`(원문이 명시)였고 기준 없는 요구 목적은 0건이다. 원문은
[A](P4-03-live-A-intent-original.json)·[B](P4-03-live-B-intent-original.json)·
[C](P4-03-live-C-intent-original.json), 요약은 [결과 JSON](P4-03-live-results.json)과
[로그](P4-03-live.log)에 있다.

**관찰 둘(결함이 아니다).** codex 는 요구되지 않은 **보존 기준**을 스스로 더했다 — A 는
"새로 고침 후 저장값 유지", B 는 "제품 코드는 바꾸지 마세요"를 보존 의무로 옮겼다. 계약상
요구되지 않은 의무의 기준도 충족돼야 하므로(미해결 기준 규칙) 이것은 완료 조건을 **늘리는**
쪽이다. B 의 C-04 는 조사 Case 에서 검증 실행이나 사람 판단(`preserved`)으로 충족해야
한다. 느슨해지는 방향의 일탈(목적 누락, 요청에 없는 판단 불가 허용)은 관찰되지 않았다.
**세 건이 표본의 전부다** — 다른 요청에서 지시를 어길 가능성을 배제하지 않는다.

## 4. 검토 중 발견해 고친 것

- **화면으로는 v2 Case 의 `met` 을 적을 수 없었을 것이다.** 결과 기록 폼에 충족 방식
  선택이 아예 없었다 — P3-R4 가 `satisfaction` 을 API 에만 넣고 화면에는 넣지 않았다.
  방식이 필수가 되면서 드러난 빈틈이라 의무별 방식·결론 선택을 넣었다. 빈 방식의 `met`
  도 그대로 보내 서버의 거부 사유(`satisfaction_required`)가 보이게 했다.
- **거부된 `met` 을 모른 채 지나가던 시험 둘.** `test_progression` 의 두 시험이
  `record_result(... "met")` 의 응답을 보지 않았다. v2 에서 그 `met` 이 거부되자 한 시험은
  실패했고(판정이 이어지지 않음), 다른 하나(`test_a_changed_criterion_does_not_keep_its_verdict`)는
  **그대로 통과했다** — 기록되지 않은 판정은 당연히 이어지지 않으므로, 시험이 보려던 것과
  다른 상황을 시험하고 있었다. 세 곳 모두 방식을 적고 응답을 단정하도록 고쳤다.
- **기준 지문의 소급.** 의무·결론 요구를 지문에 무조건 더하면 v1 기준의 지문이 바뀌어
  이미 기록된 누적 변경의 해시와 어긋난다. 값이 있을 때만 더하고 v1 지문이 그대로임을
  시험으로 고정했다.
- **후보 해시의 소급.** 목적 블록을 모든 후보 스냅샷에 넣으면 v1 Case 의 해시가 바뀌어
  controlled 의 결과 확인이 소급으로 낡는다. 계약이 있는 Case 에만 넣었다.

기존 시험 10건을 v2 의미로 고쳤다 — v2 새 Case 에서 방식 없이 `met` 을 적던 것(기능 Case 는
`changed_and_verified`, `kind = analysis` 로 만든 RCA Case 는 `investigated`+`determined`),
결과 조회의 키 목록(새 열거값 다섯), 복원되는 정의판 "2". 검사를 지운 것은 없다.

## 5. 남은 경계와 인계

- 이 결과는 **P4-03만** 완료한다. 컨텍스트 고정·재개는 P4-04, 완료·예외 전반은 P4-05,
  지식/QG-08 은 P4-06~07, 게시·push·PR 은 P5 다.
- **강제 축은 늘지 않았다.** `enforcement` 는 여전히 넷이 `enforced` 이고 `publish` 만
  P5 다. P4-03 이 더한 것은 **완료가 무엇을 뜻하는가**다.
- **Profile 재분류 경로는 만들지 않았다**(plan 3.8절). 재분류는 다음 의도 버전의 항목
  집합을 바꾸고 그것을 어떻게 이을지는 의도 구조의 결정이다. 인수 매트릭스 AC-07 중
  "원인 확정+수정은 양쪽 충족"만 닫았다. 대신 선언 목적을 Profile 이 아니라 의도에 둬
  재분류가 생겨도 목적이 사라지지 않게 했다.
- **제어부는 여전히 본문을 읽지 않는다.** 의무·결론 요구는 AI·사람이 적은 **열거값**이며,
  "원인을 정말 찾았는가", "보존 기준이 보존 계약을 전부 담았는가"는 판정하지 않는다.
  막는 것은 값끼리의 모순(판단 불가를 확정 필수 기준의 충족으로 적기 등)이다.
- **실험 정리는 관측이지 격리가 아니다**(D-44). 되돌렸다는 표시는 관측한 트리가 같다는
  뜻이고, 사람이 잔여를 보고 인수하는 것은 막지 않는다. 잔여를 정리하는 전용 동작은 없다.
- 사람이 입력하는 **의도 초안 화면**에는 목적 선언 입력을 넣지 않았다. API 는 받고, 입력이
  없으면 대표 목적만 요구된다.
- 구현 실행의 판정("변경도 명령도 없으면 실패")은 그대로다. 무변경 완료는 검증 실행의
  관측이 근거다.
- 시작은 `main`/`f6145f4`(P4-02 커밋), clean·`origin/main` 과 같았다. 이 결과는
  **사용자 지시로 커밋·push** 했다(`bf86590`). 그 허용은 이 변경에만 적용된다. 라이브 데이터는
  `%LOCALAPPDATA%\Temp\hads-p4-03-live\130017994` 에 남아 있고 저장소 `var\` 는 건드리지
  않았다. 라이브 제어부·Runner 는 종료를 확인했다.
