"""P3-R4 자동 실행·진입·완료 — 자동 시험.

**이 파일이 지키려는 한 가지:** 사람을 언제 부르는가가 값에 따라 달라지되, 부르지
않기로 한 곳에서 **사람이 확인했다는 기록이 생기지 않는다.**

R1~R3 가 붙인 강제는 전부 "막는" 방향이었다. R4 는 방향이 둘이다 — `controlled` 는
막고 기본 `ask_on_decision` 은 **연다**. 여는 쪽이 위험하다. 조건을 갖추지 않았는데
열리면 아무도 보지 않은 결과가 완료가 되고, 조건을 갖췄는데 사람 인수 기록을 함께
만들면 있지도 않은 확인이 근거로 남는다. 두 실수는 방향이 반대이고 둘 다 막아야 한다.

**실제 CLI를 부르지 않는다.** `conftest` 의 `FakeCliExecutor` 를 쓴다. 실제 CLI
연결의 증거는 라이브 검증에서 따로 만든다.
"""

from __future__ import annotations

import sqlite3

import pytest

from tests.conftest import FAKE_TASKS, fake_preparation_response
from tests.test_preparation import _agreed_case, _prepare_both, _refusals

FIELDS = {
    "goal": {"text": "로그에서 오류 줄만 뽑는다", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전 제외", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 미정", "origin": "ai_assumption"},
}


def _policy(harness, case_id):
    return harness.client.get(f"/api/cases/{case_id}/policy").json()


def _set_autonomy(harness, case_id, value):
    return harness.client.put(
        f"/api/cases/{case_id}/autonomy", json={"autonomy": value, "set_by": "owner"}
    )


# ============================================ AC-1~3 controlled 의 시작 확인


def test_controlled_refuses_work_before_the_start_is_confirmed(harness):
    """AC-1 — controlled 는 시작 확인 전에 설계·계획·구현·검증을 배정하지 않는다.

    **R1 이 "기록만 하고 막지 않는다"를 고정했던 자리다.** 이제 막으므로 그 사유가
    진입 검사 기록에도 남아야 한다 — 사람이 왜 실행이 열리지 않았는지 볼 수 있어야
    한다(FR-14).
    """
    case, _intent = _agreed_case(harness)
    assert _set_autonomy(harness, case["id"], "controlled").status_code == 200

    response = harness.ai_prepare(case["id"], "design")
    assert response.status_code == 409, response.text
    assert "controlled_start_not_confirmed" in _refusals(response)

    # **거부가 기록된다.**
    recorded = [
        r for check in harness.admission_checks(case["id"]) for r in check["refusals"]
    ]
    assert "controlled_start_not_confirmed" in recorded


def test_controlled_still_allows_the_draft_and_the_investigation(harness):
    """AC-2 — 초안 작성·의미 검토·조사는 시작 확인 전에도 배정된다.

    시작 확인의 대상은 "목표·범위·기준·허용 행동"이고, 사람이 그것을 확인하려면
    **초안이 먼저 있어야 한다**(case-profiles 3절). 조사까지 막으면 확인에 필요한
    사실을 모을 수 없다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    assert _set_autonomy(harness, case["id"], "controlled").status_code == 200

    # 초안 작성 — 열린다.
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    assert intent is not None
    # 의미 검토 — 열린다.
    assert harness.ai_gate_review(case["id"], intent).status_code == 201

    # 조사 — 열린다. (의도 동의는 controlled 와 **다른 조건**이며 그대로 요구된다.)
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    artifact = harness.submit_artifact(case["id"], "무엇이 있는지 본다")["artifact_id"]
    harness.agent.persist_pending_intakes()
    analysis = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-analysis-1",
            "instruction_artifact_id": artifact,
            "purpose": "limited_analysis",
            "role": "author",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
            "task_id": "task-1",
        },
    )
    assert analysis.status_code == 201, analysis.text


def test_confirming_the_start_opens_the_work(harness):
    """AC-1 — 시작을 확인하면 그 뒤의 작업이 열린다."""
    case, _intent = _agreed_case(harness)
    assert _set_autonomy(harness, case["id"], "controlled").status_code == 200
    harness.confirm_checkpoint(case["id"], "start_scope", subject_id=case["id"])

    assert harness.ai_prepare(case["id"], "design").status_code == 201


def test_superseding_the_start_confirmation_blocks_again(harness):
    """AC-3 — 확인한 대상이 바뀌면 다시 막히고, **확인 기록은 남는다**(FR-23)."""
    case, _intent = _agreed_case(harness)
    _set_autonomy(harness, case["id"], "controlled")
    harness.confirm_checkpoint(case["id"], "start_scope", subject_id=case["id"])
    assert harness.ai_prepare(case["id"], "design").status_code == 201

    superseded = harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/start_scope/supersede",
        json={"reason_summary": "범위가 넓어져 시작 확인을 다시 받는다"},
    )
    assert superseded.status_code == 201, superseded.text

    response = harness.ai_prepare(case["id"], "plan", run_id="run-plan-after")
    assert response.status_code == 409
    assert "controlled_start_not_confirmed" in _refusals(response)
    # 이전 확인이 무엇을 보고 한 것인지는 그대로 남아 있다.
    points = harness.client.get(f"/api/cases/{case['id']}/controlled-checkpoints").json()
    superseded_rows = [
        p
        for p in points
        if p["checkpoint"] == "start_scope" and p["state"] == "superseded"
    ]
    assert superseded_rows and superseded_rows[0]["confirmed_by"] == "owner"


# ==================================================== AC-4~6 기본 자동 완료


def test_the_default_policy_completes_without_a_person(harness):
    """AC-4 — 기본 ask-on-decision 은 조건 충족 시 **사람 인수 없이** 완료한다(D-31).

    **자동 완료를 사람 확인으로 적지 않는다.** 모드는 `auto_policy` 이고 actor 는
    정책 식별자다 — 나중에 그 기록이 "사람이 결과를 확인했다"는 근거로 쓰이면 안 된다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])

    assert _policy(harness, case["id"])["completion_mode"] == "auto_on_conditions"
    assert _policy(harness, case["id"])["completion_mode_source"] == "autonomy_derived"

    harness.mark_all_criteria_met(case["id"])

    view = harness.client.get(f"/api/cases/{case['id']}").json()
    assert view["status"] == "closed"
    assert view["result"]["closure"]["closure_kind"] == "completed"
    candidate = view["result"]["candidate"] or harness.client.get(
        f"/api/cases/{case['id']}/completion-candidates"
    ).json()[-1]
    assert candidate["acceptance"]["mode"] == "auto_policy"
    assert candidate["acceptance"]["actor"] == "policy:auto_on_conditions"
    # 사람의 인수 결정이 만들어지지 않았다.
    human = [
        d
        for d in view["decisions"]
        if d["kind"] == "final_acceptance" and d["actor"] != "policy:auto_on_conditions"
    ]
    assert human == []


