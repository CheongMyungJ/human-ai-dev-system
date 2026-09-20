"""P3-01 설계·개발계획과 단계별 검토 — AC-1·AC-5~AC-12.

**이 파일이 확인하는 핵심 하나:** 준비가 갖춰졌을 때만 기능 구현이 배정된다.
P2까지 `feature_implementation` 은 늘 거부됐고, 여기서 처음으로 허용되는 경로가
생긴다. 그 문이 정확히 무엇에 열리고 무엇에 닫히는지를 사유 코드별로 확인한다.

실제 CLI는 부르지 않는다(`FakeCliExecutor`). 실제 설계·계획 작성의 증거는 라이브
검증에서 따로 만든다.
"""

from __future__ import annotations

import copy

from tests.conftest import (
    FAKE_TASKS,
    FAKE_TOOL_ID,
    FAKE_TOOL_MODE,
    fake_preparation_response,
)

FIELDS = {
    "goal": {"text": "로그에서 오류 줄만 뽑는다", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 줄만 출력된다", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용 조회", "origin": "ai_proposal"},
    "exclusions": {"text": "회전 정책은 다루지 않는다", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬 파일만", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 미정", "origin": "ai_assumption"},
}


def _agreed_case(harness, questions=None):
    """의도 동의와 QG-01 통과까지 마친 Case. 준비 단계의 출발점이다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS, questions=questions)
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(case["id"], intent).status_code == 201
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    assert harness.gate(case["id"])["verdict"] == "pass"
    return case, intent


def _refusals(response) -> list[str]:
    return response.json()["detail"]["admission"]["refusals"]


def _prepare_both(harness, case_id, finish_first_task: bool = True):
    """설계와 계획을 AI로 작성하고 둘 다 사람 검토한다.

    **P3-02부터 계획이 작업 그래프를 낳는다.** `FAKE_TASKS` 의 T2 는 T1 을
    기다리므로, 구현 배정을 보려는 시험은 T1 을 실제 실행으로 끝내야 한다.
    사람이 "끝났다"고 적는 경로는 만들지 않았다 — 실행 증거 없이 의존을 푸는
    문이 되기 때문이다. 의존 자체를 확인하는 시험은 `finish_first_task=False` 다.
    """
    assert harness.ai_prepare(case_id, "design").status_code == 201
    assert harness.review_stage(case_id, "design").status_code == 201
    assert harness.ai_prepare(case_id, "plan").status_code == 201
    assert harness.review_stage(case_id, "plan").status_code == 201
    if finish_first_task:
        harness.complete_task(case_id, "T1")


# ------------------------------------------------------------------- AC-1


def test_both_stages_default_to_human_review(harness):
    """AC-1: **기본값은 두 단계 모두 사람 검토다.**

    설정 행이 없는 상태를 자동 진행으로 읽으면 기본값이 조용히 뒤집힌다.
    """
    case, _intent = _agreed_case(harness)
    prep = harness.preparation(case["id"])

    assert prep["design"]["mode"] == "human_review"
    assert prep["plan"]["mode"] == "human_review"
    # 사람이 정한 것이 아니라 프로젝트 기본값으로 읽은 것임을 구별한다.
    assert prep["design"]["mode_source"] == "project_default"
    assert prep["plan"]["mode_source"] == "project_default"


def test_the_two_stages_are_configured_independently(harness):
    """AC-1: 한 단계를 자동으로 바꿔도 다른 단계는 그대로다(FR-05 검토)."""
    case, _intent = _agreed_case(harness)
    assert harness.set_stage_mode(
        case["id"], "design", "auto_proceed", reason="설계가 국소적이다"
    ).status_code == 200

    prep = harness.preparation(case["id"])
    assert prep["design"]["mode"] == "auto_proceed"
    assert prep["plan"]["mode"] == "human_review"
    assert prep["plan"]["mode_source"] == "project_default"


def test_switching_to_auto_proceed_needs_a_reason(harness):
    """AC-1: 자동 진행은 사람이 고른 것이므로 왜 골랐는지가 남아야 한다."""
    case, _intent = _agreed_case(harness)
    response = harness.set_stage_mode(case["id"], "design", "auto_proceed", reason="")
    assert response.status_code == 409


# ------------------------------------------------------------------- AC-5


def test_design_and_plan_are_queried_separately(harness):
    """AC-5: **두 산출물을 각각 조회할 수 있다**(intent-artifacts 2절)."""
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])

    designs = harness.client.get(
        f"/api/cases/{case['id']}/preparation-artifacts", params={"stage": "design"}
    ).json()
    plans = harness.client.get(
        f"/api/cases/{case['id']}/preparation-artifacts", params={"stage": "plan"}
    ).json()
    both = harness.client.get(f"/api/cases/{case['id']}/preparation-artifacts").json()

    assert [d["stage"] for d in designs] == ["design"]
    assert [p["stage"] for p in plans] == ["plan"]
    assert len(both) == 2
    # 각자 버전과 검토 상태를 따로 갖는다.
    assert designs[0]["review"]["stage"] == "design"
    assert plans[0]["review"]["stage"] == "plan"
    # 계획은 어느 설계 위에 세웠는지를 갖는다.
    assert plans[0]["based_on_design_id"] == designs[0]["id"]


def test_a_simple_case_still_needs_both_artifacts(harness):
    """AC-5: **간소 수준에서도 두 산출물이 모두 존재한다.**

    intent-artifacts 2절이 허용하는 것은 한 화면·한 파일 안의 **표현**이며
    산출물을 하나로 합치는 것이 아니다.
    """
    case, _intent = _agreed_case(harness)
    assert harness.preparation(case["id"])["level"] == "simple"

    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    # 설계만 있는 상태에서는 계획이 없다는 사유로 막힌다.
    assert "plan_missing" in _refusals(harness.request_implementation(case["id"]))


def test_a_plan_cannot_be_authored_before_the_design_is_reviewed(harness):
    """AC-5: 의존 관계가 `의도 → 설계 → 개발계획` 이다.

    설계 검토 전의 계획 작성은 무엇을 구현할 계획인지 말할 수 없다.
    """
    case, _intent = _agreed_case(harness)
    # 설계가 아예 없는 상태
    response = harness.ai_prepare(case["id"], "plan", run_id="run-plan-early")
    assert response.status_code == 409
    assert "design_missing" in _refusals(response)

    # 설계는 있지만 아직 검토되지 않은 상태
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    response = harness.ai_prepare(case["id"], "plan", run_id="run-plan-early-2")
    assert response.status_code == 409
    assert "design_review_missing" in _refusals(response)


# ------------------------------------------------------------------- AC-6


def test_auto_proceed_preserves_the_artifact_and_is_not_human_approval(harness):
    """AC-6: **자동 진행에서도 원문 산출물이 보존되고 사람 승인으로 적히지 않는다.**

    sizing-and-review-ux 2절: "자동 진행이 필요한 검토·산출물·게이트의 생략이나
    사람 승인 기록 생성으로 이어지면 안 된다."
    """
    case, _intent = _agreed_case(harness)
    harness.set_stage_mode(case["id"], "design", "auto_proceed", reason="국소 변경")
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.auto_proceed(case["id"], "design").status_code == 201

    state = harness.preparation(case["id"])["design"]
    assert state["state"] == "auto_conditions_met"
    assert state["review"]["decision_id"] is None
    assert state["review"]["actor"] == "stage-auto-proceed-policy"
    # 산출물과 원문 참조가 그대로 있다. 자동 진행이 생략을 뜻하지 않는다.
    assert state["artifact"]["availability"] == "available"
    assert state["artifact"]["content_hash"]
    assert state["missing_required_sections"] == []

    # `decision` 표에 사람 검토 행이 생기지 않았다.
    decisions = harness.client.get(f"/api/cases/{case['id']}").json()["decisions"]
    assert [d for d in decisions if d["kind"] == "design_review"] == []


def test_auto_proceed_is_refused_while_the_stage_is_on_human_review(harness):
    """AC-6: 자동 진행이 사람을 대신하지 않는다."""
    case, _intent = _agreed_case(harness)
    assert harness.ai_prepare(case["id"], "design").status_code == 201

    response = harness.auto_proceed(case["id"], "design")
    assert response.status_code == 409
    assert "human review" in response.text


def test_a_human_review_records_a_decision_row(harness):
    """AC-6: 사람 검토는 `decision` 표에 남는다. 자동 진행과 기록이 다르다."""
    case, _intent = _agreed_case(harness)
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201

    decisions = harness.client.get(f"/api/cases/{case['id']}").json()["decisions"]
    rows = [d for d in decisions if d["kind"] == "design_review"]
    assert len(rows) == 1
    assert rows[0]["actor"] == "owner"
    # 검토 대상 원문의 해시가 붙는다. 내용이 바뀌면 그 검토는 새 산출물에
    # 적용되지 않는다(FR-23).
    assert rows[0]["subject_content_hash"]


def test_opening_the_screen_is_not_a_review(harness):
    """AC-6: `reviewed` 가 아니면 기록하지 않는다. 열어 본 것이 검토가 아니다."""
    case, _intent = _agreed_case(harness)
    assert harness.ai_prepare(case["id"], "design").status_code == 201

    response = harness.review_stage(case["id"], "design", reviewed=False)
    assert response.status_code == 409
    assert harness.preparation(case["id"])["design"]["state"] == "awaiting_human_review"


# ------------------------------------------------------------- AC-7 · AC-8


def test_missing_required_sections_block_the_implementation(harness):
    """AC-7: 수준이 요구하는 항목이 미정이면 배정되지 않는다.

    항목을 비운 산출물은 **비운 채로 남고** 그 사실이 사유가 된다. 채워서
    통과시키면 진입 조건이 볼 것이 없어진다.
    """
    case, _intent = _agreed_case(harness)
    # 간소 수준의 설계 필수 항목은 change_summary 와 verifiability 다.
    # verifiability 를 비운 응답을 낸다.
    harness.agent.cli_executor.design_response = fake_preparation_response(
        "설계", {"change_summary": "필터 함수를 더한다"}
    )
    assert harness.ai_prepare(case["id"], "design").status_code == 201

    state = harness.preparation(case["id"])["design"]
    assert state["missing_required_sections"] == ["verifiability"]
    # 사람이 검토했어도 항목이 비어 있으면 막힌다. 검토가 내용을 채우지 않는다.
    assert harness.review_stage(case["id"], "design").status_code == 201
    assert "design_incomplete_for_level" in _refusals(
        harness.request_implementation(case["id"])
    )


def test_a_deeper_level_requires_more_sections(harness):
    """AC-7: 수준이 올라가면 필수 항목이 늘어난다.

    같은 산출물이 간소에서는 충분하고 심층에서는 부족할 수 있다. 그것이 "업무에
    비례한 준비"의 구체적 동작이다.
    """
    case, _intent = _agreed_case(harness)
    harness.agent.cli_executor.design_response = fake_preparation_response(
        "설계",
        {
            "change_summary": "필터 함수를 더한다",
            "verifiability": "표본 파일로 확인한다",
        },
    )
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.preparation(case["id"])["design"]["missing_required_sections"] == []

    # 사람이 심층으로 올린다. 이제 같은 산출물로는 부족하다.
    assert harness.adjust_level(case["id"], "deep").status_code == 201
    harness.agent.cli_executor.design_response = fake_preparation_response(
        "설계",
        {
            "change_summary": "필터 함수를 더한다",
            "verifiability": "표본 파일로 확인한다",
        },
    )
    assert harness.ai_prepare(case["id"], "design", run_id="run-design-2").status_code == 201
    missing = harness.preparation(case["id"])["design"]["missing_required_sections"]
    assert set(missing) == {
        "alternatives",
        "failure_handling",
        "interfaces_and_data",
        "recovery",
        "requirement_mapping",
    }


def test_review_missing_is_reported_per_stage(harness):
    """AC-8: 사람 검토가 남아 있으면 단계별로 구별된 사유가 나온다."""
    case, _intent = _agreed_case(harness)
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert "design_review_missing" in _refusals(harness.request_implementation(case["id"]))

    assert harness.review_stage(case["id"], "design").status_code == 201
    assert harness.ai_prepare(case["id"], "plan").status_code == 201
    refusals = _refusals(harness.request_implementation(case["id"], run_id="run-impl-2"))
    assert "plan_review_missing" in refusals
    assert "design_review_missing" not in refusals


def test_an_auto_proceed_stage_with_an_artifact_is_not_reported_as_not_ready(harness):
    """AC-6: 산출물이 **있는데** "산출물 준비 전"으로 보이지 않는다.

    자동 진행 설정에서 조건 충족 기록만 없는 상태는 따로 구별한다. 두 상태를 합치면
    사람이 무엇을 해야 하는지 알 수 없다.
    """
    case, _intent = _agreed_case(harness)
    harness.set_stage_mode(case["id"], "design", "auto_proceed", reason="국소 변경")
    assert harness.preparation(case["id"])["design"]["state"] == "not_ready"

    assert harness.ai_prepare(case["id"], "design").status_code == 201
    state = harness.preparation(case["id"])["design"]
    assert state["artifact"] is not None
    assert state["state"] == "awaiting_auto_conditions"


def test_auto_proceed_still_needs_its_condition_record(harness):
    """AC-8: 모드를 자동으로 바꾼 것만으로 검토가 끝나지 않는다.

    설정만으로 끝났다고 적으면 그것이 곧 사람 승인 기록의 대체가 된다.
    """
    case, _intent = _agreed_case(harness)
    harness.set_stage_mode(case["id"], "design", "auto_proceed", reason="국소 변경")
    assert harness.ai_prepare(case["id"], "design").status_code == 201

    refusals = _refusals(harness.request_implementation(case["id"]))
    assert "design_review_missing" in refusals

    assert harness.auto_proceed(case["id"], "design").status_code == 201
    refusals = _refusals(harness.request_implementation(case["id"], run_id="run-impl-2"))
    assert "design_review_missing" not in refusals


# ------------------------------------------------------------------- AC-9


def test_a_new_intent_version_makes_both_artifacts_stale(harness):
    """AC-9: **오래된 승인은 재사용되지 않는다.**

    설계·계획 검토를 마친 뒤 새 의도 버전이 생기면 두 산출물이 오래된 것이 되고
    이전 검토가 적용되지 않는다(FR-23).
    """
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])
    # 준비가 끝난 상태에서는 허용된다(대조군).
    assert harness.request_implementation(case["id"]).status_code == 201

    changed = copy.deepcopy(FIELDS)
    changed["scope"]["text"] = "읽기 전용 조회 + 요약 출력"
    harness.submit_intent_draft(case["id"], changed, summary="의도 v2")

    prep = harness.preparation(case["id"])
    assert prep["design"]["stale"] is True
    assert prep["plan"]["stale"] is True
    assert prep["design"]["state"] == "needs_recheck"

    refusals = _refusals(harness.request_implementation(case["id"], run_id="run-impl-2"))
    assert "design_stale" in refusals
    assert "plan_stale" in refusals


def test_a_new_design_supersedes_the_plan_built_on_the_old_one(harness):
    """AC-9: 설계가 바뀌면 그 위의 계획은 더 이상 현재 설계의 계획이 아니다."""
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])

    assert harness.ai_prepare(case["id"], "design", run_id="run-design-2").status_code == 201
    prep = harness.preparation(case["id"])
    # 계획은 대체됐고 현재 계획이 없다.
    assert prep["plan"]["artifact"] is None

    refusals = _refusals(harness.request_implementation(case["id"], run_id="run-impl-2"))
    assert "plan_missing" in refusals

    plans = harness.client.get(
        f"/api/cases/{case['id']}/preparation-artifacts", params={"stage": "plan"}
    ).json()
    # 지워지지 않고 대체됨으로 남는다. 무엇이 있었는지는 기록이다.
    assert plans[0]["state"] == "superseded"


def test_a_stale_review_is_not_reused_after_a_new_artifact(harness):
    """AC-9: 산출물이 새로 만들어지면 이전 검토가 따라오지 않는다."""
    case, _intent = _agreed_case(harness)
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    first = harness.preparation(case["id"])["design"]["artifact"]["id"]

    assert harness.ai_prepare(case["id"], "design", run_id="run-design-2").status_code == 201
    state = harness.preparation(case["id"])["design"]
    assert state["artifact"]["id"] != first
    assert state["review"] is None
    assert state["state"] == "awaiting_human_review"


# ------------------------------------------------------------------ AC-10


def test_deferred_questions_block_the_implementation(harness):
    """AC-10: **설계·계획으로 이월한 질문이 남아 있으면 배정되지 않는다.**

    의도 단계 질문과 사유가 구별된다. 이월은 "AI가 알아서 정한다"가 아니라
    "그 단계의 작업 전에 사람에게 받는다"는 뜻이다(FR-03 질문 처리).
    """
    case, _intent = _agreed_case(
        harness,
        questions=[
            {
                "key": "q-design",
                "text": "필터를 어느 계층에 둘지 정해야 한다",
                "summary": "필터 위치",
                "decide_at": "design",
            }
        ],
    )
    # 연결 없는 이월 질문은 **모든 Task** 를 막으므로 선행 Task 조차 끝낼 수 없다.
    # 그것이 P3-02의 안전 기본값이다 — 무엇을 막는지 모르면 전부 막는다.
    _prepare_both(harness, case["id"], finish_first_task=False)

    refusals = _refusals(harness.request_implementation(case["id"]))
    assert "deferred_questions_unresolved" in refusals
    # 의도 단계 질문이 아니다. 두 사유를 뭉뚱그리지 않는다.
    assert "open_intent_questions" not in refusals

    # 답하면 열린다.
    question = next(
        q for q in harness.open_questions(case["id"]) if q["question_key"] == "q-design"
    )
    answer = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={
            "content": "reader 계층에 둔다",
            "summary": "reader 계층",
            "target_runner_id": harness.agent.config.runner_id,
        },
    )
    assert answer.status_code == 202
    # 질문이 풀리자 선행 Task 를 실행할 수 있고, 그것이 끝나면 구현이 열린다.
    harness.complete_task(case["id"], "T1")
    assert harness.request_implementation(case["id"], run_id="run-impl-2").status_code == 201


def test_a_question_raised_by_the_design_also_blocks(harness):
    """AC-10: 설계가 낳은 질문도 같은 조건이다. 출처가 기록에 남는다."""
    case, _intent = _agreed_case(harness)
    harness.agent.cli_executor.design_response = fake_preparation_response(
        "설계",
        {
            "change_summary": "필터 함수를 더한다",
            "verifiability": "표본 파일로 확인한다",
        },
        questions=[
            {
                "key": "d1",
                "text": "대소문자 구분을 켤지 사람이 정해야 한다",
                "summary": "대소문자 구분",
                "decide_at": "design",
            }
        ],
    )
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    assert harness.ai_prepare(case["id"], "plan").status_code == 201
    assert harness.review_stage(case["id"], "plan").status_code == 201

    refusals = _refusals(harness.request_implementation(case["id"]))
    assert "deferred_questions_unresolved" in refusals

    raised = next(
        q for q in harness.open_questions(case["id"]) if q["question_key"] == "design:d1"
    )
    assert raised["raised_in_stage"] == "design"
    assert raised["preparation_id"]


# ------------------------------------------------------------------ AC-11


def test_the_implementation_opens_once_everything_is_ready(harness):
    """AC-11: **조건을 모두 갖추면 허용된다.**

    P2까지 이 목적은 늘 거부됐다. 여기가 P3-01이 여는 문이다.
    """
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])

    response = harness.request_implementation(case["id"])
    assert response.status_code == 201, response.text
    assert response.json()["admission"]["outcome"] == "admitted"

    checks = harness.admission_checks(case["id"])
    admitted = [c for c in checks if c["requested_purpose"] == "feature_implementation"]
    # 허용도 기록에 남는다(FR-29).
    assert admitted and admitted[0]["outcome"] == "admitted"


def test_finishing_the_reviews_does_not_create_write_permission(harness):
    """AC-11: **검토를 마쳤다는 사실이 쓰기 권한을 만들지 않는다.**

    같은 상태에서 `workspace_write` 는 계속 거부된다. 작업공간·브랜치 준비는
    P3-03이며, 거부되는 것이 이번 단계의 올바른 동작이다.
    """
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])
    assert harness.request_implementation(case["id"]).status_code == 201

    response = harness.request_implementation(
        case["id"], run_id="run-impl-write", permission="workspace_write"
    )
    assert response.status_code == 409
    refusals = _refusals(response)
    assert "permission_not_allowed_in_stage" in refusals
    # 준비 부족이 아니다. 준비는 갖췄고 권한만 열려 있지 않다.
    assert "design_missing" not in refusals
    assert "plan_missing" not in refusals


def test_sizing_must_be_decided_before_the_implementation(harness):
    """AC-11: 수준 미결정도 배정을 막는다.

    준비 산출물이 있어도 어느 깊이로 준비했는지 알 수 없으면 필수 항목을 판단할
    수 없다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS, with_sizing=False)
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(case["id"], intent).status_code == 201
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201

    refusals = _refusals(harness.request_implementation(case["id"]))
    assert "sizing_not_decided" in refusals


