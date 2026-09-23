"""UI-02 — 입력·실행 제어(plans/UI-PLAN-02.md).

요청 중단과 그 확인, 요청 `unknown` 해제, Runner 재시작 대조, 잔류 재확인, PC 미연결 전송
거부, 보고 재시도를 **API 와 실제 Runner 코드로** 본다. 실행기는 시험용 가짜(`FakeCliExecutor`)
이며 "CLI 가 도는 동안"은 `hold` 로 만든다. 실제 프로세스 트리는
`tests/test_process_control.py`, 실제 서버·Runner 프로세스는
`tests/test_runner_process_control.py` 가 본다.

시험 이름 옆의 AC 번호는 UI-PLAN-02 5절이다.
"""

from __future__ import annotations

import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import pytest

from domain import conversation as convmod
from domain import run_control as runctl
from domain.models import (
    ConversationRefusal,
    MessageReceipt,
    RequestOutcomeReason,
    RequestSettleOutcome,
    RequestState,
    RunOutcome,
)
from tests.conftest import RUNNER_ID

REPO_ROOT = Path(__file__).resolve().parent.parent
CODEX_RAW = REPO_ROOT / "p1" / "evidence" / "codex-read-v2-347eb670.stdout.jsonl"


# ---------------------------------------------------------------- 도우미


def _refusals(response) -> list[str]:
    detail = response.json()["detail"]
    if "admission" in detail:
        return detail["admission"]["refusals"]
    return detail["refusals"]


def _db(harness) -> sqlite3.Connection:
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    return conn


_PROJECTS = iter(range(10**6))


def _conversation(harness, title: str = "대화") -> dict[str, Any]:
    project = harness.create_project(f"ui02-{next(_PROJECTS)}")
    return harness.create_conversation(project["id"], title)


def _open(harness, case_id: str, text: str, cid: str) -> dict[str, Any]:
    sent = harness.send_message(case_id, text, cid)
    assert sent["request"]["state"] == RequestState.PROCESSING.value
    return sent["request"]


def _reply_run(harness, case_id: str, request_id: str, run_id: str):
    response = harness.discussion_reply(case_id, request_id, run_id, execute=False)
    assert response.status_code == 201, response.text
    return response.json()["run"]


def _claim(harness) -> list[dict[str, Any]]:
    """Runner 가 배정을 **받기만** 한 상태를 만든다(실행하지 않는다)."""
    response = harness.client.post(f"/api/runner/{RUNNER_ID}/assignments")
    assert response.status_code == 200, response.text
    return response.json()


def _stop(harness, case_id: str, request_id: str, reason: str = "그만"):
    return harness.client.post(
        f"/api/cases/{case_id}/requests/{request_id}/stop",
        json={"actor": "owner", "reason": reason},
    )


def _request(harness, case_id: str, request_id: str) -> dict[str, Any]:
    view = harness.conversation(case_id)
    return next(r for r in view["requests"] if r["id"] == request_id)


def _run(harness, run_id: str) -> dict[str, Any]:
    response = harness.client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _reservations(harness, case_id: str, run_id: str) -> list[dict[str, Any]]:
    budget = harness.client.get(f"/api/cases/{case_id}/budget").json()
    return [r for r in budget["reservations"] if r["run_id"] == run_id]


