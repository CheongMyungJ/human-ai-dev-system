"""P3-R1 — 정책·Profile·저장소·예산의 영속 모델과 기존 데이터의 이행.

기대값은 구현 코드가 아니라 합의한 요구에서 가져온다.

  D-59  WorkDepth 와 Autonomy 분리. 기본 ask-on-decision, 선택 controlled
  D-60  위임 근거는 최초 요청 + 사용자의 후속 결정 + 정책. AI 초안은 근거가 아니다
  D-61  강제할 수 있는 예산만 강제한다. 보장할 수 없는 hard 설정은 허용하지 않는다
  D-62  여섯 Profile 의 목적별 의도 항목과 **버전 고정**
  D-63  등록 저장소 / 쓰기·게시 허용 / Case 선택 집합을 구분한다
  D-64  쓰기 허용 저장소 추가는 게시 허용 확대가 아니다
  D-65  controlled 의 시작 범위·결과 후보 확인. 확인이 권한을 만들지 않는다
  FR-14 적용 WorkDepth/Autonomy/Budget 과 **계측 불가·한도 도달**을 숨기지 않는다
  FR-23 사람 판단의 의미·대상·버전을 구분해 기록하고 실행 직전 대조한다
  DEVELOPMENT.md 3절 "새 정책을 기존 승인·동의·권한에 소급 적용하지 않는다"

**이 파일의 절반은 "아직 하지 않는 것"을 고정한다.** R1 은 모델과 이행까지이고
실행 경로·예산 강제·작업공간은 R2~R4 다. 값이 저장된다는 사실을 기능이 있다는
뜻으로 표시하지 않는 것이 이 단계의 가장 중요한 기준이다.
"""

from __future__ import annotations

import sqlite3

from domain import profiles
from domain.models import (
    BUDGET_MEASUREMENT,
    POLICY_VERSION,
    Autonomy,
    AutonomySource,
    BudgetMeasurement,
    BudgetMetric,
    CaseProfile,
    IntentField,
    ProfileSource,
)

SIX = {f.value for f in IntentField}


def _policy(harness, case_id: str) -> dict:
    response = harness.client.get(f"/api/cases/{case_id}/policy")
    assert response.status_code == 200, response.text
    return response.json()


def _set_autonomy(harness, case_id: str, value: str, **extra):
    body = {"autonomy": value, "set_by": "owner"}
    body.update(extra)
    return harness.client.put(f"/api/cases/{case_id}/autonomy", json=body)


# --------------------------------------------------------------- AC-1 Profile


def test_the_six_profiles_are_defined_with_a_version(harness):
    """AC-1 — 여섯 Profile 이 버전과 의미 항목·증거·완료 의미를 갖는다."""
    response = harness.client.get("/api/profiles")
    assert response.status_code == 200
    body = response.json()
    assert body["current_version"] == profiles.CURRENT_PROFILE_VERSION
    by_name = {p["profile"]: p for p in body["profiles"]}
    assert set(by_name) == {p.value for p in CaseProfile}

    for name, definition in by_name.items():
        assert definition["semantic_fields"], f"{name} 에 의미 항목이 없다"
        assert definition["minimum_evidence"]
        assert definition["completion_meaning"]
        # 초안에서 고정하지 않는 것도 정의에 있다 — 빈칸을 채우게 하지 않기 위해서다.
        assert definition["not_fixed_in_draft"]
        # 공통 여섯 항목은 모든 Profile 에 있고, 의미 항목이 그 위에 얹힌다.
        assert SIX < set(definition["required_fields"])


def test_a_published_profile_version_resolves_forever(harness):
    """AC-1 — 기록된 `(profile, version)` 은 계속 조회된다.

    새 정의가 기존 Case 에 소급되지 않는다는 규칙의 전제다(D-62). 조회가 실패하면
    코드는 "현재 버전으로 대신 읽자"는 유혹을 받게 되고, 그것이 곧 소급 적용이다.
    """
    for key in profiles.DEFINITIONS:
        assert profiles.resolve(*key).version == key[1]
    # 없는 버전을 현재 버전으로 대체하지 않는다.
    try:
        profiles.resolve(CaseProfile.FEATURE.value, "99")
    except KeyError:
        pass
    else:  # pragma: no cover - 실패 시 메시지를 위해 남긴다
        raise AssertionError("없는 정의판을 조용히 대체했다")


def test_profile_records_whether_a_human_chose_it(harness):
    """AC-1 — 지정한 Profile 과 `kind` 에서 유도한 Profile 을 구별한다(FR-04)."""
    project = harness.create_project()

    chosen = harness.create_case(project["id"], "리팩터링", profile="refactoring")
    assert chosen["profile"] == "refactoring"
    assert chosen["profile_source"] == ProfileSource.EXPLICIT.value
    # 기존 `kind` 축은 Profile 에서 유도된다. 없는 대응을 억지로 만들지 않는다.
    assert chosen["kind"] == "refactoring"

    derived = harness.create_case(project["id"], "버그", kind="bug")
    assert derived["profile"] == "defect_fix"
    assert derived["profile_source"] == ProfileSource.DERIVED_FROM_KIND.value


def test_a_contradictory_profile_and_kind_is_refused(harness):
    """AC-12 — 둘을 함께 주고 맞지 않으면 거부한다. 한쪽이 조용히 이기지 않는다."""
    project = harness.create_project()
    response = harness.client.post(
        f"/api/projects/{project['id']}/cases",
        json={"title": "모순", "kind": "bug", "profile": "research"},
    )
    assert response.status_code == 409
    assert "implies kind" in response.json()["detail"]