def test_auto_completion_does_not_fire_while_something_is_unresolved(harness):
    """AC-5 — 미충족 기준이 남아 있으면 자동 완료가 일어나지 않는다.

    자동 경로는 사람이 보지 않으므로 **미해결 목록이 곧 안전장치다.**
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])

    criteria = harness.criteria(case["id"])
    harness.record_result(case["id"], criteria[0]["id"], "met")
    harness.record_result(case["id"], criteria[1]["id"], "not_met")

    view = harness.client.get(f"/api/cases/{case['id']}").json()
    assert view["status"] != "closed"
    assert view["result"]["closure"] is None
    # 자동 정책은 예외를 **스스로** 수용하지 않는다.
    auto = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert auto["applied"] is False
    assert "unresolved_criteria" in auto["refusals"]


def test_auto_completion_waits_for_an_unsettled_run(harness):
    """AC-5 — 결과를 확정할 수 없는 실행이 남으면 자동 완료하지 않는다.

    completion-lifecycle 5절: "결과 후보의 유효성을 확정할 수 없는 실행이 남은
    동안은 업무 종료 확정을 보류한다."
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    harness.submit_intent_draft(case["id"], FIELDS)
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(case["id"], intent).status_code == 201
    harness.ready_for_acceptance(case["id"], project["id"])

    artifact = harness.submit_artifact(case["id"], "조사")["artifact_id"]
    harness.agent.persist_pending_intakes()
    harness.create_run(case["id"], artifact, run_id="run-open-1")

    harness.mark_all_criteria_met(case["id"])
    view = harness.client.get(f"/api/cases/{case['id']}").json()
    assert view["status"] != "closed"
    assert view["result"]["unsettled_runs"]


def test_a_case_without_criteria_never_auto_completes(harness):
    """AC-5 — 견줄 기준이 0건이면 "미해결 0건"이 되어 빈 통과가 생긴다. 막는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS, criteria=[])
    harness.ready_for_acceptance(case["id"], project["id"])

    assert harness.client.get(f"/api/cases/{case['id']}").json()["status"] != "closed"
    auto = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert auto["applied"] is False
    assert "no_success_criteria" in auto["refusals"]


def test_an_explicit_completion_setting_beats_the_derived_one(harness):
    """AC-9 — 사람이 정한 완료 정책을 도출값이 조용히 덮지 않는다.

    autonomy-budget-policy 5절: "사용자 명시 설정을 조용히 덮어쓰지 않는다."
    조회가 세 출처를 구별한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    assert _policy(harness, case["id"])["completion_mode_source"] == "autonomy_derived"

    assert harness.set_completion_mode(case["id"], "human_acceptance").status_code == 200
    policy = _policy(harness, case["id"])
    assert policy["completion_mode"] == "human_acceptance"
    assert policy["completion_mode_source"] == "case_explicit"

    # Autonomy 를 바꿔도 명시 설정이 이긴다.
    _set_autonomy(harness, case["id"], "ask_on_decision")
    assert _policy(harness, case["id"])["completion_mode"] == "human_acceptance"


# ============================================== AC-7~8 controlled 의 종료


