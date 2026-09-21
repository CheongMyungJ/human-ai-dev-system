"""P2-02 — 의도 초안·피드백·명시 동의.

기대값은 구현 코드가 아니라 합의한 요구에서 가져온다.

  FR-03  여섯 항목 초안과 필수 피드백, 최신 의도에 대한 명시 동의.
         "질문 답변·수정 요청·무응답·시간 경과·AI 평가를 전체 의도 동의로 확대하지 않는다"
  FR-04  사실·요구·가정·결정의 구분과 출처
  FR-13  구체적인 사람 판단 요청과 결정 시점 추적
  FR-23  승인 대상의 버전 고정. "승인 후 대상이 바뀌면 이전 승인으로 실행하지 않는다"
  intent-artifacts 1절 "정보가 없으면 항목을 삭제하거나 AI가 채우지 않고 미정으로 남긴다"

여기서 확인하는 거절은 **동의를 기록할 수 있는가**의 조건이다.
실행 배정을 여는 FR-29 진입 조건 검사는 P2-03이며 이 파일의 대상이 아니다.
"""

from __future__ import annotations

from domain.models import (
    AgreementRefusal,
    ConfirmationState,
    ContentOrigin,
    FeedbackState,
    FieldChange,
    IntentAgreementState,
    IntentField,
    IntentStatus,
    QuestionState,
    ReadRequestState,
)

SIX = {f.value for f in IntentField}


def _required(harness, case_id: str) -> set[str]:
    """그 Case 가 가져야 하는 의도 항목(P3-R1).

    **여섯으로 고정하지 않는다.** v0.7에서 필수 항목은 Case 의 Profile 이 정하며
    (D-62), 이 시험이 보려는 것은 "정보가 없는 항목을 지우지도 채우지도 않는다"이지
    항목의 개수가 여섯이라는 사실이 아니다. Profile 이 기록되지 않은 Case 의 필수
    항목이 여섯 그대로임은 `test_a_pre_r1_case_keeps_the_six_field_form` 이 본다.
    """
    policy = harness.client.get(f"/api/cases/{case_id}/policy").json()
    return set(policy["profile"]["required_fields"])


def _draft_fields(**overrides: dict) -> dict:
    """대표적인 초안 입력. 지정하지 않은 항목은 **비워 둔다.**"""
    fields = {
        "goal": {
            "text": "관리 화면의 데이터를 CSV로 얻을 수 있게 한다.",
            "state": ConfirmationState.PROPOSED.value,
            "origin": ContentOrigin.USER_REQUIREMENT.value,
        },
        "expected_outcome": {
            "text": "사용자가 내보내기를 요청하고 CSV 파일을 받는다.",
            "state": ConfirmationState.PROPOSED.value,
            "origin": ContentOrigin.AI_PROPOSAL.value,
        },
        "scope": {
            "text": "관리 화면 데이터의 CSV 내보내기.",
            "state": ConfirmationState.PROPOSED.value,
            "origin": ContentOrigin.USER_REQUIREMENT.value,
        },
    }
    fields.update(overrides)
    return fields


def test_all_required_fields_exist_and_missing_information_stays_undecided(harness):
    """AC-1 — 필수 항목이 모두 존재하고 빈 항목은 미정으로 남는다.

    정보가 없는 항목을 지우지도, 채우지도 않는다(intent-artifacts 1절).

    **P3-R1에서 기대값이 바뀌었다.** "여섯"이 아니라 "그 Case 의 Profile 이 요구하는
    항목 전부"다(D-62). 규칙 자체는 그대로다 — 빈 항목을 지우지 않는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_fields())

    intent = harness.latest_intent(case["id"])
    by_field = {f["field"]: f for f in intent["fields"]}
    required = _required(harness, case["id"])
    assert set(by_field) == required, "필수 항목이 모두 행으로 있어야 한다"
    assert SIX < required, "공통 여섯 항목 위에 Profile 의미 항목이 얹힌다"

    # 입력한 항목: 제안됨 + 출처가 구별된다(FR-04)
    assert by_field["goal"]["state"] == ConfirmationState.PROPOSED.value
    assert by_field["goal"]["origin"] == ContentOrigin.USER_REQUIREMENT.value
    assert by_field["expected_outcome"]["origin"] == ContentOrigin.AI_PROPOSAL.value

    # 입력하지 않은 항목: 미정이며 출처도 없다. 시스템이 값을 지어내지 않았다.
    for field in ("exclusions", "constraints", "open_questions"):
        assert by_field[field]["state"] == ConfirmationState.UNDECIDED.value
        assert by_field[field]["origin"] == ContentOrigin.NONE.value

    # 첫 버전이므로 비교 대상이 없다.
    assert {f["change_from_prev"] for f in intent["fields"]} == {FieldChange.INITIAL.value}


def test_content_with_no_origin_is_refused(harness):
    """내용이 있는데 출처가 '없음'이면 거부한다(FR-04).

    AI 추정을 확정 요구로 표시하지 않는 것과 같은 이유로, 출처 없는 내용을
    기록하지 않는다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.post(
        f"/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "출처 없는 초안",
            "target_runner_id": "runner-test-1",
            "fields": {
                "goal": {"text": "무언가", "origin": ContentOrigin.NONE.value},
            },
        },
    )
    assert response.status_code == 400
    assert "origin" in response.json()["detail"]