# ------------------------------------------------- AC-2·AC-3 Profile별 초안


def _draft_for(harness, case_id: str, omit: str | None = None) -> dict:
    """그 Case 의 필수 항목을 채운 초안 입력."""
    required = _policy(harness, case_id)["profile"]["required_fields"]
    fields = {}
    for name in required:
        if name == omit:
            continue
        fields[name] = {
            "text": f"{name} 에 대한 내용",
            "state": "proposed",
            "origin": "user_requirement",
        }
    return fields


def test_each_profile_carries_its_own_semantic_fields(harness):
    """AC-2 — 여섯 Profile 각각의 초안이 그 목적의 의미 항목을 갖는다."""
    project = harness.create_project()
    for profile in CaseProfile:
        case = harness.create_case(project["id"], f"{profile.value} 업무", profile=profile.value)
        harness.submit_intent_draft(case["id"], _draft_for(harness, case["id"]))
        intent = harness.latest_intent(case["id"])
        recorded = {f["field"] for f in intent["fields"]}
        expected = set(profiles.current(profile).required_fields)
        assert recorded == expected, f"{profile.value} 의 항목이 맞지 않다"
        # 항목마다 상태·출처가 따로 있다 — 사실·제안·미정을 구별한다(FR-04).
        assert all(f["state"] and f["origin"] for f in intent["fields"])


def test_a_structure_report_missing_a_profile_field_is_refused(harness):
    """AC-2 — Profile 필수 항목이 빠진 구조 보고는 거부한다.

    "정보가 없으면 항목을 삭제한다"가 아니라 미정으로 남기는 것이 규칙이며, 그 규칙은
    공통 항목과 의미 항목에 똑같이 적용된다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "결함", profile="defect_fix")
    harness.submit_intent_draft(case["id"], _draft_for(harness, case["id"]))
    intent = harness.latest_intent(case["id"])

    response = harness.client.post(
        "/api/runner/intent-structure",
        json={
            "runner_id": "runner-test-1",
            "intent_version_id": intent["id"],
            "fields": [
                {
                    "field": name,
                    "state": "proposed",
                    "origin": "user_requirement",
                    "change_from_prev": "initial",
                }
                for name in SIX
            ],
            "questions": [],
        },
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert "observed_behavior" in detail


def test_the_gate_rule_sees_a_missing_profile_field(harness):
    """AC-3 — 빠진 Profile 항목은 QG-01 규칙의 필수 발견으로 잡힌다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "유지", profile="maintenance")
    # `omit` 항목은 본문 없이 들어가고 `undecided` 로 남는다 — 그것은 문제가 아니다.
    # 문제는 **행이 아예 없는** 경우이며, 그 상태를 직접 만들어 규칙을 본다.
    harness.submit_intent_draft(case["id"], _draft_for(harness, case["id"]))
    intent = harness.latest_intent(case["id"])
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        conn.execute(
            "DELETE FROM intent_field WHERE intent_version_id = ? AND field = ?",
            (intent["id"], "target_state"),
        )
        conn.commit()
    finally:
        conn.close()

    response = harness.client.post(
        f"/api/cases/{case['id']}/intent-versions/{intent['id']}/gate-rules"
    )
    assert response.status_code == 200, response.text
    findings = response.json()["findings"]
    missing = [
        f
        for f in findings
        if f["criterion"] == "required_field_missing" and f["target"] == "target_state"
    ]
    assert missing and missing[0]["severity"] == "required"
    assert response.json()["rule_verdict"] == "fail"


def test_a_pre_r1_case_keeps_the_six_field_form(harness):
    """AC-2·AC-5 — Profile 이 기록되지 않은 Case 는 공통 여섯 항목 그대로다.

    지금의 의미 항목을 요구하면 그 Case 의 기존 의도 버전이 갑자기 불완전한 문서가
    된다. 새 규칙의 소급 적용이며 금지된다.
    """
    project = harness.create_project()
    case = harness.create_pre_r1_case(project["id"])
    policy = _policy(harness, case["id"])
    assert policy["profile"]["profile"] is None
    assert policy["profile"]["source"] == ProfileSource.NOT_RECORDED.value
    assert set(policy["profile"]["required_fields"]) == SIX

    harness.submit_intent_draft(
        case["id"],
        {
            "goal": {
                "text": "옛 Case 의 목표",
                "state": "proposed",
                "origin": "user_requirement",
            }
        },
    )
    intent = harness.latest_intent(case["id"])
    assert {f["field"] for f in intent["fields"]} == SIX


# ------------------------------------------------------------ AC-4·AC-5 정책


