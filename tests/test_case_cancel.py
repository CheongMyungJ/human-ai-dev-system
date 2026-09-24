"""P4-09 (e) — 업무(Case) 취소, 1단계(이슈 #4, plans/P4-PLAN-09.md AC-15~19).

설계(completion-lifecycle 2절)는 취소를 종료 상태의 하나로 정의했지만 그 상태로 가는 경로가 없었다. 이제
**끝나지 않은 실행이 없는 Case** 를 사람의 결정(사유·행위자)으로 취소한다.

    취소는 종료다               `closure_record(cancelled, 후보 없음)`·결정·`status = cancelled`, 요청·진행 종료
    성공도 예외 인수도 아니다    결과·판정·사용량·작업공간(브랜치·worktree)은 그대로 남는다
    실행이 남아 있으면 안 된다   409 `runs_unfinished` — 먼저 중단한다(2단계는 이 판에 없다)
    되돌리지 않는다             취소 뒤 새 실행·정책 변경은 거부, 설명 응답·후속 대화는 된다
    늦은 결과는 아무 것도 일으키지 않는다   취소된 Case 의 결과 뒤 훅은 후보·재시도·다음 걸음을 만들지 않는다
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from controller import db
from controller.db import utc_now
from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE, RUNNER_ID
from tests.test_work_progressor import _agree, _drive, _repo, _runs, _start, _wait_codes


def _cancel(h, case_id: str, reason: str = "방향이 바뀌어 이 업무는 버린다", actor: str = "owner"):
    return h.client.post(f"/api/cases/{case_id}/cancel", json={"actor": actor, "reason": reason})


def _case(h, case_id: str) -> dict[str, Any]:
    return h.client.get(f"/api/cases/{case_id}").json()


# ================================================== AC-15 대기 중 취소


def test_a_waiting_case_is_cancelled_with_a_reason_and_keeps_its_partial_results(processing_harness):
    """AC-15 — 사람 대기(실행 없음)에서 취소: 종료 기록·결정·상태·요청·진행·예약 정리, 결과·작업공간 보존."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    h.agent.cli_executor.write_files = {}  # 구현이 고쳤다고 적지만 바뀐 것이 없다 → 실패 → 사람 대기
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"]
    runs_before = _runs(h, case_id)
    assert all(r["status"] == "finished" for r in runs_before) and len(runs_before) >= 3
    workspace_before = h.workspace(case_id)
    assert workspace_before and workspace_before["state"] == "ready"

    response = _cancel(h, case_id)
    assert response.status_code == 200, response.text
    view = response.json()
    assert view["status"] == "cancelled"
    assert view["cancellation"]["by"] == "owner" and view["cancellation"]["reason"].startswith("방향이 바뀌어")
    closure = view["closure"]
    assert closure["closure_kind"] == "cancelled" and closure["candidate_id"] is None
    assert closure["cancelled_by"] == "owner" and closure["decision_id"]
    assert closure["snapshot_json"]  # 종료 시점의 소비 snapshot(D-87 그대로)
    decisions = _repo(h).conn.execute(
        "SELECT kind, actor FROM decision WHERE case_id = ? ORDER BY decided_at", (case_id,)
    ).fetchall()
    assert any(d["kind"] == "case_cancellation" and d["actor"] == "owner" for d in decisions)
    # 요청은 끝났고 진행은 done/cancelled, 대기 카드가 없다.
    assert view["current_request"] is None
    assert all(r["state"] != "processing" for r in view["requests"])
    assert view["progress"]["state"] == "done" and view["progress"]["step"] == "cancelled"
    assert view["progress"]["wait"] == []
    events = [e["action"] for e in view["progress"]["events"]]
    assert "cancelled" in events
    # 부분 결과·실행·판정·작업공간·사용량은 그대로다.
    assert [r["run_id"] for r in _runs(h, case_id)] == [r["run_id"] for r in runs_before]
    assert h.workspace(case_id)["state"] == "ready"
    assert Path(h.workspace(case_id)["worktree_path"]).is_dir()
    # 열린 예약이 남아 있지 않다.
    repo = _repo(h)
    held = repo.conn.execute(
        "SELECT COUNT(*) FROM budget_reservation WHERE case_id = ? AND state = 'held'", (case_id,)
    ).fetchone()[0]
    assert held == 0
    # 목록 행도 취소를 보인다.
    rows = h.client.get(f"/api/projects/{_project['id']}/conversations").json()
    assert next(r for r in rows if r["id"] == case_id)["status"] == "cancelled"


