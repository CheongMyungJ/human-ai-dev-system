"""AC-1~3, AC-5: 성공 기준과 기준별 결과.

여기서 확인하는 것은 네 가지다.

  성공 기준이 **의도 버전에 묶이고**, 초안의 기준과 사람이 확인한 기준이 구별된다
  기준별 결과의 기본값은 **`unverified`** 이며 실행이 끝났다는 사실이 판정을 만들지 않는다
  **실행 불명(`unknown`)을 근거로 한 `met` 은 거부된다** — 불명이 성공이 되지 않는다
  새 의도 버전은 기준과 판정을 **승계하지 않는다**
"""

from __future__ import annotations

import pytest

from tests.conftest import DEFAULT_CRITERIA

GOOD_FIELDS = {
    "goal": {"text": "로그에서 오류 줄만 뽑는다", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전 제외", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 미정", "origin": "ai_assumption"},
}


@pytest.fixture
def agreed_case(harness):
    """초안 제출 → QG-01 의미 검토 → 원문 열람 → 명시 동의까지 마친 Case.

    게이트 검토를 빼면 `limited_analysis` 실행이 P2-03의 진입 검사에서 거부된다.
    그것이 올바른 동작이므로 여기서 우회하지 않고 순서를 그대로 밟는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(case["id"], intent).status_code == 201
    assert harness.gate(case["id"])["verdict"] == "pass"
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    return case, intent


# ------------------------------------------------------------------- AC-1


def test_criteria_belong_to_the_intent_version_and_start_as_proposals(harness):
    """AC-1: 기준은 의도 버전에 묶이고 초안 단계에서는 **제안**이다.

    intent-artifacts 1절: "초안 단계의 기준은 제안이며, 사용자가 확인한 기준과
    구별한다." 동의 전에 `user_confirmed` 로 올라가면 그 구별이 사라진다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)

    intent = harness.latest_intent(case["id"])
    criteria = harness.criteria(case["id"])
    assert [c["criterion_key"] for c in criteria] == ["C-01", "C-02"]
    assert {c["state"] for c in criteria} == {"proposed"}
    assert {c["intent_version_id"] for c in criteria} == {intent["id"]}


def test_agreement_promotes_that_versions_criteria_only(harness):
    """AC-1: 사람이 그 버전에 명시 동의하면 **그 버전의** 기준이 확인됨이 된다.

    동의 없이 기준만 확인하는 경로는 없다. 있으면 기준이 의도에서 분리된다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)
    intent = harness.latest_intent(case["id"])

    # 원문을 읽기 전에는 동의가 안 되므로 기준도 제안 그대로다.
    assert {c["state"] for c in harness.criteria(case["id"])} == {"proposed"}

    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    assert {c["state"] for c in harness.criteria(case["id"])} == {"user_confirmed"}


def test_zero_criteria_stay_zero(harness):
    """AC-1: 기준이 0건이면 0건으로 남는다. 시스템이 채우지 않는다.

    대신 그 사실이 QG-01 규칙 검사에 **권고**로 드러나고, 최종 인수에서는
    `no_success_criteria` 로 거부된다. 빈 통과를 만들지 않는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS, criteria=[])

    assert harness.criteria(case["id"]) == []
    gate = harness.gate(case["id"])
    findings = {f["criterion"]: f for f in gate["findings"]}
    assert "no_success_criteria" in findings
    # 권고다. 규칙 검사를 실패로 만들지 않는다 — 기준의 내용 판단은 AI 검토의 몫이다.
    assert findings["no_success_criteria"]["severity"] == "advisory"
    assert gate["rule_verdict"] == "pass"