def _controlled_ready_case(harness):
    """controlled 이고 기준이 모두 충족된 Case. 종료 직전 상태다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    assert _set_autonomy(harness, case["id"], "controlled").status_code == 200
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])
    harness.mark_all_criteria_met(case["id"])
    return case


def test_controlled_does_not_close_before_the_result_is_confirmed(harness):
    """AC-7 — 결과 후보 확인 전에는 종료되지 않는다(D-65)."""
    case = _controlled_ready_case(harness)
    assert harness.client.get(f"/api/cases/{case['id']}").json()["status"] != "closed"

    candidate = harness.build_candidate(case["id"])
    refused = harness.accept(case["id"], candidate["id"])
    assert refused.status_code == 409, refused.text
    refusals = refused.json()["detail"]["refusals"]
    assert "controlled_start_not_confirmed" in refusals
    assert "controlled_result_not_confirmed" in refusals


def test_confirming_the_result_closes_the_case(harness):
    """AC-7 — 확인하면 **시스템이** 종료를 확정한다(D-65 "…→ 시스템 종료").

    사람이 또 한 번 "완료"를 눌러야 하면 같은 내용의 확인을 두 번 요구하는 것이다.
    """
    case = _controlled_ready_case(harness)
    harness.confirm_checkpoint(case["id"], "start_scope", subject_id=case["id"])
    candidate = harness.build_candidate(case["id"])
    harness.confirm_checkpoint(
        case["id"],
        "result_candidate",
        subject_type="completion_candidate",
        subject_id=candidate["id"],
        subject_hash=candidate["snapshot_hash"],
    )

    view = harness.client.get(f"/api/cases/{case['id']}").json()
    assert view["status"] == "closed"
    assert view["result"]["closure"]["closure_kind"] == "completed"
    # **사람의 확인이므로 사람 인수다.** 정책 식별자로 적지 않는다.
    accepted = harness.client.get(
        f"/api/cases/{case['id']}/completion-candidates"
    ).json()[-1]["acceptance"]
    assert accepted["mode"] == "human"
    assert accepted["actor"] == "owner"


def test_a_changed_candidate_needs_a_new_confirmation(harness):
    """AC-8 — 확인한 후보의 내용이 바뀌면 이전 확인을 새 후보에 쓰지 않는다."""
    case = _controlled_ready_case(harness)
    harness.confirm_checkpoint(case["id"], "start_scope", subject_id=case["id"])
    candidate = harness.build_candidate(case["id"])
    harness.confirm_checkpoint(
        case["id"],
        "result_candidate",
        subject_type="completion_candidate",
        subject_id=candidate["id"],
        # **다른 내용을 확인한 것으로 둔다.** 그 사이 코드·검토가 달라진 상태다.
        subject_hash="f" * 64,
    )
    refused = harness.accept(case["id"], candidate["id"])
    assert refused.status_code == 409
    assert "controlled_confirmation_stale" in refused.json()["detail"]["refusals"]


def test_the_same_candidate_is_not_re_confirmed(harness):
    """AC-8 — 같은 내용의 재전송에는 재확인을 요구하지 않는다(D-65 마지막 문장).

    후보 해시가 같으면 이전 확인이 그대로 유효하다. 상태 조회나 같은 요청의 재전송이
    사람을 다시 부르지 않는다.
    """
    case = _controlled_ready_case(harness)
    harness.confirm_checkpoint(case["id"], "start_scope", subject_id=case["id"])
    first = harness.build_candidate(case["id"])
    harness.confirm_checkpoint(
        case["id"],
        "result_candidate",
        subject_type="completion_candidate",
        subject_id=first["id"],
        subject_hash=first["snapshot_hash"],
    )
    # 확인 한 번으로 종료됐고, 확인 지점이 다시 `required` 로 돌아가지 않았다.
    assert harness.client.get(f"/api/cases/{case['id']}").json()["status"] == "closed"
    points = harness.client.get(
        f"/api/cases/{case['id']}/controlled-checkpoints"
    ).json()
    result = [p for p in points if p["checkpoint"] == "result_candidate"]
    assert [p["state"] for p in result] == ["confirmed"]
    assert result[0]["subject_hash"] == first["snapshot_hash"]


def test_a_confirmation_does_not_create_a_publish_permission(harness):
    """AC-7 — 결과 확인이 push·게시 권한을 만들지 않는다(D-32·D-65).

    게시는 P5 다. 네 축이 강제로 바뀌었다고 다섯째까지 번지지 않는다.
    """
    case = _controlled_ready_case(harness)
    harness.confirm_checkpoint(case["id"], "start_scope", subject_id=case["id"])
    candidate = harness.build_candidate(case["id"])
    harness.confirm_checkpoint(
        case["id"],
        "result_candidate",
        subject_type="completion_candidate",
        subject_id=candidate["id"],
        subject_hash=candidate["snapshot_hash"],
    )
    view = harness.client.get(f"/api/cases/{case['id']}").json()
    kinds = {d["kind"] for d in view["decisions"]}
    assert "push_approval" not in kinds and "publication_grant" not in kinds
    assert _policy(harness, case["id"])["enforcement"]["publish"]["state"] == (
        "not_implemented"
    )


# ================================ AC-29b `autonomy = NULL` 의 controlled 취급


def test_an_unrecorded_autonomy_is_treated_as_controlled(harness):
    """AC-29b — R1 이전 Case 는 controlled 로 **취급**된다(사용자 결정 2026-09-22).

    **저장된 값은 건드리지 않는다.** `controlled` 를 적어 넣으면 있지도 않은 사람의
    선택을 기록하는 일이 된다(D-14·FR-23). R1 의 시험
    (`test_a_pre_r1_case_is_never_reported_as_ask_on_decision`)이 고정한 사실이
    그대로 통과해야 한다.
    """
    project = harness.create_project()
    case = harness.create_pre_r1_case(project["id"])
    policy = _policy(harness, case["id"])

    # 기록은 그대로 **미기록**이다.
    assert policy["autonomy"] is None
    assert policy["autonomy_recorded"] is False
    assert policy["autonomy_source"] == "migrated_unknown"
    # 적용되는 값만 controlled 이며 그 출처가 따로 말해진다.
    assert policy["effective_autonomy"] == "controlled"
    assert policy["effective_source"] == "migrated_unknown_treated_as_controlled"
    assert policy["is_treatment"] is True

    # 확인 지점이 요구되고, **사람이 고른 설정과 구별된다.**
    points = harness.client.get(f"/api/cases/{case['id']}/controlled-checkpoints").json()
    assert {p["checkpoint"] for p in points} == {"start_scope", "result_candidate"}
    assert all(p["state"] == "required" for p in points)
    assert all("이행 정책" in (p["note_summary"] or "") for p in points)


def test_recording_the_autonomy_replaces_the_treatment(harness):
    """AC-29b — 사람이 값을 기록하면 그때부터 그 설정을 따른다."""
    project = harness.create_project()
    case = harness.create_pre_r1_case(project["id"])
    assert _set_autonomy(harness, case["id"], "ask_on_decision").status_code == 200

    policy = _policy(harness, case["id"])
    assert policy["autonomy"] == "ask_on_decision"
    assert policy["autonomy_recorded"] is True
    assert policy["effective_source"] == "recorded"
    assert policy["is_treatment"] is False
    # 요구되던 확인 지점은 정리된다. **확인한 기록이 있었다면 남는다.**
    assert harness.client.get(
        f"/api/cases/{case['id']}/controlled-checkpoints"
    ).json() == []


# ====================================== AC-10~12 Fast Lane 과 결합 기록


def _fast_lane_case(harness):
    """Fast Lane 조건을 만족하는 Case. 간소 수준이고 열린 질문이 없다."""
    case, _intent = _agreed_case(harness)
    return case


def test_a_fast_lane_case_needs_only_the_combined_record(harness):
    """AC-10 — Fast Lane 이면 결합 기록 하나로 구현이 배정된다(D-60).

    "별도 설계·계획 파일이나 실행 없이 요청·핵심 변경 이유·작업·검증의 최소 논리
    기록으로 진행한다"(intent-artifacts 48행)의 구현이다. **없어지는 것은 없다** —
    두 건이 한 건이 될 뿐이다.
    """
    case = _fast_lane_case(harness)
    assert harness.preparation(case["id"])["fast_lane"]["eligible"] is True

    harness.register_combined(case["id"])
    prep = harness.preparation(case["id"])
    assert prep["combined"]["artifact"] is not None
    assert prep["design"]["artifact"] is None
    assert prep["plan"]["artifact"] is None

    harness.complete_task(case["id"], "T1", run_id="run-fl-t1")
    response = harness.request_implementation(case["id"], run_id="run-fl-impl")
    assert response.status_code == 201, response.text


def test_leaving_the_fast_lane_asks_for_preparation_not_for_a_person(harness):
    """AC-11 — Fast Lane 이탈은 **사람 확인 요구가 아니라 준비 추가**다.

    autonomy-budget-policy 4절 마지막: "새 위험이나 불확실성으로 Fast Lane 조건이
    깨지면 일반 자동 진행으로 전환하고 필요한 조사·설계·검증을 추가한다. **이것만으로
    사람 확인을 요구하지 않는다.**"
    """
    case = _fast_lane_case(harness)
    harness.register_combined(case["id"])
    harness.complete_task(case["id"], "T1", run_id="run-fl-t1")

    # 수준이 올라가 Fast Lane 조건이 깨진다.
    assert harness.adjust_level(case["id"], "deep", reason="영향 범위가 넓어졌다").status_code == 201
    assert harness.preparation(case["id"])["fast_lane"]["eligible"] is False

    response = harness.request_implementation(case["id"], run_id="run-fl-impl-2")
    assert response.status_code == 409
    refusals = _refusals(response)
    assert "fast_lane_left_needs_preparation" in refusals
    # **무엇을 더 준비해야 하는지**를 말한다. 사람 확인 사유는 나오지 않는다.
    assert "design_missing" in refusals
    assert "controlled_start_not_confirmed" not in refusals


def test_a_combined_record_with_a_missing_section_is_refused(harness):
    """AC-12 — 결합 기록도 필수 항목이 미정이면 거부된다.

    Fast Lane 은 기록을 줄이는 것이지 **내용을 비우는 것이 아니다**.
    """
    case = _fast_lane_case(harness)
    harness.register_combined(case["id"], sections={"change_summary": "필터를 더한다"})

    response = harness.request_implementation(case["id"], run_id="run-fl-impl", task_id="T1")
    assert response.status_code == 409
    assert "combined_record_incomplete_for_level" in _refusals(response)


def test_the_two_stage_path_still_works_in_a_fast_lane_case(harness):
    """AC-10 — 결합 기록은 **대체하는 선택지**이지 강제가 아니다.

    이미 설계·계획이 있으면 Fast Lane 이어도 그대로 통과한다.
    """
    case = _fast_lane_case(harness)
    assert harness.preparation(case["id"])["fast_lane"]["eligible"] is True
    _prepare_both(harness, case["id"])

    assert harness.request_implementation(case["id"]).status_code == 201


# ============================ AC-13~16 가벼운 확인과 독립 의미 검토


def test_the_conformance_check_cannot_be_skipped(harness):
    """AC-13 — 요청 정합성 확인은 끌 수 없다. 기록이 없으면 `not_run` 이다.

    규칙 검사만 통과한 상태를 게이트 통과로 만들지 않는다는 QG-01의 규칙이
    방식이 둘로 갈린 뒤에도 그대로다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)

    gate = harness.gate(case["id"])
    assert gate["rule_verdict"] == "pass"
    assert gate["verdict"] == "not_run"
    conformance = harness.conformance(case["id"])
    assert conformance["method"] is None
    assert conformance["verdict"] == "not_run"