def _wait(predicate, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def _executing(harness, run_id: str) -> bool:
    with harness.agent._inflight_lock:  # noqa: SLF001 - 실행 중 표를 들여다본다
        entry = harness.agent._inflight.get(run_id)  # noqa: SLF001
        return entry is not None and entry.state == "executing"


class _Worker:
    """실행 작업자를 **다른 스레드에서** 한 회 돌린다. 시험 스레드가 제어 루프가 된다."""

    def __init__(self, harness) -> None:
        self.result: dict[str, Any] = {}
        self.thread = threading.Thread(target=self._run, args=(harness,))

    def _run(self, harness) -> None:
        self.result.update(harness.agent.execution_tick())

    def __enter__(self) -> "_Worker":
        self.thread.start()
        return self

    def __exit__(self, *_exc) -> None:
        self.thread.join(timeout=30)
        assert not self.thread.is_alive()


# ================================================== 순수 규칙 (domain.run_control)


def _finished(outcome: str, residual: str = "unknown", **extra) -> dict[str, Any]:
    return {"run_id": f"r-{outcome}-{residual}", "status": "finished", "outcome": outcome,
            "residual_activity": residual, **extra}


def test_a_run_counts_as_ended_only_with_confirmation():
    """AC-10·AC-12 — 결과와 실제 종료는 다른 축이다."""
    # 결과를 몰라도 끝난 것은 확인할 수 있다.
    ended_unknown = _finished("unknown", "none")
    assert runctl.execution_confirmed_ended(ended_unknown)
    assert not runctl.execution_unconfirmed(ended_unknown)
    # 중단된 실행의 잔류를 모르면 요청을 잠근다.
    assert runctl.execution_unconfirmed(_finished("cancelled", "unknown"))
    # **정상 종료 실행의 잔류 불명은 잠그지 않는다**(UI-01 규칙 유지).
    assert not runctl.execution_unconfirmed(_finished("completed", "unknown"))
    assert not runctl.execution_unconfirmed(_finished("failed", "unknown"))
    # 시작하지 않은 실행은 끝났다.
    assert runctl.execution_confirmed_ended(
        _finished("cancelled", "none", not_started_reason="stop_requested")
    )
    # 뒤늦은 관측이 결과 보고 값보다 앞선다. 원래 값은 그대로 둔다.
    rechecked = _finished("unknown", "unknown", residual_observed="none")
    assert runctl.effective_residual(rechecked) == "none"
    assert rechecked["residual_activity"] == "unknown"
    assert not runctl.execution_unconfirmed(rechecked)


def test_none_is_accepted_only_with_a_confirming_basis():
    """AC-10."""
    assert runctl.residual_claim_valid("none", "job_empty")
    assert runctl.residual_claim_valid("none", "job_closed_kill_on_close")
    assert runctl.residual_claim_valid("none", None)  # 근거를 보내지 않는 옛 계약
    assert not runctl.residual_claim_valid("none", "not_observable")
    assert not runctl.residual_claim_valid("none", "root_process_alive")
    assert not runctl.residual_claim_valid("none", "made_up")
    assert runctl.residual_claim_valid("unknown", "not_observable")
    assert not runctl.residual_claim_valid("maybe", None)


def test_the_controller_settles_a_request_only_after_stop_or_while_unknown():
    """AC-7·AC-11 — 제어부가 스스로 끝내는 경우는 둘뿐이다."""
    settle = runctl.system_settlement
    done = [_finished("completed", "none")]
    # 처리 중이고 중단 요청이 없으면 처리하는 쪽이 끝낸다.
    assert settle(done, state="processing", stop_requested=False) is None
    # 끝나지 않은 실행이 있으면 아직이다.
    running = [{"run_id": "r", "status": "running", "outcome": None}]
    assert settle(running, state="processing", stop_requested=True) is None
    # 중단 뒤 전부 확인되면 interrupted.
    assert settle(done, state="processing", stop_requested=True) == (
        RequestState.INTERRUPTED, RequestOutcomeReason.STOPPED_BY_REQUEST
    )
    # 확인되지 않은 실행이 있으면 unknown 으로 잠근다.
    assert settle(
        [_finished("cancelled", "unknown")], state="processing", stop_requested=True
    ) == (RequestState.UNKNOWN, RequestOutcomeReason.RUN_RESIDUAL_UNCONFIRMED)
    assert settle(
        [_finished("unknown", "unknown")], state="processing", stop_requested=True
    ) == (RequestState.UNKNOWN, RequestOutcomeReason.RUN_OUTCOME_UNKNOWN)
    # unknown 은 확인되면 풀리고, 아니면 그대로다.
    assert settle([_finished("unknown", "unknown")], state="unknown", stop_requested=False) is None
    assert settle(
        [_finished("unknown", "unknown", residual_observed="none")],
        state="unknown",
        stop_requested=False,
    ) == (RequestState.INTERRUPTED, RequestOutcomeReason.EXECUTION_ENDED_RESULT_UNKNOWN)
    # 끝난 요청은 건드리지 않는다.
    assert settle(done, state="interrupted", stop_requested=True) is None


def test_explicit_settle_follows_the_actual_end():
    """AC-7·AC-12 — 처리하는 쪽의 종료 기록."""
    stored = MessageReceipt.STORED
    decide = convmod.decide_settle
    assert decide(RequestSettleOutcome.COMPLETED, stored, [], stop_requested=True).refusal is (
        ConversationRefusal.REQUEST_STOP_REQUESTED
    )
    ended = decide(RequestSettleOutcome.COMPLETED, stored, [_finished("unknown", "none")])
    assert (ended.state, ended.reason) == (
        RequestState.INTERRUPTED, RequestOutcomeReason.EXECUTION_ENDED_RESULT_UNKNOWN
    )
    locked = decide(RequestSettleOutcome.FAILED, stored, [_finished("unknown", "unknown")])
    assert (locked.state, locked.reason) == (
        RequestState.UNKNOWN, RequestOutcomeReason.RUN_OUTCOME_UNKNOWN
    )
    fine = decide(RequestSettleOutcome.COMPLETED, stored, [_finished("completed", "unknown")])
    assert fine.state is RequestState.COMPLETED


def test_send_state_names_every_reason_and_connection_is_derived():
    """AC-15·AC-16."""
    both = convmod.general_send_state(False, {"id": "req-1", "state": "processing"}, True)
    assert not both.allowed
    assert both.to_dict()["refusals"] == ["request_in_progress", "runner_disconnected"]
    stopping = convmod.general_send_state(
        False, {"id": "req-1", "state": "processing", "stop_requested_at": "t"}
    )
    assert stopping.refusal is ConversationRefusal.REQUEST_STOP_REQUESTED
    only_pc = convmod.general_send_state(False, None, True)
    assert only_pc.to_dict()["refusals"] == ["runner_disconnected"]
    assert convmod.general_send_state(False, None, False).allowed

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    fresh = runctl.runner_connection(
        {"id": "r", "last_heartbeat_at": now.isoformat()}, stale_seconds=15
    )
    assert fresh["state"] == "connected"
    stale = runctl.runner_connection(
        {"id": "r", "last_heartbeat_at": (now - __import__("datetime").timedelta(seconds=60)).isoformat()},
        stale_seconds=15,
    )
    assert stale["state"] == "disconnected" and runctl.connection_refuses(stale)
    assert runctl.runner_connection({"id": "r", "last_heartbeat_at": None})["state"] == "never_seen"
    assert not runctl.connection_refuses(runctl.runner_connection(None))

    assigned = {"status": "assigned", "liveness_at": now.isoformat()}
    assert runctl.run_execution_state(assigned, runner_connected=True).value == "executing"
    assert runctl.run_execution_state(assigned, runner_connected=False).value == "unconfirmed"
    assert runctl.run_execution_state(
        {"status": "assigned", "liveness_at": None}, runner_connected=True
    ).value == "unconfirmed"


# ======================================================= 요청 중단 (API)


def test_stopping_before_any_run_is_assigned_costs_nothing(harness):
    """AC-6·AC-7·AC-8 — 미배정 실행은 제어부가 시작하지 않은 실행으로 끝내고, 확인됐으므로
    요청이 `interrupted` 로 끝나 전송이 열린다."""
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "이것저것 알려 주세요.", "c-stop-0")
    _reply_run(harness, case["case_id"], request["id"], "run-stop-pending")

    stopped = _stop(harness, case["case_id"], request["id"])
    assert stopped.status_code == 200, stopped.text
    body = stopped.json()
    assert body["state"] == RequestState.INTERRUPTED.value
    assert body["outcome_reason"] == RequestOutcomeReason.STOPPED_BY_REQUEST.value
    assert body["stop_requested_by"] == "owner" and body["stop_reason_summary"] == "그만"
    assert body["locking"] is False
    assert body["interruption_summary"]["not_started"] == ["run-stop-pending"]

    run = _run(harness, "run-stop-pending")
    assert run["outcome"] == RunOutcome.CANCELLED.value
    assert run["not_started_reason"] == "stop_requested"
    assert run["residual_activity"] == "none"
    assert [o["basis"] for o in run["residual_observations"]] == ["not_launched"]
    # 소비 0 — 호출이 없었다.
    rows = _reservations(harness, case["case_id"], "run-stop-pending")
    assert rows and all(r["actual_value"] == 0 for r in rows)
    assert {r["settle_source"] for r in rows} == {"not_started"}
    # Runner 는 그 실행을 받지 않는다.
    harness.agent.poll_once()
    assert harness.cli_effect_count(case["case_id"]) == 0

    view = harness.conversation(case["case_id"])
    assert view["current_request"] is None
    assert view["send"]["general"]["allowed"] is True
    # 중단 재전송은 아무 것도 바꾸지 않는다.
    again = _stop(harness, case["case_id"], request["id"])
    assert again.status_code == 200 and again.json()["state"] == RequestState.INTERRUPTED.value
    # 처리하는 쪽은 끝난 요청을 다시 적지 못한다.
    assert _refusals(harness.settle(case["case_id"], request["id"])) == [
        ConversationRefusal.REQUEST_ALREADY_SETTLED.value
    ]


