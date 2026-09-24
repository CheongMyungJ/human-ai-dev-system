# P4 수용 확인 결과 — 완료 조건의 네 축을 P4-01~07b·UI-04c 의 근거로 대조

상태: **수용 확인 끝 — 네 축 중 셋(혼합 목적의 계약, 실패/복구/변경, Case 간 지식)은 근거가 완비돼 있고, "여섯 Profile 대표" 는
계약·판정 수준에서 여섯 전부 재현됐으나 제품 흐름 수준(P4-05 진행기 경유)에서는 셋(feature·research·RCA)만 있다. 빠진 것 —
defect-fix·refactoring·maintenance 의 진행기 경유 대표 흐름과 혼합 목적의 진행기 경유 완료 — 는 [P4-PLAN-08](../../plans/P4-PLAN-08.md)
로 기록했다(READY, 착수하지 않음). P4 를 닫을지, P4-PLAN-08 을 먼저 할지는 사용자의 결정이다(7절).**
기준: [P4-PLAN-ACCEPT](../../plans/P4-PLAN-ACCEPT.md) / [DEVELOPMENT](../../DEVELOPMENT.md) 6절 "P4 완료 조건" / [case-profiles](../../case-profiles.md)
6절 / [review-acceptance-matrix](../../review-acceptance-matrix.md) / 2026-09-24. 세션 S-033. **판정 기록이며 새 기능·새 시험이 아니다.**
근거의 원천은 [P4-01](P4-01-results.md)·[P4-02](P4-02-results.md)·[P4-03](P4-03-results.md)·[P4-04](P4-04-results.md)·[P4-05](P4-05-results.md)·
[P4-05b](P4-05b-results.md)·[P4-06](P4-06-results.md)·[P4-06b](P4-06b-results.md)·[P4-07](P4-07-results.md)·[P4-07b](P4-07b-results.md)·
[UI-04c](../../ui/evidence/UI-04c-results.md) 의 결과 문서와 시험 파일이고, "지금도 통과한다" 의 근거는 이 세션의 기준선(5절)이다.
당시 수치·라이브는 당시 사실이다.

**완료 조건(6절):** "여섯 Profile 대표·혼합 목적·실패/복구/변경을 재현하고 Case 간 최소 지식 관리·추출·주입을 검증한다. 지식은
첫 버전 범위이며 FR-19/QG-08 을 일괄 후속 확장으로 제외하지 않는다. QG-08 은 모든 후보의 별도 AI 실행·사람 승인을 의무화하는
절차가 아니다."

**수준의 구분**(plan 3절): (a) **계약·판정 수준** — API·순수 시험이 완료 계약·의무·판정 규칙을 고정한 것(P4-03 이 만든 것), (b) **제품
흐름 수준** — P4-05 부터 업무 단계의 실제 경로인 진행기(업무화 → 의도 → 동의 → 준비 → 작업 그래프 → 구현·검증 → 기준 판정 → 완료)를
지나는 시험, (c) **실제 CLI 라이브** — 실제 codex 의 관찰. 코드 대조: `domain/work_flow.py` 의 진행기는 **조사 Profile 둘**(RCA·
research, `INVESTIGATION_ONLY_PROFILES`)만 분석 단계로 보내고 **제품 변경 Profile 넷**(feature·defect-fix·refactoring·maintenance)은
준비·그래프·완료 단계를 공용으로 지난다; `decide_criteria` 가 의무별 충족 방식을 정한다(`cause`/`answer` → `investigated`(+판단 불가 규칙),
`preservation` → `preserved`, 그 밖 → 변경 관측이면 `changed_and_verified` 아니면 `already_satisfied`). 진행기 시험(`tests/test_work_progressor.py`)이
지나는 분기는 `changed_and_verified` 와 `investigated`(determined·inconclusive)뿐이고 `preserved`·`already_satisfied` 분기와 그 완료는
진행기 시험이 없다 — 이것이 아래 1.1절의 "빠진 것" 이다.

## 1. 완료 조건 네 축의 대조

### 1.1 여섯 Profile 대표

