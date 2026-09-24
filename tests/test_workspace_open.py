"""UI-04c — 외부 편집·작업 PC 열기(D-89)(plans/UI-PLAN-04c.md 4·5절).

직접 파일 편집은 외부 편집기가 한다. 앱은 작업 PC 이름·경로·복사를 보이고, 폴더·편집기 열기는 **지원을
확인한 작업 PC** 에서만 한다. 외부 변경은 다음 쓰기 실행 전에 확인·보존한다.

이 파일이 지키는 것:

    열기는 Runner 명령이다        브라우저는 경로를 주지 못하고 Runner 는 자기 worktree 만 연다
    확인한 것만 지원이다          능력 행이 `verified` 일 때만 받고, 미연결 PC 는 거부한다
    열기는 권한이 아니다          쓰기 허용·진입 검사·동의를 바꾸지 않는다
    외부 변경은 드러내되 되돌리지 않는다  실행 전 지문 대조가 기록되고 파일은 그대로다

시험 이름 옆의 AC 번호는 UI-PLAN-04c 4절이다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from runner import desktop
from tests.conftest import RUNNER_ID, fake_capabilities
from tests.test_workspace import _agreed_git_case, _impl, _ready_case

OPEN_ROWS = [
    {"tool_id": "runner-host", "mode": "desktop", "capability": "open_folder", "state": "verified", "source": "시험 opener"},
    {"tool_id": "runner-host", "mode": "desktop", "capability": "open_editor", "state": "verified", "source": "시험 opener"},
]


# ================================================== 순수 — 능력 보고


def test_desktop_support_is_reported_only_when_found(monkeypatch):
    """AC-12 — `HADS_RUNNER_DESKTOP=off` 면 둘 다 `unsupported`(사유는 그 설정). 켜져 있으면 이 PC 에서 실제로 찾은
    것만 `verified` 다. 능력 행은 `runner-host/desktop` 이며 코딩 CLI 행이 아니다."""
    monkeypatch.setenv(desktop.ENV_DESKTOP, "off")
    found = desktop.detect()
    assert {k: v["state"] for k, v in found.items()} == {"open_folder": "unsupported", "open_editor": "unsupported"}
    assert all(desktop.ENV_DESKTOP in v["source"] for v in found.values())
    rows = desktop.capabilities()
    assert {(r["tool_id"], r["mode"], r["capability"], r["state"]) for r in rows} == {
        ("runner-host", "desktop", "open_folder", "unsupported"),
        ("runner-host", "desktop", "open_editor", "unsupported"),
    }
    assert desktop.supported("folder") == (False, found["open_folder"]["source"])
    with pytest.raises(RuntimeError):
        desktop.open_path("folder", str(Path.cwd()))

    monkeypatch.delenv(desktop.ENV_DESKTOP, raising=False)
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: None)
    found = desktop.detect()
    assert found["open_editor"]["state"] == "unsupported" and "code" in found["open_editor"]["source"]
    monkeypatch.setattr(desktop.shutil, "which", lambda _name: r"C:\tools\code.cmd")
    assert desktop.detect()["open_editor"] == {"state": "verified", "source": r"code on PATH: C:\tools\code.cmd"}


# ================================================== 도우미


def _register(harness, rows: list[dict[str, Any]]) -> None:
    response = harness.client.post(
        "/api/runner/register",
        json={"runner_id": RUNNER_ID, "name": RUNNER_ID, "host": "test-host", "capabilities": fake_capabilities() + rows},
    )
    assert response.status_code in (200, 201), response.text


def _open(harness, case_id: str, repository_id: str, target: str = "folder"):
    return harness.client.post(
        f"/api/cases/{case_id}/workspaces/{repository_id}/open", json={"target": target, "requested_by": "owner"}
    )


def _db(harness) -> sqlite3.Connection:
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _recording_opener(calls: list[tuple[str, str]]):
    def opener(target: str, path: str) -> None:
        calls.append((target, path))

    return opener


# ================================================== AC-12 지원·열기


def test_open_is_refused_without_a_verified_pc_and_a_connection(harness):
    """AC-12(a·b) — 능력 보고가 없거나 `unsupported` 면 409 `open_unsupported`, 미연결 PC 는 409 `runner_disconnected`.
    어느 경우에도 요청 행이 생기지 않는다."""
    case, _repo = _agreed_git_case(harness, name="open-refuse")
    workspace = harness.prepare_workspace(case["id"])
    assert workspace["state"] == "ready"
    repo_id = workspace["repository_id"]
    view = harness.workspace(case["id"])
    assert view["runner"]["runner_id"] == RUNNER_ID and view["runner"]["host"] == "test-host"
    assert view["open_support"]["open_folder"]["state"] == "unknown"

    refused = _open(harness, case["id"], repo_id)
    assert refused.status_code == 409 and "open_unsupported" in refused.text
    _register(harness, [dict(OPEN_ROWS[0], state="unsupported", source="이 OS 는 확인하지 않았다"), OPEN_ROWS[1]])
    refused = _open(harness, case["id"], repo_id, "folder")
    assert refused.status_code == 409 and "open_unsupported" in refused.text and "확인하지 않았다" in refused.text
    assert harness.workspace(case["id"])["open_support"]["open_folder"]["state"] == "unsupported"

    harness.age_heartbeat(3600 * 2)
    refused = _open(harness, case["id"], repo_id, "editor")
    assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["runner_disconnected"]
    assert harness.workspace(case["id"])["open_requests"] == []
    assert _open(harness, case["id"], repo_id, "window").status_code == 422


def test_a_verified_pc_opens_only_its_own_worktree_and_reports_the_result(harness):
    """AC-12(c) — 지원·연결이면 `pending` → heartbeat 제어로 전달 → Runner 가 자기 worktree 만 연다(시험 opener 기록)
    → `done`. 경로가 이 Runner 의 자리가 아니면 `failed`/`path_not_owned` 이고 opener 는 불리지 않는다. 열기는 쓰기
    허용을 만들지 않는다."""
    calls: list[tuple[str, str]] = []
    harness.agent.opener = _recording_opener(calls)
    _register(harness, OPEN_ROWS)
    case, _repo = _agreed_git_case(harness, name="open-done")
    workspace = harness.prepare_workspace(case["id"])
    repo_id = workspace["repository_id"]

    accepted = _open(harness, case["id"], repo_id, "folder")
    assert accepted.status_code == 202, accepted.text
    request = accepted.json()
    assert (request["state"], request["target"], request["runner_id"]) == ("pending", "folder", RUNNER_ID)
    assert "worktree_path" not in request  # 요청에는 경로가 없다
    assert harness.workspace(case["id"])["open_requests"][0]["state"] == "pending"

    tick = harness.agent.control_tick()
    assert [o["state"] for o in tick["controls"]["opened"]] == ["done"]
    assert calls == [("folder", workspace["worktree_path"])]
    latest = harness.workspace(case["id"])["open_requests"][0]
    assert (latest["id"], latest["state"], latest["result_reason"]) == (request["id"], "done", None)
    assert latest["delivered_at"] and latest["finished_at"]
    # 두 번째 heartbeat 는 같은 요청을 다시 전달하지 않는다.
    assert harness.agent.control_tick()["controls"]["opened"] == [] and len(calls) == 1

    editor = _open(harness, case["id"], repo_id, "editor").json()
    harness.agent.control_tick()
    assert calls[-1] == ("editor", workspace["worktree_path"])
    assert harness.client.get(f"/api/cases/{case['id']}/workspace").json()["workspaces"][0]["open_requests"][0]["id"] == editor["id"]

    # 제어부 행의 경로가 이 Runner 의 자리가 아니면 열지 않는다.
    conn = _db(harness)
    try:
        conn.execute(
            "UPDATE case_workspace SET worktree_path = ? WHERE case_id = ? AND repository_id = ?",
            (str(Path(harness.tmp_path) / "somewhere-else"), case["id"], repo_id),
        )
        conn.commit()
    finally:
        conn.close()
    foreign = _open(harness, case["id"], repo_id, "folder").json()
    tick = harness.agent.control_tick()
    assert [(o["state"], o["reason"]) for o in tick["controls"]["opened"]] == [("failed", "path_not_owned")]
    assert len(calls) == 2
    latest = next(r for r in harness.workspace(case["id"])["open_requests"] if r["id"] == foreign["id"])
    assert (latest["state"], latest["result_reason"]) == ("failed", "path_not_owned")

    # 열기는 권한이 아니다 — 저장소 선택·쓰기 허용은 그대로다(선택 기록 없음, 암묵 단일 저장소).
    policy = harness.client.get(f"/api/cases/{case['id']}/policy").json()
    assert policy["repositories"]["selected"] == [] and policy["repositories"]["implicit_single_repository"]
    # 다른 PC 의 결과 보고·이미 끝난 요청은 거부된다.
    other = harness.client.post(
        f"/api/runner/open-requests/{request['id']}/result", json={"runner_id": "runner-x", "state": "done", "reason": None}
    )
    assert other.status_code == 409
    again = harness.client.post(
        f"/api/runner/open-requests/{request['id']}/result", json={"runner_id": RUNNER_ID, "state": "done", "reason": None}
    )
    assert again.status_code == 409


def test_an_undelivered_open_request_expires(harness):
    """AC-12 — 60초 안에 전달되지 않은 요청은 `expired` 가 되고 뒤늦은 Runner 가 열지 않는다."""
    calls: list[tuple[str, str]] = []
    harness.agent.opener = _recording_opener(calls)
    _register(harness, OPEN_ROWS)
    case, _repo = _agreed_git_case(harness, name="open-expire")
    workspace = harness.prepare_workspace(case["id"])
    request = _open(harness, case["id"], workspace["repository_id"]).json()
    old = (datetime.now(timezone.utc) - timedelta(seconds=120)).isoformat()
    conn = _db(harness)
    try:
        conn.execute("UPDATE workspace_open_request SET requested_at = ? WHERE id = ?", (old, request["id"]))
        conn.commit()
    finally:
        conn.close()
    tick = harness.agent.control_tick()
    assert tick["controls"]["opened"] == [] and calls == []
    latest = harness.workspace(case["id"])["open_requests"][0]
    assert (latest["state"], latest["result_reason"]) == ("expired", "not_delivered_in_time")


# ================================================== AC-13 외부 변경


def test_an_external_edit_between_write_runs_is_seen_before_the_next_run_and_kept(harness):
    """AC-13 — 쓰기 실행 A 뒤 사람이 파일 **내용만** 고치면(항목 수·HEAD 그대로) 쓰기 실행 B 가 CLI 를 부르기 전에
    직전 지문과 대조해 `external_change_before_run = true`(근거 A)를 남기고, 조회의 `unexpected_external_change`
    도 참이다. 사람의 편집은 되돌려지지 않는다. 직전 실행이 없으면 `null` 이다."""
    case, _repo = _ready_case(harness, name="ext")
    harness.agent.cli_executor.write_files = {"reader.py": "# 1차\n"}
    assert _impl(harness, case, run_id="run-ext-a").status_code == 201
    harness.agent.poll_once()
    worktree = Path(harness.workspace(case["id"])["worktree_path"])
    assert (worktree / "reader.py").read_text(encoding="utf-8") == "# 1차\n"

    # 사람이 편집기로 같은 파일의 내용만 바꾼다 — 항목 수도 HEAD 도 그대로다.
    (worktree / "reader.py").write_text("# 사람이 직접 고침\n", encoding="utf-8")

    harness.agent.cli_executor.write_files = {"other.py": "# 2차 — 다른 파일\n"}
    assert _impl(harness, case, run_id="run-ext-b").status_code == 201
    harness.agent.poll_once()

    effects = {e["run_id"]: e for e in harness.workspace(case["id"])["run_effects"]}
    assert effects["run-ext-a"]["external_change_before_run"] is None  # 직전 실행 없음 — 모른다
    assert effects["run-ext-a"]["unexpected_external_change"] is False
    assert effects["run-ext-b"]["external_change_before_run"] is True
    assert effects["run-ext-b"]["external_change_basis_run_id"] == "run-ext-a"
    assert effects["run-ext-b"]["unexpected_external_change"] is True  # 지문 비교 — 항목 수·HEAD 는 같다
    assert effects["run-ext-b"]["effect"]["entries_before"] == effects["run-ext-a"]["effect"]["entries_after"]
    assert effects["run-ext-b"]["effect"]["head_before"] == effects["run-ext-a"]["effect"]["head_after"]
    # 보존 — 사람의 편집은 그대로이고 B 의 변경이 그 옆에 있다.
    assert (worktree / "reader.py").read_text(encoding="utf-8") == "# 사람이 직접 고침\n"
    assert (worktree / "other.py").exists()

    # 다음 배정은 B 가 남긴 지문을 싣는다(외부 변경이 없으면 `false`).
    harness.agent.cli_executor.write_files = {"third.py": "# 3차\n"}
    assert _impl(harness, case, run_id="run-ext-c").status_code == 201
    harness.agent.poll_once()
    effects = {e["run_id"]: e for e in harness.workspace(case["id"])["run_effects"]}
    assert effects["run-ext-c"]["external_change_before_run"] is False
    assert effects["run-ext-c"]["external_change_basis_run_id"] == "run-ext-b"
