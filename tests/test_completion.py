"""AC-5~10: 최종 결과 후보 · 사람 최종 확인 · 예외 수용 · 자동 완료 · 종료 후 새 Case.

**세 종류의 기록을 합치지 않는 것이 이 파일의 주제다**(completion-lifecycle 4·7절).

  최종 인수   이 후보를 받아들였다
  예외 결정   표시된 미충족·미검증을 수용했다 — **원래 판정은 그대로 남는다**
  종료 기록   업무가 실제로 종료로 확정됐다 — 미정리 실행이 남으면 만들어지지 않는다

그리고 인수가 다른 권한을 만들지 않는다. 인수했다고 코드 변경 실행이 열리지 않는다.
"""

from __future__ import annotations

import pytest

GOOD_FIELDS = {
    "goal": {"text": "로그에서 오류 줄만 뽑는다", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전 제외", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 미정", "origin": "ai_assumption"},
}


def _refusals(response) -> set[str]:
    return set(response.json()["detail"]["refusals"])


@pytest.fixture
def agreed_case(harness):
    """초안 → QG-01 검토 → 열람 → 동의까지 마친 Case."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(case["id"], intent).status_code == 201
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    return case, intent


# ------------------------------------------------------------------- AC-5


def test_a_candidate_bundles_intent_gate_criteria_and_execution_state(harness, agreed_case):
    """AC-5: 후보가 의도·동의·게이트·기준별 결과·미해결·실행 정리를 한 버전으로 묶는다."""
    case, intent = agreed_case
    candidate = harness.build_candidate(case["id"])

    assert candidate["intent_version_id"] == intent["id"]
    assert candidate["intent_agreement_state"] == "agreed_current"
    assert candidate["gate_verdict"] == "pass"
    assert candidate["criteria_total"] == 2
    assert candidate["criteria_met"] == 0
    assert {u["kind"] for u in candidate["unresolved"]} == {"criterion"}
    assert candidate["unsettled_runs"] == []
    # Case 는 종료가 아니라 **최종 확인 대기**로 간다.
    assert harness.client.get(f"/api/cases/{case['id']}").json()["status"] == (
        "waiting_final_acceptance"
    )


def test_an_unchanged_candidate_is_not_rebuilt(harness, agreed_case):
    """AC-5: 내용이 같으면 후보를 새로 만들지 않는다. 같은 것을 다시 확인시키지 않는다."""
    case, _intent = agreed_case
    first = harness.build_candidate(case["id"])
    second = harness.build_candidate(case["id"])
    assert first["id"] == second["id"]
    assert first["revision"] == 1


def test_a_changed_candidate_supersedes_the_one_the_user_saw(harness, agreed_case):
    """AC-5: 후보가 바뀌면 이전 확인을 새 결과의 인수로 쓰지 않는다.

    completion-lifecycle 3절: "후보가 의미 있게 바뀌면 이전 확인을 새 결과의
    인수로 사용하지 않는다."
    """
    case, _intent = agreed_case
    old = harness.build_candidate(case["id"])

    harness.mark_all_criteria_met(case["id"])
    new = harness.build_candidate(case["id"])
    assert new["id"] != old["id"]
    assert new["revision"] == 2

    # 사용자가 보던 옛 후보로는 인수할 수 없다.
    response = harness.accept(case["id"], old["id"])
    assert response.status_code == 409
    assert "candidate_superseded" in _refusals(response)


# ------------------------------------------------------------------- AC-6


def test_acceptance_needs_an_explicit_statement(harness, agreed_case):
    """AC-6: 모호한 반응을 인수로 확대하지 않는다."""
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])

    response = harness.accept(case["id"], candidate["id"], statement="좋아 보이네요 고마워요")
    assert response.status_code == 400
    assert "not_explicit" in _refusals(response)
    assert harness.result(case["id"])["closure"] is None


def test_unresolved_criteria_block_acceptance(harness, agreed_case):
    """AC-6: `met` 이 아닌 기준이 남아 있으면 인수가 거부된다."""
    case, _intent = agreed_case
    candidate = harness.build_candidate(case["id"])
    response = harness.accept(case["id"], candidate["id"])
    assert response.status_code == 409
    assert "unresolved_criteria" in _refusals(response)


def test_a_case_without_criteria_cannot_be_accepted(harness):
    """AC-6: 기준이 0건이면 인수할 수 없다.

    견줄 기준이 없으면 "미해결 0건"이 되어 아무 것도 확인하지 않은 결과가 조용히
    통과한다. 빈 통과를 만드는 대신 거부로 드러낸다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS, criteria=[])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201

    candidate = harness.build_candidate(case["id"])
    assert candidate["criteria_total"] == 0
    response = harness.accept(case["id"], candidate["id"])
    assert response.status_code == 409
    assert "no_success_criteria" in _refusals(response)