| Profile | (a) 계약·판정 수준 | (b) 제품 흐름 수준(진행기 경유) | (c) 실제 codex | 판정 |
|---|---|---|---|---|
| feature | `tests/test_profile_completion.py::test_a_feature_closes_on_changed_and_verified_behavior`, `::test_every_current_profile_has_its_own_completion_contract`(여섯 계약), `::test_met_without_saying_how_is_refused_on_a_v2_criterion`, 실험 근거 제한(`experiment_evidence_not_product`) | `tests/test_work_progressor.py::test_a_clear_feature_request_runs_to_auto_completion_with_only_the_agreement`(업무화→의도→QG-01→동의→결합 기록→작업공간→구현→검증→`changed_and_verified`→자동 완료), `::test_controlled_stops_at_the_start_and_at_the_result_candidate`, `::test_gate_findings_are_repaired_with_the_findings_in_the_assignment_up_to_the_limit`, `::test_unresolved_criteria_wait_for_a_person_and_an_exception_closes`, `::test_a_failed_task_is_retried_once_and_then_waits_for_a_person`, 브라우저 `test_web_shell.py::test_the_work_stage_runs_by_itself_and_stops_only_at_the_cards` | P4-05 라이브 16/16(업무화→동의→11 실행→예외 종료→설명), P4-06·P4-06b·P4-07(두 회차)·UI-04a 라이브의 업무 대화 전부 feature | **재현됨(세 수준)** |
| defect-fix | `::test_a_defect_already_fixed_closes_without_any_code_change`(검증 실행 하나로 무변경 완료), `::test_already_satisfied_must_be_observed_by_a_verification_run`, `tests/test_progression.py::test_not_reproducing_a_defect_is_not_a_met_criterion`, `::test_an_already_satisfied_goal_needs_run_evidence`, 혼합 `test_profile_completion.py::test_a_fix_that_also_asked_for_the_cause_needs_both`, 잔여 `::test_experiment_residue_blocks_auto_completion_of_a_product_case_only`(결함 Case 자동 완료 거부) | **RCA 에서 개정된 defect_fix 만**: `tests/test_profile_revision.py::test_a_revision_records_history_keeps_everything_else_and_carries_the_criteria`(개정 → `intent_revision` → material delta → 동의 대기까지), 브라우저 `::test_a_purpose_change_in_the_work_stage_revises_the_profile_and_reauthors_the_intent`. **처음부터 defect_fix 로 업무화해 복원(`restoration`) 판정·무변경 완료(`already_satisfied`)·종료까지 가는 진행기 시험이 없다** | P4-03 라이브 A(의도 작성 — `objectives: ["cause"]`·C-02 `restoration`), UI-01 라이브(defect-fix 초안) — 둘 다 의도 작성까지 | **계약 재현 · 흐름 빠짐** → P4-PLAN-08 |
| root-cause-analysis | `::test_an_inconclusive_cause_is_not_success_when_the_cause_must_be_found`, `::test_declaring_a_product_objective_does_not_open_implementation_in_an_rca`, `::test_experiment_residue_blocks_auto_completion_of_a_product_case_only`(RCA 는 잔여를 보이되 자동 완료), 실험 `::test_a_real_experiment_that_leaves_a_file_is_seen_as_residue` | `test_profile_revision.py::test_a_revision_records_history_…`(RCA 업무 → 분석 실행 → `cause` 기준 `not_met` → `criteria_unresolved` 대기 → 개정), `::test_a_revision_does_not_open_product_writes_by_itself`, 브라우저 위 시험(RCA 업무 → 개정). 분석 단계 자체와 확정 결론(`determined`)으로 닫히는 경로는 research 시험이 **같은 분기**(`_analysis_phase`·`cause`/`answer` 공용)를 지난다 | UI-03 라이브(분석 요청을 `research` 로 읽음 — RCA 아님), 실제 RCA 라이브 없음 | **재현됨**(흐름은 분석·판단 불가·개정 경로 + research 와 공용 분기; 실제 codex 의 RCA 관찰은 없음 — 6절) |
| research | `::test_a_bounded_research_can_close_with_an_inconclusive_answer_and_no_code`, `::test_an_investigation_answer_needs_an_investigation_run` | `test_work_progressor.py::test_a_research_case_reports_its_conclusions_from_the_analysis_run[determined·inconclusive]`(분석 실행 하나·읽기 전용·`investigated`·판단 불가 → `not_met` 대기) | P4-03 라이브 B(의도 작성 — `bounded_report_allowed`), UI-03 라이브(research 업무화 해석) | **재현됨(세 수준)** |
| refactoring | `::test_a_refactoring_without_a_preservation_criterion_does_not_close`, `::test_a_refactoring_closes_when_improvement_and_preservation_are_each_proven`(보존의 구현·실험 근거 거부, 검증 실행으로 완료) | **없음** — `preserved` 분기를 지나는 진행기 시험 없음. `tests/test_restart_recovery.py::test_policy_profile_budget_and_repositories_survive_a_forced_kill` 은 Profile 값 보존만 본다 | P4-03 라이브 C(의도 작성 — 개선 + 보존 기준 둘) | **계약 재현 · 흐름 빠짐** → P4-PLAN-08 |
| maintenance | `::test_maintenance_asks_for_preservation_only_when_conditions_were_written`(`required_by = profile_conditional`) | **없음** | **없음**(실제 codex 의 maintenance 의도 작성 표본 없음) | **계약 재현 · 흐름 빠짐** → P4-PLAN-08 |

