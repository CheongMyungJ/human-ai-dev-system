"""P4-08 — 여섯 Profile 대표 흐름의 진행기 경유 재현(plans/P4-PLAN-08.md).

P4-03 이 여섯 Profile 의 완료 계약을 API 시험으로 고정했고, P4-05 부터 업무 단계의 실제 경로는 진행기다.
그 진행기 시험(`tests/test_work_progressor.py`)은 feature·research 만 지났고 RCA 는 개정 시험이 지났다.
이 파일은 나머지 셋(defect-fix·refactoring·maintenance)과 혼합 목적을 **같은 진행기 경로**로 지나
`decide_criteria` 의 `preserved`·`already_satisfied`·`investigated`(검증 실행 근거) 분기와 완료 의미가
그대로 이어지는지를 본다.

이 파일이 지키는 것:

    제품 코드는 그대로다              가짜 CLI 의 응답만 Profile 에 맞게 바꾼다
    의무별 충족 방식은 진행기가 정한다   보고는 `met` 뿐이고 방식은 의무에서 나온다
    한쪽만 충족하면 닫히지 않는다       기준 없는 목적은 `objective_without_criteria`, 미충족은 예외 카드
    무변경 완료는 검증 실행의 관측이다   구현 실행 없이도 `already_satisfied` 로 닫힌다

시험 이름 옆의 AC 번호는 P4-PLAN-08 4절이다.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from domain import work_flow as workflow
from tests.conftest import (
    FAKE_COMBINED_SECTIONS,
    FAKE_DRAFT_RESPONSE,
    FAKE_TASKS_VERIFIED,
    fake_preparation_response,
)
from tests.test_profile_revision import (
    REVISED_DRAFT,
    _confirm_pending_deltas,
    _rca_waiting,
    _revise,
)
from tests.test_work_progressor import _agree, _drive, _runs, _start, _wait_codes

# ---------------------------------------------------------------- 응답 만들기


def _draft(
    *,
    c1: str = "expected_outcome",
    c2: str | None = "constraints",
    c1_obligation: str | None = None,
    fields: dict[str, str] | None = None,
    objectives: list[str] | None = None,
) -> str:
    """기본 초안(`FAKE_DRAFT_RESPONSE`)의 기준 연결 항목·의무·항목·선언 목적만 바꾼 초안."""
    body = FAKE_DRAFT_RESPONSE.split("```json\n", 1)[1].split("\n```", 1)[0]
    doc = json.loads(body)
    doc["criteria"][0]["relates_to"] = c1
    if c1_obligation:
        doc["criteria"][0]["obligation"] = c1_obligation
    if c2 is None:
        doc["criteria"] = doc["criteria"][:1]
    else:
        doc["criteria"][1]["relates_to"] = c2
    for name, text in (fields or {}).items():
        doc["fields"][name] = {"text": text, "origin": "user_requirement"}
    if objectives:
        doc["objectives"] = objectives
    return "여기 초안입니다.\n\n```json\n" + json.dumps(doc, ensure_ascii=False) + "\n```\n"


def _tasks(keys: list[str], *, implement: bool = True) -> list[dict[str, Any]]:
    """계획의 Task — 구현 하나(선택)와 기준 전부를 `verifies` 로 잇는 검증 하나."""
    impl, verify = (json.loads(json.dumps(t)) for t in FAKE_TASKS_VERIFIED)
    impl["criteria"] = [{"key": k, "relation": "implements"} for k in keys]
    verify["criteria"] = [{"key": k, "relation": "verifies"} for k in keys]
    if not implement:
        verify["key"] = "T1"
        verify.pop("depends_on", None)
        return [verify]
    return [impl, verify]


def _plan(keys: list[str], *, implement: bool = True) -> str:
    return fake_preparation_response("결합", FAKE_COMBINED_SECTIONS, tasks=_tasks(keys, implement=implement))


def _verification(report: list[tuple[str, str, str | None]], *, exit_code: int = 0) -> str:
    """검증 실행 응답 — 명령 하나와 기준별 판정. 방식은 적지 않는다(진행기가 의무에서 정한다)."""
    items = []
    for key, verdict, conclusion in report:
        item: dict[str, Any] = {"key": key, "verdict": verdict, "summary": f"{key} {verdict}"}
        if conclusion:
            item["conclusion"] = conclusion
        items.append(item)
    body = {
        "commands": [{"command": "python -m pytest tests", "summary": "시험", "exit_code": exit_code}],
        "result_summary": "시험을 돌렸다",
        "criteria": items,
        "detail": "표본으로 확인했다",
    }
    return "확인했습니다.\n\n```json\n" + json.dumps(body, ensure_ascii=False) + "\n```\n"


# ---------------------------------------------------------------- 도우미


def _begin(h, profile: str, *, draft: str, text: str) -> str:
    """업무화 → 의도 초안 → 동의 대기까지. 반환: case_id (동의 전)."""
    h.agent.cli_executor.draft_response = draft
    _project, case_id, _request_id = _start(h, profile=profile, git=True, text=text)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"], conv["progress"]
    return case_id


def _set_plan(h, keys: list[str], *, implement: bool = True) -> None:
    plan = _plan(keys, implement=implement)
    h.agent.cli_executor.combined_response = plan
    h.agent.cli_executor.plan_response = plan


def _case(h, case_id: str) -> dict[str, Any]:
    return h.client.get(f"/api/cases/{case_id}").json()


def _crits(h, case_id: str) -> dict[str, dict[str, Any]]:
    return {c["criterion_key"]: c for c in h.criteria(case_id)}


def _meaning(h, case_id: str) -> dict[str, Any]:
    return h.result(case_id)["completion_meaning"]


def _purposes(h, case_id: str) -> list[str]:
    return [r["purpose"] for r in _runs(h, case_id)]


def _assert_closed_by_policy(h, case_id: str) -> dict[str, Any]:
    case = _case(h, case_id)
    assert case["status"] == "closed", h.conversation(case_id)["progress"]
    assert case["result"]["closure"]["closure_kind"] == "completed"
    candidate = case["result"]["candidate"] or h.client.get(f"/api/cases/{case_id}/completion-candidates").json()[-1]
    assert candidate["acceptance"]["mode"] == "auto_policy"
    human = [d for d in case["decisions"] if not d["actor"].startswith("policy:")]
    assert [d["kind"] for d in human] == ["intent_agreement"]  # 사람의 결정은 동의 하나뿐
    for crit in h.criteria(case_id):
        assert crit["recorded_by"] == workflow.CRITERIA_RECORDER
        assert crit["evidence_run_id"].startswith("wp-")
    return case


def _assert_waits_unresolved(h, case_id: str, conv: dict[str, Any], keys: list[str]) -> None:
    assert _wait_codes(conv) == ["criteria_unresolved"], conv["progress"]
    assert _case(h, case_id)["status"] == "waiting_final_acceptance"
    assert [c["key"] for c in conv["progress"]["wait"][0]["criteria"]] == keys
    auto = h.client.post(f"/api/cases/{case_id}/auto-complete").json()
    assert auto["applied"] is False and "unresolved_criteria" in auto["refusals"]
    assert _case(h, case_id)["result"]["closure"] is None


# ================================================== AC-1·AC-2 defect-fix


def test_a_defect_fix_restores_the_behavior_through_the_progressor(processing_harness):
    """AC-1 — defect-fix 의 기준은 `restoration` 이고 구현·검증 뒤 `changed_and_verified` 로 닫힌다."""
    h = processing_harness
    case_id = _begin(h, "defect_fix", draft=_draft(), text="ERROR 줄만 나와야 하는데 INFO 줄도 나온다. 고쳐줘")
    assert _case(h, case_id)["profile"] == "defect_fix"
    _agree(h, case_id)
    _drive(h, case_id)
    _assert_closed_by_policy(h, case_id)
    assert _purposes(h, case_id) == [
        "discussion_reply", "intent_authoring", "plan_authoring", "feature_implementation", "verification_run",
    ]
    crits = _crits(h, case_id)
    assert {c["obligation"] for c in crits.values()} == {"restoration"}
    assert {c["obligation_source"] for c in crits.values()} == {"derived_from_field"}
    assert all(c["verdict"] == "met" and c["satisfaction"] == "changed_and_verified" for c in crits.values())
    rows = {r["obligation"]: r for r in _meaning(h, case_id)["objectives"]}
    assert rows["restoration"]["status"] == "met" and rows["restoration"]["required_by"] == ["profile"]


def test_an_already_fixed_defect_closes_from_a_verification_run_alone(processing_harness):
    """AC-2 — 계획에 검증 Task 만 있고 구현 실행이 없으면 검증 실행의 관측이 `already_satisfied` 로 닫는다.

    구현 실행의 판정("변경도 명령도 없으면 실패")은 그대로다 — 무변경 완료의 근거는 구현이 아니라 검증이다.
    """
    h = processing_harness
    case_id = _begin(h, "defect_fix", draft=_draft(), text="이미 고쳐졌는지 확인하고 아니면 고쳐줘")
    _agree(h, case_id)
    _set_plan(h, ["C-01", "C-02"], implement=False)
    h.agent.cli_executor.write_files = {}  # 검증은 아무것도 바꾸지 않는다 — 이미 고쳐진 코드를 관측할 뿐
    _drive(h, case_id)
    _assert_closed_by_policy(h, case_id)
    purposes = _purposes(h, case_id)
    assert "feature_implementation" not in purposes and purposes[-1] == "verification_run"
    crits = _crits(h, case_id)
    assert all(c["verdict"] == "met" and c["satisfaction"] == "already_satisfied" for c in crits.values())
    verify = _runs(h, case_id)[-1]
    assert all(c["evidence_run_id"] == verify["run_id"] for c in crits.values())
    # 작업공간은 있었다(검증도 Case 의 worktree 에서 돈다) — 구현 실행이 없으니 변경 관측도 없다.
    assert h.workspace_view(case_id) is not None
    assert verify["workspace_effect"] is None or not verify["workspace_effect"].get("changed")


def test_a_failed_reproduction_records_nothing_and_waits(processing_harness):
    """AC-2 — 검증 명령이 실패하면(미재현) `met` 보고는 적히지 않고 기준은 미확인으로 남아 사람을 기다린다."""
    h = processing_harness
    case_id = _begin(h, "defect_fix", draft=_draft(), text="ERROR 줄만 나와야 하는데 INFO 줄도 나온다. 고쳐줘")
    h.agent.cli_executor.verification_response = _verification(
        [("C-01", "met", None), ("C-02", "met", None)], exit_code=1
    )
    _agree(h, case_id)
    conv = _drive(h, case_id)
    _assert_waits_unresolved(h, case_id, conv, ["C-01", "C-02"])
    crits = _crits(h, case_id)
    assert {c["verdict"] for c in crits.values()} == {"unverified"}
    assert {c["satisfaction"] for c in crits.values()} == {None}
    events = [e for e in conv["progress"]["events"] if e["action"] == "criteria_recorded"]
    assert events and "no_successful_command" in events[-1]["detail"]


# ================================================== AC-3 refactoring


def test_a_refactoring_closes_when_improvement_and_preservation_are_each_verified(processing_harness):
    """AC-3 — 개선 기준은 `changed_and_verified`, 보존 기준은 `preserved` 로 각각 검증 실행이 근거다."""
    h = processing_harness
    draft = _draft(
        c1="improvement_target", c2="preserved_contracts",
        fields={"improvement_target": "read 의 중첩 조건을 편다", "preserved_contracts": "read(path) 의 반환 형식"},
    )
    case_id = _begin(h, "refactoring", draft=draft, text="read 함수의 구조를 정리하되 반환 형식은 그대로 둬")
    assert _case(h, case_id)["profile"] == "refactoring"
    _agree(h, case_id)
    _drive(h, case_id)
    _assert_closed_by_policy(h, case_id)
    crits = _crits(h, case_id)
    assert (crits["C-01"]["obligation"], crits["C-01"]["satisfaction"]) == ("improvement", "changed_and_verified")
    assert (crits["C-02"]["obligation"], crits["C-02"]["satisfaction"]) == ("preservation", "preserved")
    assert crits["C-02"]["obligation_source"] == "derived_from_field"
    rows = {r["obligation"]: r for r in _meaning(h, case_id)["objectives"]}
    assert rows["improvement"]["required_by"] == ["profile"] and rows["preservation"]["required_by"] == ["profile"]
    assert rows["improvement"]["status"] == "met" and rows["preservation"]["status"] == "met"


def test_a_refactoring_without_a_preservation_criterion_waits_instead_of_closing(processing_harness):
    """AC-3 — 개선 기준만 있으면 개선이 충족돼도 닫히지 않는다. 기준 없는 목적은 예외 수용 대상도 아니다."""
    h = processing_harness
    draft = _draft(c1="improvement_target", c2=None, fields={"improvement_target": "중첩 조건을 편다"})
    case_id = _begin(h, "refactoring", draft=draft, text="read 함수의 구조를 정리해줘")
    _agree(h, case_id)
    _set_plan(h, ["C-01"])
    h.agent.cli_executor.verification_response = _verification([("C-01", "met", None)])
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["objective_without_criteria"], conv["progress"]
    assert conv["progress"]["wait"][0]["obligations"] == ["preservation"]
    assert _case(h, case_id)["status"] != "closed"
    crits = _crits(h, case_id)
    assert (crits["C-01"]["verdict"], crits["C-01"]["satisfaction"]) == ("met", "changed_and_verified")
    meaning = _meaning(h, case_id)
    assert meaning["missing"] == ["preservation"]
    auto = h.client.post(f"/api/cases/{case_id}/auto-complete").json()
    assert auto["applied"] is False
    assert _case(h, case_id)["result"]["closure"] is None


def test_a_refactoring_whose_preservation_fails_keeps_the_verdict_and_waits(processing_harness):
    """AC-3 — 보존 기준이 미충족이면 개선이 충족돼도 예외 카드에서 멈추고 원래 판정은 남는다."""
    h = processing_harness
    draft = _draft(c1="improvement_target", c2="preserved_contracts", fields={"preserved_contracts": "반환 형식"})
    case_id = _begin(h, "refactoring", draft=draft, text="read 함수의 구조를 정리하되 반환 형식은 그대로 둬")
    _agree(h, case_id)
    h.agent.cli_executor.verification_response = _verification([("C-01", "met", None), ("C-02", "not_met", None)])
    conv = _drive(h, case_id)
    _assert_waits_unresolved(h, case_id, conv, ["C-02"])
    crits = _crits(h, case_id)
    assert (crits["C-01"]["verdict"], crits["C-01"]["satisfaction"]) == ("met", "changed_and_verified")
    assert (crits["C-02"]["verdict"], crits["C-02"]["satisfaction"]) == ("not_met", None)
    rows = {r["obligation"]: r for r in _meaning(h, case_id)["objectives"]}
    assert rows["improvement"]["status"] == "met" and rows["preservation"]["status"] == "open"


# ================================================== AC-4 maintenance


@pytest.mark.parametrize(
    "conditions, keys, expected",
    [
        (True, ["C-01", "C-02"], "closed"),
        (True, ["C-01"], "objective_without_criteria"),
        (False, ["C-01"], "closed"),
    ],
    ids=["conditions-both", "conditions-target-only", "no-conditions"],
)
def test_maintenance_requires_preservation_only_when_conditions_are_written(processing_harness, conditions, keys, expected):
    """AC-4 — 목표 상태 기준으로 닫히되, 보존할 조건이 적혔으면 보존 기준(`preserved`)도 있어야 한다."""
    h = processing_harness
    fields = {"maintenance_target": "requirements.txt", "target_state": "pytest 8 로 올린다"}
    if conditions:
        fields["preserved_conditions"] = "지원 Python 3.11 유지"
    draft = _draft(c1="target_state", c2="preserved_conditions" if len(keys) == 2 else None, fields=fields)
    case_id = _begin(h, "maintenance", draft=draft, text="pytest 를 8 로 올려줘")
    assert _case(h, case_id)["profile"] == "maintenance"
    _agree(h, case_id)
    _set_plan(h, keys)
    h.agent.cli_executor.verification_response = _verification([(k, "met", None) for k in keys])
    conv = _drive(h, case_id)
    crits = _crits(h, case_id)
    assert (crits["C-01"]["obligation"], crits["C-01"]["satisfaction"]) == ("target_state", "changed_and_verified")
    rows = {r["obligation"]: r for r in _meaning(h, case_id)["objectives"]}
    assert rows["target_state"]["required_by"] == ["profile"] and rows["target_state"]["status"] == "met"
    if expected == "closed":
        _assert_closed_by_policy(h, case_id)
        if conditions:
            assert (crits["C-02"]["obligation"], crits["C-02"]["satisfaction"]) == ("preservation", "preserved")
            assert rows["preservation"]["required_by"] == ["profile_conditional"]
        else:
            assert "preservation" not in rows and _meaning(h, case_id)["missing"] == []
    else:
        assert _wait_codes(conv) == ["objective_without_criteria"], conv["progress"]
        assert conv["progress"]["wait"][0]["obligations"] == ["preservation"]
        assert rows["preservation"]["required_by"] == ["profile_conditional"]
        assert _meaning(h, case_id)["missing"] == ["preservation"]
        assert _case(h, case_id)["result"]["closure"] is None


# ================================================== AC-5 혼합 목적


@pytest.mark.parametrize("both", [True, False], ids=["both-proven", "fix-only"])
def test_a_revised_case_closes_only_when_the_cause_and_the_fix_are_both_proven(processing_harness, both):
    """AC-5 (a)(b) — RCA → defect_fix 개정 뒤 동의하면 진행기가 구현·검증으로 이어 가고, 검증 실행이 원인 기준
    (`investigated`·확정)과 복원 기준(`changed_and_verified`)을 함께 적어야 닫힌다. 수정만 충족하면 예외 카드다."""
    h = processing_harness
    _project, case_id, _conv = _rca_waiting(h)
    h.agent.cli_executor.draft_response = REVISED_DRAFT
    assert _revise(h, case_id).status_code == 201
    conv = _drive(h, case_id)
    if _wait_codes(conv) == ["material_delta"]:
        assert _confirm_pending_deltas(h, case_id) >= 1
        conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"], conv["progress"]
    before = len(_runs(h, case_id))  # 동의 자체가 다음 실행(결합 기록)을 만든다 — 그 전에 센다
    _agree(h, case_id)
    _set_plan(h, ["C-01", "C-02", "C-03"])
    cause = "determined" if both else "inconclusive"
    verdict = "met" if both else "not_met"
    h.agent.cli_executor.verification_response = _verification(
        [("C-01", verdict, cause), ("C-02", verdict, cause), ("C-03", "met", None)]
    )
    conv = _drive(h, case_id)
    assert _purposes(h, case_id)[before:] == ["plan_authoring", "feature_implementation", "verification_run"]
    verify = _runs(h, case_id)[-1]
    crits = _crits(h, case_id)
    assert (crits["C-03"]["obligation"], crits["C-03"]["verdict"], crits["C-03"]["satisfaction"]) == (
        "restoration", "met", "changed_and_verified",
    )
    meaning = _meaning(h, case_id)
    assert meaning["declared_objectives"] == ["cause", "restoration"]
    rows = {r["obligation"]: r for r in meaning["objectives"]}
    if both:
        case = _case(h, case_id)
        assert case["status"] == "closed", conv["progress"]
        assert case["result"]["closure"]["closure_kind"] == "completed"
        for key in ("C-01", "C-02"):
            assert (crits[key]["obligation"], crits[key]["verdict"], crits[key]["satisfaction"], crits[key]["conclusion"]) == (
                "cause", "met", "investigated", "determined",
            )
            assert crits[key]["evidence_run_id"] == verify["run_id"]
        assert rows["cause"]["status"] == "met" and rows["restoration"]["status"] == "met"
    else:
        _assert_waits_unresolved(h, case_id, conv, ["C-01", "C-02"])
        for key in ("C-01", "C-02"):
            assert (crits[key]["verdict"], crits[key]["conclusion"]) == ("not_met", "inconclusive")
        assert rows["cause"]["status"] == "open" and rows["restoration"]["status"] == "met"


@pytest.mark.parametrize("both", [True, False], ids=["both-proven", "fix-only"])
def test_a_defect_fix_that_declared_the_cause_from_the_start_needs_both(processing_harness, both):
    """AC-5 (c) — 처음부터 defect_fix + 선언 목적 `cause` 인 Case 도 같은 규칙이다."""
    h = processing_harness
    draft = _draft(c1="expected_outcome", c2="restore_scope", c1_obligation="cause", objectives=["cause"])
    case_id = _begin(h, "defect_fix", draft=draft, text="원인을 확정하고 고쳐줘. 원인을 못 찾으면 완료가 아니다")
    _agree(h, case_id)
    cause = "determined" if both else "inconclusive"
    h.agent.cli_executor.verification_response = _verification(
        [("C-01", "met" if both else "not_met", cause), ("C-02", "met", None)]
    )
    conv = _drive(h, case_id)
    crits = _crits(h, case_id)
    assert (crits["C-01"]["obligation"], crits["C-01"]["obligation_source"]) == ("cause", "reported")
    assert (crits["C-02"]["obligation"], crits["C-02"]["satisfaction"]) == ("restoration", "changed_and_verified")
    meaning = _meaning(h, case_id)
    rows = {r["obligation"]: r for r in meaning["objectives"]}
    assert rows["cause"]["required_by"] == ["declared"] and rows["restoration"]["required_by"] == ["profile"]
    if both:
        _assert_closed_by_policy(h, case_id)
        assert (crits["C-01"]["satisfaction"], crits["C-01"]["conclusion"]) == ("investigated", "determined")
    else:
        _assert_waits_unresolved(h, case_id, conv, ["C-01"])
        assert (crits["C-01"]["verdict"], crits["C-01"]["conclusion"]) == ("not_met", "inconclusive")
        assert rows["cause"]["status"] == "open"
