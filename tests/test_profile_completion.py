"""P4-03 — 여섯 Profile 의 완료 의미.

P3-R1 이 의도 항목을, P3-R4 가 충족 방식 세 값을 만들었지만 **완료 판정은 Profile 을
보지 않았다.** 여섯 Profile 모두 "기준이 전부 met" 하나였다. 이 파일은 그 판정이
목적마다 달라졌는지, 그리고 새 규칙이 v1 Case 에 소급되지 않았는지를 본다.

근거 실행은 대부분 **DB 에 직접 넣는다**(`_evidence_run`). 여기서 보는 것은 "그
실행을 근거로 이 결과를 받아도 되는가"이고, 그 실행이 어떻게 배정됐는지는 진입
검사 시험(test_admission·test_progression)이 따로 본다. 실제 작업공간에서 실험의
흔적을 관측하는 경로는 마지막 절에서 진짜 git worktree 로 확인한다.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from controller import db
from controller.repository import Repository, _criterion_fingerprint
from domain import completion_meaning as meaning
from domain import intent_doc, profiles
from domain.models import (
    CaseProfile,
    Conclusion,
    CriterionObligation,
    CriterionVerdict,
    EvidenceKind,
    Satisfaction,
)
from runner import prompts

# ------------------------------------------------------------------ 도우미


def _crit(
    key: str,
    relates_to: str = "goal",
    *,
    obligation: str | None = None,
    conclusion_rule: str | None = None,
    summary: str | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "key": key,
        "relates_to": relates_to,
        "text": f"{key} 의 기대값",
        "method": f"{key} 를 확인하는 방법",
        "summary": summary or f"{key} 요약",
        "method_summary": f"{key} 확인 방법",
    }
    if obligation is not None:
        item["obligation"] = obligation
    if conclusion_rule is not None:
        item["conclusion_rule"] = conclusion_rule
    return item


GOAL = {"goal": {"text": "목표", "origin": "user_requirement"}}


_PROJECTS = [0]


def _agreed_case(
    harness,
    profile: str,
    criteria: list[dict[str, Any]],
    fields: dict[str, Any] | None = None,
    objectives: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Profile 로 Case 를 만들고 의도에 동의까지 한다. (case, project)."""
    _PROJECTS[0] += 1
    project = harness.create_project(name=f"p4-03-{_PROJECTS[0]}")
    case = harness.create_case(project["id"], f"{profile} Case", profile=profile)
    harness.submit_intent_draft(
        case["id"], fields or GOAL, criteria=criteria, objectives=objectives
    )
    harness.ready_for_acceptance(case["id"], project["id"])
    return case, project


def _by_key(harness, case_id: str) -> dict[str, dict[str, Any]]:
    return {c["criterion_key"]: c for c in harness.criteria(case_id)}


_RUN_CLOCK = [0]