def test_a_light_check_passes_the_gate_but_says_what_it_did_not_see(harness):
    """AC-14 — 가벼운 확인을 **독립 검토 완료로 표시하지 않는다**(D-25).

    두 방식이 같은 `pass` 로 보이면 "미실행을 통과로 표시하지 않는다"가 깨진다.
    그래서 방식과 **보지 않은 범위**가 값으로 남는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    intent = harness.latest_intent(case["id"])

    response = harness.light_conformance(case["id"], intent["id"])
    assert response.status_code == 201, response.text
    body = response.json()

    assert body["method"] == "light"
    assert body["required_method"] == "light"
    assert body["independent_review_required"] is False
    assert "AI 가 검토하지 않았다" in body["unverified_scope"]
    assert harness.gate(case["id"])["verdict"] == "pass"
    # **AI 판정은 여전히 `not_run` 이다.** 가벼운 확인이 AI 검토로 적히지 않는다.
    assert harness.gate(case["id"])["ai_verdict"] == "not_run"


@pytest.mark.parametrize(
    "setup,reason",
    [
        ("level", "level_above_simple"),
        ("evidence_gap", "evidence_gap"),
    ],
)
def test_risk_forces_the_independent_review(harness, setup, reason):
    """AC-15 — 위험·불확실성이 있으면 가벼운 확인으로 통과하지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    if setup == "evidence_gap":
        sizing = {
            "recommended_level": "simple",
            "axes": [
                {
                    "axis": axis,
                    "weight": "insufficient_evidence" if i == 0 else "low",
                    "judgement": "근거가 부족하다" if i == 0 else "영향이 작다",
                }
                for i, axis in enumerate(
                    [
                        "intent_clarity",
                        "change_scope",
                        "compatibility_and_data",
                        "permission_and_security",
                        "reversibility",
                        "uncertainty",
                        "verification_difficulty",
                    ]
                )
            ],
        }
        harness.submit_intent_draft(case["id"], FIELDS, sizing=sizing)
    else:
        harness.submit_intent_draft(case["id"], FIELDS)
        harness.adjust_level(case["id"], "deep", reason="영향이 크다")

    intent = harness.latest_intent(case["id"])
    requirement = harness.conformance(case["id"])
    assert requirement["required_method"] == "independent"
    assert reason in [r["reason"] for r in requirement["reasons"]]

    # 가벼운 확인을 기록해도 게이트는 통과하지 않는다.
    assert harness.light_conformance(case["id"], intent["id"]).status_code == 201
    assert harness.gate(case["id"])["verdict"] == "not_run"
    assert harness.conformance(case["id"])["method"] is None


