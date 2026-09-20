"""AC-3·AC-4·AC-5 — P1에서 이월한 '중복 호출 방지'를 실제 부수효과로 확인한다.

판정 근거는 로그 문장이 아니라 executor가 파일에 남기는 실행 줄 수다.
실행되지 않으면 그 줄도 없다.
"""

from __future__ import annotations

import sqlite3

import httpx
import pytest


def _run_rows(harness, run_id: str) -> int:
    conn = sqlite3.connect(harness.controller_config.db_path)
    count = conn.execute("SELECT COUNT(*) FROM run WHERE run_id = ?", (run_id,)).fetchone()[0]
    conn.close()
    return count


def test_same_run_id_resent_to_the_api_creates_one_run(harness):
    """(가) 제어 API 층: 같은 run_id 의 POST 재전송."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")

    body = {"run_id": "run-dup-1", "instruction_artifact_id": art["artifact_id"]}
    first_response = harness.client.post(f"/api/cases/{case['id']}/runs", json=body)
    second_response = harness.client.post(f"/api/cases/{case['id']}/runs", json=body)
    first, second = first_response.json(), second_response.json()

    # 만들지 않은 것을 201 Created 로 보고하지 않는다.
    assert first_response.status_code == 201
    assert second_response.status_code == 200
    assert first["created"] is True
    assert second["created"] is False
    assert first["run"]["run_id"] == second["run"]["run_id"]
    assert _run_rows(harness, "run-dup-1") == 1

    harness.agent.poll_once()
    harness.agent.poll_once()  # 두 번 더 돌려도 새 배정이 없다

    assert harness.effect_count(case["id"]) == 1
    run = harness.client.get("/api/runs/run-dup-1").json()
    assert run["status"] == "finished"
    assert run["assignment_generation"] == 1


def test_lost_result_response_does_not_cause_re_execution(harness, monkeypatch):
    """(나) 결과 보고가 유실되고 제어부가 같은 run_id 를 다시 배정한 경우.

    이것이 P1에서 넘어온 '지연 이벤트·응답 유실에서 중복 호출하지 않음'의 실제 상황이다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-lost-1")

    original_send_result = harness.agent.client.send_result
    calls = {"n": 0}

    def failing_send_result(run_id: str, payload: dict):
        calls["n"] += 1
        raise httpx.TransportError("injected: result response lost")

    monkeypatch.setattr(harness.agent.client, "send_result", failing_send_result)

    with pytest.raises(httpx.TransportError):
        harness.agent.poll_once()

    # 실행은 실제로 일어났다.
    assert harness.effect_count(case["id"]) == 1
    # 제어부는 결과를 받지 못했으므로 아직 완료가 아니다.
    run = harness.client.get("/api/runs/run-lost-1").json()
    assert run["status"] != "finished"
    assert run["outcome"] is None

    # 제어부가 같은 run_id 를 다시 배정한다.
    monkeypatch.setattr(harness.agent.client, "send_result", original_send_result)
    harness.client.post("/api/runs/run-lost-1/reassign")
    actions = harness.agent.poll_once()["assignments"]

    assert [a["action"] for a in actions] == ["replayed_stored_result"]
    # **핵심**: 실행 부수효과는 여전히 1회다.
    assert harness.effect_count(case["id"]) == 1

    run = harness.client.get("/api/runs/run-lost-1").json()
    assert run["status"] == "finished"
    assert run["outcome"] == "completed"
    assert run["assignment_generation"] == 2


def test_stale_generation_report_is_rejected_and_state_untouched(harness):
    """AC-4: 오래된 세대의 보고가 최신 상태를 덮어쓰지 않는다(NFR-03)."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-fence-1")

    harness.client.post(f"/api/runner/{harness.runner_config.runner_id}/assignments")
    reassigned = harness.client.post("/api/runs/run-fence-1/reassign").json()
    assert reassigned["assignment_generation"] == 2

    stale = harness.client.post(
        "/api/runner/runs/run-fence-1/result",
        json={
            "runner_id": harness.runner_config.runner_id,
            "generation": 1,
            "outcome": "completed",
        },
    )
    assert stale.status_code == 409
    assert "stale assignment generation" in stale.json()["detail"]

    run = harness.client.get("/api/runs/run-fence-1").json()
    assert run["status"] != "finished"
    assert run["outcome"] is None

    stale_events = harness.client.post(
        "/api/runner/runs/run-fence-1/events",
        json={
            "runner_id": harness.runner_config.runner_id,
            "generation": 1,
            "events": [{"seq": 1, "ts": "2026-09-20T00:00:00Z", "type": "run_started"}],
        },
    )
    assert stale_events.status_code == 409
    assert harness.client.get("/api/runs/run-fence-1").json()["events"] == []


def test_duplicate_events_are_not_stored_twice(harness):
    """AC-5: 같은 (run_id, seq) 재전송이 이벤트를 늘리지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-evt-1")
    harness.client.post(f"/api/runner/{harness.runner_config.runner_id}/assignments")

    events = [
        {"seq": 1, "ts": "2026-09-20T00:00:00Z", "type": "run_started"},
        {"seq": 2, "ts": "2026-09-20T00:00:01Z", "type": "tool_call_started"},
    ]
    payload = {
        "runner_id": harness.runner_config.runner_id,
        "generation": 1,
        "events": events,
    }
    first = harness.client.post("/api/runner/runs/run-evt-1/events", json=payload).json()
    second = harness.client.post("/api/runner/runs/run-evt-1/events", json=payload).json()

    assert first == {"stored": 2, "duplicate": 0}
    assert second == {"stored": 0, "duplicate": 2}
    assert len(harness.client.get("/api/runs/run-evt-1").json()["events"]) == 2


def test_idempotency_key_replays_the_stored_response(harness):
    """헤더 멱등 키를 쓴 쓰기의 재전송은 같은 응답을 돌려주고 새 기록을 만들지 않는다."""
    project = harness.create_project()
    headers = {"Idempotency-Key": "case-create-001"}
    body = {"title": "같은 요청", "kind": "feature"}

    first = harness.client.post(
        f"/api/projects/{project['id']}/cases", json=body, headers=headers
    ).json()
    second = harness.client.post(
        f"/api/projects/{project['id']}/cases", json=body, headers=headers
    ).json()

    assert first["id"] == second["id"]
    assert len(harness.client.get(f"/api/projects/{project['id']}/cases").json()) == 1


def test_finished_run_is_not_overwritten_by_a_different_outcome(harness):
    """이미 끝난 Run에 다른 결과를 쓰려는 보고는 거부한다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-final-1")
    harness.agent.poll_once()

    response = harness.client.post(
        "/api/runner/runs/run-final-1/result",
        json={
            "runner_id": harness.runner_config.runner_id,
            "generation": 1,
            "outcome": "failed",
        },
    )
    assert response.status_code == 409
    assert harness.client.get("/api/runs/run-final-1").json()["outcome"] == "completed"
