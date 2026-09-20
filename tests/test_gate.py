"""AC-1~5: QG-01 의도 초안 품질 게이트.

게이트는 평가 보고서가 아니라 **다음 작업이 의존하는 결과를 받아들여도 되는지의
조건**이다(quality-gates.md 권고 요지). 그래서 여기서 확인하는 것은 점수가 아니라
다음 네 가지다.

  규칙 검사와 AI 의미 검토가 **따로** 판정되고, 규칙만 통과한 상태는 통과가 아니다
  AI 의미 검토는 **작성과 별도 세션**이다
  게이트와 사람의 동의는 **별개 기록**이다
  게이트가 실패해도 **열람·질문·피드백은 막히지 않는다**
"""

from __future__ import annotations

GOOD_FIELDS = {
    "goal": {"text": "로그에서 오류 줄만 뽑는다", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전 제외", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 미정", "origin": "ai_assumption"},
}


def _criteria(gate, source=None):
    return {
        f["criterion"] for f in gate["findings"] if source is None or f["source"] == source
    }


def test_rule_check_passes_a_complete_draft_but_the_gate_does_not(harness):
    """AC-1·AC-2: 규칙 검사 통과는 **게이트 통과가 아니다.**

    AI 의미 검토를 실행하지 않았으면 `not_run` 이다. 여기서 승격시키면 QG-01의
    AI 검사 항목을 아무도 보지 않은 채 통과한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)

    gate = harness.gate(case["id"])
    assert gate["rule_verdict"] == "pass"
    assert gate["ai_verdict"] == "not_run"
    assert gate["verdict"] == "not_run"


def test_rule_check_reports_each_violation_with_its_criterion(harness):
    """AC-1: 발견 사항은 기준·필수/권고·차단 효과·확실성과 함께 남는다.

    종합 점수를 만들지 않는다 — 중요한 결함이 사소한 항목으로 상쇄되지 않게.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    # 목표를 비우면 "요청 누락"이다. 검토를 요청할 준비가 된 것이 아니다.
    fields = dict(GOOD_FIELDS)
    fields.pop("goal")
    harness.submit_intent_draft(case["id"], fields)

    gate = harness.gate(case["id"])
    assert gate["rule_verdict"] == "fail"
    assert gate["verdict"] == "fail"
    assert "goal_undecided" in _criteria(gate, "rule")

    finding = next(f for f in gate["findings"] if f["criterion"] == "goal_undecided")
    assert finding["severity"] == "required"
    assert finding["blocking"] == 1
    assert finding["certainty"] == "confirmed"
    assert finding["target"] == "goal"
    assert len(finding["summary"]) <= 200
    # 점수 컬럼이 없다. 판정은 기준별 발견에서 나온다.
    assert "score" not in gate


def test_open_intent_questions_do_not_fail_the_gate(harness):
    """AC-1: **미정 질문이 있는 것은 문제가 아니다.**

    QG-01의 통과 조건은 "질문을 숨기거나 임의로 답하지 않는 것"이다. 질문이 남아
    있다는 사실은 권고로 표시하되 게이트를 막지 않는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        GOOD_FIELDS,
        questions=[
            {
                "key": "case-sensitivity",
                "text": "대소문자를 구분해야 합니까?",
                "summary": "대소문자 구분 여부",
                "decide_at": "intent",
            }
        ],
    )

    gate = harness.gate(case["id"])
    assert gate["rule_verdict"] == "pass"
    advisory = next(
        f for f in gate["findings"] if f["criterion"] == "open_intent_questions_present"
    )
    assert advisory["severity"] == "advisory"
    assert advisory["blocking"] == 0


def test_ai_review_runs_in_a_separate_session_from_the_author(harness):
    """AC-2: 의미 검토는 작성과 별도 세션이다(FR-29).

    두 실행의 세션 식별자가 실제로 다른지 기록으로 확인한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])

    response = harness.ai_gate_review(case["id"], intent)
    assert response.status_code == 201, response.text

    gate = harness.gate(case["id"])
    assert gate["ai_verdict"] == "pass"
    assert gate["verdict"] == "pass"
    assert gate["author_session_ref"] == "fake-session-run-draft-1"
    assert gate["ai_session_ref"] == "fake-session-run-review-1"
    assert gate["author_session_ref"] != gate["ai_session_ref"]

    author = harness.client.get("/api/runs/run-draft-1").json()
    reviewer = harness.client.get("/api/runs/run-review-1").json()
    assert author["role"] == "author"
    assert reviewer["role"] == "reviewer"


def test_a_review_in_the_authoring_session_is_not_accepted_as_a_pass(harness):
    """AC-2: 같은 세션에서 한 검토는 통과로 반영하지 않는다.

    작성자가 자기 판단을 그대로 정당화하는 것을 별도 세션 검토로 세탁하지 않는다
    (quality-gates 4절 A·B·C의 구분).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    # 작성과 검토가 같은 세션 식별자를 쓰도록 만든다.
    harness.agent.cli_executor.fixed_session_ref = "same-session"
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    gate = harness.gate(case["id"])
    assert gate["ai_verdict"] == "hold"
    assert gate["verdict"] == "hold"
    assert "review_session_not_separate" in _criteria(gate, "ai")


def test_ai_cannot_invent_a_new_required_criterion(harness):
    """AC-1: AI의 막연한 의견이 새 필수 요구를 만들지 않는다(quality-gates 3절).

    목록 밖의 기준은 기록하되 권고로 내린다. 내려갔다는 사실도 남는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.agent.cli_executor.review_response = (
        '{"findings": [{"criterion": "style_preference", "severity": "required",'
        ' "certainty": "confirmed", "target": "goal", "summary": "문장이 길다"}]}'
    )
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    gate = harness.gate(case["id"])
    finding = next(f for f in gate["findings"] if f["criterion"] == "style_preference")
    assert finding["severity"] == "advisory"
    assert finding["blocking"] == 0
    assert gate["verdict"] == "pass"


