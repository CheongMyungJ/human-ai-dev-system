"""P4-10d (이슈 #10, D-98) — 결과 모름(`unknown`)으로 끝난 실행이 업무 종료를 영원히 막지 않는다(plans/P4-PLAN-10d.md).

    버그       진행기가 미정리 실행 앞에서 요청을 "처리 중" 으로 열어 두지 않는다 — 사람 대기 `unsettled_runs`(실행 목록)
    B 자동     같은 작업·목적의 뒤 시도가 `completed` 이고 앞 시도의 트리 종료가 확인됐으면 앞 `unknown` 은 대체됐다
    A 사람     나머지 끝난 `unknown` 은 사람이 "작업공간 영향을 확인했다" + 사유를 적으면 종료를 막지 않는다
    어느 쪽도  결과를 바꾸지 않는다(`unknown` 그대로). 트리 종료가 확인되지 않은 실행은 사람이 대신 확인하지 않는다(UI-02)
    복구       이미 걸린 Case(이슈 #10 모양)가 제어부 재시작 복구에서 종료까지 간다

`conftest` 의 가짜 실행기로 진행기 경유 흐름을 돈다. **AI 를 부르지 않는다.**
"""

from __future__ import annotations

import sqlite3

import pytest

from controller import db
from controller.repository import Repository
from controller.work_progressor import WorkProgressor
from domain import run_control as runctl
from tests.test_work_progressor import _agree, _drive, _runs, _start, _wait_codes


def _run(h, run_id: str) -> dict:
    return h.client.get(f"/api/runs/{run_id}").json()


def _processing(h, case_id: str) -> list[dict]:
    return [r for r in h.conversation(case_id)["requests"] if r["state"] == "processing"]


def _events(h, case_id: str) -> list[dict]:
    return h.client.get(f"/api/cases/{case_id}/progress").json()["progress"]["events"]


def _confirm(h, case_id: str, run_id: str, **body) -> object:
    payload = {"actor": "owner", "workspace_checked": True, "reason": "출력과 작업 폴더를 보고 영향 없음을 확인"}
    payload.update(body)
    return h.client.post(f"/api/cases/{case_id}/runs/{run_id}/unknown-confirmation", json=payload)


def _side_unknown_run(h, case_id: str, run_id: str, *, residual: str = "none") -> None:
    """요청에 묶이지 않은 읽기 전용 분석 실행 하나를 `unknown` 으로 끝낸다(뒤 시도가 없는 실행)."""
    artifact = h.submit_artifact(case_id, "곁가지 확인")["artifact_id"]
    h.agent.persist_pending_intakes()
    h.create_run(case_id, artifact, run_id=run_id, purpose="limited_analysis", task_id="side-check")
    run = _run(h, run_id)
    body = {"runner_id": "runner-test-1", "generation": run["assignment_generation"], "outcome": "unknown",
            "residual_activity": residual}
    if residual == "none":
        body["residual_basis"] = "in_process"
    reported = h.client.post(f"/api/runner/runs/{run_id}/result", json=body)
    assert reported.status_code == 200, reported.text


# ============================================================== 순수 규칙 (B)


def _r(run_id, *, task="T2", purpose="verification_run", outcome="unknown", created="2026-09-24T12:00:00",
       residual="none", status="finished"):
    return {"run_id": run_id, "task_id": task, "purpose": purpose, "outcome": outcome, "status": status,
            "created_at": created, "residual_activity": residual, "not_started_reason": None}