**Profile 공통**(여섯 전부에 적용): 정의판 v2 의 계약(`test_every_current_profile_has_its_own_completion_contract`), 의무의 출처
(`test_a_criterion_obligation_is_reported_or_derived_and_says_which`), 방식 필수(`test_met_satisfaction_differs_by_obligation`), v1 비소급
(`test_a_v1_case_keeps_the_old_completion_rules`·`test_a_v1_criterion_keeps_its_old_fingerprint`·이행 `test_migration.py` v14→v15), 여섯 Profile 의
개정 거부·허용(`test_profile_revision.py::test_revisions_are_refused_where_they_would_lie`), 재시작 보존(`test_obligations_conclusions_and_meaning_survive_a_reopened_database`).
의도 초안의 업무별 항목은 R1·P4-03 의 문서 v5/v6(`test_the_v5_document_reports_enumerations_only`, `test_the_document_keeps_retained_fields_and_their_criteria`).

### 1.2 혼합 목적

| 수준 | 근거 | 판정 |
|---|---|---|
| (a) 계약 | `test_profile_completion.py::test_a_fix_that_also_asked_for_the_cause_needs_both`(수정만 충족하면 닫히지 않음), `::test_a_declared_objective_without_a_criterion_blocks_completion`(목적 누락은 예외 불가), `::test_a_conclusion_rule_only_belongs_to_cause_and_answer_criteria`; UI-04c AC-5(개정 뒤 `objectives_json = ["cause","restoration"]`·`completion_meaning` 이 양쪽 요구) | 재현됨 |
| (b) 흐름 | UI-04c AC-7(RCA → defect_fix 개정 → `intent_revision` 실행의 지시문에 유지 항목·유지 목적·직전 기준 → 새 버전 → material delta → **동의 대기까지**). **동의 뒤 양쪽 목적(`cause` 의 조사 결론 + `restoration` 의 검증)이 각각 판정돼 닫히거나, 한쪽만 충족해 닫히지 않는 것을 진행기 경유로 본 시험이 없다** | **빠짐** → P4-PLAN-08 |
| (c) 실제 codex | P4-03 라이브 A(defect-fix + "원인을 확정하지 못하면 완료가 아닙니다" → `objectives: ["cause"]`·C-01 `cause`+`definitive_required`) — 의도 작성까지 | 관찰 있음(의도까지) |

### 1.3 실패 / 복구 / 변경의 재현