def test_a_new_case_defaults_to_ask_on_decision(harness):
    """AC-4 — 새 Case 의 기본은 ask-on-decision 이고 출처는 시스템 기본값이다(D-11)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    policy = _policy(harness, case["id"])
    assert policy["autonomy"] == Autonomy.ASK_ON_DECISION.value
    assert policy["autonomy_source"] == AutonomySource.SYSTEM_DEFAULT.value
    assert policy["autonomy_recorded"] is True
    assert policy["policy_version"] == POLICY_VERSION
    # WorkDepth 는 **다른 축**이며 수준 판단이 만든다. 여기서 복제하지 않는다.
    assert policy["work_depth_source"] == "sizing_assessment"
    # 확인 지점은 controlled 의 것이다. 기본 Case 에는 없다.
    assert policy["checkpoints"] == []


def test_changing_autonomy_keeps_the_previous_value(harness):
    """AC-4 — 설정 변경은 새 revision 이고 이전 값은 `superseded` 로 남는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    assert _set_autonomy(harness, case["id"], "controlled").status_code == 200
    assert _set_autonomy(harness, case["id"], "ask_on_decision").status_code == 200

    revisions = harness.client.get(f"/api/cases/{case['id']}/policy-revisions").json()
    assert [r["revision"] for r in revisions] == [1, 2, 3]
    assert [r["state"] for r in revisions] == ["superseded", "superseded", "current"]
    assert revisions[1]["autonomy"] == Autonomy.CONTROLLED.value
    assert revisions[-1]["autonomy_source"] == AutonomySource.CASE_EXPLICIT.value


def test_a_pre_r1_case_is_never_reported_as_ask_on_decision(harness):
    """AC-5 — 이행된 Case 의 Autonomy 는 **미기록**이며 기본값으로 읽지 않는다.

    v0.6에서 사람이 검토·인수하기로 하고 진행한 업무가 조용히 자동 진행 대상이
    되어서는 안 된다. 가장 가까운 값(`controlled`)으로 적지도 않는다 — 있지도 않은
    사람의 확인을 기록하는 일이다.
    """
    project = harness.create_project()
    case = harness.create_pre_r1_case(project["id"])
    policy = _policy(harness, case["id"])
    assert policy["autonomy"] is None
    assert policy["autonomy_recorded"] is False
    assert policy["autonomy_source"] == AutonomySource.MIGRATED_UNKNOWN.value
    assert policy["policy_version"] == "0.6"
    # 기본값이 무엇인지는 보여 준다. 그것이 이 Case 에 적용됐다고 말하지는 않는다.
    assert policy["default_autonomy"] == Autonomy.ASK_ON_DECISION.value


def test_policy_changes_do_not_touch_existing_human_records(harness):
    """AC-5·AC-11 — 정책을 바꿔도 동의·결정·완료 정책 기록은 그대로다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_for(harness, case["id"]))
    intent = harness.ready_for_acceptance(case["id"], project["id"])
    before = harness.client.get(f"/api/cases/{case['id']}").json()
    before_decisions = before["decisions"]
    before_completion = before["result"]["completion_mode"]

    assert _set_autonomy(harness, case["id"], "controlled").status_code == 200

    after = harness.client.get(f"/api/cases/{case['id']}").json()
    assert after["decisions"] == before_decisions
    assert after["result"]["completion_mode"] == before_completion
    assert after["intent_state"]["agreement_state"] == "agreed_current"
    assert after["intent_state"]["agreed_version"]["subject_id"] == intent["id"]


def test_policy_cannot_be_changed_after_closure(harness):
    """AC-12 — 종료된 Case 의 정책·예산·저장소 설정은 거부한다(D-33)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_for(harness, case["id"]))
    harness.ready_for_acceptance(case["id"], project["id"])
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])
    assert harness.accept(case["id"], candidate["id"]).status_code == 201

    refused = _set_autonomy(harness, case["id"], "controlled")
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusals"] == ["case_already_closed"]

    budget = harness.client.put(
        f"/api/cases/{case['id']}/budget",
        json={
            "metric": "run_count",
            "threshold_kind": "hard",
            "limit_value": 3,
            "set_by": "owner",
        },
    )
    assert budget.status_code == 409
    assert budget.json()["detail"]["refusals"] == ["case_already_closed"]


# ------------------------------------------------------- AC-6 controlled 확인


def test_controlled_creates_the_two_checkpoints(harness):
    """AC-6 — controlled 는 시작 범위·결과 후보 확인 지점을 만든다(D-65).

    설계·계획의 사람 검토는 **이 목록에 없다.** 별도 선택 사항이며 단계 검토 설정이
    따로 관리한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    assert _set_autonomy(harness, case["id"], "controlled").status_code == 200
    points = harness.client.get(f"/api/cases/{case['id']}/controlled-checkpoints").json()
    assert {p["checkpoint"] for p in points} == {"start_scope", "result_candidate"}
    assert {p["state"] for p in points} == {"required"}


def test_a_checkpoint_confirmation_records_who_saw_what(harness):
    """AC-6 — 확인 기록은 주체·시점·대상과 그 해시를 갖는다(FR-23)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _set_autonomy(harness, case["id"], "controlled")

    response = harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/start_scope/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": True,
            "subject_type": "case",
            "subject_id": case["id"],
            "subject_hash": "a" * 64,
            "note_summary": "목표·범위·허용 행동을 확인했다",
        },
    )
    assert response.status_code == 201, response.text
    start = [p for p in response.json() if p["checkpoint"] == "start_scope"][0]
    assert start["state"] == "confirmed"
    assert start["confirmed_by"] == "owner"
    assert start["confirmed_at"]
    assert start["subject_hash"] == "a" * 64