def test_supersession_needs_a_later_completed_attempt_of_the_same_work_and_a_confirmed_end():
    """AC-3 — 같은 작업·목적의 뒤 시도가 `completed` 이고 앞 시도의 트리 종료가 확인됐을 때만 대체다."""
    old = _r("T2-1", created="2026-09-24T12:13")
    later = _r("T2-3", outcome="completed", created="2026-09-24T13:26")
    assert runctl.superseding_run(old, [old, later]) == "T2-3"
    # 뒤 시도가 없거나 완료가 아니다.
    assert runctl.superseding_run(old, [old]) is None
    assert runctl.superseding_run(old, [old, {**later, "outcome": "failed"}]) is None
    assert runctl.superseding_run(old, [old, {**later, "status": "running", "outcome": None}]) is None
    # 앞의 완료는 대체가 아니다(뒤 시도만).
    assert runctl.superseding_run(old, [{**later, "created_at": "2026-09-24T11:00"}, old]) is None
    # 다른 작업·다른 목적.
    assert runctl.superseding_run(old, [old, {**later, "task_id": "T3"}]) is None
    assert runctl.superseding_run(old, [old, {**later, "purpose": "feature_implementation"}]) is None
    # 트리 종료를 모른다 — 대체하지 않는다(아직 쓰고 있을 수 있다).
    assert runctl.superseding_run({**old, "residual_activity": "unknown"}, [old, later]) is None
    # 논의 응답은 요청마다 다른 답이지 같은 작업의 재시도가 아니다.
    reply = _r("reply-1", task="conversation", purpose="discussion_reply")
    assert runctl.superseding_run(reply, [reply, {**reply, "run_id": "reply-2", "outcome": "completed",
                                                  "created_at": "2026-09-24T13:00"}]) is None
    # `unknown` 이 아닌 실행은 대상이 아니다.
    assert runctl.superseding_run({**old, "outcome": "failed"}, [old, later]) is None


# ============================================================== B 흐름