| 축 | 근거(시험·라이브) | 판정 |
|---|---|---|
| 실패 — 게이트·repair | `tests/test_quality_gates.py::test_initial_failure_then_two_repairs_and_no_third`, `::test_environment_recovery_and_gate_toggles_do_not_reset_or_consume_repairs`, `::test_an_independent_review_needs_a_reviewer_run_and_a_separate_session`; 진행기 `test_work_progressor.py::test_gate_findings_are_repaired_with_the_findings_in_the_assignment_up_to_the_limit`; 상한 `tests/test_progress_limits.py` 23(`test_raising_the_limit_goes_once_more_and_stops_again_at_the_new_limit` 등)·브라우저 `test_a_limit_card_raises_the_limit_and_goes_once_more` | 재현됨 |
| 실패 — 작업·검증·실행 | `test_work_progressor.py::test_a_failed_task_is_retried_once_and_then_waits_for_a_person`, `::test_unresolved_criteria_wait_for_a_person_and_an_exception_closes`(`not_met`·`unverified` → 예외 카드 → `closed_with_exceptions`, 원래 판정 보존), `tests/test_quality_changes.py::test_the_reservation_lands_when_the_verification_ends_even_on_a_failure`(실패 판정 보존), `tests/test_context.py::test_a_missing_core_input_stops_the_run_before_the_cli_and_costs_nothing`(`failed`·`not_started`·소비 0), `tests/test_completion.py::test_an_exception_preserves_the_original_verdict`·`::test_auto_mode_does_not_accept_its_own_exceptions`, 예산 `tests/test_budget.py::test_reaching_a_hard_limit_does_not_close_or_cancel_the_case`; 라이브 P4-05 C(기준 셋 `unverified` → 자동 완료 없음 → 사람 예외 수용) | 재현됨 |
| 복구 — 제어부 강제 종료 | `tests/test_restart_recovery.py` 12건(실제 uvicorn `taskkill /F /T` — `test_progression_records_survive_a_forced_kill`, `test_conversation_requests_and_lock_survive_a_forced_kill`, `test_context_plans_receipts_and_recovered_usage_survive_a_forced_kill`, `test_policy_profile_budget_and_repositories_survive_a_forced_kill` 등), 파일 DB 재개(`test_gate_policy_failure_and_repair_survive_a_reopened_database`, `test_reservations_and_late_results_survive_a_reopened_database`, `test_obligations_conclusions_and_meaning_survive_a_reopened_database`), 처리기 기동 복구 `test_request_processor.py::test_startup_recovery_creates_missing_replies_and_settles_finished_requests`, 진행기 `test_work_progressor.py::test_recovery_pauses_a_running_progress_whose_request_already_ended` | 재현됨 |
| 복구 — Runner·실행 | `tests/test_run_control.py::test_restart_reconciliation_reports_without_reexecution_or_new_reservation`(원장 넷·CLI 재호출 0·새 세대 없음), `tests/test_runner_process_control.py::test_a_real_runner_stops_a_real_tree_and_reconciles_after_its_own_crash`(실제 Runner 프로세스), `tests/test_context.py::test_a_restarted_runner_recovers_usage_from_the_real_codex_raw_log`, `::test_a_new_session_after_an_unknown_run_resets_nothing`(Profile·기준·질문·repair·예산 유지), `test_work_progressor.py::test_a_stopped_progress_request_pauses_and_resume_continues`; 라이브 UI-02 C(Runner 강제 종료 → 트리 종료 → 재기동 대조), P4-04 D(실행 중 강제 종료 → 재호출 0·`unknown`) | 재현됨. 한계: 시간 예산 자동 중단 없음·claude 미실증·비 Windows 미지원(DEVELOPMENT 9절) |
| 변경 — 요청·코드·권한·정책 | `tests/test_quality_changes.py::test_a_request_change_only_touches_the_checks_that_used_it`, `::test_a_code_change_leaves_evidence_from_other_repositories_alone`, `::test_a_permission_change_blocks_the_next_assignment_without_waiting`, `::test_an_unknown_scope_is_not_recorded_as_unaffected`, `::test_a_change_during_a_verification_is_reserved_and_changes_nothing_yet`, `::test_a_late_result_stays_with_its_own_run_and_starts_nothing`; 누적 delta `tests/test_progression.py::test_deltas_accumulate_against_the_last_delegation`·`::test_a_pending_delta_blocks_the_dependent_work`·`::test_a_delta_confirmation_must_be_explicit`; 기준 약화 `test_profile_completion.py::test_weakening_a_conclusion_rule_is_a_material_change`; 최신성 `test_context.py::test_freshness_records_inputs_that_arrived_after_the_run_fixed_its_context`; 지식 개정 뒤 drift `tests/test_knowledge.py::test_an_update_elsewhere_keeps_the_old_input_and_shows_up_as_drift`; 설정 변경의 적용 시점 `tests/test_project_settings.py::test_project_defaults_apply_to_new_conversations_and_runs_but_not_to_existing_ones` | 재현됨 |
| 변경 — 목적·Profile | UI-04c AC-1~8(`tests/test_profile_revision.py` — 개정 이력·유지 항목·유지 목적·`carried_from` 승계·거부 다섯·쓰기 가드·진행기·AI 해석) | 재현됨 |

### 1.4 Case 간 지식 관리·추출·주입