def test_original_is_readable_through_the_temporary_relay(harness):
    """AC-2 — 사람이 초안 원문을 실제로 읽을 수 있다.

    본문은 소유 Runner에서 오고 제어부는 메모리에서만 취급한다.
    한 번 받아 가면 버퍼에서 버린다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    accepted = harness.submit_intent_draft(case["id"], _draft_fields())

    request, content = harness.read_original(accepted["artifact_id"], accepted["revision"])
    assert request["state"] == ReadRequestState.DELIVERED.value
    assert content is not None
    assert "관리 화면의 데이터를 CSV로" in content
    # 중계 버퍼에 남지 않는다.
    assert harness.client.get("/api/health").json()["relay_buffered"] == 0

    # 같은 요청으로 다시 받아 갈 수 없다. 필요하면 새로 요청한다.
    again = harness.client.get(f"/api/read-requests/{request['id']}").json()
    assert again["content"] is None
    assert again["request"]["state"] == ReadRequestState.DELIVERED.value


def test_original_stays_pending_while_the_runner_does_not_answer(harness):
    """AC-2 — Runner에 닿지 못하면 '연결 필요'로 남는다.

    빈 문서나 삭제로 표시하지 않는다(data-boundary-review 3절).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    accepted = harness.submit_intent_draft(case["id"], _draft_fields())

    request, content = harness.read_original(
        accepted["artifact_id"], accepted["revision"], serve=False
    )
    assert request["state"] == ReadRequestState.PENDING.value
    assert content is None
    assert request["content_hash"] is None