def test_a_stop_blocks_follow_up_runs_and_reaches_a_claimed_run(harness):
    """AC-6·AC-7 — 중단은 후속 실행을 막고, 배정만 받은 실행은 CLI 를 부르지 않고 끝난다."""
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "길게 생각해 주세요.", "c-stop-1")
    _reply_run(harness, case["case_id"], request["id"], "run-stop-claimed")
    [claimed] = _claim(harness)
    assert claimed["stop_requested"] is False

    body = _stop(harness, case["case_id"], request["id"]).json()
    assert body["state"] == RequestState.PROCESSING.value and body["stopping"] is True
    assert _run(harness, "run-stop-claimed")["stop_requested_at"]

    # 후속 실행을 막는다 — 진입 검사에서.
    follow = harness.discussion_reply(
        case["case_id"], request["id"], "run-stop-follow", execute=False
    )
    assert follow.status_code == 409
    assert _refusals(follow) == ["request_stop_requested"]
    # 처리하는 쪽은 중단된 요청을 적지 못한다 — 확인한 제어부가 끝낸다.
    assert _refusals(harness.settle(case["case_id"], request["id"], "failed")) == [
        ConversationRefusal.REQUEST_STOP_REQUESTED.value
    ]
    # 일반 전송은 "중단 요청 중" 으로 막힌다.
    blocked = harness.post_message(case["case_id"], "다음 질문", "c-stop-1b")
    assert _refusals(blocked) == [ConversationRefusal.REQUEST_STOP_REQUESTED.value]
    # heartbeat 응답이 중단을 전달한다.
    controls = harness.client.post(f"/api/runner/{RUNNER_ID}/heartbeat").json()["controls"]
    assert [s["run_id"] for s in controls["stop"]] == ["run-stop-claimed"]

    # Runner 가 (중단 전에 받은) 배정을 처리한다 — 영수증 응답이 중단을 알려 CLI 를 부르지 않는다.
    action = harness.agent.handle_assignment(claimed)
    assert action["action"] == "refused_stop_requested"
    assert harness.cli_effect_count(case["case_id"]) == 0
    run = _run(harness, "run-stop-claimed")
    assert (run["outcome"], run["not_started_reason"]) == ("cancelled", "stop_requested")
    after = _request(harness, case["case_id"], request["id"])
    assert after["state"] == RequestState.INTERRUPTED.value