# ------------------------------------------------------------------ AC-12


def test_an_authoring_run_is_given_the_previous_version(harness):
    """AC-12: **작성 실행이 이전 버전을 본다.**

    P2-04에서 재작성 실행에 요청 원문 하나만 들어가 AI가 의도를 처음부터 다시
    썼고 초안이 퇴화했다. 이제 이전 버전과 미해결 피드백이 참조로 고정된다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"], run_id="run-draft-1")
    intent = harness.latest_intent(case["id"])
    harness.submit_feedback(case["id"], intent["id"], "범위를 좁혀 주세요", summary="범위")

    harness.ai_draft(case["id"], request_text="피드백을 반영해 주세요", run_id="run-draft-2")

    refs = harness.context_refs("run-draft-2")
    roles = [r["role"] for r in refs]
    assert "previous_intent" in roles
    assert "feedback" in roles
    # 지시문에 실제로 이전 버전 본문이 들어갔다.
    call = next(c for c in harness.agent.cli_executor.calls if c["run_id"] == "run-draft-2")
    assert "고정 컨텍스트" in call["prompt"]
    assert intent["artifact_id"] in call["prompt"]


def test_the_design_run_is_given_the_agreed_intent(harness):
    """AC-12: 설계 작성에는 동의된 의도가, 계획 작성에는 현재 설계가 고정된다."""
    case, intent = _agreed_case(harness)
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    assert harness.ai_prepare(case["id"], "plan").status_code == 201

    design_roles = [r["role"] for r in harness.context_refs("run-design-1")]
    plan_roles = [r["role"] for r in harness.context_refs("run-plan-1")]
    assert design_roles == ["agreed_intent"]
    assert "agreed_intent" in plan_roles
    assert "current_design" in plan_roles

    # 산출물 원문에 "무엇을 읽었는가"가 남는다.
    design = harness.preparation(case["id"])["design"]["artifact"]
    _request, content = harness.read_original(design["artifact_id"], design["artifact_rev"])
    assert '"role": "agreed_intent"' in content
    assert '"read": true' in content


def test_an_unreadable_reference_is_reported_as_unread(harness):
    """AC-12: 읽지 못한 참조를 **읽은 것으로 적지 않는다.**

    조용히 빼면 AI는 그런 자료가 없었다고 생각하고 처음부터 다시 쓴다 — 퇴화의
    경로가 정확히 그것이다. 읽지 못한 사실을 지시문과 산출물에 남긴다.
    """
    case, intent = _agreed_case(harness)
    # 소유 Runner의 저장소에서 의도 원문을 치운다. 참조는 그대로 남는다.
    stored = harness.agent.store.path_for(intent["artifact_id"], intent["artifact_rev"])
    stored.unlink()

    assert harness.ai_prepare(case["id"], "design").status_code == 201
    call = next(c for c in harness.agent.cli_executor.calls if c["run_id"] == "run-design-1")
    assert "이 자료를 읽지 못했다" in call["prompt"]

    design = harness.preparation(case["id"])["design"]["artifact"]
    _request, content = harness.read_original(design["artifact_id"], design["artifact_rev"])
    assert '"read": false' in content


def test_a_skeleton_executor_cannot_author_a_design(harness):
    """AC-12(보강): 설계·계획 작성도 실제 코딩 CLI가 필요하다.

    골격 실행기로 배정하면 실행은 정상 종료하는데 산출물이 없어 아무 일도 일어나지
    않은 것처럼 보인다. 그 조합을 진입 검사에서 막는다.
    """
    case, _intent = _agreed_case(harness)
    instruction = harness.submit_artifact(
        case["id"], "설계를 써 주세요", kind="instruction", summary="요청"
    )
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-design-skeleton",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "design_authoring",
            "role": "author",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
        },
    )
    assert response.status_code == 409
    assert "tool_is_not_a_coding_cli" in _refusals(response)


def test_a_malformed_preparation_response_fails_the_run(harness):
    """AC-12(보강): 형식을 못 맞춘 응답을 추측으로 고치지 않는다.

    CLI가 정상 종료했어도 산출물이 없으면 완료가 아니다(FR-28).
    """
    case, _intent = _agreed_case(harness)
    harness.agent.cli_executor.design_response = "JSON 없이 설명만 적었습니다."
    assert harness.ai_prepare(case["id"], "design").status_code == 201

    run = harness.client.get("/api/runs/run-design-1").json()
    assert run["outcome"] == "failed"
    assert harness.preparation(case["id"])["design"]["artifact"] is None


def test_an_admitted_implementation_run_without_an_executor_fails_cleanly(harness):
    """AC-11(보강): 진입 조건과 실행 경로는 **서로 다른 것**이다.

    P3-01은 `feature_implementation` 의 배정 조건을 열었지만 실행기는 P3-03이다.
    그 배정을 받은 Runner 는 **실행하지 않고 실패로 보고한다.** 예외로 죽으면
    실행이 `assigned` 로 멈춘 채 남고 사람은 왜 아무 일도 일어나지 않는지 알 수 없다
    (라이브에서 실제로 났던 일).
    """
    case, _intent = _agreed_case(harness)
    _prepare_both(harness, case["id"])
    before = harness.cli_effect_count(case["id"])
    assert harness.request_implementation(case["id"]).status_code == 201

    # 한 번 돌려도 예외가 나지 않고, 다른 배정 처리도 막히지 않는다.
    result = harness.agent.poll_once()
    actions = {a["run_id"]: a["action"] for a in result["assignments"]}
    assert actions["run-impl-1"] == "refused_no_execution_path"

    run = harness.client.get("/api/runs/run-impl-1").json()
    assert run["status"] == "finished"
    # **완료가 아니다.** 실행 경로가 없다는 사실이 실패로 남는다(FR-28).
    assert run["outcome"] == "failed"
    # **CLI를 부르지 않았다.** 실행 경로가 없다는 것을 알고 나서 실행하지 않는다.
    assert harness.cli_effect_count(case["id"]) == before


def test_raising_the_level_makes_an_existing_artifact_insufficient(harness):
    """AC-7: **수준을 올리면 이미 있는 산출물도 부족해진다.**

    필수 항목을 산출물이 작성된 시점의 수준으로 정하면 조정이 겉치레가 되고, 얕게
    쓴 산출물로 "준비 완료"가 된다. 라이브 검증에서 실제로 이 구멍이 드러났다
    (sizing-and-review-ux 1·3절: 조정의 영향을 받는 산출물을 보여 준다).
    """
    case, _intent = _agreed_case(harness)
    # 간소 수준에 필요한 만큼만 쓴 산출물을 만든다. 기본 가짜 응답은 심층 항목까지
    # 채우므로 여기서는 얕은 응답을 쓴다 — 올렸을 때 부족해지는 것을 보려면 필요하다.
    harness.agent.cli_executor.design_response = fake_preparation_response(
        "설계",
        {"change_summary": "필터 함수를 더한다", "verifiability": "표본 파일로 확인한다"},
    )
    harness.agent.cli_executor.plan_response = fake_preparation_response(
        "계획",
        {"tasks": "T1 구현(완료 조건: 시험 통과)", "verification": "표본 파일 시험 1건"},
        tasks=FAKE_TASKS,
    )
    _prepare_both(harness, case["id"])
    assert harness.preparation(case["id"])["design"]["missing_required_sections"] == []
    assert harness.request_implementation(case["id"]).status_code == 201

    # 산출물을 다시 만들지 않고 수준만 올린다.
    assert harness.adjust_level(case["id"], "deep").status_code == 201

    prep = harness.preparation(case["id"])
    # 산출물은 그대로이고 작성 시점 수준도 그대로 기록돼 있다.
    assert prep["design"]["artifact"]["level"] == "simple"
    # 그런데 **지금** 요구되는 항목이 늘어 부족해졌다.
    assert prep["design"]["missing_required_sections"]
    assert prep["plan"]["missing_required_sections"]

    refusals = _refusals(harness.request_implementation(case["id"], run_id="run-impl-2"))
    assert "design_incomplete_for_level" in refusals
    assert "plan_incomplete_for_level" in refusals

    # 항목 표에는 "지금 필수"와 "보고 시점에 필수였는가"가 따로 있다.
    sections = {s["section"]: s for s in prep["design"]["artifact"]["sections"]}
    assert sections["alternatives"]["required"] is True
    assert sections["alternatives"]["required_at_report"] is False

    # 되돌리면 다시 충분해진다. 조정이 기록을 지우지 않는다.
    assert harness.adjust_level(case["id"], "simple").status_code == 201
    assert harness.preparation(case["id"])["design"]["missing_required_sections"] == []
    assert harness.request_implementation(case["id"], run_id="run-impl-3").status_code == 201