def _evidence_run(
    harness,
    case_id: str,
    run_id: str,
    purpose: str,
    *,
    experiment: bool = False,
    outcome: str = "completed",
    status: str = "finished",
    permission: str = "workspace_write",
    effect: dict[str, Any] | None = None,
    repository_id: str | None = None,
) -> str:
    """끝난 실행 한 건을 **직접** 넣는다. 배정 경로가 아니라 근거 규칙을 보기 위해서다."""
    artifact = harness.submit_artifact(case_id, f"{run_id} 지시")
    harness.agent.persist_pending_intakes()
    _RUN_CLOCK[0] += 1
    at = f"2026-09-23T00:00:{_RUN_CLOCK[0]:02d}.000000+00:00"
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        conn.execute(
            "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
            " instruction_artifact_id, instruction_artifact_rev, status,"
            " assignment_generation, outcome, created_at, finished_at, purpose,"
            " is_experiment, repository_id, workspace_effect_json)"
            " VALUES (?, ?, 'task-1', 'author', 'codex', 'exec', ?, ?, 1, ?, 1, ?, ?, ?,"
            " ?, ?, ?, ?)",
            (
                run_id,
                case_id,
                permission,
                artifact["artifact_id"],
                status,
                outcome,
                at,
                at,
                purpose,
                1 if experiment else 0,
                repository_id,
                json.dumps(effect) if effect is not None else None,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return run_id


def _effect(before: str, after: str, head: str = "h1") -> dict[str, Any]:
    return {
        "tree_digest_before": before,
        "tree_digest_after": after,
        "head_before": head,
        "head_after": head,
        "changed": before != after,
        "outside_workspace_changed": False,
    }


def _refusals(response) -> list[str]:
    body = response.json()
    return body.get("refusals") or []


def _closure(harness, case_id: str) -> dict[str, Any] | None:
    return harness.result(case_id)["closure"]


def _set_profile_version(harness, case_id: str, version: str) -> None:
    """Case 를 옛 정의판으로 되돌린다 — v14 에서 이행된 Case 의 모습이다."""
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        conn.execute('UPDATE "case" SET profile_version = ? WHERE id = ?', (version, case_id))
        conn.commit()
    finally:
        conn.close()


# ============================================ AC-2 여섯 Profile 의 완료 계약


def test_every_current_profile_has_its_own_completion_contract():
    """AC-2 — 여섯 Profile 의 계약이 목적마다 다르고, v1 에는 계약이 없다."""
    required = {
        p.value: [
            (r.obligation.value, r.when_field_filled.value if r.when_field_filled else None)
            for r in profiles.current(p).completion.requirements
        ]
        for p in CaseProfile
    }
    assert required == {
        "feature": [("behavior", None)],
        "defect_fix": [("restoration", None)],
        "root_cause_analysis": [("cause", None)],
        "research": [("answer", None)],
        # **개선과 보존을 함께** 요구한다. 개선 기준의 통과가 보존을 대신하지 않는다.
        "refactoring": [("improvement", None), ("preservation", None)],
        # 보존은 보존할 조건이 적혔을 때만.
        "maintenance": [("target_state", None), ("preservation", "preserved_conditions")],
    }
    assert profiles.CURRENT_PROFILE_VERSION == "2"
    for p in CaseProfile:
        # v1 은 고치지 않았다 — 계약이 없고 의미 항목은 v2 와 같다.
        v1 = profiles.resolve(p.value, "1")
        assert v1.completion is None
        assert v1.semantic_fields == profiles.current(p).semantic_fields
    catalog = {d["profile"]: d for d in profiles.catalog()}
    assert catalog["research"]["completion_contract"]["primary_obligation"] == "answer"


def test_met_satisfaction_differs_by_obligation():
    """AC-4 — 의무마다 허용되는 충족 방식이 다르고 미재현은 어디에도 없다."""
    table = meaning.MET_SATISFACTION
    assert all(Satisfaction.NOT_REPRODUCED not in allowed for allowed in table.values())
    assert table[CriterionObligation.CAUSE] == {Satisfaction.INVESTIGATED}
    assert table[CriterionObligation.ANSWER] == {Satisfaction.INVESTIGATED}
    assert table[CriterionObligation.PRESERVATION] == {Satisfaction.PRESERVED}
    for ob in (
        CriterionObligation.BEHAVIOR,
        CriterionObligation.RESTORATION,
        CriterionObligation.IMPROVEMENT,
        CriterionObligation.TARGET_STATE,
    ):
        assert table[ob] == {Satisfaction.CHANGED_AND_VERIFIED, Satisfaction.ALREADY_SATISFIED}


# ======================================================= AC-3 기준의 의무


def test_a_criterion_obligation_is_reported_or_derived_and_says_which(harness):
    """AC-3 — 원문이 적은 의무와 연결 항목에서 도출한 의무를 출처로 구별한다."""
    case, _ = _agreed_case(
        harness,
        "refactoring",
        [
            _crit("C-01", "improvement_target"),
            _crit("C-02", "preserved_contracts"),
            _crit("C-03", "goal", obligation="preservation"),
        ],
    )
    crits = _by_key(harness, case["id"])
    assert (crits["C-01"]["obligation"], crits["C-01"]["obligation_source"]) == (
        "improvement",
        "derived_from_field",
    )
    assert (crits["C-02"]["obligation"], crits["C-02"]["obligation_source"]) == (
        "preservation",
        "derived_from_field",
    )
    assert (crits["C-03"]["obligation"], crits["C-03"]["obligation_source"]) == (
        "preservation",
        "reported",
    )


def test_a_conclusion_rule_only_belongs_to_cause_and_answer_criteria(harness):
    """AC-16 — 결론 요구는 원인·조사 기준에만 붙는다. 문서가 먼저 거부한다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "기능", profile="feature")
    response = harness.client.post(
        f"/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "초안",
            "target_runner_id": "runner-test",
            "fields": GOAL,
            "criteria": [_crit("C-01", conclusion_rule="bounded_report_allowed")],
        },
    )
    assert response.status_code == 400
    assert "conclusion_rule" in response.text


# ================================================ feature 대표 흐름


def test_a_feature_closes_on_changed_and_verified_behavior(harness):
    """AC-2·AC-4 — feature: 합의한 동작을 바꾸고 확인했으면 자동 완료한다.

    실험을 근거로 "바꾸고 확인했다"를 적지 않는다 — 실험의 작업공간은 제품이 아니다.
    """
    case, _ = _agreed_case(
        harness, "feature", [_crit("C-01", "desired_behavior"), _crit("C-02", "constraints")]
    )
    crits = _by_key(harness, case["id"])
    assert {c["obligation"] for c in crits.values()} == {"behavior"}
    impl = _evidence_run(harness, case["id"], "run-impl-1", "feature_implementation")
    exp = _evidence_run(
        harness, case["id"], "run-exp-1", "local_experiment", experiment=True,
        effect=_effect("d0", "d0"),
    )
    refused = harness.record_result(
        case["id"], crits["C-01"]["id"], "met", evidence_kind="run_output",
        evidence_run_id=exp, satisfaction="changed_and_verified",
    )
    assert refused.status_code == 409
    assert "experiment_evidence_not_product" in refused.text

    for key in ("C-01", "C-02"):
        assert harness.record_result(
            case["id"], crits[key]["id"], "met", evidence_kind="run_output",
            evidence_run_id=impl, satisfaction="changed_and_verified",
        ).status_code == 200
    closure = _closure(harness, case["id"])
    assert closure is not None and closure["closure_kind"] == "completed"
    meaning_view = harness.result(case["id"])["completion_meaning"]
    assert meaning_view["contract"] == "profile_completion_contract"
    assert [(r["obligation"], r["status"]) for r in meaning_view["objectives"]] == [
        ("behavior", "met")
    ]


# ================================= AC-4·5 defect-fix: 생략 우회·무변경·미재현


def test_met_without_saying_how_is_refused_on_a_v2_criterion(harness):
    """AC-4 — **생략 우회를 막는다.** P3-R4 는 `not_reproduced` 로 적은 `met` 만 막았다.

    방식을 비워 두기만 하면 미재현을 해결로 적을 수 있었다.
    """
    case, _ = _agreed_case(harness, "defect_fix", [_crit("C-01", "expected_behavior")])
    crit = _by_key(harness, case["id"])["C-01"]
    assert crit["obligation"] == "restoration"

    bare = harness.record_result(case["id"], crit["id"], "met")
    assert bare.status_code == 409
    assert "satisfaction_required" in bare.text

    not_reproduced = harness.record_result(
        case["id"], crit["id"], "met", satisfaction="not_reproduced"
    )
    assert not_reproduced.status_code == 409
    assert "not reproducing" in not_reproduced.text

    # 조사 결론의 방식을 복원 기준에 쓰지 않는다.
    wrong = harness.record_result(
        case["id"], crit["id"], "met", satisfaction="investigated", conclusion="determined"
    )
    assert wrong.status_code == 409
    assert "satisfaction_not_allowed_for_obligation" in wrong.text
    assert "conclusion_not_applicable" in wrong.text

    # 미재현은 **미충족 쪽의 기록으로는** 남길 수 있다.
    recorded = harness.record_result(
        case["id"], crit["id"], "not_met", satisfaction="not_reproduced"
    )
    assert recorded.status_code == 200, recorded.text
    assert _closure(harness, case["id"]) is None


def test_a_defect_already_fixed_closes_without_any_code_change(harness):
    """AC-5 — **무변경 성공.** 검증 실행이 목표 상태를 관측하면 구현 없이 완료한다.

    구현 실행의 판정("바뀐 것이 없으면 실패")은 바꾸지 않았다. 무변경 완료의 근거는
    구현의 성공이 아니라 검증 실행의 관측이다.
    """
    case, _ = _agreed_case(harness, "defect_fix", [_crit("C-01", "expected_behavior")])
    crit = _by_key(harness, case["id"])["C-01"]
    run_id = _evidence_run(harness, case["id"], "run-verify-1", "verification_run")

    response = harness.record_result(
        case["id"],
        crit["id"],
        "met",
        evidence_kind="run_output",
        evidence_run_id=run_id,
        satisfaction="already_satisfied",
    )
    assert response.status_code == 200, response.text
    closure = _closure(harness, case["id"])
    assert closure is not None and closure["closure_kind"] == "completed"
    # 구현 실행은 한 번도 없었다.
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        purposes = {
            r[0]
            for r in conn.execute("SELECT purpose FROM run WHERE case_id = ?", (case["id"],))
        }
    finally:
        conn.close()
    assert purposes == {"verification_run"}


def test_already_satisfied_must_be_observed_by_a_verification_run(harness):
    """AC-5·AC-12 — "이미 목표 상태다"의 근거는 검증 실행이다.

    구현 실행의 관측은 "바꿨다"는 기록 위의 관측이고, 실험은 임시 변경 위의 관측이다.
    """
    case, _ = _agreed_case(harness, "defect_fix", [_crit("C-01", "expected_behavior")])
    crit = _by_key(harness, case["id"])["C-01"]
    impl = _evidence_run(harness, case["id"], "run-impl-1", "feature_implementation")
    exp = _evidence_run(harness, case["id"], "run-exp-1", "local_experiment", experiment=True)

    by_impl = harness.record_result(
        case["id"], crit["id"], "met", evidence_kind="run_output",
        evidence_run_id=impl, satisfaction="already_satisfied",
    )
    assert by_impl.status_code == 409
    assert "observation_needs_verification_run" in by_impl.text

    by_exp = harness.record_result(
        case["id"], crit["id"], "met", evidence_kind="run_output",
        evidence_run_id=exp, satisfaction="already_satisfied",
    )
    assert by_exp.status_code == 409
    assert "experiment_evidence_not_product" in by_exp.text


# ============================ AC-6 RCA: 원인 확정이 필수면 판단 불가는 성공이 아니다


def test_an_inconclusive_cause_is_not_success_when_the_cause_must_be_found(harness):
    """AC-6 — 확정 필수(명시 또는 **미기록**)면 판단 불가로 `met` 을 적지 않는다.

    판단 불가는 `not_met` 이며 자동 완료는 없고, 사람이 예외로 수용해도 원래 판정이
    남는다.
    """
    case, _ = _agreed_case(
        harness,
        "root_cause_analysis",
        [
            _crit("C-01", "cause_questions", conclusion_rule="definitive_required"),
            # 결론 요구를 적지 않은 기준 — 확정 필수로 **취급**한다.
            _crit("C-02", "analysis_end_condition"),
        ],
    )
    crits = _by_key(harness, case["id"])
    assert crits["C-02"]["conclusion_rule"] is None
    assert crits["C-02"]["conclusion_rule_effective"] == "definitive_required"
    analysis = _evidence_run(harness, case["id"], "run-analysis-1", "limited_analysis")

    for key in ("C-01", "C-02"):
        refused = harness.record_result(
            case["id"], crits[key]["id"], "met", evidence_kind="run_output",
            evidence_run_id=analysis, satisfaction="investigated", conclusion="inconclusive",
        )
        assert refused.status_code == 409, key
        assert "inconclusive_not_allowed" in refused.text

    # 결론을 적지 않은 `met` 도 받지 않는다 — 확정인지 판단 불가인지 모른다.
    silent = harness.record_result(
        case["id"], crits["C-01"]["id"], "met", evidence_kind="run_output",
        evidence_run_id=analysis, satisfaction="investigated",
    )
    assert silent.status_code == 409
    assert "conclusion_required" in silent.text

    # C-02 는 확정됐고 C-01 은 판단 불가로 남았다.
    assert harness.record_result(
        case["id"], crits["C-02"]["id"], "met", evidence_kind="run_output",
        evidence_run_id=analysis, satisfaction="investigated", conclusion="determined",
    ).status_code == 200
    inconclusive = harness.record_result(
        case["id"], crits["C-01"]["id"], "not_met", evidence_kind="run_output",
        evidence_run_id=analysis, satisfaction="investigated", conclusion="inconclusive",
        summary="두 가설을 모두 기각하지 못했다",
    )
    assert inconclusive.status_code == 200, inconclusive.text
    assert _closure(harness, case["id"]) is None

    auto = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert auto["applied"] is False
    assert "unresolved_criteria" in auto["refusals"]

    # 사람이 판단 불가를 알고 수용한다.
    candidate = harness.build_candidate(case["id"])
    accepted = harness.accept_exception(case["id"], candidate["id"], crits["C-01"]["id"])
    assert accepted.status_code == 201, accepted.text
    assert harness.accept(case["id"], candidate["id"]).status_code == 201
    closure = _closure(harness, case["id"])
    assert closure["closure_kind"] == "closed_with_exceptions"
    after = _by_key(harness, case["id"])["C-01"]
    # **원래 판정과 결론이 그대로다.** 예외는 충족이 아니다.
    assert after["verdict"] == "not_met"
    assert after["conclusion"] == "inconclusive"


# ================================ AC-7 research: 판단 불가도 정상 결과일 수 있다


def test_a_bounded_research_can_close_with_an_inconclusive_answer_and_no_code(harness):
    """AC-7 — 합의한 조사를 마치고 한계를 보고하면 판단 불가도 정상 완료다.

    코드 변경도 구현 실행도 없다. 근거는 조사 실행이다.
    """
    case, _ = _agreed_case(
        harness,
        "research",
        [_crit("C-01", "research_questions", conclusion_rule="bounded_report_allowed")],
    )
    crit = _by_key(harness, case["id"])["C-01"]
    analysis = _evidence_run(harness, case["id"], "run-analysis-1", "limited_analysis")

    response = harness.record_result(
        case["id"], crit["id"], "met", evidence_kind="run_output",
        evidence_run_id=analysis, satisfaction="investigated", conclusion="inconclusive",
        summary="두 후보의 우열을 가릴 근거가 없다는 결론과 한계를 보고했다",
    )
    assert response.status_code == 200, response.text
    closure = _closure(harness, case["id"])
    assert closure is not None and closure["closure_kind"] == "completed"


def test_an_investigation_answer_needs_an_investigation_run(harness):
    """AC-7 — 조사 결론의 근거는 분석·실험·검증 실행이다. 초안을 쓴 실행이 아니다."""
    case, _ = _agreed_case(
        harness,
        "research",
        [_crit("C-01", "research_questions", conclusion_rule="bounded_report_allowed")],
    )
    crit = _by_key(harness, case["id"])["C-01"]
    authoring = _evidence_run(harness, case["id"], "run-draft-x", "intent_authoring")
    refused = harness.record_result(
        case["id"], crit["id"], "met", evidence_kind="run_output",
        evidence_run_id=authoring, satisfaction="investigated", conclusion="determined",
    )
    assert refused.status_code == 409
    assert "evidence_run_not_investigation" in refused.text

    # 실험 실행은 조사 근거가 **될 수 있다**(D-66 — 실험은 조사의 수단이다).
    experiment = _evidence_run(
        harness, case["id"], "run-exp-1", "local_experiment", experiment=True,
        effect=_effect("d0", "d0"),
    )
    allowed = harness.record_result(
        case["id"], crit["id"], "met", evidence_kind="run_output",
        evidence_run_id=experiment, satisfaction="investigated", conclusion="determined",
    )
    assert allowed.status_code == 200, allowed.text


# ============================= AC-8·11 refactoring: 개선과 보존을 함께


def test_a_refactoring_without_a_preservation_criterion_does_not_close(harness):
    """AC-8·AC-11 — 개선 기준만 있으면 완료하지 않는다. 사람도 인수할 수 없다.

    기준이 없는 목적은 예외 수용 대상도 아니다 — 예외는 기준에만 붙는다.
    """
    case, _ = _agreed_case(harness, "refactoring", [_crit("C-01", "improvement_target")])
    crit = _by_key(harness, case["id"])["C-01"]
    assert harness.record_result(
        case["id"], crit["id"], "met", satisfaction="changed_and_verified"
    ).status_code == 200
    assert _closure(harness, case["id"]) is None

    view = harness.result(case["id"])["completion_meaning"]
    assert view["missing"] == ["preservation"]
    rows = {row["obligation"]: row for row in view["objectives"]}
    assert rows["improvement"]["status"] == "met"
    assert rows["preservation"]["status"] == "missing"

    candidate = harness.build_candidate(case["id"])
    assert {"kind": "objective_without_criteria", "id": "preservation", "verdict": "missing"} in (
        candidate["unresolved"]
    )
    refused = harness.accept(case["id"], candidate["id"])
    assert refused.status_code == 409
    assert "objective_without_criteria" in refused.text


def test_a_refactoring_closes_when_improvement_and_preservation_are_each_proven(harness):
    """AC-8 — 보존은 **검증 실행이나 사람 판단**으로만 충족된다. 실험·구현은 아니다."""
    case, _ = _agreed_case(
        harness,
        "refactoring",
        [_crit("C-01", "improvement_target"), _crit("C-02", "preserved_contracts")],
    )
    crits = _by_key(harness, case["id"])
    impl = _evidence_run(harness, case["id"], "run-impl-1", "feature_implementation")
    exp = _evidence_run(
        harness, case["id"], "run-exp-1", "local_experiment", experiment=True,
        effect=_effect("d0", "d0"),
    )
    verify = _evidence_run(harness, case["id"], "run-verify-1", "verification_run")

    # 개선을 "보존됐다"로 적지 않는다.
    assert "satisfaction_not_allowed_for_obligation" in harness.record_result(
        case["id"], crits["C-01"]["id"], "met", satisfaction="preserved"
    ).text
    # 보존을 "바꾸고 확인했다"로 적지 않는다.
    assert "satisfaction_not_allowed_for_obligation" in harness.record_result(
        case["id"], crits["C-02"]["id"], "met", satisfaction="changed_and_verified"
    ).text
    for run_id, code in (
        (impl, "observation_needs_verification_run"),
        (exp, "experiment_evidence_not_product"),
    ):
        refused = harness.record_result(
            case["id"], crits["C-02"]["id"], "met", evidence_kind="run_output",
            evidence_run_id=run_id, satisfaction="preserved",
        )
        assert refused.status_code == 409 and code in refused.text, run_id

    assert harness.record_result(
        case["id"], crits["C-01"]["id"], "met", evidence_kind="run_output",
        evidence_run_id=impl, satisfaction="changed_and_verified",
    ).status_code == 200
    assert _closure(harness, case["id"]) is None
    assert harness.record_result(
        case["id"], crits["C-02"]["id"], "met", evidence_kind="run_output",
        evidence_run_id=verify, satisfaction="preserved",
    ).status_code == 200
    assert _closure(harness, case["id"])["closure_kind"] == "completed"


# ====================================== AC-9 maintenance: 조건부 보존


def test_maintenance_asks_for_preservation_only_when_conditions_were_written(harness):
    """AC-9 — 보존할 조건이 적혔으면 보존 기준이 필요하고, 비었으면 요구하지 않는다."""
    with_conditions = {
        **GOAL,
        "preserved_conditions": {"text": "지원 Python 3.11 유지", "origin": "user_requirement"},
    }
    case, _ = _agreed_case(
        harness, "maintenance", [_crit("C-01", "target_state")], fields=with_conditions
    )
    crit = _by_key(harness, case["id"])["C-01"]
    assert harness.record_result(
        case["id"], crit["id"], "met", satisfaction="changed_and_verified"
    ).status_code == 200
    view = harness.result(case["id"])["completion_meaning"]
    assert view["missing"] == ["preservation"]
    required = {row["obligation"]: row["required_by"] for row in view["objectives"]}
    assert required["preservation"] == ["profile_conditional"]
    assert _closure(harness, case["id"]) is None

    plain, _ = _agreed_case(harness, "maintenance", [_crit("C-01", "target_state")])
    crit = _by_key(harness, plain["id"])["C-01"]
    assert harness.record_result(
        plain["id"], crit["id"], "met", satisfaction="changed_and_verified"
    ).status_code == 200
    assert harness.result(plain["id"])["completion_meaning"]["missing"] == []
    assert _closure(harness, plain["id"])["closure_kind"] == "completed"


# ================================ AC-10 혼합 목적: 원인 확정과 수정


def test_a_fix_that_also_asked_for_the_cause_needs_both(harness):
    """AC-10 — "원인 확정과 수정" 중 수정만 성공하면 완료하지 않는다.

    선언된 목적은 대표 Profile 에 묻히지 않는다.
    """
    case, _ = _agreed_case(
        harness,
        "defect_fix",
        [
            _crit("C-01", "expected_behavior"),
            _crit("C-02", "goal", obligation="cause", conclusion_rule="definitive_required"),
        ],
        objectives=["cause"],
    )
    crits = _by_key(harness, case["id"])
    assert crits["C-02"]["obligation"] == "cause"
    assert harness.record_result(
        case["id"], crits["C-01"]["id"], "met", satisfaction="changed_and_verified"
    ).status_code == 200
    assert _closure(harness, case["id"]) is None

    rows = {
        row["obligation"]: row
        for row in harness.result(case["id"])["completion_meaning"]["objectives"]
    }
    assert rows["restoration"]["status"] == "met"
    assert rows["cause"]["status"] == "open"
    assert rows["cause"]["required_by"] == ["declared"]

    assert harness.record_result(
        case["id"], crits["C-02"]["id"], "met", satisfaction="investigated",
        conclusion="determined",
    ).status_code == 200
    assert _closure(harness, case["id"])["closure_kind"] == "completed"


def test_a_declared_objective_without_a_criterion_blocks_completion(harness):
    """AC-10·AC-11 — 원인을 요청했는데 원인 기준이 하나도 없으면 완료하지 않는다."""
    case, _ = _agreed_case(
        harness, "defect_fix", [_crit("C-01", "expected_behavior")], objectives=["cause"]
    )
    crit = _by_key(harness, case["id"])["C-01"]
    assert harness.record_result(
        case["id"], crit["id"], "met", satisfaction="changed_and_verified"
    ).status_code == 200
    assert _closure(harness, case["id"]) is None
    assert harness.result(case["id"])["completion_meaning"]["missing"] == ["cause"]
    auto = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert "objective_without_criteria" in auto["refusals"]


def test_declaring_a_product_objective_does_not_open_implementation_in_an_rca(harness):
    """AC-21 — 선언된 목적이 조사 Profile 의 제품 수정 차단(D-66)을 풀지 않는다."""
    case, _ = _agreed_case(
        harness,
        "root_cause_analysis",
        [_crit("C-01", "cause_questions"), _crit("C-02", "goal", obligation="restoration")],
        objectives=["restoration"],
    )
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
    assert admission.status_code == 409
    assert "purpose_outside_case_objective" in json.dumps(admission.json())


# ======================================= AC-12~14 로컬 실험의 근거와 잔여


def test_experiment_cleanup_is_derived_from_what_was_observed():
    """AC-13 — 정리 상태는 관측에서 도출한다. 모르는 것은 정리됨이 아니다."""
    runs = [
        {"run_id": "e-restored", "status": "finished", "permission": "workspace_write",
         "is_experiment": 1, "repository_id": "r1", "workspace_effect": _effect("a", "a")},
        {"run_id": "e-left", "status": "finished", "permission": "workspace_write",
         "is_experiment": 1, "repository_id": "r1", "workspace_effect": _effect("a", "b")},
        {"run_id": "e-later", "status": "finished", "permission": "workspace_write",
         "is_experiment": 1, "repository_id": "r2", "workspace_effect": _effect("x", "y")},
        {"run_id": "e-blind", "status": "finished", "permission": "workspace_write",
         "is_experiment": 1, "repository_id": "r1", "workspace_effect": None},
        {"run_id": "e-read", "status": "finished", "permission": "read_only",
         "is_experiment": 1, "repository_id": "r1", "workspace_effect": None},
        {"run_id": "e-running", "status": "running", "permission": "workspace_write",
         "is_experiment": 1, "repository_id": "r1", "workspace_effect": None},
        # r2 의 뒤 실행이 실험 전 지문 x 에서 시작했다 — e-later 의 임시 변경은 걷혔다.
        {"run_id": "verify-r2", "status": "finished", "permission": "read_only",
         "is_experiment": 0, "repository_id": "r2", "workspace_effect": _effect("x", "x")},
        # r1 의 뒤 실행은 b 에서 시작했다 — e-left 의 변경이 남은 채다.
        {"run_id": "impl-r1", "status": "finished", "permission": "workspace_write",
         "is_experiment": 0, "repository_id": "r1", "workspace_effect": _effect("b", "c")},
    ]
    rows = {r["run_id"]: r for r in meaning.experiment_cleanup(runs)}
    assert rows["e-restored"]["cleanup"] == "restored_in_run"
    assert rows["e-left"]["cleanup"] == "left_changes"
    assert (rows["e-later"]["cleanup"], rows["e-later"]["restored_by"]) == (
        "restored_later",
        "verify-r2",
    )
    assert rows["e-blind"]["cleanup"] == "unobserved"
    assert rows["e-read"]["cleanup"] == "no_write_permission"
    assert rows["e-running"]["cleanup"] == "not_finished"
    assert set(rows) == {"e-restored", "e-left", "e-later", "e-blind", "e-read", "e-running"}
    assert meaning.RESIDUE_STATES == {"left_changes", "unobserved"}


def test_experiment_residue_blocks_auto_completion_of_a_product_case_only(harness):
    """AC-14 — 제품 목적 Case 에 잔여가 있으면 자동 완료하지 않고, 사람은 보고 닫는다.

    조사 목적만 있는 Case 는 잔여를 **보이기만** 한다 — 그 결과는 보고서다.
    """
    case, _ = _agreed_case(harness, "defect_fix", [_crit("C-01", "expected_behavior")])
    _evidence_run(
        harness, case["id"], "run-exp-1", "local_experiment", experiment=True,
        effect=_effect("d0", "d1"),
    )
    crit = _by_key(harness, case["id"])["C-01"]
    assert harness.record_result(
        case["id"], crit["id"], "met", satisfaction="changed_and_verified"
    ).status_code == 200
    assert _closure(harness, case["id"]) is None
    view = harness.result(case["id"])["completion_meaning"]
    assert view["residue"] == ["run-exp-1"]
    assert view["residue_blocks_auto_completion"] is True

    auto = harness.client.post(f"/api/cases/{case['id']}/auto-complete").json()
    assert auto["applied"] is False
    assert "experiment_residue_unresolved" in auto["refusals"]
    candidate = auto["candidate"]
    assert candidate["meaning"]["residue"] == ["run-exp-1"]
    # 사람은 후보에 드러난 잔여를 보고 닫을 수 있다.
    assert harness.accept(case["id"], candidate["id"]).status_code == 201
    assert _closure(harness, case["id"])["closure_kind"] == "completed"

    rca, _ = _agreed_case(harness, "root_cause_analysis", [_crit("C-01", "cause_questions")])
    _evidence_run(
        harness, rca["id"], "run-exp-2", "local_experiment", experiment=True,
        effect=_effect("d0", "d1"),
    )
    crit = _by_key(harness, rca["id"])["C-01"]
    assert harness.record_result(
        rca["id"], crit["id"], "met", evidence_kind="run_output", evidence_run_id="run-exp-2",
        satisfaction="investigated", conclusion="determined",
    ).status_code == 200
    rca_view = harness.result(rca["id"])
    assert rca_view["completion_meaning"]["residue"] == ["run-exp-2"]
    assert rca_view["completion_meaning"]["residue_blocks_auto_completion"] is False
    assert rca_view["closure"]["closure_kind"] == "completed"


def test_a_real_experiment_that_leaves_a_file_is_seen_as_residue(harness):
    """AC-13 — **실제 git worktree** 에서 실험이 남긴 파일을 관측으로 찾는다.

    가짜 CLI 도 진짜 파일을 쓴다. 실행 전후 트리 지문이 달라졌고 뒤에 되돌린 관측이
    없으므로 `left_changes` 다. 파일을 쓰지 않은 실험은 `restored_in_run` 이다.
    """
    project, _repo = harness.create_git_project(name="experiment-residue")
    case = harness.create_case(project["id"], "지연 원인", profile="root_cause_analysis")
    harness.prepare_workspace(case["id"])
    fake = harness.agent.cli_executor
    fake.analysis_response = json.dumps(
        {
            "commands": [{"command": "python probe.py", "summary": "계측", "exit_code": 0}],
            "result_summary": "지연을 재현했다",
            "temporary_changes": "probe.txt 를 남겼다",
            "detail": "계측 파일을 되돌리지 않았다",
        }
    )
    fake.write_files = {"probe.txt": "임시 계측\n"}
    artifact = harness.submit_artifact(case["id"], "재현해 주세요")["artifact_id"]
    harness.agent.persist_pending_intakes()
    assert harness.run_experiment(case["id"], artifact).status_code == 201
    harness.agent.poll_once()

    fake.write_files = {}
    artifact2 = harness.submit_artifact(case["id"], "다시 재현")["artifact_id"]
    harness.agent.persist_pending_intakes()
    assert harness.run_experiment(case["id"], artifact2, run_id="run-experiment-2").status_code == 201
    harness.agent.poll_once()

    rows = {
        e["run_id"]: e for e in harness.result(case["id"])["completion_meaning"]["experiments"]
    }
    assert rows["run-experiment-1"]["cleanup"] == "left_changes"
    assert rows["run-experiment-2"]["cleanup"] == "restored_in_run"
    # 원래 저장소 쪽 관측도 함께 보인다(D-44 — 감지이지 격리가 아니다).
    assert rows["run-experiment-1"]["outside_workspace_changed"] is False


# ========================= AC-15 결론 요구 약화는 누적 변경, v1 지문은 그대로


def test_weakening_a_conclusion_rule_is_a_material_change(harness):
    """AC-15 — 확정 필수 → 판단 불가 허용은 완료를 쉽게 만드는 가장 조용한 변경이다."""
    case, _ = _agreed_case(
        harness,
        "root_cause_analysis",
        [_crit("C-01", "cause_questions", conclusion_rule="definitive_required")],
    )
    harness.submit_intent_draft(
        case["id"],
        GOAL,
        criteria=[_crit("C-01", "cause_questions", conclusion_rule="bounded_report_allowed")],
    )
    pending = harness.material_deltas(case["id"])["pending"]
    assert [d["target_key"] for d in pending] == ["C-01"]
    assert pending[0]["materiality"] == "material"


def test_a_v1_criterion_keeps_its_old_fingerprint():
    """AC-15 — 의무·결론 요구가 없는 기준의 지문은 P4-03 이전과 같다."""
    import hashlib

    row = {"summary": "요약", "method_summary": "방법", "relates_to": "goal"}
    legacy = "sha256:" + hashlib.sha256("요약\x00방법\x00goal".encode("utf-8")).hexdigest()
    assert _criterion_fingerprint({**row, "obligation": None, "conclusion_rule": None}) == legacy
    assert _criterion_fingerprint(row) == legacy
    assert _criterion_fingerprint({**row, "obligation": "cause"}) != legacy


# ============================================= AC-1 v1 Case 는 그대로다


def test_a_v1_case_keeps_the_old_completion_rules(harness):
    """AC-1 — 정의판 "1" Case 는 방식 없는 `met` 을 받고 계약 거부가 없다.

    새 완료 규칙을 기존 Case 에 조용히 소급하지 않는다(D-62).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "옛 리팩터링", profile="refactoring")
    _set_profile_version(harness, case["id"], "1")
    harness.submit_intent_draft(case["id"], GOAL, criteria=[_crit("C-01", "improvement_target")])
    harness.ready_for_acceptance(case["id"], project["id"])
    crit = _by_key(harness, case["id"])["C-01"]
    assert crit["obligation"] is None and crit["obligation_source"] is None

    # 새 방식·결론은 v1 기준에서 받지 않는다.
    assert "satisfaction_needs_obligation" in harness.record_result(
        case["id"], crit["id"], "met", satisfaction="preserved"
    ).text
    assert "conclusion_not_applicable" in harness.record_result(
        case["id"], crit["id"], "met", conclusion="determined"
    ).text

    # 방식 없는 `met` 이 v1 규칙대로 받아지고, 보존 기준 없이도 닫힌다.
    assert harness.record_result(case["id"], crit["id"], "met").status_code == 200
    view = harness.result(case["id"])
    assert view["completion_meaning"]["contract"] is None
    assert view["closure"]["closure_kind"] == "completed"
    # 후보에 목적 블록이 없다 — 해시가 P4-03 이전의 모양 그대로다.
    candidate = harness.client.get(f"/api/cases/{case['id']}/completion-candidates").json()
    items = candidate if isinstance(candidate, list) else candidate["candidates"]
    assert items[-1]["meaning"] is None


def test_a_v1_case_does_not_accept_objectives(harness):
    """AC-1 — 계약이 없는 Case 에 목적 선언을 기록하지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "옛 결함", profile="defect_fix")
    _set_profile_version(harness, case["id"], "1")
    response = harness.client.post(
        f"/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "초안",
            "target_runner_id": "runner-test",
            "fields": GOAL,
            "criteria": [_crit("C-01", "expected_behavior")],
            "objectives": ["cause"],
        },
    )
    assert response.status_code == 400
    assert "completion contract" in response.text


# ================================== AC-16·17 의도 문서 v5 와 AI 지시문


def test_the_v5_document_reports_enumerations_only():
    """AC-16 — 목적·의무·결론 요구가 문서에 있고 구조 보고에는 열거값만 올라간다."""
    body = intent_doc.compose(
        fields={"goal": {"text": "원인을 확정하고 고친다", "origin": "user_requirement"}},
        questions=[],
        case_id="case-x",
        authored_by="owner",
        criteria=[
            _crit("C-01", "expected_behavior"),
            _crit("C-02", "goal", obligation="cause", conclusion_rule="definitive_required"),
        ],
        profile="defect_fix",
        profile_version="2",
        objectives=["cause", "cause"],
    )
    doc = json.loads(body)
    assert doc["doc_version"] == 5
    assert doc["objectives"] == ["cause"]
    # 도출값은 문서에 쓰지 않는다 — "원문이 명시했다"와 구별되지 않게 되기 때문이다.
    assert "obligation" not in doc["criteria"][0]
    report = intent_doc.structure(body)
    assert report["objectives"] == ["cause"]
    assert report["criteria"][1] == {
        "key": "C-02",
        "relates_to": "goal",
        "summary": "C-02 요약",
        "method_summary": "C-02 확인 방법",
        "obligation": "cause",
        "conclusion_rule": "definitive_required",
    }
    # 옛 문서는 목적 선언이 **없음**이다.
    old = json.loads(body)
    old["doc_version"] = 4
    del old["objectives"]
    assert intent_doc.parse(json.dumps(old).encode("utf-8"))["objectives"] is None
    with pytest.raises(ValueError):
        intent_doc.compose(
            fields={}, questions=[], case_id="c", authored_by="o",
            criteria=[_crit("C-01", obligation="cause")],
            profile="defect_fix", profile_version="1",
        )


def test_the_intent_prompt_asks_for_the_contract_only_where_there_is_one():
    """AC-17 — v2 Profile 의 지시문만 목적·의무·결론 요구를 요구한다."""
    v2 = prompts._intent_profile_note("root_cause_analysis", "2")
    for token in ('"objectives"', '"obligation"', '"conclusion_rule"', "definitive_required"):
        assert token in v2
    # 모르면 적지 않는다 — 판단 불가 허용을 지어내지 않게 한다.
    assert "말하지 않으면 적지 마라" in v2
    v1 = prompts._intent_profile_note("root_cause_analysis", "1")
    assert '"objectives"' not in v1
    # 실험 지시문이 정리를 요구한다.
    assert "임시 변경을 되돌려" in prompts.LOCAL_EXPERIMENT_PROMPT


def test_an_ai_draft_reports_objectives_and_obligations(harness):
    """AC-17 — AI 초안의 목적·의무·결론 요구가 Runner 를 거쳐 제어부에 기록된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "결함", profile="defect_fix")
    fake = harness.agent.cli_executor
    fake.draft_response = json.dumps(
        {
            "fields": {"goal": {"text": "저장 뒤 목록 갱신", "origin": "user_requirement"}},
            "questions": [],
            "objectives": ["cause"],
            "criteria": [
                {"key": "C-01", "relates_to": "expected_behavior", "obligation": "restoration",
                 "text": "저장 뒤 새 값이 보인다", "method": "저장 후 목록 확인",
                 "summary": "새 값 표시", "method_summary": "목록 확인"},
                {"key": "C-02", "relates_to": "goal", "obligation": "cause",
                 "conclusion_rule": "definitive_required",
                 "text": "원인을 확정한다", "method": "재현·대조",
                 "summary": "원인 확정", "method_summary": "재현·대조"},
            ],
        }
    )
    harness.ai_draft(case["id"], "저장 뒤 목록이 옛 값이에요. 원인도 확정해 주세요.")
    crits = _by_key(harness, case["id"])
    assert (crits["C-01"]["obligation"], crits["C-01"]["obligation_source"]) == (
        "restoration",
        "reported",
    )
    assert crits["C-02"]["conclusion_rule"] == "definitive_required"
    view = harness.result(case["id"])["completion_meaning"]
    assert view["declared_objectives"] == ["cause"]
    assert {row["obligation"] for row in view["objectives"]} == {"restoration", "cause"}