def test_a_case_setting_can_raise_but_not_lower_the_requirement(harness):
    """AC-15 — Case 설정은 독립 검토를 **요구하는 방향으로만** 작용한다.

    "필수 요청 정합성 확인은 일반 preset 이나 AI 추천으로 완화할 수 없다"
    (autonomy-budget-policy 5절). 낮추는 인자가 API 표면에 없는 것이 그 계약이다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    assert harness.conformance(case["id"])["required_method"] == "light"

    assert harness.client.put(
        f"/api/cases/{case['id']}/conformance-policy",
        json={
            "required": True,
            "set_by": "owner",
            "reason": "이 의도는 독립 검토를 받는다",
        },
    ).status_code == 200
    requirement = harness.conformance(case["id"])
    assert requirement["required_method"] == "independent"
    assert "case_policy_requires_independent_review" in [
        r["reason"] for r in requirement["reasons"]
    ]


def test_the_independent_review_is_still_a_separate_session(harness):
    """AC-16 — 독립 검토는 여전히 작성과 별도 세션이다(D-28).

    방식이 둘로 갈렸다고 독립 검토의 조건이 느슨해지지 않는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.agent.cli_executor.fixed_session_ref = "same-session"
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    gate = harness.gate(case["id"])
    assert gate["verdict"] != "pass"
    assert any(f["criterion"] == "review_session_not_separate" for f in gate["findings"])


def test_an_independent_review_is_recorded_as_a_conformance_check(harness):
    """AC-14 — 독립 검토도 같은 표에 **다른 방식으로** 남는다.

    두 방식을 한 컬럼으로 합치면 무엇을 실제로 했는지가 사라진다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(case["id"], intent).status_code == 201

    conformance = harness.conformance(case["id"])
    assert conformance["method"] == "independent"
    assert conformance["verdict"] == "pass"
    # 독립 검토에는 **보지 않은 범위**가 없다. 원문의 의미를 실제로 봤다.
    assert conformance["unverified_scope"] is None
    assert harness.gate(case["id"])["verdict"] == "pass"


# ======================================= AC-18~21 누적 material delta


def _change_an_agreed_field(harness, case_id, origin="ai_proposal", feedback=None):
    """동의된 의도의 항목 하나를 바꾼 새 버전을 낸다."""
    fields = dict(FIELDS)
    fields["scope"] = {
        "text": "읽기 전용에서 쓰기까지 넓힌다",
        "origin": origin,
        "change_from_prev": "changed",
    }
    return harness.submit_intent_draft(
        case_id, fields, reflects_feedback=feedback or []
    )


def test_an_ai_change_to_an_agreed_intent_becomes_a_pending_delta(harness):
    """AC-18 — AI 출처 변경이 동의된 의도를 바꾸면 `pending` 으로 쌓인다(D-60)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])

    _change_an_agreed_field(harness, case["id"])
    state = harness.material_deltas(case["id"])
    pending = [d for d in state["pending"] if d["target_key"] == "scope"]
    assert pending, state
    assert pending[0]["materiality"] == "material"
    assert pending[0]["state"] == "pending"
    # 비교 대상이 **위임 기준**이라는 사실이 응답에 있다.
    assert "AI 초안이 아니다" in state["detail"]


def test_a_pending_delta_blocks_the_dependent_work(harness):
    """AC-18 — 미확인 변경이 의존 작업을 막는다.

    연결을 모르는 변경은 **전부 막는다** — 모르는 것을 안전한 쪽으로 읽으면
    연결하지 않는 것만으로 차단이 사라진다.
    """
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])
    _change_an_agreed_field(harness, case["id"])

    response = harness.request_implementation(case["id"], run_id="run-delta-impl")
    assert response.status_code == 409
    assert "material_delta_unconfirmed" in _refusals(response)