| 축 | 근거 | 판정 |
|---|---|---|
| 관리(등록·개정·활성·무효·충돌·범위·권위) | `tests/test_knowledge.py::test_candidates_activation_invalidation_and_revision_keep_history`, `::test_registered_rules_reach_every_work_run_as_originals_and_the_manifest_says_so`, `::test_repository_scope_does_not_mix_repositories_and_follows_scope_expansion`, `::test_a_conflict_between_applied_required_rules_waits_for_a_person`, `::test_a_rule_said_in_conversation_is_registered_and_injected_with_the_users_words`(자동 등록·권위 = 사용자 말), `::test_bad_registration_items_are_refused_with_a_reason`; 서버 저장 `tests/test_knowledge_server.py` 6(수동 등록·해시 대조·옛 지식 이행·권위 메시지 보존 규칙·이행); 화면 UI-04a AC-4·6·7·8(규칙 화면의 채택 확인·활성화·개정·무효·수동 등록) | 검증됨 |
| 추출(후보·근거·관계·채택 확인·반자동 활성) | `tests/test_knowledge_extraction.py::test_a_verification_run_leaves_a_candidate_and_a_run_without_a_block_leaves_nothing`, `::test_supports_and_duplicates_become_evidence_and_supersedes_contradicts_become_related_candidates`, `::test_activation_passes_the_adoption_check_narrows_only_and_can_apply_into_another_item`(QG-08 채택 확인), `::test_a_proposal_in_a_discussion_reply_is_only_a_candidate_without_an_authority_message`, `::test_reports_from_other_purposes_incomplete_runs_and_too_many_or_unknown_keys_are_refused`, P4-07b `::test_the_auto_reference_conditions_are_all_or_nothing_and_each_one_can_fail_alone`·`::test_a_candidate_is_ready_only_with_two_runs_and_is_activated_only_when_a_human_clicks`; AI 제안은 어떤 경로로도 활성 필수가 되지 않음(`::test_an_ai_proposal_is_only_a_candidate`, DB CHECK) | 검증됨(첫 버전 범위) |
| **Case 간** 주입 | P4-06 AC-12(다른 대화의 의도 초안에 `knowledge_required`+`knowledge_source`), P4-06b `test_knowledge_server.py::test_a_rule_from_one_pc_reaches_work_on_another_pc_even_while_the_first_is_disconnected`(다른 PC·소유 PC 미연결·실행 넷 전부 `read`·`body_source = server`), P4-07 AC-4·6(다음 검증 실행에 후보 둘·`into` 뒤 v2 제공), P4-07b AC-6(넷째 대화의 검증 실행에 활성 참고 v2), 활동·범위 선택 `test_knowledge.py::test_selection_follows_activity_and_scope_and_never_reads_unknown_as_not_applicable`, 필수 원문 불가의 보류 `::test_an_unreadable_required_rule_stops_the_run_and_a_reference_does_not`, 한도 `::test_required_rules_over_the_inline_limit_hold_the_run`; UI-04a AC-3(`knowledge-use` 집계 — "주입은 준수의 증거가 아니다") | 검증됨 |
| 실제 codex | P4-06 21/21(대화의 규칙 → 다른 대화의 실행 6개 주입), P4-06b 29/29(두 Runner, PC A 미연결에서 PC B 주입), P4-07 5/5·13/13(정리 응답의 제안 둘 → 활성화 → 다른 대화의 검증 실행 2개 주입; **작업 실행은 후보를 남기지 않았다 — 관찰**), UI-04a 26/26(규칙 등록·제안·활성화·적용 집계) | 관찰 있음 |
| FR-19/QG-08 의 범위 | 채택 확인(`adoption_check`)·후보의 권한 없음·코드 변경만으로 규칙 폐기 없음·주입≠준수는 구현·시험됨. **독립 AI 검토 실행은 없음**(선택 사항 — `adoption.independent_review = not_run` 으로 기록, QG-08 "매 Case 별도 AI review 를 강제하지 않음"), 자동 충돌 탐지 없음, 참고 후보의 완전 자동 활성은 없음(사용자 결정: 반자동). 완료 조건이 허용하는 첫 버전 범위 안이다 | 첫 버전 범위 충족 |

## 2. case-profiles 6절 수용 시나리오 1~10

