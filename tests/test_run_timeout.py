"""P4-10 (이슈 #8, D-95) — 실행 제한 시간의 설정화와 시간 초과의 구분(plans/P4-PLAN-10.md AC-1~6).

    제한은 설정이다              Case 명시 → 프로젝트 기본값 → 시스템 기본값(1시간). 실행을 만들 때 적는다(다음 실행부터)
    Runner 가 그 제한으로 끊는다   결과에 `stop_reason = timeout`·적용 제한. 결과는 `unknown` 그대로(실패가 아니다)
    같은 제한으로 되풀이하지 않는다 진행기가 `run_timed_out` 사람 대기로 멈춘다. 재시도 상한을 쓰지 않는다
    늘리면 이어 간다              제한을 올리면 새 제한으로 다시 돌고, 끊긴 실행은 종료를 막지 않는다
    부분 결과는 판정에 쓰지 않는다

Runner 의 실제 끊기(AC-2)는 PATH 의 시험용 `codex.cmd`(가짜 codex, 실제 프로세스 트리)로 본다. 나머지는 `conftest` 의
가짜 실행기로 진행기 경유 흐름을 돈다. **AI 를 부르지 않는다.**
"""

from __future__ import annotations

import json
import time

import pytest

from controller.repository import ConflictError, Repository
from domain.models import Permission, RunOutcome
from runner import process_tree
from tests.test_process_control import _execute, _pids, _wait_dead, fake_codex  # noqa: F401 — 픽스처
from tests.test_work_progressor import _agree, _drive, _runs, _start, _wait_codes


def _limits(h, case_id: str) -> dict:
    return h.client.get(f"/api/cases/{case_id}/progress").json()["limits"]


def _set(h, case_id: str, **values) -> None:
    response = h.client.put(f"/api/cases/{case_id}/progress/limits", json={**values, "reason_summary": "긴 빌드"})
    assert response.status_code == 200, response.text


def _run(h, run_id: str) -> dict:
    return h.client.get(f"/api/runs/{run_id}").json()


# ============================================================== AC-1 설정·적용 시점