def test_a_checkpoint_needs_an_explicit_confirmation(harness):
    """AC-6 — 명시적 확인이 아닌 요청을 확인으로 적지 않는다(D-14)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _set_autonomy(harness, case["id"], "controlled")
    response = harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/start_scope/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": False,
            "subject_type": "case",
            "subject_id": case["id"],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["refusals"] == ["not_explicit"]


def test_ask_on_decision_has_no_checkpoint_to_confirm(harness):
    """AC-6 — 요구되지 않은 확인을 만들지 않는다.

    기본 자율 진행 Case 에 controlled 의 확인 기록을 만들 수 있으면, 나중에 그 기록이
    "사람이 확인했다"는 근거로 쓰인다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/start_scope/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": True,
            "subject_type": "case",
            "subject_id": case["id"],
        },
    )
    assert response.status_code == 409
    assert response.json()["detail"]["refusals"] == ["checkpoint_not_required"]


def test_a_confirmation_creates_no_permission_and_no_acceptance(harness):
    """AC-6 — 확인이 push·게시 권한이나 최종 인수를 만들지 않는다(D-32·D-65)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _set_autonomy(harness, case["id"], "controlled")
    harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/result_candidate/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": True,
            "subject_type": "completion_candidate",
            "subject_id": "cand-x",
            "subject_hash": "b" * 64,
        },
    )
    view = harness.client.get(f"/api/cases/{case['id']}").json()
    kinds = {d["kind"] for d in view["decisions"]}
    assert "push_approval" not in kinds and "publication_grant" not in kinds
    assert "final_acceptance" not in kinds
    assert view["result"]["closure"] is None
    # 저장소 게시 허용도 생기지 않는다.
    repos = harness.client.get(f"/api/cases/{case['id']}/repositories").json()
    assert repos["selected"] == []


def test_superseding_a_checkpoint_keeps_the_earlier_confirmation(harness):
    """AC-6 — 확인한 대상이 바뀌면 새 확인을 요구하되 **기록은 남는다**(FR-23)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _set_autonomy(harness, case["id"], "controlled")
    harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/result_candidate/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": True,
            "subject_type": "completion_candidate",
            "subject_id": "cand-A",
            "subject_hash": "c" * 64,
        },
    )
    response = harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/result_candidate/supersede",
        json={"reason_summary": "CI 수정으로 후보 내용이 바뀌었다"},
    )
    assert response.status_code == 201, response.text
    points = [p for p in response.json() if p["checkpoint"] == "result_candidate"]
    states = {p["state"]: p for p in points}
    assert set(states) == {"superseded", "required"}
    # 무엇을 보고 확인했는지가 남아 있다.
    assert states["superseded"]["subject_id"] == "cand-A"
    assert states["superseded"]["confirmed_by"] == "owner"


def test_returning_to_ask_on_decision_keeps_confirmed_records(harness):
    """AC-6 — 설정을 되돌려도 사람이 실제로 확인한 기록은 없어지지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _set_autonomy(harness, case["id"], "controlled")
    harness.client.post(
        f"/api/cases/{case['id']}/controlled-checkpoints/start_scope/confirmation",
        json={
            "confirmed_by": "owner",
            "explicit": True,
            "subject_type": "case",
            "subject_id": case["id"],
        },
    )
    _set_autonomy(harness, case["id"], "ask_on_decision")
    points = harness.client.get(f"/api/cases/{case['id']}/controlled-checkpoints").json()
    assert [p["checkpoint"] for p in points] == ["start_scope"]
    assert points[0]["state"] == "confirmed"


# ------------------------------------------------------------ AC-9 예산


def test_no_budget_setting_means_unlimited(harness):
    """AC-9 / R3 AC-1 — 설정이 없으면 무제한이고 아무 것도 막지 않는다(D-56).

    **P3-R3에서 갱신됐다.** R1은 `usage is None` 을 고정했고 그것은 "아직 재지
    않는다"는 뜻이었다. 이제 잰다. 다만 무제한 Case 에서는 재는 것이 배정을 바꾸지
    않아야 하며, 실행이 없으면 0 이고 그 0 은 **관측된 0**(`complete = true`)이다 —
    "재지 않아서 모른다"와 다르다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    budget = harness.client.get(f"/api/cases/{case['id']}/budget").json()
    assert budget["unlimited"] is True
    assert budget["limits"] == []
    assert budget["stop"]["stopped"] is False
    assert budget["usage"]["run_count"]["exposure"] == 0.0
    assert budget["usage"]["run_count"]["complete"] is True
    assert budget["usage"]["run_count"]["runs_counted"] == 0
    assert "P4-01" in budget["repair_limit_note"]