| # | 시나리오(요지) | 근거 | 판정 |
|---|---|---|---|
| 1 | 여섯 Profile 의 요청에 같은 긴 폼을 요구하지 않고 업무별 문제·기대 상태를 구분한 초안 | `test_profile_completion.py::test_the_intent_prompt_asks_for_the_contract_only_where_there_is_one`, `::test_an_ai_draft_reports_objectives_and_obligations`, 문서 v5/v6 시험; 라이브 P4-03 A·B·C(세 Profile)·UI-01(defect-fix)·P4-05 외(feature) | 재현됨(실제 codex 표본은 feature·defect-fix·research·refactoring — maintenance·RCA 없음) |
| 2 | 중요한 제품 선택이 남은 초안도 읽고 피드백, 의존 실행은 보류 | `test_work_progressor.py::test_intent_questions_stop_the_flow_and_a_card_answer_resumes_it`, `test_progression.py::test_a_pending_delta_blocks_the_dependent_work`, UI-01 AC-10 | 재현됨 |
| 3 | 저위험 기능은 추가 전체 승인 없이 진행, 정책 기록과 사람 확인 기록 구분 | `test_a_clear_feature_request_runs_to_auto_completion_with_only_the_agreement`(사람 결정 = 동의 하나), `tests/test_completion.py::test_auto_completion_is_not_recorded_as_a_human_acceptance` | 재현됨 |
| 4 | 특정 질문의 답을 전체 승인으로 확대하지 않음, 이월 질문은 의존 작업 전에 | UI-01 AC-10(카드 답변 한정), P4-05 라이브 C(이월 질문 답 뒤 진행 요청) | 재현됨 |
| 5 | RCA-only 에서 허용된 로컬 계측은 수행, 제품 수정은 자동 시작하지 않음 | `test_progression.py::test_controlled_still_allows_the_draft_and_the_investigation`·`::test_a_local_experiment_does_not_need_the_feature_pipeline`, `test_profile_completion.py::test_declaring_a_product_objective_does_not_open_implementation_in_an_rca`, `test_profile_revision.py::test_a_revision_does_not_open_product_writes_by_itself` | 재현됨 |
| 6 | "원인 확정과 수정" 중 수정만 성공하면 완료 아님; 합의된 판단 불가는 정상 결과 가능 | `::test_a_fix_that_also_asked_for_the_cause_needs_both`, `::test_a_bounded_research_can_close_with_an_inconclusive_answer_and_no_code`, `::test_an_inconclusive_cause_is_not_success_when_the_cause_must_be_found` | 계약 재현 · **진행기 경유는 빠짐**(1.2절) |
| 7 | 목표가 이미 충족됨을 유효한 증거로 확인하면 무변경 완료 가능, 미재현만으로 해결 선언 없음 | `::test_a_defect_already_fixed_closes_without_any_code_change`, `::test_already_satisfied_must_be_observed_by_a_verification_run`, `test_progression.py::test_not_reproducing_a_defect_is_not_a_met_criterion` | 계약 재현 · **진행기 경유는 빠짐**(1.1절 defect-fix) |
| 8 | Profile 변경·세션 교체 뒤에도 기준·권한·피드백 범위·시도 이력·예산 유지 | UI-04c AC-1(개정 뒤 위임 근거·Autonomy·결정·이전 버전·기준·판정·예약·시도 수 그대로), `test_context.py::test_a_new_session_after_an_unknown_run_resets_nothing` | 재현됨 |
| 9 | 미정 논의로 시작한 Case 를 같은 대화의 명확한 요청으로 업무화, 미정 해소 ≠ 활성 재분류 | UI-01 AC-1·13, UI-03 AC-6, `test_profile_revision.py::test_revisions_are_refused_where_they_would_lie`(준비 단계 개정 거부 `case_not_in_work_stage`) | 재현됨 |
| 10 | 미완료 RCA 에 같은 문제의 수정 요청 → 같은 Case 의 개정 연결, 기존 기준·증거·실패·repair·사용량 보존, 쓰기 조건 전 수정 실행 없음 | UI-04c AC-1·4·6·7·8, 브라우저 `test_a_purpose_change_in_the_work_stage_revises_the_profile_and_reauthors_the_intent` | 재현됨(동의까지; 그 뒤 완료는 1.2절) |

## 3. 수용 점검표의 P4 관련 행