def test_a_suspected_required_violation_holds_instead_of_failing(harness):
    """AC-1: 모호한 발견을 통과로 감추지도, 확정 실패로 과장하지도 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.agent.cli_executor.review_response = (
        '{"findings": [{"criterion": "unverifiable_success_criteria", "severity": "required",'
        ' "certainty": "suspected", "target": "expected_outcome", "summary": "확인 방법이 불분명"}]}'
    )
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    gate = harness.gate(case["id"])
    assert gate["ai_verdict"] == "hold"
    assert gate["verdict"] == "hold"


def test_a_confirmed_required_violation_fails_the_gate(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.agent.cli_executor.review_response = (
        '{"findings": [{"criterion": "request_missing_or_contradictory", "severity": "required",'
        ' "certainty": "confirmed", "target": "scope", "summary": "요청의 절반이 빠졌다"}]}'
    )
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    gate = harness.gate(case["id"])
    assert gate["ai_verdict"] == "fail"
    assert gate["verdict"] == "fail"


def test_a_new_intent_version_forces_a_recheck(harness):
    """AC-4: 새 버전이 생기면 이전 판정을 승계하지 않는다.

    이전 판정은 사라지지 않고 `needs_recheck` 로 남는다 — 대상이 바뀌었으니
    다시 봐야 한다는 사실이 기록이다(quality-gates 3절 "변경으로 재검토 필요").
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"])
    v1 = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], v1)
    assert harness.gate(case["id"])["verdict"] == "pass"

    # 사람이 피드백을 반영한 새 버전을 만든다.
    harness.submit_intent_draft(case["id"], GOOD_FIELDS)

    gate = harness.gate(case["id"])
    assert gate["intent_version_id"] != v1["id"]
    assert gate["verdict"] == "not_run"
    assert gate["ai_verdict"] == "not_run"

    results = harness.client.get(f"/api/cases/{case['id']}/gate-results").json()
    old = next(r for r in results if r["intent_version_id"] == v1["id"])
    assert old["verdict"] == "needs_recheck"
    assert old["superseded_at"] is not None
    # 이전 검토의 근거는 지워지지 않는다.
    assert old["ai_run_id"] == "run-review-1"


def test_the_gate_and_the_human_agreement_are_separate_records(harness):
    """AC-3: 게이트 통과가 동의를 만들지 않고, 동의가 게이트를 통과시키지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)

    # 게이트는 통과했지만 동의는 없다.
    assert harness.gate(case["id"])["verdict"] == "pass"
    assert harness.intent_state(case["id"])["agreement_state"] == "never_agreed"

    # 사람이 원문을 읽고 동의한다.
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    assert harness.intent_state(case["id"])["agreement_state"] == "agreed_current"

    decisions = harness.client.get(f"/api/cases/{case['id']}").json()["decisions"]
    agreements = [d for d in decisions if d["kind"] == "intent_agreement"]
    assert len(agreements) == 1
    # 게이트 판정은 decision 표에 들어가지 않는다. 다른 기록이다.
    assert all(d["kind"] != "quality_gate" for d in decisions)


def test_agreement_is_possible_while_the_gate_fails(harness):
    """AC-5: 게이트 실패가 사람의 접점을 막지 않는다.

    QG-01은 "사람에게 검토를 요청할 준비"를 보는 것이고, 동의는 별도 조건이다.
    게이트 실패는 **실행을 막지 동의를 막지 않는다**(test_admission.py 가 실행 쪽).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.agent.cli_executor.review_response = (
        '{"findings": [{"criterion": "request_missing_or_contradictory", "severity": "required",'
        ' "certainty": "confirmed", "target": "scope", "summary": "범위가 요청과 다르다"}]}'
    )
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    harness.ai_gate_review(case["id"], intent)
    assert harness.gate(case["id"])["verdict"] == "fail"

    # 열람
    content = harness.read_intent_original(intent)
    assert content

    # 피드백
    feedback = harness.submit_feedback(case["id"], intent["id"], "범위를 다시 봐 주세요")
    assert feedback["feedback"]["state"] == "received"

    # 질문 답변
    harness.submit_intent_draft(
        case["id"],
        GOOD_FIELDS,
        questions=[
            {
                "key": "q-open",
                "text": "정말로 읽기만 합니까?",
                "summary": "읽기 전용 여부",
                "decide_at": "intent",
            }
        ],
    )
    latest = harness.latest_intent(case["id"])
    question = latest["questions"][0]
    answered = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={
            "content": "네, 읽기만 합니다.",
            "summary": "읽기 전용 확인",
            "target_runner_id": "runner-test-1",
        },
    )
    assert answered.status_code == 202