def test_a_user_directed_change_updates_the_delegation_instead(harness):
    """AC-19 — 사용자 지시에서 온 변경은 위임 기준을 갱신하고 막지 않는다(D-60).

    "실제 답한 항목과 명시한 범위의 위임 기준만 갱신"이 그 문장이다. 정상 흐름을
    여는 경로가 여기다 — 그것이 없으면 과다 차단이 곧 막다른 길이 된다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])

    intent = harness.latest_intent(case["id"])
    feedback = harness.submit_feedback(
        case["id"], intent["id"], "범위를 쓰기까지 넓혀 주세요"
    )["feedback"]
    _change_an_agreed_field(
        harness,
        case["id"],
        origin="user_requirement",
        feedback=[feedback["id"]],
    )

    state = harness.material_deltas(case["id"])
    scope = [d for d in state["all"] if d["target_key"] == "scope"]
    assert scope and scope[0]["materiality"] == "user_directed"
    assert scope[0]["state"] == "adopted"
    assert [d for d in state["pending"] if d["target_key"] == "scope"] == []


def test_deltas_accumulate_against_the_last_delegation(harness):
    """AC-20 — 작은 변경을 연속 채택해도 **누적 차이가 사라지지 않는다**(D-60).

    AI 자신의 직전 초안끼리 비교하면 매번 "한 항목만 바뀌었다"가 되어 원래 요청과
    다른 결과로 이동할 수 있다. 그래서 기준은 마지막 유효 위임이다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])

    for index, text in enumerate(("1차 확대", "2차 확대", "3차 확대")):
        fields = dict(FIELDS)
        fields["scope"] = {
            "text": text,
            "origin": "ai_proposal",
            "change_from_prev": "changed",
        }
        harness.submit_intent_draft(case["id"], fields)

    pending = harness.material_deltas(case["id"])["pending"]
    assert len([d for d in pending if d["target_key"] == "scope"]) == 3


def test_an_ai_assessment_does_not_clear_a_pending_delta(harness):
    """AC-21 — AI 의 "의미가 같다" 평가만으로 `pending` 이 풀리지 않는다.

    autonomy-budget-policy 3절: "AI 자신의 최근 초안끼리만 비교하거나 `의미가 같음`
    이라는 주장만으로 새 의미를 승인하지 않는다." 이 경로에 해소 분기가 하나라도
    있으면 AI 가 자기 평가로 차단을 푼다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])
    _change_an_agreed_field(harness, case["id"])

    delta = harness.material_deltas(case["id"])["pending"][0]
    response = harness.client.post(
        f"/api/cases/{case['id']}/material-deltas/{delta['id']}/assessment",
        json={"assessment": "표현만 정리했고 의미는 같다"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["ai_assessment"]
    # **상태는 그대로다.**
    assert response.json()["state"] == "pending"
    assert harness.material_deltas(case["id"])["pending"]


def test_a_person_clears_one_delta_at_a_time(harness):
    """AC-18 — 사람의 확인은 그 변경 한 건에만 적용된다.

    한 번의 확인이 누적 전체의 승인이 되면 누적을 세는 의미가 없다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])
    for text in ("1차", "2차"):
        fields = dict(FIELDS)
        fields["scope"] = {
            "text": text,
            "origin": "ai_proposal",
            "change_from_prev": "changed",
        }
        harness.submit_intent_draft(case["id"], fields)

    pending = harness.material_deltas(case["id"])["pending"]
    assert len(pending) >= 2
    response = harness.client.post(
        f"/api/cases/{case['id']}/material-deltas/{pending[0]['id']}/confirmation",
        json={"actor": "owner", "explicit": True},
    )
    assert response.status_code == 201, response.text
    assert len(response.json()["pending"]) == len(pending) - 1


def test_a_delta_confirmation_must_be_explicit(harness):
    """AC-18 — 명시적 확인이 아닌 요청을 확인으로 적지 않는다(D-14)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])
    _change_an_agreed_field(harness, case["id"])

    delta = harness.material_deltas(case["id"])["pending"][0]
    response = harness.client.post(
        f"/api/cases/{case['id']}/material-deltas/{delta['id']}/confirmation",
        json={"actor": "owner", "explicit": False},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["refusals"] == ["not_explicit"]


# ===================================== AC-22 피드백 영향의 자동 연결


def test_an_unaffected_criterion_keeps_its_verdict(harness):
    """AC-22 — 피드백이 반영돼도 **영향 없는 판정은 유지된다**.

    intent-artifacts 69행: "의도가 바뀌면 연결된 설계·계획·성공 기준을 재검토하고,
    **영향이 없는 기록은 유지한다**." 한 항목을 고친 피드백 하나가 모든 검증을
    무효로 만들면 그 규칙이 깨진다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])

    criteria = harness.criteria(case["id"])
    harness.record_result(case["id"], criteria[0]["id"], "met")

    # 의도 항목만 바꾸고 기준은 그대로 둔다.
    fields = dict(FIELDS)
    fields["constraints"] = {
        "text": "Windows 로컬, 한글 인코딩 유지",
        "origin": "user_requirement",
        "change_from_prev": "changed",
    }
    harness.submit_intent_draft(case["id"], fields)

    after = {c["criterion_key"]: c for c in harness.criteria(case["id"])}
    kept = after[criteria[0]["criterion_key"]]
    assert kept["verdict"] == "met"
    # **다시 확인한 것이 아니라 이어진 판정**임이 드러난다.
    assert kept["recheck_source"].startswith("carried_from:")