def test_a_stale_intent_agreement_blocks_acceptance(harness, agreed_case):
    """AC-6: 새 의도 버전이 생기면 옛 동의로 결과를 인수하지 않는다."""
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)  # v2

    candidate = harness.build_candidate(case["id"])
    assert candidate["intent_agreement_state"] == "stale_agreement"
    response = harness.accept(case["id"], candidate["id"])
    assert response.status_code == 409
    assert "intent_not_agreed" in _refusals(response)


def test_a_clean_result_is_accepted_and_closed(harness, agreed_case):
    """AC-6: 조건을 갖추면 사람이 인수하고 종료가 확정된다.

    거부만 하는 시스템이 아니라는 것도 확인한다.
    """
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])

    response = harness.accept(case["id"], candidate["id"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["acceptance"]["mode"] == "human"
    assert body["acceptance"]["actor"] == "owner"
    assert body["closure"]["closure_kind"] == "completed"
    assert body["closure"]["exception_count"] == 0
    assert harness.client.get(f"/api/cases/{case['id']}").json()["status"] == "closed"


# ------------------------------------------------------------------- AC-7


def test_an_exception_preserves_the_original_verdict(harness, agreed_case):
    """AC-7: 예외를 수용해도 **원래 판정은 바뀌지 않는다.**

    completion-lifecycle 4절: "'10만 행 통과'로 표시하지 않는다."
    """
    case, _intent = agreed_case
    criteria = harness.criteria(case["id"])
    passing, failing = criteria[0], criteria[1]
    assert (
        harness.record_result(
            case["id"], passing["id"], "met", evidence_kind="human_judgement"
        ).status_code
        == 200
    )
    assert (
        harness.record_result(
            case["id"],
            failing["id"],
            "not_met",
            evidence_kind="human_judgement",
            summary="10만 행에서 실패했다",
        ).status_code
        == 200
    )
    candidate = harness.build_candidate(case["id"])

    accepted = harness.accept_exception(case["id"], candidate["id"], failing["id"])
    assert accepted.status_code == 201, accepted.text
    exception = accepted.json()
    assert exception["original_verdict"] == "not_met"

    # 기준 판정은 그대로다. 예외가 충족으로 바꾸지 않는다.
    after = {c["id"]: c for c in harness.criteria(case["id"])}
    assert after[failing["id"]]["verdict"] == "not_met"

    response = harness.accept(case["id"], candidate["id"])
    assert response.status_code == 201, response.text
    assert response.json()["closure"]["closure_kind"] == "closed_with_exceptions"
    assert response.json()["closure"]["exception_count"] == 1


def test_an_exception_cannot_target_a_met_criterion(harness, agreed_case):
    """AC-7: 충족된 기준에 예외를 걸지 않는다. 걸 것이 없다."""
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])
    criterion = harness.criteria(case["id"])[0]

    response = harness.accept_exception(case["id"], candidate["id"], criterion["id"])
    assert response.status_code == 409
    assert "exception_target_not_failing" in response.json()["detail"]


# ------------------------------------------------------------------- AC-8


def test_auto_completion_is_not_recorded_as_a_human_acceptance(harness, agreed_case):
    """AC-8: 자동 완료를 사람 확인으로 표시하지 않는다(FR-17, D-31)."""
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    assert harness.set_completion_mode(case["id"], "auto_on_conditions").status_code == 200

    response = harness.client.post(f"/api/cases/{case['id']}/auto-complete")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["applied"] is True
    assert body["acceptance"]["mode"] == "auto_policy"
    assert body["acceptance"]["actor"] == "policy:auto_on_conditions"
    assert body["closure"]["closure_kind"] == "completed"