# ================================================== AC-16 거부


def test_cancelling_with_runs_still_open_or_without_a_reason_or_after_closure_is_refused(processing_harness):
    """AC-16 — 실행이 남아 있으면 409 `runs_unfinished`, 사유 없음 거부, 종료 Case 409."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    # 업무화 직후 — 진행기가 만든 의도 초안 실행이 아직 끝나지 않았다(Runner 를 돌리지 않았다).
    pending = [r for r in _runs(h, case_id) if r["status"] != "finished"]
    assert pending, "끝나지 않은 실행이 있어야 한다"
    refused = _cancel(h, case_id)
    assert refused.status_code == 409 and "runs_unfinished" in refused.text
    assert _case(h, case_id)["status"] != "cancelled"

    assert _cancel(h, case_id, reason="   ").status_code in (409, 422)

    _drive(h, case_id)
    ok = _cancel(h, case_id)
    assert ok.status_code == 200, ok.text
    again = _cancel(h, case_id, reason="한 번 더")
    assert again.status_code == 409 and "case_already_closed" in again.text


# ================================================== AC-17 취소 뒤


def test_after_a_cancellation_new_runs_are_refused_but_explanations_and_a_follow_up_still_work(processing_harness):
    """AC-17 — 새 실행·정책 변경은 거부, 설명 응답은 붙고, 후속 대화를 만들 수 있다. 되돌리기 경로는 없다."""
    h = processing_harness
    _project, case_id, request_id = _start(h)
    _drive(h, case_id)
    assert _cancel(h, case_id).status_code == 200
    opening = h.conversation(case_id)["messages"][0]

    # 새 실행은 진입 검사에서 `case_already_closed` 다.
    refused = h.client.post(
        f"/api/cases/{case_id}/runs",
        json={
            "run_id": "run-after-cancel",
            "instruction_artifact_id": opening["artifact_id"],
            "instruction_artifact_rev": opening["artifact_rev"],
            "purpose": "feature_implementation",
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "workspace_write",
            "task_id": "T1",
        },
    )
    assert refused.status_code == 409 and "case_already_closed" in refused.text
    policy = h.client.put(
        f"/api/cases/{case_id}/autonomy", json={"autonomy": "controlled", "set_by": "owner", "reason": "x"}
    )
    assert policy.status_code == 409, policy.text

    # 설명 응답은 같은 대화에 붙는다(종료 Case 의 설명 전용 진입, D-87 그대로).
    before = len(h.conversation(case_id)["messages"])
    h.agent.cli_executor.discussion_response = "취소된 업무의 결과를 설명합니다.\n\n```hads-interpretation\n{\"kind\": \"discussion\"}\n```"
    h.send_message(case_id, "여기까지 무엇을 했지?", "c-explain")
    h.agent.poll_once()
    conv = h.conversation(case_id)
    assert len(conv["messages"]) >= before + 2
    assert conv["status"] == "cancelled"  # 설명이 상태를 바꾸지 않는다

    # 후속 대화(연결된 새 Case)는 된다 — 취소를 되돌리는 경로는 없다.
    successor = h.client.post(
        f"/api/cases/{case_id}/successor", json={"title": "다시", "profile": "feature", "reason_summary": "새로"}
    )
    assert successor.status_code == 201, successor.text
    resumed = h.client.post(f"/api/cases/{case_id}/progress/resume", json={"actor": "owner"})
    assert resumed.status_code == 409, resumed.text  # 되돌리기 경로가 아니다
    assert _case(h, case_id)["status"] == "cancelled"


# ================================================== AC-18 늦은 결과 무반응


def test_hooks_after_a_cancellation_make_nothing(processing_harness):
    """AC-18 — 취소된 Case 에서 진행기·후보 등록 훅은 아무 것도 만들지 않는다(결과 저장은 이미 됐다)."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    h.agent.cli_executor.write_files = {}
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"]
    assert _cancel(h, case_id).status_code == 200
    repo = _repo(h)
    runs_before = [r["run_id"] for r in _runs(h, case_id)]
    last = _runs(h, case_id)[-1]
    # 결과 뒤 훅을 그 실행으로 다시 부른다 — 후보 블록이 있었더라도 등록하지 않고, 다음 걸음도 없다.
    repo.conn.execute(
        "UPDATE run SET knowledge_report_json = ? WHERE run_id = ?",
        (json.dumps([{"kind": "operation", "obligation": "reference", "summary": "늦은 후보",
                      "artifact_id": last["output_artifact_id"] or "x", "revision": 1, "activities": []}]),
         last["run_id"]),
    )
    repo.conn.commit()
    assert repo.apply_extraction_report(last["run_id"]) == []
    assert repo.conn.execute("SELECT COUNT(*) FROM knowledge_intake WHERE case_id = ?", (case_id,)).fetchone()[0] == 0
    from controller.work_progressor import WorkProgressor

    progressor = WorkProgressor(repo, enabled=True)
    assert progressor.on_run_finished(last) is None
    assert progressor.on_human_input(case_id, origin_ref="late") is None
    assert progressor.on_workspace_reported(case_id) is None
    assert [r["run_id"] for r in _runs(h, case_id)] == runs_before
    assert h.conversation(case_id)["progress"]["state"] == "done"