def test_feedback_creates_a_new_version_with_a_field_level_diff(harness):
    """AC-3 — 피드백을 반영한 새 버전에서 바뀐 항목과 남은 질문이 함께 제시된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_fields())
    v1 = harness.latest_intent(case["id"])

    wanted = harness.submit_feedback(
        case["id"], v1["id"], "제외사항을 분명히 해 주세요. 예약 내보내기는 빼죠.", "제외사항 요청"
    )
    ignored = harness.submit_feedback(
        case["id"], v1["id"], "글꼴도 바꿔 주세요.", "이번 범위 밖 요청"
    )

    # 피드백만으로는 아직 아무 것도 반영되지 않았다.
    assert wanted["feedback"]["state"] == FeedbackState.RECEIVED.value

    fields = _draft_fields(
        exclusions={
            "text": "예약 내보내기·다른 파일 형식은 이번에 다루지 않는다.",
            "state": ConfirmationState.PROPOSED.value,
            "origin": ContentOrigin.USER_REQUIREMENT.value,
        }
    )
    harness.submit_intent_draft(
        case["id"],
        fields,
        summary="의도 초안 v2",
        reflects_feedback=[wanted["feedback"]["id"]],
        not_reflected={ignored["feedback"]["id"]: "이번 의도 범위 밖이라 새 Case로 분리한다"},
    )
    v2 = harness.latest_intent(case["id"])
    assert v2["revision"] == 2

    diff = harness.client.get(
        f"/api/cases/{case['id']}/intent-versions/{v2['id']}/diff"
    ).json()
    assert diff["compared_with_revision"] == 1
    assert diff["changed_fields"] == ["exclusions"], diff["changed_fields"]
    # 전체 본문 차이는 제어부에 없다. 원문을 열람해 비교한다.
    assert diff["full_text_diff"] == "not_on_controller"

    by_id = {f["id"]: f for f in harness.client.get(f"/api/cases/{case['id']}/feedback").json()}
    assert by_id[wanted["feedback"]["id"]]["state"] == FeedbackState.REFLECTED.value
    assert by_id[wanted["feedback"]["id"]]["reflected_in_version_id"] == v2["id"]
    # 반영하지 않은 피드백은 이유와 함께 남는다. 조용히 닫지 않는다.
    assert by_id[ignored["feedback"]["id"]]["state"] == FeedbackState.NOT_REFLECTED.value
    assert by_id[ignored["feedback"]["id"]]["disposition_note"]


def test_viewing_feedback_and_answering_do_not_create_agreement(harness):
    """AC-4 — 조회·피드백·질문 답변·무응답은 동의가 되지 않는다(FR-03)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    accepted = harness.submit_intent_draft(
        case["id"],
        _draft_fields(),
        questions=[
            {
                "key": "row-scope",
                "text": "현재 필터 전체·현재 페이지·선택한 행 중 무엇을 내보내야 하는가?",
                "summary": "내보낼 행 범위",
                "decide_at": "intent",
            }
        ],
    )
    intent = harness.latest_intent(case["id"])

    # (1) 원문을 실제로 받아 본다 — 전달이 열람 기록을 만든다
    _request, content = harness.read_original(accepted["artifact_id"], accepted["revision"])
    assert content is not None
    assert len(harness.intent_state(case["id"])["views"]) == 1

    # (2) 피드백을 준다
    harness.submit_feedback(case["id"], intent["id"], "행 범위는 현재 필터 전체로 합시다.")

    # (3) 질문에 답한다
    question = harness.latest_intent(case["id"])["questions"][0]
    answered = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={
            "content": "현재 필터에 맞는 전체 결과를 내보낸다.",
            "summary": "행 범위 답변",
            "target_runner_id": "runner-test-1",
        },
    )
    assert answered.status_code == 202
    assert answered.json()["question"]["state"] == QuestionState.ANSWERED.value

    # (4) 그리고 아무 것도 더 하지 않는다 — 무응답
    state = harness.intent_state(case["id"])
    assert state["agreement_state"] == IntentAgreementState.NEVER_AGREED.value
    assert state["agreed_version"] is None

    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    agreements = [d for d in detail["decisions"] if d["kind"] == "intent_agreement"]
    assert agreements == [], "조회·피드백·질문 답변이 동의 기록을 만들었다"
    assert detail["intent_versions"][0]["status"] == IntentStatus.DRAFT.value


def test_explicit_agreement_records_the_version_and_the_content_hash(harness):
    """AC-5 — 명시 동의는 대상 버전·원문 해시·행위자와 함께 기록된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_fields())
    intent = harness.latest_intent(case["id"])

    # 명시 표시가 없으면 동의가 아니다.
    refused = harness.agree(case["id"], intent, agree=False)
    assert refused.status_code == 400
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.NOT_EXPLICIT.value

    # 문구만 비어 있어도 동의가 아니다.
    refused = harness.agree(case["id"], intent, statement="   ")
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.NOT_EXPLICIT.value

    # 원문을 받아 보지 않은 채로는 동의할 수 없다. 요약만 보고 동의하지 않는다.
    refused = harness.agree(case["id"], intent)
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.ORIGINAL_NOT_READ.value

    harness.read_intent_original(intent)
    agreed = harness.agree(case["id"], intent)
    assert agreed.status_code == 201, agreed.text
    decision = agreed.json()["decision"]
    assert decision["kind"] == "intent_agreement"
    assert decision["subject_id"] == intent["id"]
    assert decision["subject_revision"] == intent["revision"]
    assert decision["subject_content_hash"] == intent["content_hash"]
    assert decision["actor"] == "owner"

    state = harness.intent_state(case["id"])
    assert state["agreement_state"] == IntentAgreementState.AGREED_CURRENT.value

    # 동의한 버전에서 내용이 있는 항목만 '사용자 확인됨'이 된다.
    fields = {f["field"]: f for f in harness.latest_intent(case["id"])["fields"]}
    assert fields["goal"]["state"] == ConfirmationState.USER_CONFIRMED.value
    assert fields["constraints"]["state"] == ConfirmationState.UNDECIDED.value


def test_old_agreement_does_not_carry_to_a_newer_version(harness):
    """AC-6 — 오래된 의도 동의가 최신 버전에 적용되지 않는다(FR-23)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_fields())
    v1 = harness.latest_intent(case["id"])
    harness.read_intent_original(v1)
    assert harness.agree(case["id"], v1).status_code == 201

    harness.submit_intent_draft(
        case["id"],
        _draft_fields(
            constraints={
                "text": "개인정보 필드는 제외한다.",
                "state": ConfirmationState.PROPOSED.value,
                "origin": ContentOrigin.PROJECT_RULE.value,
            }
        ),
        summary="의도 초안 v2",
    )
    v2 = harness.latest_intent(case["id"])
    assert v2["revision"] == 2
    assert v2["status"] == IntentStatus.DRAFT.value

    state = harness.intent_state(case["id"])
    assert state["agreement_state"] == IntentAgreementState.STALE_AGREEMENT.value
    assert state["agreed_version"]["subject_id"] == v1["id"]

    # v1의 동의 기록 자체는 보존된다.
    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    agreements = [d for d in detail["decisions"] if d["kind"] == "intent_agreement"]
    assert len(agreements) == 1 and agreements[0]["subject_id"] == v1["id"]

    # 이제 v1에 다시 동의할 수 없다.
    refused = harness.agree(case["id"], v1)
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.NOT_LATEST_VERSION.value