def test_a_changed_criterion_does_not_keep_its_verdict(harness):
    """AC-22 — 기준의 내용이 바뀌면 이전 판정을 잇지 않는다.

    이쪽이 없으면 위 시험은 "판정을 영원히 들고 간다"가 된다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])
    criteria = harness.criteria(case["id"])
    harness.record_result(case["id"], criteria[0]["id"], "met")

    changed = [
        {
            "key": criteria[0]["criterion_key"],
            "relates_to": criteria[0]["relates_to"],
            "text": "기대값이 달라진 기준",
            "method": "다른 방법으로 확인한다",
            "summary": "기대값이 달라졌다",
            "method_summary": "다른 방법",
        }
    ]
    harness.submit_intent_draft(case["id"], FIELDS, criteria=changed)

    after = {c["criterion_key"]: c for c in harness.criteria(case["id"])}
    assert after[criteria[0]["criterion_key"]]["verdict"] == "unverified"


# ============================== AC-23~25 목적의 경계와 로컬 실험


def test_an_analysis_case_cannot_widen_into_a_product_change(harness):
    """AC-23 — 원인 분석 Case 는 제품 수정으로 목적을 확대하지 않는다(D-66·FR-20)."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "지연 원인", profile="root_cause_analysis")
    artifact = harness.submit_artifact(case["id"], "고쳐 주세요")["artifact_id"]
    harness.agent.persist_pending_intakes()

    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-rca-impl",
            "instruction_artifact_id": artifact,
            "purpose": "feature_implementation",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "workspace_write",
            "task_id": "task-1",
        },
    )
    assert response.status_code == 409
    assert "purpose_outside_case_objective" in _refusals(response)


def test_a_user_decision_widens_the_objective(harness):
    """AC-23 — 넓히는 방법은 **사용자의 명시 결정** 하나다(D-62·D-66).

    Profile 재분류로 넓히지 않는다. 그 경로가 열려 있으면 분류를 바꾸는 것만으로
    권한이 생긴다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "지연 원인", profile="root_cause_analysis")
    response = harness.client.post(
        f"/api/cases/{case['id']}/delegation-basis",
        json={
            "basis_kind": "user_decision",
            "summary": "원인을 찾으면 그 수정까지 해 주세요",
        },
    )
    assert response.status_code == 201, response.text

    artifact = harness.submit_artifact(case["id"], "고쳐 주세요")["artifact_id"]
    harness.agent.persist_pending_intakes()
    admission = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-rca-impl",
            "instruction_artifact_id": artifact,
            "purpose": "feature_implementation",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "workspace_write",
            "task_id": "task-1",
        },
    )
    # 다른 조건(작업공간·준비)으로는 막혀도 **목적 사유는 사라진다.**
    assert "purpose_outside_case_objective" not in _refusals(admission)


def test_a_local_experiment_does_not_need_the_feature_pipeline(harness):
    """AC-24 — 로컬 실험은 설계·계획·작업 그래프를 요구하지 않는다(D-66).

    "임시 코드가 있다는 이유만으로 기능 개발 전체 절차를 요구하지 않는다."
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "지연 원인", profile="root_cause_analysis")
    artifact = harness.submit_artifact(case["id"], "재현해 주세요")["artifact_id"]
    harness.agent.persist_pending_intakes()

    refusals = _refusals(harness.run_experiment(case["id"], artifact))
    # 준비·그래프 사유는 나오지 않는다.
    assert "design_missing" not in refusals
    assert "plan_missing" not in refusals
    assert "work_graph_missing" not in refusals
    # **작업공간은 그대로 요구된다.** 실험이라고 사용자의 트리를 보호하지 않는 것이
    # 아니다(FR-08·FR-26).
    assert "workspace_not_ready" in refusals


def test_a_local_experiment_needs_a_recorded_profile(harness):
    """AC-24 — Profile 이 기록되지 않은 Case 에서는 실험을 열지 않는다(D-62).

    유도한 목적으로 쓰기를 여는 것은 "유도해 채우지 않는다"를 가장 비싼 방식으로
    어기는 일이다.
    """
    project = harness.create_project()
    case = harness.create_pre_r1_case(project["id"])
    artifact = harness.submit_artifact(case["id"], "재현해 주세요")["artifact_id"]
    harness.agent.persist_pending_intakes()

    assert "profile_not_recorded" in _refusals(harness.run_experiment(case["id"], artifact))


def test_an_experiment_run_is_marked_as_one(harness):
    """AC-25 — 실험 변경이 제품 변경과 구별된다(D-66 "증거와 임시 변경을 구분한다").

    **요청이 스스로 주장하지 못한다.** 표시는 목적에서 도출된다 — 요청이 그 구별을
    정하면 임시 변경을 실험으로 적어 검증을 건너뛸 수 있다.
    """
    project, _repo = harness.create_git_project(name="experiment")
    case = harness.create_case(project["id"], "지연 원인", profile="root_cause_analysis")
    harness.prepare_workspace(case["id"])
    artifact = harness.submit_artifact(case["id"], "재현해 주세요")["artifact_id"]
    harness.agent.persist_pending_intakes()

    response = harness.run_experiment(case["id"], artifact)
    assert response.status_code == 201, response.text
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT is_experiment, purpose FROM run WHERE run_id = 'run-experiment-1'"
    ).fetchone()
    conn.close()
    assert row["purpose"] == "local_experiment"
    assert row["is_experiment"] == 1


# ============================== AC-26 무변경 목표 충족과 미재현


