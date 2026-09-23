"""UI-03 AC-8 — 기존 접수 네 경로도 본문을 **기록보다 먼저** 중계한다.

UI-01 은 새 메시지 경로만 이 순서로 바꿨다. `/artifacts`·`/intent-drafts`·`/feedback`·
`/questions/{id}/answer` 는 접수를 커밋한 **뒤에** 본문을 중계 버퍼에 넣어서, 그 사이에 Runner
가 폴링하면 본문 없는 접수가 `lost_before_persist` 로 표시됐다(DEVELOPMENT.md 9절). 여기서는
커밋 직후의 순간을 붙잡아 그때 이미 버퍼에 본문이 있는지 보고(UI-01 의 메시지 경로 시험과 같은
방법), 거부된 입력이 버퍼에 남지 않는지 본다.
"""

from __future__ import annotations

from typing import Any

import pytest

from controller.repository import Repository
from tests.conftest import RUNNER_ID
from tests.test_conversation import _case_with_question
from tests.test_intent import _draft_fields


def _buffered(harness) -> int:
    return harness.client.get("/api/health").json()["relay_buffered"]


def _submit(harness, path: str) -> str:
    """경로 하나로 원문을 접수하고 접수 식별자를 돌려준다(아직 저장 전)."""
    if path == "artifacts":
        project = harness.create_project()
        case = harness.create_case(project["id"])
        response = harness.client.post(
            f"/api/cases/{case['id']}/artifacts",
            json={
                "kind": "instruction",
                "content": "지시 원문",
                "summary": "지시",
                "target_runner_id": RUNNER_ID,
            },
        )
        assert response.status_code == 202, response.text
        return response.json()["intake_id"]
    if path == "intent-drafts":
        project = harness.create_project()
        case = harness.create_case(project["id"])
        return harness.submit_intent_draft(case["id"], _draft_fields(), persist=False)["intake_id"]
    if path == "feedback":
        project = harness.create_project()
        case = harness.create_case(project["id"])
        harness.submit_intent_draft(case["id"], _draft_fields())
        intent = harness.latest_intent(case["id"])
        return harness.submit_feedback(case["id"], intent["id"], "고쳐 주세요", persist=False)[
            "intake_id"
        ]
    _project, case, _intent, question = _case_with_question(harness)
    response = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={"content": "빼 주세요", "summary": "답", "target_runner_id": RUNNER_ID},
    )
    assert response.status_code == 202, response.text
    return response.json()["intake_id"]


@pytest.mark.parametrize("path", ["artifacts", "intent-drafts", "feedback", "answer"])
def test_the_body_is_relayed_before_the_intake_is_committed(harness, monkeypatch, path):
    """AC-8 — 커밋된 순간 본문은 이미 버퍼에 있고, 그때 폴링해도 유실되지 않는다."""
    relay = harness.client.app.state.relay
    seen: list[dict[str, Any]] = []
    original = Repository.open_intake

    def spy(self, *args, **kwargs):
        intake = original(self, *args, **kwargs)
        seen.append(
            {"state": intake["state"], "body_ready": relay.get(intake["id"]) is not None}
        )
        return intake

    monkeypatch.setattr(Repository, "open_intake", spy)
    intake_id = _submit(harness, path)
    # 준비 단계의 다른 접수(예: 의도 초안)가 앞에 있을 수 있다 — 마지막이 이 경로다.
    assert seen[-1] == {"state": "pending", "body_ready": True}
    harness.agent.persist_pending_intakes()
    assert harness.client.get(f"/api/intakes/{intake_id}").json()["state"] == "stored"
    assert relay.get(intake_id) is None  # 저장되면 버퍼에서 버린다


def test_a_refused_intake_leaves_nothing_in_the_relay(harness):
    """AC-8 — 기록 전후 어디서 거부되든 본문이 버퍼에 남지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    before = _buffered(harness)

    # 기록 단계에서 거부(모르는 PC).
    unknown_runner = harness.client.post(
        f"/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "지시",
            "summary": "지시",
            "target_runner_id": "runner-nope",
        },
    )
    assert unknown_runner.status_code == 404
    assert _buffered(harness) == before

    # 접수는 기록됐지만 뒤 단계에서 거부(없는 의도 버전에 대한 피드백).
    wrong_target = harness.client.post(
        f"/api/cases/{case['id']}/feedback",
        json={
            "target_intent_version_id": "intent-nope",
            "content": "피드백",
            "summary": "피드백",
            "target_runner_id": RUNNER_ID,
        },
    )
    assert wrong_target.status_code in (404, 409), wrong_target.text
    assert _buffered(harness) == before
