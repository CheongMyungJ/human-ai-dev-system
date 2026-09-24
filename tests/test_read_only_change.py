"""P4-10b (D-96) — CLI 권한 전부 허용 뒤 **읽기 전용 실행의 변경 감지·알림**(plans/P4-PLAN-10b.md AC-3~5).

    막지 못하면 드러낸다      읽기 전용 실행 전후의 작업 트리를 대조해 바뀌었으면 결과에 싣고 제어부가 적는다
    실패로 표시하지 않는다     결과(`completed`)·응답은 그대로 — 사람에게 알리기만 한다(사용자 결정)
    사실만 올라간다            자리 이름(작업공간·원래 저장소)뿐, 경로·본문 없음
    모르면 모른다              git 저장소가 아니면 `unobserved`

**실제 CLI 를 부르지 않는다.** `conftest` 의 가짜 실행기가 읽기 전용 실행에서 파일을 쓰게 해 Runner 의 실제 대조 경로를 지난다.
"""

from __future__ import annotations

import pytest

from controller.repository import ConflictError, Repository
from domain.models import RunOutcome


def _discussion(h, *, git: bool, writes: dict[str, str] | None) -> tuple[dict, str]:
    if git:
        project, _repo_path = h.create_git_project("읽기 전용 감지")
    else:
        project = h.create_project("git 아님")
    case_id = h.create_conversation(project["id"], "논의")["case_id"]
    executor = h.agent.cli_executor
    executor.residual_activity = "none"
    executor.residual_basis = "in_process"
    executor.read_only_write_files = dict(writes or {})
    h.send_message(case_id, "이 저장소 구조를 설명해줘", "c-1")
    h.agent.poll_once()
    return project, case_id


def _reply_run(h, case_id: str) -> dict:
    [run] = [r for r in h.client.get(f"/api/cases/{case_id}").json()["runs"] if r["purpose"] == "discussion_reply"]
    return run


def test_a_read_only_run_that_changes_the_folder_is_reported_but_not_failed(processing_harness):
    """AC-3·AC-4 — 논의 응답(읽기 전용, 원래 저장소에서 돈다)이 파일을 쓰면 결과는 `completed` 그대로이고 응답도 대화에
    붙는다. 실행에 `read_only_change{changed, where: [original_repo]}` 가 적히고, 대화 조회·목록 행의 수·진행 이력이
    그것을 보인다. 경로·본문은 올라오지 않는다."""
    h = processing_harness
    project, case_id = _discussion(h, git=True, writes={"stray.txt": "read-only run wrote this\n"})
    run = _reply_run(h, case_id)
    assert run["outcome"] == "completed" and run["permission"] == "read_only"
    assert run["read_only_change"] == {
        "observed": True, "changed": True, "where": ["original_repo"], "unobserved": [],
    }
    conv = h.conversation(case_id)
    assert [m["author"] for m in conv["messages"]] == ["user", "assistant"]  # 응답은 그대로 붙었다
    assert [(c["run_id"], c["where"]) for c in conv["read_only_changes"]] == [(run["run_id"], ["original_repo"])]
    rows = h.client.get(f"/api/projects/{project['id']}/conversations").json()
    row = next(r for r in (rows["conversations"] if isinstance(rows, dict) else rows) if r["id"] == case_id)
    assert row["read_only_changes"] == 1
    events = [e for e in Repository(h.client.app.state.conn).list_progress_events(case_id) if e["step"] == "read_only_changed"]
    assert len(events) == 1 and events[0]["run_id"] == run["run_id"] and "stray.txt" not in (events[0]["detail"] or "")


def test_an_untouched_folder_is_observed_and_unchanged_and_a_non_git_folder_is_unobserved(processing_harness):
    """AC-3 — 바꾸지 않으면 `changed = false`(관측함). git 저장소가 아니면 `unobserved` — 바뀌지 않음으로 읽지 않는다."""
    h = processing_harness
    _project, case_id = _discussion(h, git=True, writes=None)
    change = _reply_run(h, case_id)["read_only_change"]
    assert change == {"observed": True, "changed": False, "where": [], "unobserved": []}
    assert h.conversation(case_id)["read_only_changes"] == []

    _project, other = _discussion(h, git=False, writes={"stray.txt": "x"})
    change = _reply_run(h, other)["read_only_change"]
    assert change["observed"] is False and change["changed"] is False and change["unobserved"] == ["original_repo"]


def test_only_a_read_only_run_may_carry_the_report_and_only_place_names_are_kept(processing_harness):
    """AC-5 — 쓰기 권한 실행이 보낸 읽기 전용 변경 보고는 거부한다. 모르는 자리 이름(경로 같은 것)은 버린다."""
    h = processing_harness
    repo = Repository(h.client.app.state.conn)
    kept = repo._read_only_change_json(
        {"observed": True, "changed": True, "where": ["C:/Users/secret/file.txt", "workspace"], "unobserved": ["x"]}
    )
    assert kept == '{"observed": true, "changed": true, "where": ["workspace"], "unobserved": []}'
    only_path = repo._read_only_change_json({"observed": True, "changed": True, "where": ["C:/a"]})
    assert '"changed": false' in only_path

    from tests.test_work_progressor import _agree, _drive, _runs, _start

    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    _drive(h, case_id, polls=30)
    write_run = next(r for r in _runs(h, case_id) if r["permission"] == "workspace_write")
    with pytest.raises(ConflictError):
        repo.report_result(
            run_id=write_run["run_id"],
            generation=write_run["assignment_generation"],
            outcome=RunOutcome(write_run["outcome"]),
            read_only_change={"observed": True, "changed": True, "where": ["workspace"]},
        )