def test_a_stop_ends_an_executing_run_and_unlocks_after_confirmation(harness):
    """AC-1·AC-3·AC-7·AC-8 — CLI 가 도는 동안 제어 루프가 원문을 저장하고 실행 중을 보고하며,
    중단을 전달해 실행이 끝나고, 확인된 뒤에만 전송이 열린다."""
    fake = harness.agent.cli_executor
    fake.hold = threading.Event()
    fake.residual_activity = "none"
    fake.residual_basis = "in_process"
    case = _conversation(harness)
    other = _conversation(harness, "다른 대화")
    request = _open(harness, case["case_id"], "천천히 답해 주세요.", "c-exec-0")
    _reply_run(harness, case["case_id"], request["id"], "run-exec-1")

    with _Worker(harness) as worker:
        assert _wait(lambda: _executing(harness, "run-exec-1"))
        # 긴 실행 중 — 다른 대화의 메시지가 접수되고 실행 중이 보고된다.
        posted = harness.post_message(other["case_id"], "그동안 이것도", "c-exec-other")
        assert posted.status_code == 202
        tick = harness.agent.control_tick()
        assert tick["stored_intakes"], "실행 중에도 원문이 저장돼야 한다"
        found = harness.client.get(
            f"/api/cases/{other['case_id']}/messages/by-client-id/c-exec-other"
        ).json()
        assert found["receipt"] == "stored"
        running = _request(harness, case["case_id"], request["id"])
        assert running["runs"][0]["execution_state"] == "executing"
        assert _run(harness, "run-exec-1")["liveness_at"]

        _stop(harness, case["case_id"], request["id"])
        stopping = harness.conversation(case["case_id"])
        assert stopping["current_request"]["stopping"] is True
        assert stopping["send"]["general"]["refusal"] == "request_stop_requested"
        delivered = harness.agent.control_tick()["controls"]["stop_delivered"]
        assert delivered == ["run-exec-1"]
    assert worker.result["assignments"][0]["action"] == "executed"

    run = _run(harness, "run-exec-1")
    assert run["stop_delivered_at"]
    assert (run["outcome"], run["residual_activity"]) == ("cancelled", "none")
    assert [o["basis"] for o in run["residual_observations"]] == ["in_process"]
    done = _request(harness, case["case_id"], request["id"])
    assert (done["state"], done["outcome_reason"]) == ("interrupted", "stopped_by_request")
    summary = done["interruption_summary"]
    assert summary["by_outcome"] == {"cancelled": 1} and summary["execution_unconfirmed"] == []
    # 중단은 취소 성공이 아니다 — 사용량·출력이 남는다.
    assert run["output_artifact_id"]
    assert harness.post_message(case["case_id"], "이어서", "c-exec-1").status_code == 202