# ================================================== AC-19 이행


def test_an_old_closure_record_survives_the_v28_rebuild_and_the_check_holds(tmp_path):
    """AC-19 — v27 의 `closure_record`(후보 필수) 행이 그대로 남고, 새 CHECK 가 후보 없는 완료를 막는다."""
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    db.migrate(conn)
    now = utc_now()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1', 'prj-1', 'old', 'feature', 'closed', ?, ?)", (now, now),
    )
    conn.execute(
        "INSERT INTO closure_record (id, case_id, candidate_id, final_acceptance_id, closure_kind,"
        " exception_count, confirmed_at, snapshot_json) VALUES ('clo-1', 'case-1', 'cand-1', 'acc-1',"
        " 'completed', 0, ?, NULL)", (now,)
    )
    # v27 로 되돌려 이행을 다시 돌린다(표 재구성 경로).
    conn.execute("DELETE FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,))
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (27, ?)", (now,))
    conn.commit()
    conn.close()
    conn = db.connect(path)
    db.migrate(conn)
    row = dict(conn.execute("SELECT * FROM closure_record WHERE case_id = 'case-1'").fetchone())
    assert row["candidate_id"] == "cand-1" and row["closure_kind"] == "completed"
    assert row["cancelled_by"] is None and row["cancel_reason"] is None and row["decision_id"] is None
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'closure_record'").fetchone()[0]
    assert "closure_kind = 'cancelled'" in ddl and "closure_record__rebuild" not in ddl
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO closure_record (id, case_id, candidate_id, closure_kind, exception_count, confirmed_at)"
            " VALUES ('clo-2', 'case-1', NULL, 'completed', 0, ?)", (now,)
        )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO closure_record (id, case_id, candidate_id, closure_kind, exception_count, confirmed_at)"
            " VALUES ('clo-3', 'case-1', NULL, 'cancelled', 0, ?)", (now,)  # 취소인데 행위자 없음
        )
    db.migrate(conn)  # 멱등
    assert conn.execute("SELECT COUNT(*) FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,)).fetchone()[0] == 1
    conn.close()