def test_not_reproducing_a_defect_is_not_a_met_criterion(harness):
    """AC-26 — 미재현은 `met` 으로 저장되지 않는다(case-profiles 4절).

    화면 문구로만 구별하면 API 직접 호출로 우회된다. 그래서 **쓰기 경로에서** 막는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "결함", profile="defect_fix")
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])
    criterion = harness.criteria(case["id"])[0]

    response = harness.record_result(
        case["id"], criterion["id"], "met", satisfaction="not_reproduced"
    )
    assert response.status_code == 409
    assert "not reproducing" in response.text


def test_an_already_satisfied_goal_needs_run_evidence(harness):
    """AC-26 — 무변경 충족은 **검증 실행의 증거**를 요구한다.

    "실제 변경 없이 이미 목표 상태임을 증거로 확인한 경우도 정상 완료할 수 있다.
    그러나 재현 실패나 단일 테스트 통과를 기존 문제 해결의 증거로 확대하지 않는다"
    (case-profiles 4절). 사람 판단만으로 적으면 미재현과 구별되지 않는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "결함", profile="defect_fix")
    harness.submit_intent_draft(case["id"], FIELDS)
    harness.ready_for_acceptance(case["id"], project["id"])
    criterion = harness.criteria(case["id"])[0]

    refused = harness.record_result(
        case["id"],
        criterion["id"],
        "met",
        evidence_kind="human_judgement",
        satisfaction="already_satisfied",
    )
    assert refused.status_code == 409
    assert "run_output evidence" in refused.text


# ============================ AC-27 우회하지 않는다 (R2·R3 와 함께)


def test_the_automatic_path_still_passes_the_repository_check(harness):
    """AC-27 — 자동 진행이 R2 의 저장소 검사를 우회하지 않는다."""
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])
    # 작업공간을 만들지 않은 채 쓰기를 요청한다.
    response = harness.request_implementation(
        case["id"], run_id="run-nows", permission="workspace_write"
    )
    assert response.status_code == 409
    assert "workspace_not_ready" in _refusals(response)


def test_the_automatic_path_still_passes_the_budget_check(harness):
    """AC-27 — 자동 진행이 R3 의 예약을 우회하지 않는다.

    새 자동 경로가 `create_run()` 을 거치지 않으면 예산이 무의미해진다.
    """
    case, _intent = _agreed_case(harness)
    harness.client.put(
        f"/api/cases/{case['id']}/budget",
        json={
            "metric": "run_count",
            "threshold_kind": "hard",
            "limit_value": 2,
            "set_by": "owner",
        },
    )
    # 이 Case 는 의미 검토 실행 하나를 이미 썼다. 한도 2 는 준비 실행 하나를 더
    # 허용하고 그 다음을 막는다.
    first = harness.ai_prepare(case["id"], "design")
    second = harness.ai_prepare(case["id"], "design", run_id="run-design-2")
    assert first.status_code == 201
    assert second.status_code == 409
    assert "budget_hard_limit_reached" in _refusals(second)


# ================================================== AC-28 재시작 복원


def test_the_progression_records_survive_a_reopened_database(harness):
    """AC-28 — 연결을 닫고 다시 열어도 확인·delta·정합성 기록이 그대로다.

    (프로세스 강제 종료는 `test_restart_recovery.py` 가 따로 확인한다.)
    """
    from controller import db as dbmod
    from controller.repository import Repository

    project = harness.create_project()
    case = harness.create_case(project["id"])
    _set_autonomy(harness, case["id"], "controlled")
    harness.submit_intent_draft(case["id"], FIELDS)
    intent = harness.latest_intent(case["id"])
    harness.light_conformance(case["id"], intent["id"])
    harness.confirm_checkpoint(case["id"], "start_scope", subject_id=case["id"])
    harness.ready_for_acceptance(case["id"], project["id"])
    _change_an_agreed_field(harness, case["id"])

    conn = dbmod.connect(harness.controller_config.db_path)
    dbmod.migrate(conn)
    repo = Repository(conn)
    state = repo.checkpoint_state(case["id"])
    deltas = repo.material_delta_state(case["id"])
    conformance = repo.conformance_state(case["id"])
    conn.close()

    assert state["start_confirmed"] is True
    assert deltas["pending"]
    # 새 의도 버전이 생겼으므로 옛 가벼운 확인은 이 버전의 것이 아니다.
    assert conformance["method"] is None


# ====================================== AC-30 강제 표시와 남은 경계


def test_the_enforcement_table_now_shows_four_enforced_axes(harness):
    """AC-30 — `autonomy`·`controlled_checkpoint` 가 강제로 바뀌고 게시만 남는다.

    (같은 사실을 `test_policy.py` 가 축별로 확인한다. 여기서는 **남은 경계**를 본다.)
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    enforcement = _policy(harness, case["id"])["enforcement"]
    enforced = {k for k, v in enforcement.items() if v["state"] == "enforced"}
    assert enforced == {
        "autonomy",
        "controlled_checkpoint",
        "budget",
        "repository_selection",
    }
    assert enforcement["publish"]["state"] == "not_implemented"


def test_the_controller_keeps_no_bodies_in_the_new_tables(harness):
    """AC-31 — 새 표에 본문 컬럼이 없고 요약에 길이 상한이 걸려 있다."""
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    body_like = {"content", "body", "text", "raw", "payload", "reason", "note", "statement"}
    for table in ("material_delta", "conformance_check"):
        columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        assert columns, f"{table} 이 없다"
        assert not (columns & body_like), f"{table} 에 본문 컬럼이 있다"
    rows = {
        r["name"]: r["sql"]
        for r in conn.execute(
            "SELECT name, sql FROM sqlite_master"
            " WHERE name IN ('material_delta','conformance_check')"
        )
    }
    assert "length(detail) <= 200" in rows["material_delta"]
    assert "length(ai_assessment) <= 200" in rows["material_delta"]
    assert "length(unverified_scope) <= 300" in rows["conformance_check"]
    conn.close()