def test_both_modes_agree_on_the_criteria_even_though_one_waits_for_a_person(
    harness, agreed_case
):
    """AC-8: 같은 후보를 두 모드로 봐도 **기준 충족 판정은 같다.**

    completion-lifecycle 9절 1: "사람 확인 필요 여부만 달라지고 기준 충족 판정은
    같아야 한다."
    """
    case, _intent = agreed_case
    criteria = harness.criteria(case["id"])
    harness.record_result(case["id"], criteria[0]["id"], "met", evidence_kind="human_judgement")

    human_view = harness.build_candidate(case["id"])
    assert harness.set_completion_mode(case["id"], "auto_on_conditions").status_code == 200
    auto = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()

    assert auto["applied"] is False
    assert auto["reason"] == "conditions_not_met"
    # 판정 자체는 모드와 무관하게 같다.
    assert auto["candidate"]["criteria_met"] == human_view["criteria_met"] == 1
    assert auto["candidate"]["criteria_total"] == human_view["criteria_total"] == 2
    assert "unresolved_criteria" in auto["refusals"]


def test_auto_mode_does_not_accept_its_own_exceptions(harness, agreed_case):
    """AC-8: 자동 모드는 미충족·미검증을 **스스로 수용하지 않는다.**"""
    case, _intent = agreed_case
    criteria = harness.criteria(case["id"])
    harness.record_result(case["id"], criteria[0]["id"], "met", evidence_kind="human_judgement")
    harness.record_result(
        case["id"], criteria[1]["id"], "not_met", evidence_kind="human_judgement"
    )
    candidate = harness.build_candidate(case["id"])
    assert harness.set_completion_mode(case["id"], "auto_on_conditions").status_code == 200

    # 정책 경로로도 예외 경로로도 스스로 수용하지 않는다.
    auto = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert auto["applied"] is False
    assert "unresolved_criteria" in auto["refusals"]

    attempted = harness.accept_exception(case["id"], candidate["id"], criteria[1]["id"])
    assert attempted.status_code == 409
    assert "auto_policy_cannot_accept_exception" in attempted.json()["detail"]


def test_a_human_acceptance_policy_never_auto_completes(harness, agreed_case):
    """AC-8: 기본 정책에서는 자동 완료가 아무 것도 하지 않는다."""
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])

    result = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert result["applied"] is False
    assert result["reason"] == "policy_is_human_acceptance"
    assert result["closure"] is None


# ------------------------------------------------------------------- AC-9


def test_acceptance_is_a_separate_record_from_agreement_and_gate(harness, agreed_case):
    """AC-9: 인수·예외·의도 동의가 **각각의 행**으로 남는다(FR-23)."""
    case, _intent = agreed_case
    criteria = harness.criteria(case["id"])
    harness.record_result(case["id"], criteria[0]["id"], "met", evidence_kind="human_judgement")
    harness.record_result(
        case["id"], criteria[1]["id"], "not_met", evidence_kind="human_judgement"
    )
    candidate = harness.build_candidate(case["id"])
    harness.accept_exception(case["id"], candidate["id"], criteria[1]["id"])
    assert harness.accept(case["id"], candidate["id"]).status_code == 201

    kinds = [d["kind"] for d in harness.client.get(f"/api/cases/{case['id']}").json()["decisions"]]
    assert kinds.count("intent_agreement") == 1
    assert kinds.count("exception_closure") == 1
    assert kinds.count("final_acceptance") == 1
    # 하나가 다른 하나를 만들지 않는다. push 승인은 없다.
    assert "push_approval" not in kinds


def test_acceptance_does_not_open_code_changing_execution(harness, agreed_case):
    """AC-9: 인수가 실행 권한을 만들지 않는다.

    P2-03이 거부하던 것은 인수 뒤에도 그대로 거부된다. 종료된 Case이므로 이제는
    더 앞단(`case_already_closed`)에서 막히고, 그것도 같은 원칙이다.
    """
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])
    assert harness.accept(case["id"], candidate["id"]).status_code == 201

    instruction = harness.client.get(f"/api/cases/{case['id']}").json()["artifacts"][0]
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-after-acceptance",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "feature_implementation",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "workspace_write",
        },
    )
    assert response.status_code == 409, response.text
    assert "case_already_closed" in str(response.json()["detail"])


def test_code_changing_execution_is_still_refused_before_closure(harness, agreed_case):
    """AC-9: 종료 전에도 마찬가지다. 인수 여부와 무관하게 선행 조건이 없다."""
    case, _intent = agreed_case
    instruction = harness.client.get(f"/api/cases/{case['id']}").json()["artifacts"][0]
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-impl",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "feature_implementation",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "workspace_write",
        },
    )
    assert response.status_code == 409
    refusals = response.json()["detail"]["admission"]["refusals"]
    # 준비 산출물이 없다는 사유(P3-01)와 쓰기 권한이 열려 있지 않다는 사유는
    # **서로 다른 것**이다. 준비를 갖춰도 쓰기 권한은 생기지 않는다(P3-03).
    assert "design_missing" in refusals
    assert "plan_missing" in refusals
    assert "permission_not_allowed_in_stage" in refusals