def test_a_criterion_without_a_verification_method_is_refused(harness):
    """AC-1: 확인 방법이 없는 기준은 받지 않는다.

    확인할 방법이 없는 기준은 기준이 아니라 바람이고, 빈 값으로 통과시키면
    QG-01의 `unverifiable_success_criteria` 가 볼 것이 없어진다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.post(
        f"/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "의도 초안",
            "target_runner_id": "runner-test-1",
            "fields": GOOD_FIELDS,
            "criteria": [
                {
                    "key": "C-01",
                    "text": "빠르게 동작한다",
                    "method": "",
                    "summary": "빠르다",
                    "method_summary": "미정",
                }
            ],
        },
    )
    assert response.status_code == 422, response.text


# ------------------------------------------------------------------- AC-2


def test_results_start_unverified_and_a_finished_run_does_not_change_that(
    harness, agreed_case
):
    """AC-2: 기본값은 `unverified` 다. 실행이 끝났다는 사실이 판정을 만들지 않는다."""
    case, _intent = agreed_case
    assert {c["verdict"] for c in harness.criteria(case["id"])} == {"unverified"}

    # 실행을 한 바퀴 돌린다. 정상 완료해도 기준 판정은 그대로다.
    instruction = harness.submit_artifact(case["id"], "로그를 읽고 확인해 주세요")
    created = harness.create_run(
        case["id"], instruction["artifact_id"], "run-analysis-1", purpose="limited_analysis"
    )
    assert created["created"] is True
    harness.agent.poll_once()
    run = harness.client.get("/api/runs/run-analysis-1").json()
    assert run["outcome"] == "completed"

    assert {c["verdict"] for c in harness.criteria(case["id"])} == {"unverified"}


def test_a_verdict_needs_evidence(harness, agreed_case):
    """AC-2: 근거 없는 판정은 기록하지 않는다. 실패도 근거 없이 적지 않는다."""
    case, _intent = agreed_case
    criterion = harness.criteria(case["id"])[0]

    for verdict in ("met", "not_met", "blocked"):
        response = harness.record_result(
            case["id"], criterion["id"], verdict, evidence_kind="none"
        )
        assert response.status_code == 409, (verdict, response.text)
        assert "requires evidence" in response.json()["detail"]

    # `unverified` 로 되돌리는 것만 근거가 필요 없다.
    response = harness.record_result(
        case["id"], criterion["id"], "unverified", evidence_kind="none", summary="되돌림"
    )
    assert response.status_code == 200, response.text


def test_needs_recheck_cannot_be_written_by_hand(harness, agreed_case):
    """AC-2: `needs_recheck` 는 시스템이 전이시키는 값이지 사람이 적는 값이 아니다."""
    case, _intent = agreed_case
    criterion = harness.criteria(case["id"])[0]
    response = harness.record_result(
        case["id"], criterion["id"], "needs_recheck", evidence_kind="human_judgement"
    )
    assert response.status_code == 409
    assert "not recorded directly" in response.json()["detail"]


# ------------------------------------------------------------------- AC-3


@pytest.mark.parametrize("outcome", ["unknown", "failed", "cancelled"])
def test_an_unsettled_run_cannot_prove_a_criterion(harness, agreed_case, outcome):
    """AC-3: **실행 불명이 성공이 되지 않는다.**

    `unknown` 은 정식 값이며 실패로도 성공으로도 바뀌지 않는다. 그 실행을 근거로
    `met` 을 적는 것이 바로 불명을 성공으로 바꾸는 경로이므로 거부한다
    (FR-28, completion-lifecycle 5절).
    """
    case, _intent = agreed_case
    instruction = harness.submit_artifact(case["id"], "확인 요청")
    harness.create_run(
        case["id"], instruction["artifact_id"], "run-x", purpose="limited_analysis"
    )
    run = harness.client.get("/api/runs/run-x").json()
    reported = harness.client.post(
        "/api/runner/runs/run-x/result",
        json={
            "runner_id": "runner-test-1",
            "generation": run["assignment_generation"],
            "outcome": outcome,
        },
    )
    assert reported.status_code == 200, reported.text

    criterion = harness.criteria(case["id"])[0]
    response = harness.record_result(
        case["id"],
        criterion["id"],
        "met",
        evidence_kind="run_output",
        evidence_run_id="run-x",
    )
    assert response.status_code == 409, response.text
    assert f"its outcome is '{outcome}'" in response.json()["detail"]

    # 같은 실행을 근거로 **미충족**을 적는 것은 막지 않는다. 실패를 감추지 않는다.
    allowed = harness.record_result(
        case["id"],
        criterion["id"],
        "not_met",
        evidence_kind="run_output",
        evidence_run_id="run-x",
        summary="실행 결과를 확정할 수 없었다",
    )
    assert allowed.status_code == 200, allowed.text


def test_a_running_run_cannot_prove_a_criterion(harness, agreed_case):
    """AC-3: 아직 끝나지 않은 실행을 근거로 충족을 적지 않는다."""
    case, _intent = agreed_case
    instruction = harness.submit_artifact(case["id"], "확인 요청")
    harness.create_run(
        case["id"], instruction["artifact_id"], "run-y", purpose="limited_analysis"
    )
    criterion = harness.criteria(case["id"])[0]
    response = harness.record_result(
        case["id"],
        criterion["id"],
        "met",
        evidence_kind="run_output",
        evidence_run_id="run-y",
    )
    assert response.status_code == 409
    assert "still pending" in response.json()["detail"]


def test_a_completed_run_can_prove_a_criterion(harness, agreed_case):
    """AC-3의 반대편: 정상 완료한 실행은 근거가 된다. 기준을 막기만 하지 않는다."""
    case, _intent = agreed_case
    instruction = harness.submit_artifact(case["id"], "확인 요청")
    harness.create_run(
        case["id"], instruction["artifact_id"], "run-ok", purpose="limited_analysis"
    )
    harness.agent.poll_once()
    run = harness.client.get("/api/runs/run-ok").json()
    assert run["outcome"] == "completed"

    criterion = harness.criteria(case["id"])[0]
    response = harness.record_result(
        case["id"],
        criterion["id"],
        "met",
        evidence_kind="run_output",
        evidence_run_id="run-ok",
        evidence_artifact_id=run["output_artifact_id"],
        evidence_artifact_rev=run["output_artifact_rev"],
    )
    assert response.status_code == 200, response.text
    recorded = response.json()
    assert recorded["verdict"] == "met"
    # 근거 원문의 참조가 남는다. 본문은 Runner에 있고 화면은 일시중계로 읽는다.
    assert recorded["evidence_artifact_id"] == run["output_artifact_id"]


# ------------------------------------------------------------------- AC-5


def test_a_new_intent_version_does_not_inherit_criteria_or_verdicts(harness, agreed_case):
    """AC-5: 새 의도 버전은 기준과 **영향받은 판정**을 승계하지 않는다.

    게이트와 같은 규칙이다. 승계하면 바뀐 의도에 옛 기준과 옛 판정이 그대로 붙는다.

    **P3-R4에서 "영향받은"이 붙었다.** v0.6 에서는 새 버전이 생기는 순간 모든 판정이
    `needs_recheck` 였다. 그 규칙은 한 항목을 고친 피드백 하나가 **모든 검증을
    무효로 만든다** — intent-artifacts 69행은 그 뒤에 "영향이 없는 기록은 유지한다"를
    함께 요구한다. 그래서 여기서는 **영향을 받는 경우**를 확인하고, 받지 않는 경우는
    `test_progression.py` 가 짝으로 확인한다.

    이 시험에서 C-02 는 새 버전에 없으므로 승계할 대상 자체가 사라졌고, C-01 은
    기대 결과 항목이 바뀌어 옛 판정이 다른 것을 확인한 결과가 된다.
    """
    case, _intent = agreed_case
    criterion = harness.criteria(case["id"])[0]
    assert (
        harness.record_result(
            case["id"], criterion["id"], "met", evidence_kind="human_judgement"
        ).status_code
        == 200
    )

    # v2 를 제출한다. **기준이 가리키는 의도 항목을 바꾸고** 기준 한 건만 남긴다.
    changed = dict(GOOD_FIELDS)
    changed["expected_outcome"] = {
        "text": "ERROR 와 WARN 을 함께 출력",
        "origin": "ai_proposal",
        "change_from_prev": "changed",
    }
    harness.submit_intent_draft(case["id"], changed, criteria=[DEFAULT_CRITERIA[0]])

    current = harness.criteria(case["id"])
    assert [c["criterion_key"] for c in current] == ["C-01"]
    # 새 버전의 기준은 다시 제안이고 판정은 미확인이다.
    assert current[0]["state"] == "proposed"
    assert current[0]["verdict"] == "unverified"

    # 옛 버전의 기준은 지워지지 않는다. 대체됨으로 남고 판정은 재검토 필요가 된다.
    # 목록은 최신 버전이 앞이다. v1 을 찾아 확인한다.
    versions = harness.client.get(f"/api/cases/{case['id']}").json()["intent_versions"]
    old = next(v for v in versions if v["revision"] == 1)
    assert {c["state"] for c in old["criteria"]} == {"superseded"}
    assert {c["verdict"] for c in old["criteria"]} == {"needs_recheck"}


def test_a_superseded_criterion_refuses_new_results(harness, agreed_case):
    """AC-5: 대체된 버전의 기준에 지금 판정을 적지 않는다."""
    case, _intent = agreed_case
    old_criterion = harness.criteria(case["id"])[0]
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)

    response = harness.record_result(
        case["id"], old_criterion["id"], "met", evidence_kind="human_judgement"
    )
    assert response.status_code == 409
    assert "superseded intent version" in response.json()["detail"]