def test_a_measurable_hard_limit_is_recorded(harness):
    """AC-9 — 정확히 셀 수 있는 지표의 hard 한도는 받는다. 단위·측정 방식이 함께 남는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.put(
        f"/api/cases/{case['id']}/budget",
        json={
            "metric": "run_count",
            "threshold_kind": "hard",
            "limit_value": 5,
            "set_by": "owner",
            "reason_summary": "이 업무는 다섯 번의 실행 안에서 끝낸다",
        },
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["unlimited"] is False
    limit = body["limits"][0]
    assert limit["metric"] == "run_count"
    assert limit["measurement"] == BudgetMeasurement.EXACT.value
    assert limit["unit"] == "runs"
    # **강제 상태를 값과 함께 남긴다.** 설정한 사람이 무엇을 약속받았는지 알도록.
    #
    # P3-R3에서 `recorded_not_enforced` 에서 바뀌었다. 실행 수는 배정 전에 정확히
    # 1 을 잡을 수 있으므로 **절대 상한**을 약속한다.
    assert limit["enforcement"] == "enforced_absolute"
    assert limit["guarantee"] == "absolute"
    assert limit["enforced_by"] == "P3-R3"


def test_an_unenforceable_hard_limit_is_refused(harness):
    """AC-9 — 보장할 수 없는 정확한 hard 한도는 **설정을 받지 않는다**(D-61).

    저장해 두면 설정한 사람은 상한이 있다고 믿는데 시스템은 지킬 방법이 없다.
    어댑터가 사용량을 주지 않거나 사후에만 주는 지표가 그 경우다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    for metric in (BudgetMetric.INPUT_TOKENS, BudgetMetric.ESTIMATED_COST):
        assert BUDGET_MEASUREMENT[metric] is not BudgetMeasurement.EXACT
        response = harness.client.put(
            f"/api/cases/{case['id']}/budget",
            json={
                "metric": metric.value,
                "threshold_kind": "hard",
                "limit_value": 100,
                "set_by": "owner",
            },
        )
        assert response.status_code == 409, metric.value
        assert response.json()["detail"]["refusals"] == ["hard_limit_not_enforceable"]
    assert harness.client.get(f"/api/cases/{case['id']}/budget").json()["unlimited"] is True


def test_a_warning_threshold_is_allowed_on_an_estimated_metric(harness):
    """AC-9 — 경고선은 추정 지표에도 받는다. 경고는 표시이며 보장이 아니다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.put(
        f"/api/cases/{case['id']}/budget",
        json={
            "metric": "estimated_cost",
            "threshold_kind": "warn",
            "limit_value": 2.5,
            "set_by": "owner",
        },
    )
    assert response.status_code == 201, response.text
    limit = response.json()["limits"][0]
    assert limit["threshold_kind"] == "warn"
    assert limit["measurement"] == BudgetMeasurement.ESTIMATED.value


def test_a_non_positive_limit_is_refused(harness):
    """AC-12 — 0 이하의 한도는 거부한다. 0을 "무제한"으로도, 즉시 정지로도 읽지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.put(
        f"/api/cases/{case['id']}/budget",
        json={
            "metric": "run_count",
            "threshold_kind": "hard",
            "limit_value": 0,
            "set_by": "owner",
        },
    )
    assert response.status_code == 422  # 입력 계약에서 먼저 걸린다


def test_clearing_a_limit_keeps_its_history(harness):
    """AC-9 — 한도를 바꾸거나 해제해도 이력이 남는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    for value in (5, 9):
        harness.client.put(
            f"/api/cases/{case['id']}/budget",
            json={
                "metric": "run_count",
                "threshold_kind": "hard",
                "limit_value": value,
                "set_by": "owner",
            },
        )
    cleared = harness.client.delete(f"/api/cases/{case['id']}/budget/run_count/hard").json()
    assert cleared["unlimited"] is True
    assert [h["limit_value"] for h in cleared["history"]] == [5.0, 9.0]
    assert {h["state"] for h in cleared["history"]} == {"superseded"}


# -------------------------------------------------- AC-7·AC-8 저장소 모델


def test_a_project_starts_with_one_registered_repository(harness):
    """AC-8 — Project 생성이 등록 저장소 한 건을 만든다. 값은 기존 경로와 같다."""
    project = harness.create_project()
    view = harness.client.get(f"/api/projects/{project['id']}/repositories").json()
    assert len(view["repositories"]) == 1
    assert view["repositories"][0]["repo_path"] == project["repo_path"]
    assert view["legacy_repo_path"] == project["repo_path"]
    assert view["journal_repository_id"] is None


def test_write_allowance_does_not_imply_publish_allowance(harness):
    """AC-7 — 선택·쓰기 허용·게시 허용은 서로 다른 집합이다(D-63·D-64)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    repo_id = harness.client.get(
        f"/api/projects/{project['id']}/repositories"
    ).json()["repositories"][0]["id"]

    response = harness.client.put(
        f"/api/cases/{case['id']}/repositories",
        json={
            "repository_id": repo_id,
            "code_write_allowed": True,
            "publish_allowed": False,
            "selected_by": "owner",
        },
    )
    assert response.status_code == 201, response.text
    state = response.json()
    selected = state["selected"][0]
    assert selected["code_write_allowed"] == 1
    assert selected["publish_allowed"] == 0
    assert state["write_allowance_implies_publish"] is False


def test_the_journal_repository_is_not_a_code_target(harness):
    """AC-7 — 지정한 기록 저장소를 코드 쓰기 대상으로 선택할 수 없다(D-17·FR-30)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    journal = harness.client.post(
        f"/api/projects/{project['id']}/repositories",
        json={"name": "journal", "repo_path": "C:/tmp/journal", "registered_by": "owner"},
    ).json()
    assert (
        harness.client.put(
            f"/api/projects/{project['id']}/journal-repository",
            json={"repository_id": journal["id"]},
        ).status_code
        == 200
    )

    refused = harness.client.put(
        f"/api/cases/{case['id']}/repositories",
        json={
            "repository_id": journal["id"],
            "code_write_allowed": True,
            "publish_allowed": True,
            "selected_by": "owner",
        },
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusals"] == [
        "journal_repository_not_a_code_target"
    ]


def test_a_repository_from_another_project_is_refused(harness):
    """AC-12 — 다른 Project 의 저장소는 선택할 수 없다."""
    first = harness.create_project("one")
    second = harness.create_project("two")
    case = harness.create_case(first["id"])
    foreign = harness.client.get(
        f"/api/projects/{second['id']}/repositories"
    ).json()["repositories"][0]["id"]
    refused = harness.client.put(
        f"/api/cases/{case['id']}/repositories",
        json={
            "repository_id": foreign,
            "code_write_allowed": False,
            "publish_allowed": False,
            "selected_by": "owner",
        },
    )
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusals"] == ["repository_not_in_project"]


def test_an_unselected_case_shows_the_implicit_single_repository(harness):
    """AC-8 — 선택 기록이 없는 Case 를 "저장소 없음"으로도 "선택했다"로도 적지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    state = harness.client.get(f"/api/cases/{case['id']}/repositories").json()
    assert state["selected"] == []
    implicit = state["implicit_single_repository"]
    assert implicit is not None
    assert implicit["repo_path"] == project["repo_path"]
    assert "기록된 선택이 아니다" in implicit["detail"]