| ID | 판정 | 근거·배정 |
|---|---|---|
| AC-01 작은 기능 결합 진행 | 검증됨 | P3-R4·P3-04 경로 A, P4-05 AC-7(결합 기록 하나·`auto_conditions_met`) |
| AC-02 모호한 요청의 미결 구분·초안 열람과 실행 분리 | 검증됨 | R1 초안, P4-05 AC-2(질문 대기·카드 답변), `test_controlled_still_allows_the_draft_and_the_investigation` |
| AC-03 deep + ask-on-decision 자동 수행 | 검증됨 | R4·P3-04, P4-05 대표 시험(사람 결정은 동의 하나) |
| AC-04 위험 증가 시 게이트·독립 검토 추가, 자동 controlled 전환 없음 | 검증됨 | P4-01 AC-8~10, `test_progression.py::test_an_unrecorded_autonomy_is_treated_as_controlled`(도출만), UI-04b AC-5(QG-02~07 설정은 사유 필수·권한 아님) |
| AC-05 누적 delta 와 마지막 유효 위임 비교 | 검증됨 | `test_deltas_accumulate_against_the_last_delegation`, `test_weakening_a_conclusion_rule_is_a_material_change` |
| AC-06 한 질문의 답은 그 항목만 확정 | 검증됨 | UI-01 AC-10, P4-05 AC-2 |
| AC-07 Profile 변경·혼합 목적 | 검증됨(계약·개정) · 진행기 경유 완료는 빠짐 | P4-03 AC-10, UI-04c AC-1~8 — 1.2절 |
| AC-08 여섯 Profile 의 intake | 검증됨 | 1.1절 공통(문서 v5/v6·계약 여섯), 라이브 표본은 넷 |
| AC-09 원인 분석의 로컬 실험, 제품 수정 확대 없음 | 검증됨 | `test_a_real_experiment_that_leaves_a_file_is_seen_as_residue`, `test_declaring_a_product_objective_does_not_open_implementation_in_an_rca` |
| AC-10 무변경 완료·미재현 금지 | 검증됨(계약) · 진행기 경유는 빠짐 | 2절 7행 |
| AC-11 불확실 결론의 완료 조건 | 검증됨 | 1.1절 RCA·research |
| AC-12 refactor/maintenance 의 개선·보존 입증 | 검증됨(계약) · 진행기 경유는 빠짐 | 1.1절 refactoring·maintenance |
| AC-13 Fast Lane 독립 검토의 구별·별도 세션 | 검증됨 | P4-01 AC-8~10, P4-05 AC-3(가벼운 확인/독립 검토 `method`) |
| AC-14 게이트 실패·repair 2회, 재분할·세션 교체 초기화 없음 | 검증됨 | P4-01 AC-11~15, P4-05b(상한 설정), `test_a_new_session_after_an_unknown_run_resets_nothing` |
| AC-15 검증 중 게이트 OFF 요청 | 검증됨 | P4-02 AC-2~7·17 |
| AC-16 예산 미설정·경고·hard 도달 | 검증됨(라이브 경로 C 는 스킵) | R3, `test_reaching_a_hard_limit_does_not_close_or_cancel_the_case`, UI-04b AC-13(도달 알림) |
| AC-17 마지막 예산의 병렬 경쟁 | 검증됨 | `test_budget.py::test_the_last_slot_is_won_by_exactly_one_of_two_concurrent_requests`, UI-02 AC-9(재시작 새 예약 없음) |
| AC-18 토큰·비용 미제공·in-flight 초과 | 검증됨(한계 표시) | `test_unreported_tokens_are_unavailable_not_zero`, `test_an_estimated_metric_still_refuses_a_hard_limit`, `test_a_time_limit_is_accepted_but_not_as_an_absolute_cap`; 정확한 hard 한도 불가 시 배정 보류의 전체 실증은 P6 |
| AC-19 예산 절약을 위한 모델 변경 | 부분 — 모델 설정 없음 | 도구 변경은 UI-04b(확인이 아님·진입 검사 `tool_not_available`), 모델·깊이 기본값 없음(UI-04b 4절). 필수 검사 제거 금지는 P4-01·02 |
| AC-20 미결 선택·실패·권한 철회 | 검증됨(철회 기계는 P6-03) | `test_a_pending_delta_blocks_the_dependent_work`, P4-02 AC-14·16·18 |
| AC-30 결과 일부 미충족·예외 수용 | 검증됨 | P4-05 AC-10, `test_completion.py` 예외 시험 셋 |
| AC-31 종료 뒤 수정 요청·설명 질문 | 검증됨(이슈 연결은 P5) | P4-05 AC-15·16 |
| AC-32 확정 규칙과 AI 후보의 구분 | 검증됨 | 1.4절 |
| AC-33 후보 없음·예산 부족에도 완료 | 검증됨 | `test_a_verification_run_leaves_a_candidate_and_a_run_without_a_block_leaves_nothing`(둘째 대화), P4-07 4절(별도 추출 실행 없음) |
| AC-34 활동·Repo·경로·계약별 적용, Manifest | 검증됨 | P4-06 AC-4·5·8·9 |
| AC-35 필수 지식 충돌·원문 불가·초과 | 검증됨 | P4-06 AC-6·7, P4-06b AC-5(해시 불일치) |
| AC-36 다른 Case/Runner 의 지식·새 버전 | 검증됨 | 1.4절 Case 간 주입, `test_an_update_elsewhere_keeps_the_old_input_and_shows_up_as_drift` |
| AC-39 긴 문맥·세션 교체·부분 복원 | 검증됨 | P4-04 AC-2·3·13·14·18 |

AC-21~29(복수 저장소·외부 반영)·AC-37~38·40 은 P3·P5·P6 의 몫이며 여기서 판정하지 않는다.

## 4. 빠진 것 → P4-PLAN-08