def test_a_retried_unknown_attempt_is_superseded_and_the_case_closes(processing_harness):
    """AC-2 — 검증 T2-1 이 `unknown`(트리 종료 확인)으로 끝나고 재시도 T2-2 가 완료되면 T2-1 은 종료를 막지 않는다 —
    자동 완료된다. T2-1 의 결과는 `unknown` 그대로이고 실행 조회·진행 이력에 대체 사실이 남는다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    h.agent.cli_executor.unknown = lambda call: "task-T2-1" in call["run_id"]
    conv = _drive(h, case_id, polls=30)
    assert conv["progress"]["state"] == "done", conv["progress"]
    t2 = [r for r in _runs(h, case_id) if r["task_id"] == "T2"]
    assert [r["outcome"] for r in t2] == ["unknown", "completed"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    assert case["result"]["unsettled_runs"] == []
    settlement = _run(h, t2[0]["run_id"])["unknown_settlement"]
    assert settlement == {"kind": "superseded", "by_run_id": t2[1]["run_id"]}
    listed = {r["run_id"]: r for r in case["runs"]}
    assert listed[t2[0]["run_id"]]["unknown_settlement"]["kind"] == "superseded"
    assert listed[t2[1]["run_id"]]["unknown_settlement"] is None
    lines = [e for e in _events(h, case_id) if e["step"] == "unknown_run_superseded"]
    assert len(lines) == 1 and t2[0]["run_id"] in lines[0]["detail"] and t2[1]["run_id"] in lines[0]["detail"]
    assert _processing(h, case_id) == []


# ============================================================== 버그 + A 흐름


def test_an_unknown_run_without_a_later_attempt_waits_for_a_person_and_a_confirmation_closes(processing_harness):
    """AC-1·AC-4·AC-6 — 뒤 시도가 없는 `unknown` 실행이 남으면 진행 요청이 "처리 중" 으로 남지 않고 끝나며 진행은
    `unsettled_runs` 사람 대기(실행 목록)다. 사람이 확인을 적으면 결과는 `unknown` 그대로 풀리고 자동 완료된다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    _side_unknown_run(h, case_id, "side-unknown-1")
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["unsettled_runs"], conv["progress"]
    [wait] = conv["progress"]["wait"]
    [entry] = wait["runs"]
    assert entry["run_id"] == "side-unknown-1" and entry["outcome"] == "unknown"
    assert entry["ended_confirmed"] is True and entry["confirmable"] is True
    assert _processing(h, case_id) == []
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "waiting_human"

    # 거부: 표시 없음·사유 없음(422), 종료 뒤가 아닌 것들은 아래 시험.
    assert _confirm(h, case_id, "side-unknown-1", workspace_checked=False).status_code == 422
    assert _confirm(h, case_id, "side-unknown-1", reason="").status_code == 422
    done = _confirm(h, case_id, "side-unknown-1")
    assert done.status_code == 201, done.text
    record = done.json()["confirmation"]
    assert (record["actor"], record["workspace_checked"]) == ("owner", True)
    # 재전송은 같은 기록.
    again = _confirm(h, case_id, "side-unknown-1", reason="다른 사유")
    assert again.status_code == 200 and again.json()["confirmation"]["confirmed_at"] == record["confirmed_at"]

    conv = _drive(h, case_id)
    assert conv["progress"]["state"] == "done", conv["progress"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    run = _run(h, "side-unknown-1")
    assert run["outcome"] == "unknown"
    assert run["unknown_settlement"]["kind"] == "confirmed"
    assert run["unknown_settlement"]["reason"] == "출력과 작업 폴더를 보고 영향 없음을 확인"
    decisions = Repository(h.client.app.state.conn).conn.execute(
        "SELECT kind, subject_type, subject_id FROM decision WHERE case_id = ? AND kind = 'unknown_run_confirmation'",
        (case_id,),
    ).fetchall()
    assert [tuple(d) for d in decisions] == [("unknown_run_confirmation", "run", "side-unknown-1")]
    # 종료 뒤에는 확인을 받지 않는다.
    assert _confirm(h, case_id, "side-unknown-1").status_code in (200, 409)


def test_a_person_cannot_confirm_a_run_whose_end_is_not_confirmed(processing_harness):
    """AC-4 — 트리 종료를 모르는 `unknown` 은 사람이 대신 확인하지 않는다(UI-02). 카드에는 보이되 확인할 수 없다.
    `unknown` 이 아닌 실행·다른 Case 의 실행도 거부한다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    _side_unknown_run(h, case_id, "side-unknown-2", residual="unknown")
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["unsettled_runs"], conv["progress"]
    [entry] = conv["progress"]["wait"][0]["runs"]
    assert (entry["ended_confirmed"], entry["confirmable"]) == (False, False)
    refused = _confirm(h, case_id, "side-unknown-2")
    assert refused.status_code == 409 and "execution_unconfirmed" in refused.text
    completed = next(r for r in _runs(h, case_id) if r["outcome"] == "completed")
    assert _confirm(h, case_id, completed["run_id"]).status_code == 409
    other = h.create_conversation(_project["id"], "다른 대화")
    assert _confirm(h, other["case_id"], "side-unknown-2").status_code == 404

    # PC 가 종료를 확인하면 풀리고 진행이 이어져 닫힌다.
    run = _run(h, "side-unknown-2")
    rechecked = h.client.post(
        "/api/runner/runs/side-unknown-2/residual",
        json={"runner_id": "runner-test-1", "residual": "none", "basis": "job_terminated", "terminated": 0},
    )
    assert rechecked.status_code == 200, rechecked.text
    assert run["outcome"] == "unknown"
    conv = _drive(h, case_id)
    assert conv["progress"]["state"] == "waiting_human", conv["progress"]  # 종료 확인만으로는 대체가 아니다
    [entry] = conv["progress"]["wait"][0]["runs"]
    assert (entry["ended_confirmed"], entry["confirmable"]) == (True, True)
    assert _confirm(h, case_id, "side-unknown-2").status_code == 201
    assert _drive(h, case_id)["progress"]["state"] == "done"


# ============================================================== 이미 걸린 Case 의 복구 (이슈 #10 모양)


def test_a_case_stuck_on_runs_unsettled_closes_on_restart_recovery(processing_harness):
    """AC-5 — 이슈 #10 모양: T2-1·T2-2 `unknown`(종료 확인) 뒤 사람이 상한을 올려 T2-3 가 완료했고, 고치기 전 진행기가
    진행 요청을 `processing`·진행 `running` 으로 남겼다. 재시작 복구(`recover`)가 그 Case 를 닫고 요청을 끝낸다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    executor = h.agent.cli_executor
    executor.unknown = lambda call: "task-T2" in call["run_id"]
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["task_failed"], conv["progress"]
    executor.unknown = None
    repo = Repository(h.client.app.state.conn, auto_process_requests=True)
    # 사람이 상한을 올리면 T2-3 이 돌아 완료한다(이슈 #10 의 13:26 시도).
    h.client.put(f"/api/cases/{case_id}/progress/limits", json={"task_retry_limit": 2, "reason_summary": "다시"})
    for _ in range(10):
        h.agent.poll_once()
    t2 = [r for r in _runs(h, case_id) if r["task_id"] == "T2"]
    assert [r["outcome"] for r in t2] == ["unknown", "unknown", "completed"], t2
    # 고친 코드에서는 여기서 이미 닫힌다. 고치기 전 코드가 남긴 상태(요청 processing · 진행 running · 닫히지 않음)를
    # DB 에 되돌려 만든 뒤 재시작 복구만 돌린다.
    assert h.client.get(f"/api/cases/{case_id}").json()["result"]["closure"] is not None
    conn = h.client.app.state.conn
    request_id = t2[2]["request_id"]
    conn.execute("DELETE FROM closure_record WHERE case_id = ?", (case_id,))
    conn.execute("DELETE FROM final_acceptance WHERE case_id = ?", (case_id,))
    conn.execute("DELETE FROM decision WHERE case_id = ? AND kind = 'final_acceptance'", (case_id,))
    conn.execute('UPDATE "case" SET status = ? WHERE id = ?', ("in_progress", case_id))
    conn.execute(
        "UPDATE conversation_request SET state = 'processing', settled_at = NULL, settled_by = NULL,"
        " outcome_reason = NULL WHERE id = ?",
        (request_id,),
    )
    conn.execute(
        "UPDATE case_progress SET state = 'running', step = 'task:T2', request_id = ?, wait_json = '[]'"
        " WHERE case_id = ?",
        (request_id, case_id),
    )
    conn.commit()
    assert [r["id"] for r in _processing(h, case_id)] == [request_id]

    counts = WorkProgressor(repo, enabled=True).recover()
    assert counts == {"advanced": 1, "paused": 0}
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed", case["result"]
    assert _processing(h, case_id) == []
    assert h.conversation(case_id)["progress"]["state"] == "done"
    assert [_run(h, r["run_id"])["unknown_settlement"]["kind"] for r in t2[:2]] == ["superseded", "superseded"]


# ============================================================== 다른 busy 의 보강


def test_the_intent_structure_report_arriving_after_the_result_continues_progress(processing_harness):
    """AC-6 — 의도 구조가 결과 보고 **뒤에** 오면(구조 보고가 늦거나 다시 보낸 경우) 진행기는 그 사이 `intent_structure_pending`
    에서 기다리고, 구조 보고 끝점이 진행기를 불러 이어 간다 — 요청이 "처리 중" 으로 남지 않는다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    held: list[dict] = []
    client = h.agent.client
    real = client.send_intent_structure
    client.send_intent_structure = lambda payload: held.append(payload) or {}
    try:
        for _ in range(3):
            h.agent.poll_once()
    finally:
        client.send_intent_structure = real
    assert len(held) == 1
    conv = h.conversation(case_id)
    # 구조 없이 결과만 왔다 — 진행은 `running` 에 머문다(사용자 요청은 처리기가 끝냈다). 뒤따를 보고가 구조 보고다.
    assert (conv["progress"]["state"], conv["progress"]["step"]) == ("running", "intent_authoring"), conv["progress"]
    assert all(r["status"] == "finished" for r in h.client.get(f"/api/cases/{case_id}").json()["runs"])

    reported = h.client.post("/api/runner/intent-structure", json=held[0])
    assert reported.status_code == 200, reported.text
    conv = _drive(h, case_id)
    # 구조가 붙은 뒤 진행이 이어졌다 — 의도 단계의 사람 대기(동의 등)에서 멈추고 요청은 끝났다.
    assert conv["progress"]["state"] == "waiting_human", conv["progress"]
    assert _wait_codes(conv) and "intent_structure_pending" not in _wait_codes(conv)
    assert _processing(h, case_id) == []


def test_migration_to_v30_keeps_rows_and_adds_the_confirmation_table(tmp_path):
    """AC-8 — v29 DB 를 올리면 확인 표가 생기고 기존 행은 그대로다(데이터 이행 없음)."""
    path = tmp_path / "c.sqlite3"
    conn = db.connect(path)
    db.migrate(conn)
    assert db.SCHEMA_VERSION >= 30
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "run_unknown_confirmation" in names
    conn.execute("DROP TABLE run_unknown_confirmation")
    conn.execute("DELETE FROM schema_version WHERE version >= 30")
    conn.commit()
    db.migrate(conn)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "run_unknown_confirmation" in names
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 30
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO run_unknown_confirmation (run_id, case_id, decision_id, actor, reason, workspace_checked,"
            " confirmed_at) VALUES ('r', 'c', 'd', 'owner', 'x', 0, 'now')"
        )