# ============================================ AC-20 재시작 뒤 복원


def test_obligations_conclusions_and_meaning_survive_a_reopened_database(harness):
    """AC-20 — 의무·결론·목적·후보 meaning 이 파일 DB 재개 뒤에도 같다."""
    case, _ = _agreed_case(
        harness,
        "defect_fix",
        [
            _crit("C-01", "expected_behavior"),
            _crit("C-02", "goal", obligation="cause", conclusion_rule="bounded_report_allowed"),
        ],
        objectives=["cause"],
    )
    crits = _by_key(harness, case["id"])
    assert harness.record_result(
        case["id"], crits["C-02"]["id"], "met", satisfaction="investigated",
        conclusion="inconclusive",
    ).status_code == 200
    candidate = harness.build_candidate(case["id"])
    before = harness.result(case["id"])["completion_meaning"]

    harness.client.app.state.conn.close()
    conn = db.connect(harness.controller_config.db_path)
    db.migrate(conn)
    repo = Repository(conn)
    after = repo.completion_meaning(case["id"])
    assert after["objectives"] == before["objectives"]
    assert after["declared_objectives"] == ["cause"]
    restored = repo.get_success_criterion(crits["C-02"]["id"])
    assert (restored["obligation"], restored["conclusion_rule"]) == (
        "cause",
        "bounded_report_allowed",
    )
    assert repo.get_criterion_result(crits["C-02"]["id"])["conclusion"] == "inconclusive"
    assert repo.get_completion_candidate(candidate["id"])["meaning"] == candidate["meaning"]
    conn.close()


# ============================================ 순수 규칙 한 곳의 회귀


def test_check_result_is_the_only_place_the_rules_live():
    """결과 기록·시험이 같은 함수를 본다 — 두 벌로 쓰면 한쪽만 고친다."""
    violations = meaning.check_result(
        contract_applies=True,
        obligation="answer",
        conclusion_rule="bounded_report_allowed",
        verdict=CriterionVerdict.MET,
        satisfaction=Satisfaction.INVESTIGATED,
        conclusion=Conclusion.INCONCLUSIVE,
        evidence_kind=EvidenceKind.HUMAN_JUDGEMENT,
        evidence_run=None,
    )
    assert violations == []
    legacy = meaning.check_result(
        contract_applies=False,
        obligation=None,
        conclusion_rule=None,
        verdict=CriterionVerdict.MET,
        satisfaction=None,
        conclusion=None,
        evidence_kind=EvidenceKind.HUMAN_JUDGEMENT,
        evidence_run=None,
    )
    assert legacy == []