완료 조건이 요구하는데 어느 결과 문서의 AC 도 고정하지 않은 것은 **하나의 묶음**이다: **제품 흐름 수준(진행기 경유)의 대표 재현이
defect-fix·refactoring·maintenance 에 없고, 혼합 목적의 완료(양쪽 목적의 판정 → 종료 / 한쪽만 충족 → 미완료)도 진행기 경유로 본 시험이
없다.** 코드 대조로는 세 Profile 이 feature 와 같은 단계를 지나고 `decide_criteria` 가 `preserved`·`already_satisfied` 를 정하도록 돼
있으나, 그 분기를 지나 닫히는(또는 닫히지 않는) 진행기 시험이 없으므로 "재현했다" 고 적을 수 없다. 이것을 [P4-PLAN-08](../../plans/P4-PLAN-08.md)
로 기록했다(READY — 성공 기준·검증 방법·경계; 착수하지 않음). 그 밖의 것은 전부 "남은 한계"(6절)이거나 P5·P6 의 몫이다.

## 5. 검증

- **기준선(S-033 시작, 문서 외 변경 없음, `pwsh -NoProfile -ExecutionPolicy Bypass -File scripts\run-tests.ps1`)**: 웹 빌드 성공, 웹 단위
  **37** 통과, pytest **740 통과·0 실패·2 건너뜀**(15분 7초; 건너뜀은 이행 시험의 옛 스키마 커밋 창), P1 계약 **18** 통과, "전체 시험 통과"
  (종료 코드 0). 이 세션은 코드·시험을 바꾸지 않았으므로 이것이 최종 수치다. S-032 의 최종(pytest 740·0 실패·2 건너뜀, 웹 단위 37,
  P1 18)과 같다. 1절의 모든 시험 파일이 이 실행 안에 있다.
- **시험 이름 확인**: 이 문서·[UI-04 결과](../../ui/evidence/UI-04-results.md)·P4-PLAN-08 에 적은 `test_*` 이름을 `tests/` 에서 전부 찾았다
  (스크립트, DEVELOPMENT 10절 S-033).
- **링크 확인**: 이 세션이 만들거나 고친 문서의 상대 링크가 실제 파일을 가리킨다(스크립트).
- **실제 CLI**: 하지 않았다(새 기능 없음).

## 6. 남은 한계(빠진 것이 아님 — 배정 위치는 DEVELOPMENT 9절)

- **검증 실행이 이 호스트에서 시험을 돌리지 못한다** — 실제 codex 의 샌드박스 셸이 `python`·`rg` 를 찾지 못해 라이브에서는 기준이 전부
  `unverified` 였고(P3-03·P3-04·P4-05·P4-06·P4-06b·P4-07), 제품이 `met` 을 실제 검증 실행으로 적은 라이브 증거가 없다(가짜 CLI 시험만).
  절대 경로 인터프리터는 시도하지 않았다. 환경을 갖춘 뒤 본다 — 7절의 질문.
- **실제 codex 의 작업 실행은 후보를 남기지 않았다**(P4-07 두 회차 네 실행) — 후보·근거·관측 문맥의 제품 규칙은 가짜 CLI 로 고정돼 있다.
- **QG-02~07 은 진행기가 돌리지 않는다**(P4-05 → 관리 화면·사람 대기), QG-08 독립 AI 검토 실행 없음, 자동 충돌 탐지 없음.
- **실제 codex 의 Profile 표본**: 의도 작성은 feature·defect-fix·research·refactoring, 업무 진행은 feature 뿐. RCA·maintenance 는 관찰이 없다.
- **경로 C(예산 도달의 기능 흐름 라이브)** 는 사용자 지시로 스킵(P3). **여러 Runner 의 배정 경로** 는 P6-01.
- 명령·종료 코드는 자기보고, 근거의 진위·옮겨 적기의 충실성·주입≠준수 — 9절 그대로.

## 7. 사람에게 물어야 할 것

1. **P4 의 종료 판정** — (가) P4-PLAN-08(진행기 경유 세 Profile + 혼합 목적 완료, 코드 변경 없이 시험 추가가 목표)을 먼저 하고 P4 를
   닫는다, (나) 계약·판정 수준의 여섯 재현으로 충분하다고 보고 P4 를 `DONE_WITH_LIMITATIONS` 로 닫고 P4-PLAN-08 은 필요할 때. 이 문서는
   (가)를 제안한다 — P4-05 부터 실제 경로가 진행기이고, `preserved`·`already_satisfied` 분기는 어떤 시험도 지나지 않았기 때문이다.
2. **검증 환경** — 실제 codex 가 검증 실행에서 시험을 돌릴 수 있게 하는 시도(절대 경로 인터프리터·PATH 전달)를 별도 작은 실험으로 할지.
   제품 기능이 아니라 환경·CLI 샌드박스의 문제이며, 성공하면 처음으로 실제 `met` 라이브 증거가 생긴다.
3. **실제 codex 의 RCA·maintenance 관찰** — P4-PLAN-08 의 선택 사항(`p4/live/profile_intents.py` 재사용)으로 둘지.