# ------------------------------------------ AC-10 아직 강제하지 않는다는 표시


def test_the_policy_view_says_who_enforces_each_axis(harness):
    """AC-10 — 각 축을 **지금 누가 강제하는가**를 담당 작업과 함께 표시한다.

    **P3-R2에서 갱신했다.** `repository_selection` 이 `recorded_not_enforced` 에서
    `enforced` 로 바뀌었다 — R2 가 선택·쓰기 허용으로 실제 작업공간을 막기 때문이다.
    바뀌지 않은 채 이 시험이 통과했다면 강제를 붙이지 않은 것이고, 그것이 이 시험을
    남겨 두는 이유다(DEVELOPMENT.md 9절).

    나머지 셋은 아직 기록뿐이다. R3·R4 가 붙일 때 이 시험이 다시 갱신돼야 한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    enforcement = _policy(harness, case["id"])["enforcement"]
    assert enforcement["autonomy"]["state"] == "recorded_not_enforced"
    assert enforcement["autonomy"]["enforced_by"] == "P3-R4"
    assert enforcement["controlled_checkpoint"]["state"] == "recorded_not_enforced"
    assert enforcement["controlled_checkpoint"]["enforced_by"] == "P3-R4"
    # **P3-R3에서 바뀐 축.** 예약·집계·정지가 실제로 배정을 정한다.
    assert enforcement["budget"]["state"] == "enforced"
    assert enforcement["budget"]["enforced_by"] == "P3-R3"
    # 다만 "강제한다"가 모든 지표에 같은 약속은 아니다. 그 차이를 조회가 말한다.
    assert "절대 상한" in enforcement["budget"]["detail"]
    # **P3-R2가 실제로 강제한다.**
    assert enforcement["repository_selection"]["state"] == "enforced"
    assert enforcement["repository_selection"]["enforced_by"] == "P3-R2"
    # 게시는 여전히 구현되지 않았다. 쓰기 허용이 게시 허용으로 번지지 않는다(D-64).
    assert enforcement["publish"]["state"] == "not_implemented"
    assert enforcement["publish"]["enforced_by"] == "P5"


def test_a_hard_budget_now_stops_the_next_run(harness):
    """R3 AC-2 — hard 한도에 도달하면 다음 실행이 **거부되고 그 사유가 기록된다**.

    **R1의 `test_a_hard_budget_does_not_yet_change_admission` 을 대체한다.** 저
    시험은 "기록만 하고 막지 않는다"를 고정했고, 그것이 R1·R2 시점의 사실이었다.
    이제 막으므로 시험도 반대를 확인한다 — 통과한 채로 남았다면 강제를 붙이지 않은
    것이다(DEVELOPMENT.md 9절).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    harness.client.put(
        f"/api/cases/{case['id']}/budget",
        json={
            "metric": "run_count",
            "threshold_kind": "hard",
            "limit_value": 1,
            "set_by": "owner",
        },
    )
    artifact = harness.submit_artifact(case["id"], "조사 지시")["artifact_id"]
    harness.agent.persist_pending_intakes()
    harness.create_run(case["id"], artifact, run_id="run-budget-1")

    refused = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-budget-2",
            "instruction_artifact_id": artifact,
            "purpose": "limited_analysis",
            "role": "author",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
            "task_id": "task-1",
        },
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["admission"]["refusals"] == ["budget_hard_limit_reached"]

    # **거부가 기록된다.** 사람이 왜 실행이 열리지 않았는지 볼 수 있어야 한다(FR-14).
    refusals = [
        r for check in harness.admission_checks(case["id"]) for r in check["refusals"]
    ]
    assert "budget_hard_limit_reached" in refusals
    # 두 번째 Run 은 **만들어지지 않았다.**
    runs = harness.client.get(f"/api/cases/{case['id']}").json()["runs"]
    assert [r["run_id"] for r in runs] == ["run-budget-1"]