# ------------------------------------------------------------------ AC-10


@pytest.fixture
def closed_case(harness, agreed_case):
    case, intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])
    assert harness.accept(case["id"], candidate["id"]).status_code == 201
    return case, intent


def test_a_closed_case_refuses_new_intent_versions(harness, closed_case):
    """AC-10: 종료된 Case를 되살리지 않는다."""
    case, _intent = closed_case
    response = harness.client.post(
        f"/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "수정 초안",
            "target_runner_id": "runner-test-1",
            "fields": GOOD_FIELDS,
        },
    )
    assert response.status_code == 409
    assert "case_already_closed" in response.json()["detail"]


def test_a_closed_case_refuses_new_feedback_and_a_second_acceptance(harness, closed_case):
    """AC-10: 종료 후에는 피드백·재인수도 받지 않는다."""
    case, intent = closed_case
    feedback = harness.client.post(
        f"/api/cases/{case['id']}/feedback",
        json={
            "target_intent_version_id": intent["id"],
            "content": "이것도 바꿔 주세요",
            "summary": "추가 요청",
            "target_runner_id": "runner-test-1",
        },
    )
    assert feedback.status_code == 409
    assert "case_already_closed" in feedback.json()["detail"]

    candidate = harness.result(case["id"])["candidate"]
    again = harness.accept(case["id"], candidate["id"], actor="someone-else")
    # 같은 후보의 재전송은 기존 인수를 그대로 돌려준다. 두 번째 인수를 만들지 않는다.
    assert again.status_code == 201
    assert again.json()["acceptance"]["actor"] == "owner"


def test_a_follow_up_change_becomes_a_linked_new_case(harness, closed_case):
    """AC-10: 완료 후 수정은 **연결된 새 Case** 이고 이전 동의를 승계하지 않는다(D-33)."""
    case, _intent = closed_case
    response = harness.client.post(
        f"/api/cases/{case['id']}/successor",
        json={
            "title": "선택한 열만 내보내기",
            "kind": "feature",
            "reason_summary": "완료 후 추가 요청",
        },
    )
    assert response.status_code == 201, response.text
    successor = response.json()
    assert successor["id"] != case["id"]
    assert successor["status"] == "received"

    # 새 Case 는 의도 버전 0개로 시작한다. 옛 동의가 따라오지 않는다.
    state = harness.intent_state(successor["id"])
    assert state["agreement_state"] == "no_intent"

    # 두 Case 가 출처로 연결된다. 이전 종료 기록은 그대로 남는다.
    relations = harness.result(successor["id"])["relations"]
    assert [r["relation"] for r in relations] == ["follow_up_change"]
    assert relations[0]["from_case_id"] == case["id"]
    assert harness.result(case["id"])["closure"]["closure_kind"] == "completed"


def test_reading_a_closed_case_still_works(harness, closed_case):
    """AC-10: 종료 후 **설명 질문**은 막지 않는다. 막는 것은 변경이다.

    completion-lifecycle 6절: "완료 후 질문은 기존 결과·증거를 설명하는 대화로
    처리할 수 있다."
    """
    case, intent = closed_case
    detail = harness.client.get(f"/api/cases/{case['id']}")
    assert detail.status_code == 200
    # 원문 열람도 그대로 된다.
    _request, content = harness.read_original(intent["artifact_id"], intent["artifact_rev"])
    assert content is not None


# ------------------------------------------------------------------ AC-14


def _leave_run_unsettled(harness, case_id: str, run_id: str, outcome: str | None) -> None:
    """결과를 확정할 수 없는 실행을 하나 남긴다.

    `outcome=None` 이면 아직 끝나지 않은 실행, `unknown` 이면 결과 불명이다.
    둘 다 "이 결과가 유효한지 확정할 수 없다"는 같은 상태다.
    """
    instruction = harness.submit_artifact(case_id, "확인 요청")
    harness.create_run(
        case_id, instruction["artifact_id"], run_id, purpose="limited_analysis"
    )
    if outcome is not None:
        run = harness.client.get(f"/api/runs/{run_id}").json()
        reported = harness.client.post(
            f"/api/runner/runs/{run_id}/result",
            json={
                "runner_id": "runner-test-1",
                "generation": run["assignment_generation"],
                "outcome": outcome,
            },
        )
        assert reported.status_code == 200, reported.text