def test_an_unconfirmed_stop_stays_locked_until_a_recheck_confirms_it(harness):
    """AC-7·AC-10·AC-11 — 잔류를 확인하지 못한 중단은 `unknown` 으로 잠기고, Runner 의 재확인이
    확인 근거를 보내야 풀린다. 원래 보고 값은 고치지 않는다."""
    fake = harness.agent.cli_executor
    fake.hold = threading.Event()  # 잔류는 기본값 unknown, 근거 없음
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "오래 걸려요.", "c-unk-0")
    _reply_run(harness, case["case_id"], request["id"], "run-unk-1")
    with _Worker(harness):
        assert _wait(lambda: _executing(harness, "run-unk-1"))
        _stop(harness, case["case_id"], request["id"])
        harness.agent.control_tick()

    locked = _request(harness, case["case_id"], request["id"])
    assert (locked["state"], locked["outcome_reason"]) == ("unknown", "run_residual_unconfirmed")
    view = harness.conversation(case["case_id"])
    assert view["send"]["general"]["refusal"] == ConversationRefusal.REQUEST_STATE_UNKNOWN.value
    assert locked["runs"][0]["execution_state"] == "ended_unconfirmed"
    assert _refusals(harness.settle(case["case_id"], request["id"])) == [
        ConversationRefusal.REQUEST_STATE_UNKNOWN.value
    ]
    # 잠길 때 재확인이 요청됐다.
    assert _run(harness, "run-unk-1")["residual_check_requested_at"]
    # 끝났는지 모르는 중단 실행은 업무 종료도 막는다(미정리 실행).
    result = harness.client.get(f"/api/cases/{case['case_id']}/result").json()
    assert [r["run_id"] for r in result["unsettled_runs"]] == ["run-unk-1"]
    # 사람이 다시 확인을 요청할 수 있다(선언이 아니다).
    again = harness.client.post(
        f"/api/cases/{case['case_id']}/requests/{request['id']}/reconcile"
    )
    assert again.status_code == 200 and again.json()["state"] == "unknown"

    # Runner 의 제어 루프가 원장의 시작 기록(in_process)으로 확인한다.
    checked = harness.agent.control_tick()["controls"]["residual_checked"]
    assert checked[0]["residual"]["basis"] == "in_process"
    run = _run(harness, "run-unk-1")
    assert run["residual_activity"] == "unknown"  # 원래 보고 값 그대로
    assert [(o["source"], o["residual"]) for o in run["residual_observations"]] == [
        ("recheck", "none")
    ]
    assert run["residual_check_requested_at"] is None
    result = harness.client.get(f"/api/cases/{case['case_id']}/result").json()
    assert result["unsettled_runs"] == []  # 확인되면 빠진다
    freed = _request(harness, case["case_id"], request["id"])
    assert (freed["state"], freed["outcome_reason"]) == ("interrupted", "stopped_by_request")
    assert harness.conversation(case["case_id"])["send"]["general"]["allowed"] is True
    # 풀린 요청에 재확인을 요청할 수 없다.
    late = harness.client.post(
        f"/api/cases/{case['case_id']}/requests/{request['id']}/reconcile"
    )
    assert _refusals(late) == [ConversationRefusal.REQUEST_NOT_UNKNOWN.value]


def test_a_recheck_without_evidence_leaves_the_lock_and_nobody_can_declare_it(harness):
    """AC-11 — 확인 근거가 없으면 잠금이 남는다. 사람이 대신 확인을 선언하는 경로는 없다."""
    fake = harness.agent.cli_executor
    fake.outcome = RunOutcome.UNKNOWN
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "무엇이든.", "c-noev-0")
    harness.discussion_reply(case["case_id"], request["id"], "run-noev-1")
    # 원장의 시작 기록을 **트리 제어 없이 시작된** 것으로 바꾼다(비 Windows·옛 방식의 모양).
    harness.agent.ledger._update(  # noqa: SLF001
        "run-noev-1", launch={"pid": None, "kill_on_close": False}
    )
    settled = harness.settle(case["case_id"], request["id"], "failed").json()
    assert settled["state"] == "unknown"

    checked = harness.agent.control_tick()["controls"]["residual_checked"]
    assert checked[0]["residual"] == {"residual": "unknown", "basis": "not_observable",
                                      "terminated": None}
    assert _request(harness, case["case_id"], request["id"])["state"] == "unknown"
    # 근거 없는 none 은 제어부가 받지 않는다.
    forged = harness.client.post(
        "/api/runner/runs/run-noev-1/residual",
        json={"runner_id": RUNNER_ID, "residual": "none", "basis": "not_observable"},
    )
    assert forged.status_code == 409
    assert _request(harness, case["case_id"], request["id"])["state"] == "unknown"