def test_new_profiles_do_not_loosen_the_existing_admission_rules(harness):
    """AC-11 — 새 Profile·kind 값이 기존 진입 조건을 느슨하게 만들지 않는다.

    `refactoring` 은 v0.6에 없던 값이다. 그 Case 의 구현 요청은 기존 비기능 Case 와
    **같은** 선행 조건 거부를 받는다.
    """
    project = harness.create_project()
    new_kind = harness.create_case(project["id"], "리팩터링", profile="refactoring")
    old_kind = harness.create_case(project["id"], "조사", kind="analysis")

    refusals = {}
    for case in (new_kind, old_kind):
        artifact = harness.submit_artifact(case["id"], "구현 지시")["artifact_id"]
        harness.agent.persist_pending_intakes()
        response = harness.client.post(
            f"/api/cases/{case['id']}/runs",
            json={
                "run_id": f"run-impl-{case['id'][-6:]}",
                "instruction_artifact_id": artifact,
                "purpose": "feature_implementation",
                "role": "author",
                "tool_id": "codex",
                "mode": "exec",
                "permission": "workspace_write",
                "task_id": "task-1",
            },
        )
        assert response.status_code == 409, response.text
        refusals[case["id"]] = set(response.json()["detail"]["admission"]["refusals"])

    assert refusals[new_kind["id"]] == refusals[old_kind["id"]]
    assert "sizing_not_decided" in refusals[new_kind["id"]]
    assert "workspace_not_ready" in refusals[new_kind["id"]]


def test_a_profile_change_does_not_reset_history(harness):
    """AC-11 — Profile 재분류로 성공 기준·예산·질문·결정이 초기화되지 않는다(D-62).

    R1 은 Profile 변경 경로를 만들지 않는다. **그래서 이 시험은 "바꿀 수 없다"를
    확인한다** — 경로가 없는데 있다고 적지 않기 위해서다. 변경이 필요해지면 그
    작업에서 보존 규칙과 함께 만든다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "결함", profile="defect_fix")
    response = harness.client.put(
        f"/api/cases/{case['id']}/profile", json={"profile": "feature"}
    )
    assert response.status_code == 405 or response.status_code == 404


# ------------------------------------------------------- AC-1·AC-4 위임 근거


def test_the_delegation_basis_is_recorded_and_versioned(harness):
    """AC-4 — 위임 근거와 그 이력을 남긴다(D-60). AI 초안은 근거가 아니다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    artifact = harness.submit_artifact(case["id"], "원 요청 원문", kind="intent")
    harness.agent.persist_pending_intakes()

    first = harness.client.post(
        f"/api/cases/{case['id']}/delegation-basis",
        json={
            "basis_kind": "original_request",
            "summary": "최초 요청",
            "artifact_id": artifact["artifact_id"],
            "artifact_rev": artifact["revision"],
        },
    )
    assert first.status_code == 201, first.text
    body = first.json()
    assert body["current"]["basis_kind"] == "original_request"
    # 그 시점 원문의 해시가 함께 남는다 — 나중에 바뀌면 근거가 바뀐 것이다.
    assert body["current"]["content_hash"]

    second = harness.client.post(
        f"/api/cases/{case['id']}/delegation-basis",
        json={"basis_kind": "user_decision", "summary": "행 범위는 선택한 행만"},
    ).json()
    assert second["current"]["basis_kind"] == "user_decision"
    assert [h["revision"] for h in second["history"]] == [1, 2]
    assert second["history"][0]["state"] == "superseded"
    # AI 초안을 근거로 적을 수 있는 값이 없다.
    refused = harness.client.post(
        f"/api/cases/{case['id']}/delegation-basis",
        json={"basis_kind": "ai_draft", "summary": "AI 초안"},
    )
    assert refused.status_code == 422


# --------------------------------------------------------- AC-13·AC-14 경계


def test_policy_records_survive_a_reopened_database(harness):
    """AC-13 — 연결을 닫고 다시 열어도 기록이 그대로다(프로세스 재시작은 별도 시험)."""
    from controller import db as dbmod
    from controller.repository import Repository

    project = harness.create_project()
    case = harness.create_case(project["id"], "유지", profile="maintenance")
    _set_autonomy(harness, case["id"], "controlled", reason_summary="외부 반영이 있는 업무")
    harness.client.put(
        f"/api/cases/{case['id']}/budget",
        json={
            "metric": "execution_seconds",
            "threshold_kind": "hard",
            "limit_value": 900,
            "set_by": "owner",
        },
    )
    before = _policy(harness, case["id"])

    conn = dbmod.connect(harness.controller_config.db_path)
    dbmod.migrate(conn)
    repo = Repository(conn)
    after = repo.effective_policy(case["id"])
    conn.close()

    assert after["autonomy"] == before["autonomy"]
    assert after["profile"]["profile"] == "maintenance"
    assert [p["checkpoint"] for p in after["checkpoints"]] == [
        p["checkpoint"] for p in before["checkpoints"]
    ]
    assert after["budget"]["limits"][0]["limit_value"] == 900.0


def test_new_p3_r1_tables_have_no_body_columns(harness):
    """AC-14 — 새 표에 본문 컬럼이 없고 요약에 길이 상한이 걸려 있다."""
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    body_like = {
        "content",
        "body",
        "text",
        "raw",
        "payload",
        "reason",
        "note",
        "detail",
        "statement",
    }
    tables = (
        "case_policy",
        "delegation_basis",
        "controlled_checkpoint",
        "budget_setting",
        "project_repository",
        "case_repository",
    )
    for table in tables:
        columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        assert columns, f"{table} 이 없다"
        assert not (columns & body_like), f"{table} 에 본문 컬럼이 있다: {columns & body_like}"

    rows = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE name IN"
        " ('case_policy','delegation_basis','controlled_checkpoint','budget_setting',"
        "  'case_repository')"
    ).fetchall()
    limits = {r["name"]: r["sql"] for r in rows}
    assert "length(reason_summary) <= 200" in limits["case_policy"]
    assert "length(summary) <= 200" in limits["delegation_basis"]
    assert "length(note_summary) <= 200" in limits["controlled_checkpoint"]
    assert "length(reason_summary) <= 200" in limits["budget_setting"]
    assert "length(reason_summary) <= 200" in limits["case_repository"]
    conn.close()