def test_agreement_waits_when_the_original_cannot_be_read(harness):
    """AC-7 — 원문을 확인할 수 없으면 동의를 기록하지 않는다.

    data-boundary-review 3절: "정확한 원본과 현재 버전의 확인이 필요한 행위는
    확인 가능한 자료가 없으면 대기한다."
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    accepted = harness.submit_intent_draft(case["id"], _draft_fields(), persist=False)
    intent = accepted["intent_version"]
    intent["content_hash"] = accepted["content_hash"]

    refused = harness.agree(case["id"], intent)
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.ORIGINAL_NOT_AVAILABLE.value

    # Runner가 저장을 마치고 사람이 원문을 받아 보면 같은 동의가 기록된다.
    harness.agent.persist_pending_intakes()
    persisted = harness.latest_intent(case["id"])
    harness.read_intent_original(persisted)
    assert harness.agree(case["id"], persisted).status_code == 201


def test_agreement_is_refused_when_the_read_content_no_longer_matches(harness):
    """AC-7 — 사람이 읽은 원문과 현재 원문이 다르면 거절한다(FR-23)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_fields())
    intent = harness.latest_intent(case["id"])

    refused = harness.agree(case["id"], intent, content_hash="sha256:" + "0" * 64)
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.CONTENT_CHANGED.value