def test_a_run_whose_result_is_unknown_but_ended_settles_as_interrupted(harness):
    """AC-12 — 결과를 모르지만 끝난 것은 확인한 실행은 완료로도 실패로도 적지 않는다."""
    fake = harness.agent.cli_executor
    fake.outcome = RunOutcome.UNKNOWN
    fake.residual_activity = "none"
    fake.residual_basis = "in_process"
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "무엇이든.", "c-ended-0")
    harness.discussion_reply(case["case_id"], request["id"], "run-ended-1")
    body = harness.settle(case["case_id"], request["id"], "completed").json()
    assert (body["state"], body["outcome_reason"]) == (
        "interrupted", "execution_ended_result_unknown"
    )
    assert body["locking"] is False


def test_residual_claims_need_a_basis_at_the_api(harness):
    """AC-10 — 결과 보고에서도 근거 없는 `none` 은 409 다."""
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "무엇이든.", "c-basis-0")
    _reply_run(harness, case["case_id"], request["id"], "run-basis-1")
    [claimed] = _claim(harness)
    bad = harness.client.post(
        "/api/runner/runs/run-basis-1/result",
        json={"runner_id": RUNNER_ID, "generation": claimed["assignment_generation"],
              "outcome": "completed", "residual_activity": "none",
              "residual_basis": "not_observable"},
    )
    assert bad.status_code == 409
    assert _run(harness, "run-basis-1")["status"] == "assigned"


def test_a_run_level_stop_is_only_for_runs_outside_a_request(harness):
    """AC-6 — 요청에 연결된 실행은 요청 단위로 멈춘다."""
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "무엇이든.", "c-runstop-0")
    _reply_run(harness, case["case_id"], request["id"], "run-linked")
    linked = harness.client.post("/api/runs/run-linked/stop", json={"actor": "owner"})
    assert _refusals(linked) == [ConversationRefusal.RUN_LINKED_TO_REQUEST.value]

    project = harness.create_project("run-level")
    work = harness.create_case(project["id"], "관리 실행", kind="analysis")
    instruction = harness.submit_artifact(work["id"], "조사해 주세요.")
    harness.create_run(work["id"], instruction["artifact_id"], "run-loose")
    stopped = harness.client.post("/api/runs/run-loose/stop", json={"actor": "owner"})
    assert stopped.status_code == 200, stopped.text
    run = stopped.json()
    assert (run["outcome"], run["not_started_reason"], run["stop_requested_by"]) == (
        "cancelled", "stop_requested", "owner"
    )
    again = harness.client.post("/api/runs/run-loose/stop", json={"actor": "owner"})
    assert _refusals(again) == [ConversationRefusal.RUN_ALREADY_FINISHED.value]


# ====================================================== 재시작 대조


def _dead_pid() -> int:
    proc = subprocess.Popen([sys.executable, "-c", "pass"])
    proc.wait()
    return proc.pid


def test_restart_reconciliation_reports_without_reexecution_or_new_reservation(harness):
    """AC-9 — 이전 프로세스의 실행을 원장으로 대조한다. CLI 를 다시 부르지 않고 세대를 올리지
    않는다(새 예약 없음)."""
    runs = {}
    for key in ("none", "nolaunch", "launched", "finished"):
        case = _conversation(harness, key)
        request = _open(harness, case["case_id"], f"{key} 요청", f"c-rec-{key}")
        _reply_run(harness, case["case_id"], request["id"], f"run-rec-{key}")
        runs[key] = (case["case_id"], request["id"])
    claimed = {a["run_id"]: a for a in _claim(harness)}
    assert len(claimed) == 4
    ledger = harness.agent.ledger
    ledger.claim("run-rec-nolaunch", 1)
    ledger.claim("run-rec-launched", 1)
    ledger.record_launch(
        "run-rec-launched",
        {
            "job_name": "Local\\hads-run-test-reconcile-gone",
            "kill_on_close": True,
            "pid": _dead_pid(),
            "pid_created": 1,
        },
    )
    shutil.copyfile(CODEX_RAW, harness.runner_config.raw_dir / "run-rec-launched.stdout.jsonl")
    ledger.claim("run-rec-finished", 1)
    ledger.finish(
        "run-rec-finished",
        {"outcome": "completed", "residual_activity": "none", "residual_basis": "in_process",
         "usage": "not_reported", "observed_tool_version": "codex/fake"},
    )

    actions = {a["run_id"]: a for a in harness.agent.reconcile_unfinished()}

    assert actions["run-rec-none"]["action"] == "reported_not_launched"
    assert actions["run-rec-nolaunch"]["action"] == "reported_not_launched"
    assert actions["run-rec-launched"]["action"] == "reported_unknown_without_reexecution"
    assert actions["run-rec-finished"]["action"] == "replayed_stored_result"
    for key in ("none", "nolaunch"):
        run = _run(harness, f"run-rec-{key}")
        assert (run["outcome"], run["not_started_reason"]) == ("failed", "not_launched")
    launched = _run(harness, "run-rec-launched")
    assert (launched["outcome"], launched["residual_activity"]) == ("unknown", "none")
    assert [(o["source"], o["basis"]) for o in launched["residual_observations"]] == [
        ("reconcile", "job_closed_kill_on_close")
    ]
    assert launched["usage"]["tokens"]["input_tokens"] == 32305  # P4-04 복구 유지
    assert _run(harness, "run-rec-finished")["outcome"] == "completed"
    # 재실행 없음, 세대 그대로, 새 세대 예약 없음.
    for key, (case_id, _rid) in runs.items():
        assert harness.cli_effect_count(case_id) == 0
        run = _run(harness, f"run-rec-{key}")
        assert run["assignment_generation"] == 1
        assert {r["generation"] for r in _reservations(harness, case_id, f"run-rec-{key}")} == {1}
    # 결과를 모르지만 끝난 실행 — 요청은 interrupted 로 끝난다.
    case_id, request_id = runs["launched"]
    body = harness.settle(case_id, request_id, "failed").json()
    assert (body["state"], body["outcome_reason"]) == (
        "interrupted", "execution_ended_result_unknown"
    )
    # 다시 대조해도 새로 보고할 것이 없다.
    assert harness.agent.reconcile_unfinished() == []