def test_the_run_timeout_is_a_setting_recorded_on_each_new_run(processing_harness):
    """AC-1 — 새 실행은 그때의 유효 제한을 적는다(기본 3600초, 시스템 기본값). Case 에서 바꾸면 **다음** 실행부터 새
    값·출처·이력이 남고 이미 만든 실행은 그대로다. 범위 밖(10초 미만·24시간 초과)은 거부한다. 프로젝트 기본값은 그 뒤
    만든 대화에 적용된다. Runner 는 배정의 값을 실행기에 넘긴다."""
    h = processing_harness
    project, case_id, _request_id = _start(h)
    first = _runs(h, case_id)
    assert first and all(r["timeout_seconds"] == 3600 for r in first)
    limits = _limits(h, case_id)
    assert (limits["run_timeout_seconds"]["value"], limits["run_timeout_seconds"]["source"]) == (3600, "system_default")
    assert h.agent.cli_executor.calls[-1]["timeout"] == 3600

    _set(h, case_id, run_timeout_seconds=7200)
    limits = _limits(h, case_id)
    assert (limits["run_timeout_seconds"]["value"], limits["run_timeout_seconds"]["source"]) == (7200, "case_setting")
    assert [(r["limit_key"], r["limit_value"], r["reason_summary"]) for r in limits["history"]] == [
        ("run_timeout_seconds", 7200, "긴 빌드")
    ]
    _drive(h, case_id)
    _agree(h, case_id)
    _drive(h, case_id, polls=30)
    newer = [r for r in _runs(h, case_id) if r["run_id"] not in {f["run_id"] for f in first}]
    assert newer and all(r["timeout_seconds"] == 7200 for r in newer)
    assert all(r["timeout_seconds"] == 3600 for r in _runs(h, case_id) if r["run_id"] in {f["run_id"] for f in first})
    assert h.agent.cli_executor.calls[-1]["timeout"] == 7200

    for bad in (5, 86401, 0):
        refused = h.client.put(f"/api/cases/{case_id}/progress/limits", json={"run_timeout_seconds": bad})
        assert refused.status_code == 422, (bad, refused.text)

    saved = h.client.put(
        f"/api/projects/{project['id']}/settings", json={"values": {"run_timeout_seconds": 1800}}
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["settings"]["run_timeout_seconds"]["value"] == 1800
    view = h.create_conversation(project["id"], "다른 대화")
    later = _limits(h, view["case_id"])
    assert (later["run_timeout_seconds"]["value"], later["run_timeout_seconds"]["source"]) == (1800, "project_setting")
    # 이 대화는 Case 설정이 앞선다.
    assert _limits(h, case_id)["run_timeout_seconds"]["value"] == 7200


# ============================================================== AC-3 결과 기록의 경계


def test_a_stop_reason_must_match_the_outcome(tmp_path):
    """AC-3 — 시간 초과는 `unknown` 과만, 사람의 중단은 완료가 아닐 때만 받는다(끊긴 것은 결과가 아니라 이유다)."""
    from controller import db

    conn = db.connect(tmp_path / "c.sqlite3")
    db.migrate(conn)
    repo = Repository(conn)
    for outcome, reason in (
        (RunOutcome.COMPLETED, "timeout"),
        (RunOutcome.FAILED, "timeout"),
        (RunOutcome.COMPLETED, "stop_requested"),
        (RunOutcome.UNKNOWN, "nap"),
    ):
        with pytest.raises(ConflictError):
            repo.report_result(run_id="run-x", generation=1, outcome=outcome, stop_reason=reason)


# ============================================================== AC-4·5·6 진행기


def test_a_timed_out_task_waits_for_a_longer_limit_instead_of_retrying_and_then_closes(processing_harness):
    """AC-4·5·6 — 검증 T2 가 제한에 걸려 끊기면(`unknown`·`timeout`) 진행기는 같은 제한으로 다시 돌리지 않고
    `run_timed_out` 대기(실행·적용 제한·지금 제한·출처)로 멈춘다. `다시 시도` 해도 같은 제한이면 새 실행이 없다(재시도
    상한도 쓰지 않는다). 제한을 늘리면 T2 가 새 제한으로 다시 돌아 기준을 적고 자동 완료한다 — 끊긴 실행은 종료를
    막지 않는다. 끊긴 실행의 기준 보고는 판정에 쓰지 않는다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    executor = h.agent.cli_executor
    executor.times_out = lambda call: "task-T2-1" in call["run_id"]
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["run_timed_out"], conv["progress"]
    [wait] = conv["progress"]["wait"]
    cut = next(r for r in _runs(h, case_id) if r["task_id"] == "T2")
    assert wait["run_id"] == cut["run_id"] and wait["task_key"] == "T2" and wait["purpose"] == "verification_run"
    assert (wait["timeout_seconds"], wait["limit"], wait["limit_source"]) == (3600, 3600, "system_default")
    assert (cut["outcome"], cut["stop_reason"], cut["timeout_seconds"]) == ("unknown", "timeout", 3600)
    assert all(c["verdict"] != "met" and c.get("evidence_run_id") != cut["run_id"] for c in h.criteria(case_id))
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "waiting_human"

    # 같은 제한의 `다시 시도` 는 새 실행을 만들지 않는다.
    before = len(_runs(h, case_id))
    assert h.client.post(f"/api/cases/{case_id}/progress/resume", json={"actor": "owner"}).status_code == 200
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["run_timed_out"] and len(_runs(h, case_id)) == before

    # 부분 결과는 판정에 쓰지 않는다(보고가 있어도).
    repo = Repository(h.client.app.state.conn)
    repo.conn.execute(
        "UPDATE run SET criteria_report_json = ? WHERE run_id = ?",
        (json.dumps([{"key": "C-01", "verdict": "not_met", "summary": "끊기기 전 본 것"}]), cut["run_id"]),
    )
    assert repo.apply_criteria_report(cut["run_id"]) == [
        {"key": "C-01", "recorded": False, "reason": "run_timed_out"}
    ]

    _set(h, case_id, run_timeout_seconds=7200)
    conv = _drive(h, case_id, polls=30)
    assert conv["progress"]["state"] == "done", conv["progress"]
    t2 = [r for r in _runs(h, case_id) if r["task_id"] == "T2"]
    assert [(r["outcome"], r["timeout_seconds"]) for r in t2] == [("unknown", 3600), ("completed", 7200)]
    assert all(c["verdict"] == "met" and c["evidence_run_id"] == t2[1]["run_id"] for c in h.criteria(case_id))
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    assert conv["progress"]["attempts"]["task:T2"] == 2


def test_a_second_timeout_after_raising_waits_again_not_as_a_failure(processing_harness):
    """AC-4 — 늘린 제한에서도 끊기면 다시 `run_timed_out`(새 제한)이고 `task_failed`(거듭 실패)가 아니다 — 시간 초과는
    재시도 상한의 소비가 아니다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    h.agent.cli_executor.times_out = lambda call: "task-T2" in call["run_id"]
    _drive(h, case_id, polls=30)
    _set(h, case_id, run_timeout_seconds=5400)
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["run_timed_out"], conv["progress"]
    [wait] = conv["progress"]["wait"]
    assert (wait["timeout_seconds"], wait["limit"], wait["limit_source"], wait["timeouts"]) == (5400, 5400, "case_setting", 2)


# ============================================================== AC-2 Runner 의 실제 끊기


@pytest.mark.skipif(not process_tree.IS_WINDOWS, reason="프로세스 트리 제어는 Windows 에서만 지원한다")
def test_the_adapter_cuts_the_cli_tree_at_the_given_limit(fake_codex):  # noqa: F811
    """AC-2 — 실행기는 호출별 제한(여기서는 2초)으로 CLI 트리를 끊고 `unknown`·`stop_reason = timeout`·적용 제한을
    낸다. 손자까지 끝났는지는 OS 에서 따로 본다. 제한을 주지 않으면 기본 1시간이다."""
    started = time.monotonic()
    output = _execute(fake_codex, "HADS_FAKE_SLEEP=90 기다려 주세요", "run-pt-timeout", timeout=2)
    assert time.monotonic() - started < 40
    assert output.outcome is RunOutcome.UNKNOWN
    assert (output.stop_reason, output.timeout_seconds) == ("timeout", 2.0)
    assert (output.residual_activity, output.residual_basis) == ("none", "job_terminated")
    for pid in _pids(fake_codex["pids"], "grandchild") + _pids(fake_codex["pids"], "cli"):
        assert _wait_dead(pid), pid
    body = output.output_body.decode("utf-8")
    assert "stop_reason=timeout" in body and "timeout_seconds=2" in body

    from runner import cli_adapter

    assert cli_adapter.DEFAULT_TIMEOUT_SECONDS == 3600.0
    assert cli_adapter.CliExecutor(fake_codex["effects"]).timeout == 3600.0
    assert Permission.READ_ONLY  # 읽기 전용 실행도 같은 제한을 받는다(_execute 가 읽기 전용이다)


# ============================================================== AC-12 이행


def test_a_v28_limit_table_is_rebuilt_with_the_new_keys_and_old_rows_stay(tmp_path):
    """AC-12 — v28 의 `progress_limit_setting`(키 둘·0~10)이 새 키 둘과 키별 범위로 다시 만들어지고 옛 행은 그대로다.
    옛 실행의 제한·끊긴 이유는 NULL(기록 없음)이다. DB 가 키별 범위의 마지막 방어선이다."""
    import sqlite3

    from controller import db
    from controller.db import utc_now

    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    db.migrate(conn)
    now = utc_now()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TABLE progress_limit_setting")
    conn.execute(
        "CREATE TABLE progress_limit_setting (id TEXT PRIMARY KEY, case_id TEXT NOT NULL REFERENCES \"case\"(id),"
        " revision INTEGER NOT NULL,"
        " limit_key TEXT NOT NULL CHECK (limit_key IN ('repair_limit', 'task_retry_limit')),"
        " limit_value INTEGER NOT NULL CHECK (limit_value BETWEEN 0 AND 10), set_by TEXT NOT NULL,"
        " reason_summary TEXT, state TEXT NOT NULL CHECK (state IN ('current', 'superseded')),"
        " created_at TEXT NOT NULL, superseded_at TEXT, UNIQUE (case_id, revision),"
        " CHECK (reason_summary IS NULL OR length(reason_summary) <= 200))"
    )
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1', 'prj-1', 'old', 'feature', 'in_progress', ?, ?)", (now, now),
    )
    conn.execute(
        "INSERT INTO progress_limit_setting (id, case_id, revision, limit_key, limit_value, set_by, state, created_at)"
        " VALUES ('pl-1', 'case-1', 1, 'repair_limit', 3, 'owner', 'current', ?)", (now,)
    )
    conn.execute("DELETE FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,))
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (28, ?)", (now,))
    conn.commit()
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] == db.SCHEMA_VERSION >= 29
    row = dict(conn.execute("SELECT * FROM progress_limit_setting WHERE id = 'pl-1'").fetchone())
    assert (row["limit_key"], row["limit_value"], row["state"]) == ("repair_limit", 3, "current")
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'progress_limit_setting'").fetchone()[0]
    assert "'run_timeout_seconds'" in ddl and "__rebuild" not in ddl
    conn.execute(
        "INSERT INTO progress_limit_setting (id, case_id, revision, limit_key, limit_value, set_by, state, created_at)"
        " VALUES ('pl-2', 'case-1', 2, 'run_timeout_seconds', 7200, 'owner', 'current', ?)", (now,)
    )
    for key, value in (("repair_limit", 11), ("remediation_limit", 3600), ("run_timeout_seconds", 5)):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO progress_limit_setting (id, case_id, revision, limit_key, limit_value, set_by, state,"
                " created_at) VALUES (?, 'case-1', 9, ?, ?, 'owner', 'current', ?)", (f"bad-{key}", key, value, now)
            )
    columns = {r[1] for r in conn.execute("PRAGMA table_info(run)")}
    assert {"timeout_seconds", "stop_reason"} <= columns
    view = Repository(conn).progress_limits_view("case-1")
    assert (view["repair_limit"]["value"], view["run_timeout_seconds"]["value"]) == (3, 7200)
    db.migrate(conn)  # 멱등
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,)
    ).fetchone()[0] == 1
    conn.close()