def test_open_intent_stage_question_blocks_agreement_but_deferred_one_does_not(harness):
    """AC-7 — 의도 단계 질문은 동의를 막고, 이월한 질문은 막지 않는다.

    intent-artifacts 2절: "의도 단계의 결정을 미해결로 둔 채 AI가 대신 확정하지 않는다."
    설계·계획으로 이월한 질문은 그 단계의 작업 전에 해결한다(FR-03 질문 처리).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        _draft_fields(),
        questions=[
            {
                "key": "row-scope",
                "text": "어느 행 집합을 내보내야 하는가?",
                "summary": "내보낼 행 범위",
                "decide_at": "intent",
            },
            {
                "key": "perf-env",
                "text": "성능 측정 환경은 무엇으로 하는가?",
                "summary": "성능 측정 환경",
                "decide_at": "design",
                "blocks": ["design-task-perf"],
            },
        ],
    )
    intent = harness.latest_intent(case["id"])

    refused = harness.agree(case["id"], intent)
    assert refused.status_code == 409
    detail = refused.json()["detail"]
    assert detail["refusal"] == AgreementRefusal.OPEN_INTENT_QUESTIONS.value
    assert "row-scope" in detail["message"]
    assert "perf-env" not in detail["message"], "이월한 질문이 동의를 막아서는 안 된다"

    # 열람·피드백은 미정 질문이 있어도 막히지 않는다(FR-03 수용 기준).
    assert harness.submit_feedback(case["id"], intent["id"], "행 범위는 필터 전체로.")

    by_key = {q["question_key"]: q for q in intent["questions"]}
    harness.client.post(
        f"/api/cases/{case['id']}/questions/{by_key['row-scope']['id']}/answer",
        json={
            "content": "현재 필터 전체를 내보낸다.",
            "summary": "행 범위 답변",
            "target_runner_id": "runner-test-1",
        },
    )

    # 의도 단계 질문이 닫혔으므로 이제 동의를 기록할 수 있다.
    # 이월한 design 질문은 여전히 열려 있지만 동의를 막지 않는다.
    current = harness.latest_intent(case["id"])
    harness.read_intent_original(current)
    agreed = harness.agree(case["id"], current)
    assert agreed.status_code == 201, agreed.text
    state = harness.intent_state(case["id"])
    assert state["agreement_state"] == IntentAgreementState.AGREED_CURRENT.value
    assert [q["question_key"] for q in state["open_intent_questions"]] == []
    still_open = [
        q for q in harness.latest_intent(case["id"])["questions"] if q["state"] == "open"
    ]
    assert [q["question_key"] for q in still_open] == ["perf-env"]


def test_a_small_feature_still_goes_through_the_whole_flow(harness):
    """AC-8 — 작은 기능도 초안·피드백·동의를 건너뛰지 않는다(FR-03 수용 기준)."""
    project = harness.create_project()
    case = harness.create_case(project["id"], title="버튼 문구 한 줄 바꾸기")

    # 초안이 없으면 동의할 대상 자체가 없다.
    assert harness.intent_state(case["id"])["agreement_state"] == (
        IntentAgreementState.NO_INTENT.value
    )
    missing = harness.client.post(
        f"/api/cases/{case['id']}/intent-versions/none-at-all/agreement",
        json={"agree": True, "statement": "동의", "content_hash": "sha256:0"},
    )
    assert missing.status_code == 404

    harness.submit_intent_draft(
        case["id"],
        {
            "goal": {
                "text": "저장 버튼 문구를 '저장'에서 '변경 저장'으로 바꾼다.",
                "state": ConfirmationState.PROPOSED.value,
                "origin": ContentOrigin.USER_REQUIREMENT.value,
            }
        },
        summary="작은 기능 초안",
    )
    intent = harness.latest_intent(case["id"])
    assert set(f["field"] for f in intent["fields"]) == _required(
        harness, case["id"]
    ), "작은 기능이라고 항목을 줄이지 않는다"

    harness.submit_feedback(case["id"], intent["id"], "'저장'이 더 낫습니다. 그대로 둡시다.")
    assert harness.intent_state(case["id"])["agreement_state"] == (
        IntentAgreementState.NEVER_AGREED.value
    )

    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    assert harness.intent_state(case["id"])["agreement_state"] == (
        IntentAgreementState.AGREED_CURRENT.value
    )


def test_structure_report_must_carry_all_required_fields(harness):
    """필수 항목 중 일부만 보고하는 구조는 거부한다.

    "정보가 없으면 항목을 삭제한다"가 아니라 미정으로 남기는 것이 규칙이므로,
    항목이 빠진 보고를 받아들이면 그 규칙이 조용히 무너진다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_fields())
    intent = harness.latest_intent(case["id"])

    response = harness.client.post(
        "/api/runner/intent-structure",
        json={
            "runner_id": "runner-test-1",
            "intent_version_id": intent["id"],
            "fields": [
                {
                    "field": "goal",
                    "state": ConfirmationState.PROPOSED.value,
                    "origin": ContentOrigin.USER_REQUIREMENT.value,
                    "change_from_prev": FieldChange.INITIAL.value,
                }
            ],
            "questions": [],
        },
    )
    assert response.status_code == 409
    assert "required fields" in response.json()["detail"]


def test_knowing_the_hash_is_not_reading_the_original(harness):
    """AC-7 — 요약과 해시만 알고는 동의할 수 없다.

    intent-artifacts 5절: "요약만 읽은 상태를 상세 원문에 대한 확인으로 기록하지 않는다."
    열람 기록은 **원문이 실제로 전달된 순간에만** 생기므로 호출자가 지어낼 수 없다.
    화면을 거치지 않고 API를 직접 불러도 같다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], _draft_fields())

    # 상태 조회만으로 해시를 알 수 있다. 그것으로는 부족하다.
    intent = harness.latest_intent(case["id"])
    assert intent["content_hash"]
    refused = harness.agree(case["id"], intent)
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.ORIGINAL_NOT_READ.value
    assert harness.intent_state(case["id"])["views"] == []

    # 다른 사람이 읽은 것도 이 사람의 확인이 되지 않는다.
    created = harness.client.post(
        f"/api/artifacts/{intent['artifact_id']}/{intent['artifact_rev']}/read-requests",
        json={"requested_by": "somebody-else"},
    ).json()
    harness.agent.serve_read_requests()
    assert harness.client.get(f"/api/read-requests/{created['id']}").json()["content"]
    refused = harness.agree(case["id"], intent)
    assert refused.json()["detail"]["refusal"] == AgreementRefusal.ORIGINAL_NOT_READ.value

    # 본인이 받아 보면 기록되고, 그때 동의할 수 있다.
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