def test_a_run_whose_owner_process_is_alive_is_left_alone(harness):
    """AC-10 — 그 실행을 맡은 다른 Runner 프로세스가 살아 있으면 끊지도 보고하지도 않는다."""
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "무엇이든.", "c-owner-0")
    _reply_run(harness, case["case_id"], request["id"], "run-owner-1")
    _claim(harness)
    other = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        from runner import process_tree

        identity = process_tree.process_identity(other.pid)
        harness.agent.ledger.claim("run-owner-1", 1, identity)
        harness.agent.ledger.record_launch("run-owner-1", {"in_process": True})
        [action] = harness.agent.reconcile_unfinished()
        assert action["action"] == "skipped_owner_runner_alive"
        assert _run(harness, "run-owner-1")["status"] == "assigned"
    finally:
        other.kill()
        other.wait()


def test_a_stale_workspace_lock_is_released_only_for_its_own_run(harness, tmp_path):
    """AC-13 — 잔류가 확인된 대조만 그 실행이 잡고 있던 권고 잠금을 푼다."""
    from runner import workspace

    worktree = tmp_path / "wt" / "case-x"
    worktree.mkdir(parents=True)
    assignment = {
        "run_id": "run-lock-1",
        "workspace": {"worktree_path": str(worktree), "base_commit": "abc"},
        "workspace_path": str(worktree),
    }
    lock = workspace.AdvisoryLock(workspace.lock_path_for(worktree))
    assert lock.acquire(f"{RUNNER_ID}:run-lock-1")
    other = dict(assignment, run_id="run-lock-2")
    assert harness.agent._release_stale_lock(other) is False  # noqa: SLF001
    assert workspace.lock_holder(workspace.lock_path_for(worktree)) is not None
    assert harness.agent._release_stale_lock(assignment) is True  # noqa: SLF001
    assert workspace.lock_holder(workspace.lock_path_for(worktree)) is None


# ====================================================== 보고 재시도


def test_the_worker_resends_a_result_after_a_transport_error(harness, monkeypatch):
    """AC-14 — 작업자 흐름은 전송 오류면 결과를 다시 보낸다. 409 는 다시 보내지 않는다."""
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "무엇이든.", "c-retry-0")
    _reply_run(harness, case["case_id"], request["id"], "run-retry-1")
    original = harness.agent.client.send_result
    attempts = []

    def flaky(run_id, payload):
        attempts.append(run_id)
        if len(attempts) < 3:
            raise httpx.ConnectError("controller is restarting")
        return original(run_id, payload)

    monkeypatch.setattr(harness.agent.client, "send_result", flaky)
    monkeypatch.setattr(harness.agent, "RETRY_MAX_DELAY", 0.05)
    harness.agent._retry_reports = True  # noqa: SLF001 - 작업자 흐름의 설정
    harness.agent.execution_tick()
    assert len(attempts) == 3
    assert _run(harness, "run-retry-1")["outcome"] == "completed"

    def refused(run_id, payload):
        response = httpx.Response(409, request=httpx.Request("POST", "http://x"))
        raise httpx.HTTPStatusError("stale", request=response.request, response=response)

    monkeypatch.setattr(harness.agent.client, "send_result", refused)
    with pytest.raises(httpx.HTTPStatusError):
        harness.agent._send(harness.agent.client.send_result, "run-x", {})  # noqa: SLF001


# ====================================================== PC 연결


