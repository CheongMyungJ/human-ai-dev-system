"""AC-1: 제어부·DB·Runner가 실제로 한 줄로 연결되는지.

mock 응답이 아니라 SQLite 행과 Runner 로컬 파일로 확인한다.
"""

from __future__ import annotations

import sqlite3

from domain.models import Availability, CaseStatus, DecisionKind, IntentStatus


def test_end_to_end_case_to_run_result(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])

    instruction = harness.submit_artifact(case["id"], "파일 두 개를 읽고 요약해줘.\n두 번째 줄.")
    created = harness.create_run(case["id"], instruction["artifact_id"], "run-flow-1")
    assert created["created"] is True
    assert created["run"]["status"] == "pending"

    result = harness.agent.poll_once()
    assert [a["action"] for a in result["assignments"]] == ["executed"]

    run = harness.client.get("/api/runs/run-flow-1").json()
    assert run["status"] == "finished"
    assert run["outcome"] == "completed"
    # 사용량을 제공하지 않는 실행기다. 0이 아니라 not_reported 로 남아야 한다.
    assert run["usage"] == "not_reported"
    assert run["output_artifact_id"]
    # 정규화 이벤트가 P1 계약의 종류로 올라왔는지.
    assert [e["type"] for e in run["events"]] == [
        "run_started",
        "tool_call_started",
        "tool_call_finished",
        "assistant_message",
        "run_finished",
    ]

    # 출력 원문은 Runner 로컬에 있고 제어부에는 참조만 있다.
    body = harness.agent.store.get(run["output_artifact_id"], run["output_artifact_rev"])
    assert b"run_id=run-flow-1" in body

    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    kinds = {a["kind"]: a for a in detail["artifacts"]}
    assert kinds["instruction"]["availability"] == Availability.AVAILABLE.value
    assert kinds["run_output"]["availability"] == Availability.AVAILABLE.value
    assert len(detail["runs"]) == 1

    # DB에도 실제로 들어갔는지 직접 확인한다(API 응답만 믿지 않는다).
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM run WHERE run_id = 'run-flow-1'").fetchone()
    assert row["outcome"] == "completed"
    assert row["assignment_generation"] == 1
    conn.close()


def test_intent_version_and_agreement_are_separate_records(harness):
    """의도 버전과 사람의 동의는 별개 기록이다(FR-23).

    P2-02에서 동의는 전용 경로에서만 만들어진다. 이 시험은 그 경로를 거친 뒤에도
    두 기록이 서로 독립이고, 새 버전이 이전 동의를 승계하지 않음을 확인한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        {"goal": {"text": "목표: ...", "state": "proposed", "origin": "user_requirement"}},
        summary="의도 초안 v1",
    )
    intent = harness.latest_intent(case["id"])
    assert intent["status"] == IntentStatus.DRAFT.value

    harness.read_intent_original(intent)
    decision = harness.agree(case["id"], intent).json()["decision"]
    assert decision["kind"] == "intent_agreement"

    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    assert detail["intent_versions"][0]["status"] == IntentStatus.AGREED.value

    # 새 의도 버전이 생기면 이전 동의가 새 버전으로 승계되지 않는다.
    harness.submit_intent_draft(
        case["id"],
        {"goal": {"text": "목표: 바뀜", "state": "proposed", "origin": "user_requirement"}},
        summary="의도 초안 v2",
    )
    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    by_rev = {iv["revision"]: iv for iv in detail["intent_versions"]}
    assert by_rev[2]["status"] == IntentStatus.DRAFT.value
    assert by_rev[1]["status"] == IntentStatus.SUPERSEDED.value
    # 동의 기록 자체는 지우지 않는다. 대상 버전에 묶여 보존된다.
    assert len(detail["decisions"]) == 1
    assert detail["decisions"][0]["subject_id"] == intent["id"]


def test_the_generic_decision_endpoint_cannot_record_an_intent_agreement(harness):
    """의도 동의로 가는 두 번째 입구를 만들지 않는다.

    일반 결정 경로로 intent_agreement 를 넣을 수 있으면 최신 버전·원문 확인·열람
    기록·미해결 질문 검사를 통째로 건너뛴다. 화면에서 버튼을 없애는 것만으로는
    부족하므로 서버가 거절한다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        {"goal": {"text": "목표", "state": "proposed", "origin": "user_requirement"}},
    )
    intent = harness.latest_intent(case["id"])

    refused = harness.client.post(
        f"/api/cases/{case['id']}/decisions",
        json={
            "kind": DecisionKind.INTENT_AGREEMENT.value,
            "subject_type": "intent_version",
            "subject_id": intent["id"],
            "subject_revision": intent["revision"],
            "actor": "owner",
        },
    )
    assert refused.status_code == 409
    assert "intent-versions" in refused.json()["detail"]

    # 상태도 바뀌지 않았다.
    assert harness.latest_intent(case["id"])["status"] == IntentStatus.DRAFT.value
    assert harness.intent_state(case["id"])["agreement_state"] == "never_agreed"

    # 다른 종류의 결정은 이 경로로 계속 기록된다.
    other = harness.client.post(
        f"/api/cases/{case['id']}/decisions",
        json={
            "kind": DecisionKind.DESIGN_REVIEW.value,
            "subject_type": "case",
            "subject_id": case["id"],
            "subject_revision": 1,
            "actor": "owner",
        },
    )
    assert other.status_code == 201


def test_run_is_refused_when_instruction_is_not_persisted(harness):
    """Runner가 읽을 수 없는 지시로는 실행을 배정하지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    accepted = harness.client.post(
        f"/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "아직 Runner가 저장하지 않은 지시",
            "summary": "지시",
            "target_runner_id": "runner-test-1",
        },
    ).json()
    # 일부러 persist_pending_intakes() 를 부르지 않는다 → pending 상태

    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={"run_id": "run-not-ready", "instruction_artifact_id": accepted["artifact_id"]},
    )
    assert response.status_code == 409
    assert "pending" in response.json()["detail"]


def test_capabilities_are_reported_without_promoting_cli_support(harness):
    """P2-01 실행기는 코딩 CLI가 아니다. CLI 능력을 verified 로 올리지 않는다."""
    runners = harness.client.get("/api/runners").json()
    assert len(runners) == 1
    caps = {c["capability"]: c["state"] for c in runners[0]["capabilities"]}
    assert caps["safe_stop_next_call"] == "unsupported"
    assert caps["session_identity"] == "unsupported"
    assert set(caps.values()) <= {"doc_only", "verified", "unsupported", "unknown"}


def test_case_starts_in_received_state(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    assert case["status"] == CaseStatus.RECEIVED.value