@pytest.mark.parametrize("outcome", [None, "unknown"])
def test_acceptance_is_kept_but_closure_is_withheld_while_a_run_is_unsettled(
    harness, agreed_case, outcome
):
    """AC-14: 미정리 실행이 남으면 **인수는 기록하고 종료는 확정하지 않는다.**

    completion-lifecycle 5절: "결과 후보의 유효성을 확정할 수 없는 실행이 남은
    동안은 인수 결정을 보존하더라도 업무 종료 확정을 보류한다." 인수를 거부하지도
    않고, 인수를 종료로 취급하지도 않는다 — 두 상태를 함께 보인다.
    """
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    _leave_run_unsettled(harness, case["id"], "run-unsettled", outcome)

    candidate = harness.build_candidate(case["id"])
    assert [r["run_id"] for r in candidate["unsettled_runs"]] == ["run-unsettled"]

    response = harness.accept(case["id"], candidate["id"])
    assert response.status_code == 201, response.text
    assert response.json()["acceptance"]["mode"] == "human"
    # 인수는 남고 종료는 없다.
    assert response.json()["closure"] is None
    assert harness.result(case["id"])["closure"] is None
    # Case 는 닫히지 않는다. 최종 확인 대기 그대로다.
    assert harness.client.get(f"/api/cases/{case['id']}").json()["status"] == (
        "waiting_final_acceptance"
    )


def test_auto_completion_refuses_while_a_run_is_unsettled(harness, agreed_case):
    """AC-14: 자동 완료는 미정리 실행이 있으면 아예 완료하지 않는다."""
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    _leave_run_unsettled(harness, case["id"], "run-unsettled", "unknown")
    assert harness.set_completion_mode(case["id"], "auto_on_conditions").status_code == 200

    result = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert result["applied"] is False
    assert "unsettled_runs_present" in result["refusals"]
    assert result["closure"] is None


# ------------------------------------- 남은 항목의 사유를 종류별로 구별한다


def test_open_questions_and_unresolved_feedback_get_their_own_refusal(harness, agreed_case):
    """미해결 피드백을 "기준 미충족"이라고 적지 않는다.

    사유 코드가 뭉뚱그려지면 사람이 엉뚱한 곳을 고친다. 항목 종류마다 다른 코드를
    붙이고, 피드백은 **사람이** 반영/미반영으로 닫아야 사라진다
    (intent-artifacts 3절 — AI가 스스로 "반영했다"고 선언하지 않는다).
    """
    case, intent = agreed_case
    harness.mark_all_criteria_met(case["id"])

    submitted = harness.submit_feedback(case["id"], intent["id"], "이 부분을 바꿔 주세요")
    candidate = harness.build_candidate(case["id"])
    response = harness.accept(case["id"], candidate["id"])
    assert response.status_code == 409
    codes = _refusals(response)
    assert "unresolved_feedback" in codes
    # 기준은 전부 충족이므로 기준 사유는 붙지 않는다.
    assert "unresolved_criteria" not in codes

    # 미반영으로 닫으려면 이유가 있어야 한다.
    feedback_id = submitted["feedback"]["id"]
    silent = harness.client.post(
        f"/api/cases/{case['id']}/feedback/{feedback_id}/disposition",
        json={"reflected": False},
    )
    assert silent.status_code == 409
    assert "needs a reason" in silent.json()["detail"]

    closed = harness.client.post(
        f"/api/cases/{case['id']}/feedback/{feedback_id}/disposition",
        json={"reflected": False, "reason": "이번 범위 밖이라 후속 Case 로 넘긴다"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["state"] == "not_reflected"
    assert closed.json()["disposition_note"].startswith("이번 범위 밖")

    # 닫고 나면 후보가 바뀌고, 새 후보로는 인수할 수 있다.
    candidate = harness.build_candidate(case["id"])
    assert harness.accept(case["id"], candidate["id"]).status_code == 201


def test_a_closed_case_does_not_get_a_new_candidate(harness, agreed_case):
    """종료된 Case 에 새 후보를 만들지 않는다.

    만들면 인수된 후보를 대체해 "무엇을 인수했는가"가 흐려진다.
    """
    case, _intent = agreed_case
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])
    assert harness.accept(case["id"], candidate["id"]).status_code == 201

    response = harness.client.post(f"/api/cases/{case['id']}/completion-candidates")
    assert response.status_code == 409
    assert "case_already_closed" in response.json()["detail"]
    # 인수된 후보는 그대로 남는다.
    assert harness.result(case["id"])["candidate"]["id"] == candidate["id"]