def test_policy_reasons_do_not_leak_bodies_into_the_controller(harness):
    """AC-14 — 요약 인자로 본문을 밀어 넣을 수 없다(길이 상한)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    long_body = "본문" * 400
    response = _set_autonomy(harness, case["id"], "controlled", reason_summary=long_body)
    assert response.status_code == 422  # 입력 계약에서 먼저 걸린다


def test_a_success_criterion_can_point_at_a_profile_field(harness):
    """AC-2 — 성공 기준이 Profile 의미 항목을 가리킬 수 있다.

    **라이브에서 실제로 막혔던 자리다.** 기준의 대상 항목을 공통 여섯 항목으로만
    검증하면, 실제 CLI 가 `improvement_target` 에 걸린 기준을 쓰는 순간 구조 보고가
    500으로 죽고 초안 전체가 사라진다. 검증은 유지하되 대상 집합을 Profile 이
    정하게 한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], "리팩터링", profile="refactoring")
    harness.submit_intent_draft(
        case["id"],
        _draft_for(harness, case["id"]),
        criteria=[
            {
                "key": "C-01",
                "relates_to": "preserved_contracts",
                "text": "공개 API 의 동작이 그대로다",
                "method": "기존 계약 시험을 그대로 실행한다",
                "summary": "공개 API 보존",
                "method_summary": "기존 계약 시험 실행",
            }
        ],
    )
    criteria = harness.criteria(case["id"])
    assert [c["relates_to"] for c in criteria] == ["preserved_contracts"]

    # 모르는 이름은 여전히 저장하지 않는다.
    intent = harness.latest_intent(case["id"])
    response = harness.client.post(
        "/api/runner/intent-structure",
        json={
            "runner_id": "runner-test-1",
            "intent_version_id": intent["id"],
            "fields": [
                {
                    "field": name,
                    "state": "proposed",
                    "origin": "user_requirement",
                    "change_from_prev": "unchanged",
                }
                for name in profiles.current("refactoring").required_fields
            ],
            "questions": [],
            "criteria": [
                {
                    "key": "C-02",
                    "relates_to": "no_such_field",
                    "summary": "요약",
                    "method_summary": "확인 방법",
                }
            ],
        },
    )
    assert response.status_code == 409
    assert "unknown intent field" in response.json()["detail"]


def test_an_excluded_repository_is_not_listed_as_selected(harness):
    """AC-7 — 명시적으로 제외한 저장소를 선택 목록에 넣지 않는다(D-63).

    한 목록에 함께 두면 화면이 제외를 선택으로 보여 주고, R2 의 허용 내 자동 추가가
    제외 경계를 읽을 근거가 흐려진다. 그리고 제외에는 쓰기·게시 허용을 붙일 수 없다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    other = harness.client.post(
        f"/api/projects/{project['id']}/repositories",
        json={"name": "vendor", "repo_path": "C:/tmp/vendor"},
    ).json()

    state = harness.client.put(
        f"/api/cases/{case['id']}/repositories",
        json={
            "repository_id": other["id"],
            "selection_source": "excluded",
            "code_write_allowed": False,
            "publish_allowed": False,
            "selected_by": "owner",
            "reason_summary": "이 업무의 대상이 아니다",
        },
    ).json()
    assert [r["repository_id"] for r in state["excluded"]] == [other["id"]]
    assert state["selected"] == []
    # 기록이 있으므로 "암묵적 단일 저장소"라는 가정을 씌우지 않는다.
    assert state["implicit_single_repository"] is None

    refused = harness.client.put(
        f"/api/cases/{case['id']}/repositories",
        json={
            "repository_id": other["id"],
            "selection_source": "excluded",
            "code_write_allowed": True,
            "publish_allowed": False,
            "selected_by": "owner",
        },
    )
    assert refused.status_code == 409
    assert "excluded repository cannot carry" in refused.json()["detail"]


def test_a_successor_case_does_not_inherit_the_profile_or_the_policy(harness):
    """AC-11 — 후속 Case 는 Profile·Autonomy·확인 기록을 승계하지 않는다(D-33)."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "원래 기능", profile="feature")
    _set_autonomy(harness, case["id"], "controlled")
    harness.submit_intent_draft(case["id"], _draft_for(harness, case["id"]))
    harness.ready_for_acceptance(case["id"], project["id"])
    harness.mark_all_criteria_met(case["id"])
    candidate = harness.build_candidate(case["id"])
    assert harness.accept(case["id"], candidate["id"]).status_code == 201

    successor = harness.client.post(
        f"/api/cases/{case['id']}/successor",
        json={
            "title": "완료 후 발견한 결함",
            "profile": "defect_fix",
            "reason_summary": "완료 뒤 발견한 동작 차이",
        },
    )
    assert successor.status_code == 201, successor.text
    new_case = successor.json()
    assert new_case["profile"] == "defect_fix"
    policy = _policy(harness, new_case["id"])
    assert policy["autonomy"] == Autonomy.ASK_ON_DECISION.value
    assert policy["autonomy_source"] == AutonomySource.SYSTEM_DEFAULT.value
    assert policy["checkpoints"] == []