def test_a_disconnected_pc_refuses_every_user_input_and_queues_nothing(harness):
    """AC-15·AC-16 — heartbeat 가 끊긴 PC 로 가는 사용자 입력은 받지 않는다. 연결되면 받는다."""
    from tests.test_conversation import _QUESTION
    from tests.test_intent import _draft_fields

    project = harness.create_project()
    case = harness.create_case(project["id"], "질문이 있는 업무")
    harness.submit_intent_draft(case["id"], _draft_fields(), questions=[_QUESTION])
    intent = harness.latest_intent(case["id"])
    question = intent["questions"][0]
    conv = harness.create_conversation(project["id"], "논의")

    harness.age_heartbeat(7200)
    before = harness.intake_count()
    view = harness.conversation(conv["case_id"])
    connection = view["send"]["runner_connection"]
    assert connection["state"] == "disconnected" and connection["last_seen_at"]
    assert connection["runner_id"] == RUNNER_ID
    assert view["send"]["general"]["refusals"] == ["runner_disconnected"]
    assert view["send"]["runner_connection_enforced"] is True

    general = harness.post_message(conv["case_id"], "보낼게요", "c-pc-0")
    card = harness.post_message(
        case["id"], "빼 주세요", "c-pc-1", kind="card_answer",
        question_id=question["id"], intent_version_id=intent["id"],
    )
    legacy_answer = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={"content": "빼 주세요", "summary": "답", "target_runner_id": RUNNER_ID},
    )
    feedback = harness.client.post(
        f"/api/cases/{case['id']}/feedback",
        json={"content": "의견", "summary": "의견", "target_runner_id": RUNNER_ID,
              "target_intent_version_id": intent["id"]},
    )
    for response in (general, card, legacy_answer, feedback):
        assert response.status_code == 409, response.text
        assert _refusals(response) == [ConversationRefusal.RUNNER_DISCONNECTED.value]
    assert harness.conversation(case["id"])["send"]["card_answer"]["allowed"] is False
    assert harness.intake_count() == before  # 대기열 없음
    assert harness.latest_intent(case["id"])["questions"][0]["state"] == "open"

    harness.agent.poll_once()  # 다시 연결된다
    view = harness.conversation(conv["case_id"])
    assert view["send"]["runner_connection"]["state"] == "connected"
    assert view["send"]["general"]["allowed"] is True
    # 자동으로 보내진 것은 없다 — 사용자가 다시 보내야 한다.
    assert harness.conversation(conv["case_id"])["messages"] == []
    assert harness.post_message(conv["case_id"], "보낼게요", "c-pc-0").status_code == 202


def test_an_assigned_run_on_a_disconnected_pc_is_unconfirmed(harness):
    """AC-16 — 배정된 실행은 Runner 가 미연결이면 실행 중이라고 보이지 않는다."""
    case = _conversation(harness)
    request = _open(harness, case["case_id"], "무엇이든.", "c-unconf-0")
    _reply_run(harness, case["case_id"], request["id"], "run-unconf-1")
    [claimed] = _claim(harness)
    harness.client.post(
        f"/api/runner/{RUNNER_ID}/heartbeat",
        json={"executing": [{"run_id": "run-unconf-1", "generation": 1}]},
    )
    live = _request(harness, case["case_id"], request["id"])
    assert live["runs"][0]["execution_state"] == "executing"
    harness.age_heartbeat(7200)
    gone = _request(harness, case["case_id"], request["id"])
    assert gone["runs"][0]["execution_state"] == "unconfirmed"
    # 다른 Runner·옛 세대의 보고는 실행 중을 만들지 않는다.
    with _db(harness) as conn:
        conn.execute("UPDATE run SET liveness_at = NULL WHERE run_id = 'run-unconf-1'")
    harness.client.post(
        f"/api/runner/{RUNNER_ID}/heartbeat",
        json={"executing": [{"run_id": "run-unconf-1", "generation": 9}]},
    )
    assert _run(harness, "run-unconf-1")["liveness_at"] is None
    assert claimed["run_id"] == "run-unconf-1"


# ====================================================== 경계


def test_ui02_records_keep_no_bodies_and_enforcement_is_unchanged(harness):
    """AC-20 — 새 표에 본문·경로 컬럼이 없고 강제 축은 넷 그대로다."""
    with _db(harness) as conn:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(run_residual_observation)")}
    assert columns == {
        "id", "run_id", "generation", "seq", "source", "residual", "basis", "terminated",
        "runner_id", "observed_at",
    }
    project = harness.create_project()
    case = harness.create_case(project["id"])
    enforcement = harness.client.get(f"/api/cases/{case['id']}/policy").json()["enforcement"]
    assert {k for k, v in enforcement.items() if v["state"] == "enforced"} == {
        "autonomy", "controlled_checkpoint", "budget", "repository_selection"
    }
    assert enforcement["publish"]["state"] == "not_implemented"
