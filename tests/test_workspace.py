"""P3-03 작업공간·실행 — 자동 시험.

**이 시험들이 지키려는 두 가지:**

    사용자의 원래 작업 트리를 건드리지 않는다.
    바뀌지 않았는데 바뀌었다고 하지 않는다.

첫째가 쓰기 권한을 P3-02까지 열지 않았던 이유다(FR-08·FR-26). 둘째는 P3-02가 연
의존 해제를 지키는 조건이다 — 아무 것도 바꾸지 않은 실행 하나가 완료로 기록되면
후속 Task 가 증거 없이 전부 열린다.

**실제 코딩 CLI를 부르지 않는다.** `conftest` 의 `FakeCliExecutor` 를 쓴다. 다만
**git 은 진짜로 쓴다** — worktree 가 원래 트리를 건드리지 않는다는 것은 흉내로
확인할 수 없기 때문이다. 실제 CLI 연결의 증거는 라이브 검증에서 따로 만든다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import (
    FAKE_TOOL_ID,
    FAKE_TOOL_MODE,
    _git,
    fake_preparation_response,
)
from tests.test_preparation import FIELDS, _prepare_both, _refusals


def _agreed_git_case(harness, dirty: bool = False, name: str = "demo"):
    """실제 git 저장소를 가리키는 프로젝트에서 의도 동의까지 마친 Case.

    `name` 은 프로젝트 이름이자 **실행 id 의 접두사**다. 한 시험이 Case 를 둘
    만들 때 실행 id 가 겹치면 두 번째 요청이 "같은 run_id 의 재전송"으로 읽혀
    아무 것도 만들어지지 않는다(그 멱등성은 P2-01이 일부러 만든 것이다).
    """
    project, repo = harness.create_git_project(name=name, dirty=dirty)
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    intent = harness.latest_intent(case["id"])
    assert harness.ai_gate_review(
        case["id"], intent, run_id=f"run-{name}-review"
    ).status_code == 201
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201
    return case, repo


def _ready_case(harness, dirty: bool = False, workspace: bool = True, name: str = "demo"):
    """구현 배정까지 열 수 있는 Case + 준비된 작업공간.

    `_prepare_both` 가 T1 을 실제 실행으로 끝내므로 구현 Task T2 의 의존이 풀린다.
    """
    case, repo = _agreed_git_case(harness, dirty=dirty, name=name)
    if workspace:
        harness.prepare_workspace(case["id"])
    _prepare_both(harness, case["id"], run_prefix=f"run-{name}")
    return case, repo


def _impl(harness, case, run_id="run-impl-w", permission="workspace_write", task_id="T2"):
    return harness.request_implementation(
        case["id"], run_id=run_id, permission=permission, task_id=task_id
    )


# ------------------------------------------------------------------- AC-1


def test_a_workspace_is_recorded_with_a_branch_and_a_base_commit(harness):
    """AC-1: 브랜치·worktree 경로·**기준 커밋 SHA** 가 남는다."""
    case, repo = _agreed_git_case(harness)

    requested = harness.request_workspace(case["id"])
    assert requested.status_code == 201, requested.text
    # **요청은 준비됨이 아니다.** 아직 아무 것도 만들어지지 않았다.
    assert requested.json()["state"] == "requested"
    assert requested.json()["branch"] == f"hads/{case['id']}"
    assert requested.json()["base_commit"] == ""

    harness.agent.prepare_workspaces()
    workspace = harness.workspace(case["id"])
    assert workspace["state"] == "ready"
    assert workspace["base_commit"] == _git(repo, "rev-parse", "HEAD").strip()
    assert Path(workspace["worktree_path"]).is_dir()
    # worktree 는 **저장소 밖**에 있다. 안에 두면 사용자의 미추적 파일로 보인다.
    assert Path(repo) not in Path(workspace["worktree_path"]).parents
    # 브랜치가 실제로 생겼고 그 worktree 를 가리킨다.
    assert f"hads/{case['id']}" in _git(repo, "branch", "--list", f"hads/{case['id']}")


def test_a_missing_repository_fails_instead_of_being_created(harness):
    """AC-1: **없는 저장소를 빈 디렉터리로 만들어 주지 않는다.**

    만들어 주면 "프로젝트가 가리키는 코드가 이 호스트에 없다"는 사실이 가려지고,
    그 위에서 CLI 가 빈 저장소를 고치기 시작한다.
    """
    project = harness.create_project()  # repo_path 가 실재하지 않는다
    case = harness.create_case(project["id"])
    assert harness.request_workspace(case["id"]).status_code == 201

    harness.agent.prepare_workspaces()
    workspace = harness.workspace(case["id"])
    assert workspace["state"] == "failed"
    assert workspace["failure_reason"]
    assert workspace["base_commit"] == ""
    assert not (harness.runner_config.worktrees_dir / case["id"]).exists()


# ------------------------------------------------------------------- AC-2


def test_the_users_own_working_tree_is_left_alone(harness):
    """AC-2: **미커밋·미추적 파일을 건드리지 않는다.**

    자동 커밋·stash·reset·삭제가 없고, 기준 커밋은 커밋된 상태이므로 사용자의
    변경을 담지 않는다. 선택되지 않은 변경을 복사하지도 폐기하지도 않는다
    (execution-workspace-review 2절, FR-08·FR-26).
    """
    case, repo = _agreed_git_case(harness, dirty=True)
    before_status = _git(repo, "status", "--porcelain")
    before_head = _git(repo, "rev-parse", "HEAD").strip()
    before_body = (repo / "reader.py").read_text(encoding="utf-8")

    # UI-04d(D-77). 더러운 트리는 **선택 없이 만들어지지 않는다** — Runner 가 묻고 사람이 "커밋된 코드에서
    # 시작" 을 고른 뒤에야 만든다. 그 뒤의 단언은 P3-03 그대로다(포함하지 않은 변경은 원래 폴더에만 남는다).
    asked = harness.prepare_workspace(case["id"], basis=None)
    assert asked["state"] == "awaiting_basis" and asked["base_commit"] == ""
    assert _git(repo, "status", "--porcelain") == before_status
    harness.decide_start_basis(case["id"], asked["repository_id"], "committed")
    harness.agent.prepare_workspaces()

    assert _git(repo, "status", "--porcelain") == before_status
    assert _git(repo, "rev-parse", "HEAD").strip() == before_head
    assert (repo / "reader.py").read_text(encoding="utf-8") == before_body
    assert (repo / "scratch.txt").exists()

    workspace = harness.workspace(case["id"])
    # 관측은 했다. **정리하지 않았다는 사실**이 기록으로 남는다.
    assert workspace["user_tree_dirty"] is True
    assert workspace["user_tree_entries"] == 2
    assert workspace["state"] == "ready" and workspace["start_basis"] == "committed"
    assert workspace["committed_base"] == workspace["base_commit"] == before_head

    worktree = Path(workspace["worktree_path"])
    # 기준 커밋에는 사용자의 미커밋 변경이 없다.
    assert "사용자가 쓰던 중" not in (worktree / "reader.py").read_text(encoding="utf-8")
    # 미추적 파일도 따라오지 않는다. 조용히 복사하지 않는다.
    assert not (worktree / "scratch.txt").exists()


# ------------------------------------------------------------------- AC-3


def test_an_existing_branch_is_not_taken_over(harness):
    """AC-3: 같은 이름의 브랜치가 이미 있으면 **덮어쓰지 않고 거부한다.**"""
    case, repo = _agreed_git_case(harness)
    _git(repo, "branch", f"hads/{case['id']}")

    assert harness.request_workspace(case["id"]).status_code == 201
    harness.agent.prepare_workspaces()

    workspace = harness.workspace(case["id"])
    assert workspace["state"] == "failed"
    assert "덮어쓰지 않는다" in workspace["failure_reason"]


def test_a_non_empty_path_is_not_taken_over(harness):
    """AC-3: 비어 있지 않은 경로도 마찬가지다. 소유를 확인할 수 없다.

    **경로는 P3-R2에서 `{case}/{repo}` 로 바뀌었다.** 자리를 직접 계산하지 않고
    Runner 에게 물어 오는 이유는, 시험이 옛 자리를 붙잡고 있으면 실제 대상 경로가
    비어 있게 되어 준비가 성공하고 "덮어쓰지 않는다"가 확인되지 않기 때문이다.
    """
    case, _repo = _agreed_git_case(harness)
    repository_id = harness.project_repository_id(case["project_id"])
    squatter = harness.agent.worktree_for(case["id"], repository_id)
    squatter.mkdir(parents=True, exist_ok=True)
    (squatter / "someone-elses.txt").write_text("남의 파일\n", encoding="utf-8")

    assert harness.request_workspace(case["id"]).status_code == 201
    harness.agent.prepare_workspaces()

    assert harness.workspace(case["id"])["state"] == "failed"
    assert (squatter / "someone-elses.txt").exists()


def test_our_own_workspace_is_reused_with_the_same_base_commit(harness):
    """AC-3: 우리가 만든 것으로 확인되면 재사용한다.

    **기준 커밋은 처음 만든 그 커밋이다.** 재사용 시점의 HEAD 로 바꾸면 이미 한
    변경이 기준에 섞여 "무엇이 바뀌었는가"를 답할 수 없다.
    """
    case, repo = _agreed_git_case(harness)
    first = harness.prepare_workspace(case["id"])

    # 저장소가 앞으로 나아가도 이 Case 의 기준은 움직이지 않는다.
    (repo / "other.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "another")

    # 보고가 유실돼 다시 요청된 상태를 만든다.
    harness.client.post(f"/api/cases/{case['id']}/workspace", json={"base_ref": "HEAD"})
    harness.client.post(
        f"/api/runner/workspaces/{case['id']}/failed",
        json={"runner_id": harness.runner_config.runner_id, "reason": "보고 유실"},
    )
    harness.client.post(f"/api/cases/{case['id']}/workspace", json={"base_ref": "HEAD"})
    harness.agent.prepare_workspaces()

    again = harness.workspace(case["id"])
    assert again["state"] == "ready"
    assert again["base_commit"] == first["base_commit"]


# ------------------------------------------------------------------- AC-4


def test_write_permission_opens_only_with_a_ready_workspace(harness):
    """AC-4: **쓰기 권한이 열렸다 — 준비된 작업공간이 있을 때만.**"""
    case, _repo = _ready_case(harness)
    response = _impl(harness, case)
    assert response.status_code == 201, response.text
    assert response.json()["run"]["permission"] == "workspace_write"


def test_write_is_refused_without_a_workspace(harness):
    """AC-4: 작업공간이 없으면 `workspace_not_ready` 다."""
    case, _repo = _ready_case(harness, workspace=False)
    assert "workspace_not_ready" in _refusals(_impl(harness, case))


def test_a_requested_workspace_is_not_a_ready_one(harness):
    """AC-4: **요청을 준비됨으로 읽지 않는다.**"""
    case, _repo = _ready_case(harness, workspace=False)
    assert harness.request_workspace(case["id"]).status_code == 201
    assert "workspace_not_ready" in _refusals(_impl(harness, case))


def test_a_failed_workspace_is_reported_as_such(harness):
    """AC-4: 실패한 준비는 `workspace_failed` 로 구별된다.

    "아직 없다"와 "만들려다 실패했다"는 사람이 할 조치가 다르다.
    """
    case, _repo = _ready_case(harness, workspace=False)
    assert harness.request_workspace(case["id"]).status_code == 201
    harness.client.post(
        f"/api/runner/workspaces/{case['id']}/failed",
        json={"runner_id": harness.runner_config.runner_id, "reason": "브랜치가 이미 있다"},
    )
    assert "workspace_failed" in _refusals(_impl(harness, case))


@pytest.mark.parametrize("purpose", ["design_authoring", "plan_authoring"])
def test_preparation_purposes_still_refuse_write(harness, purpose):
    """AC-4: **초안·설계·계획을 쓰는 실행에는 쓰기를 주지 않는다.**

    전역 권한 목록 하나를 넓혔다면 여기까지 함께 열렸을 것이다.
    """
    case, _repo = _ready_case(harness)
    instruction = harness.submit_artifact(case["id"], "요청", summary="요청")
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": f"run-{purpose}-w",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": purpose,
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "workspace_write",
            "task_id": "T2",
        },
    )
    assert response.status_code == 409, response.text
    assert "permission_not_allowed_in_stage" in _refusals(response)


def test_escalated_permission_is_still_closed(harness):
    """AC-4: `explicit_escalated` 는 이번에도 열지 않았다.

    어댑터에 매핑이 없고(P1-02), 무엇을 어디까지 올리는지 사람이 확인하는
    경로도 아직 없다.
    """
    case, _repo = _ready_case(harness)
    refusals = _refusals(_impl(harness, case, permission="explicit_escalated"))
    assert "permission_not_allowed_in_stage" in refusals


# ------------------------------------------------------------- AC-5 · AC-6


def test_an_implementation_that_changes_code_is_completed(harness):
    """AC-5: 실제로 바뀐 것이 `workspace_effect` 로 남는다."""
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.write_files = {
        "reader.py": "def read(path):\n    return [l for l in open(path) if l.startswith('ERROR')]\n"
    }
    assert _impl(harness, case).status_code == 201
    harness.agent.poll_once()

    run = harness.client.get("/api/runs/run-impl-w").json()
    assert run["outcome"] == "completed"
    effect = run["workspace_effect"]
    assert effect["changed"] is True
    assert effect["files_changed"] == 1
    assert effect["base_commit"] == harness.workspace(case["id"])["base_commit"]
    # **커밋하지 않는다.** HEAD 는 그대로이고 변경은 작업 트리에 있다.
    assert effect["head_before"] == effect["head_after"] == effect["base_commit"]
    # 격리 한계를 값으로 남긴다. "격리했다"가 아니다(D-44).
    assert effect["isolation"] == "worktree_file_layout_only"


def test_a_new_file_counts_as_a_change(harness):
    """AC-5: **새로 만든 파일도 변경이다.**

    `git diff` 는 추적되는 변경만 본다. 미추적 파일을 세지 않으면 "파일을 새로
    만든 구현"이 변경 없음으로 보여 실패로 기록된다.
    """
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.write_files = {"filter.py": "def only_errors(lines):\n    return lines\n"}
    assert _impl(harness, case).status_code == 201
    harness.agent.poll_once()

    run = harness.client.get("/api/runs/run-impl-w").json()
    assert run["outcome"] == "completed"
    assert run["workspace_effect"]["files_changed"] == 1
    assert run["workspace_effect"]["insertions"] == 2


def test_an_implementation_that_changes_nothing_is_not_completed(harness):
    """AC-6: **"고쳤다"는 보고만으로 완료가 되지 않는다.**

    이 시험이 P3-03에서 가장 중요하다. CLI 는 정상 종료했고 응답 형식도 맞았지만
    작업공간은 그대로다. 이것을 완료로 올리면 P3-02가 연 의존 해제가 증거 없이
    풀린다(FR-09).
    """
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.write_files = {}  # 아무 것도 바꾸지 않는다
    assert _impl(harness, case).status_code == 201
    harness.agent.poll_once()

    run = harness.client.get("/api/runs/run-impl-w").json()
    assert run["outcome"] == "failed"
    assert run["workspace_effect"]["changed"] is False
    # Task 도 끝나지 않는다.
    states = {t["task_key"]: t["state"] for t in harness.work_graph(case["id"])["tasks"]}
    assert states["T2"] != "done"


def test_a_blocked_implementation_is_reported_as_failed(harness):
    """AC-6: 막혔다고 적은 실행은 실패다. **억지 변경보다 낫다.**"""
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.implementation_response = (
        '{"changed_summary": "", "blocked": true, "blocked_reason": "인터페이스가 미정이다"}'
    )
    harness.agent.cli_executor.write_files = {"reader.py": "# 손댐\n"}
    assert _impl(harness, case).status_code == 201
    harness.agent.poll_once()

    assert harness.client.get("/api/runs/run-impl-w").json()["outcome"] == "failed"


# ------------------------------------------------------------------- AC-7


def _verification(harness, case, run_id="run-verify-1"):
    instruction = harness.submit_artifact(case["id"], "검증해 주세요", summary="검증 요청")
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": run_id,
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "verification_run",
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "workspace_write",
            "task_id": "T2",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_a_verification_run_records_the_commands_it_ran(harness):
    """AC-7: 명령 요약·종료 코드가 증거로 남는다. **원문은 Runner 에 있다.**"""
    case, _repo = _ready_case(harness)
    _verification(harness, case)
    harness.agent.poll_once()

    run = harness.client.get("/api/runs/run-verify-1").json()
    assert run["outcome"] == "completed"
    assert [c["command_summary"] for c in run["commands"]] == ["reader 시험"]
    assert run["commands"][0]["exit_code"] == 0


def test_a_failing_test_is_still_a_completed_verification(harness):
    """AC-7: **"테스트가 실패했다"와 "검증을 수행하지 못했다"는 다른 것이다.**

    실패한 종료 코드를 걸러 내면 실패한 시험이 없었던 일이 된다. 그것은 기준
    판정의 입력이지 실행의 실패가 아니다.
    """
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.verification_response = (
        '{"commands": [{"command": "pytest", "summary": "전체 시험", "exit_code": 1}],'
        ' "result_summary": "1건 실패"}'
    )
    _verification(harness, case)
    harness.agent.poll_once()

    run = harness.client.get("/api/runs/run-verify-1").json()
    assert run["outcome"] == "completed"
    assert run["commands"][0]["exit_code"] == 1


def test_a_verification_without_commands_is_not_completed(harness):
    """AC-7: 명령이 없으면 무엇을 확인했는지 말할 수 없다."""
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.verification_response = (
        '{"commands": [], "result_summary": "환경이 없어 실행하지 못했다"}'
    )
    _verification(harness, case)
    harness.agent.poll_once()

    run = harness.client.get("/api/runs/run-verify-1").json()
    assert run["outcome"] == "failed"
    assert run["commands"] == []


# ------------------------------------------------------------------- AC-8


def test_writes_in_one_case_are_serialised(harness):
    """AC-8: 같은 Case 의 두 번째 쓰기는 거부된다.

    두 실행이 같은 worktree 에 동시에 쓰면 실행 전후 대조가 무엇도 답하지
    못한다 — 그 대조가 우리가 가진 유일한 증거다.
    """
    case, _repo = _ready_case(harness)
    assert _impl(harness, case, run_id="run-impl-a").status_code == 201

    refusals = _refusals(_impl(harness, case, run_id="run-impl-b"))
    assert "case_write_in_progress" in refusals


def test_read_only_runs_are_not_blocked_by_a_write(harness):
    """AC-8: **읽기 전용은 그때도 허용된다.** 직렬화 대상은 쓰기다."""
    case, _repo = _ready_case(harness)
    assert _impl(harness, case, run_id="run-impl-a").status_code == 201

    instruction = harness.submit_artifact(case["id"], "읽어 주세요", summary="조사 요청")
    response = harness.create_run(
        case["id"],
        instruction["artifact_id"],
        "run-read-1",
        purpose="limited_analysis",
        tool_id=FAKE_TOOL_ID,
        mode=FAKE_TOOL_MODE,
        permission="read_only",
        task_id="T2",
    )
    assert response["run"]["run_id"] == "run-read-1"


def test_the_serialisation_clears_when_the_write_finishes(harness):
    """AC-8: 끝난 쓰기는 자리를 잡고 있지 않는다."""
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.write_files = {"reader.py": "# 1\n"}
    assert _impl(harness, case, run_id="run-impl-a").status_code == 201
    harness.agent.poll_once()

    assert _impl(harness, case, run_id="run-impl-b").status_code == 201


# ------------------------------------------------------------------- AC-9


def test_a_runner_takes_one_write_at_a_time(harness):
    """AC-9: 같은 Runner 의 동시 쓰기는 기본 1개다(FR-26).

    **거부가 아니라 미룸이다.** 두 번째 쓰기는 `pending` 으로 남았다가 앞의
    쓰기가 끝나면 그대로 배정된다 — 사람이 고칠 조건이 없는 사유를 만들지 않는다.
    """
    case_a, _repo_a = _ready_case(harness, name="alpha")
    case_b, _repo_b = _ready_case(harness, name="beta")
    assert _impl(harness, case_a, run_id="run-impl-a").status_code == 201
    assert _impl(harness, case_b, run_id="run-impl-b").status_code == 201

    claimed = harness.client.post(
        f"/api/runner/{harness.runner_config.runner_id}/assignments"
    ).json()
    write_runs = [c["run_id"] for c in claimed if c["permission"] == "workspace_write"]
    assert write_runs == ["run-impl-a"]

    slot = harness.client.get(
        f"/api/runners/{harness.runner_config.runner_id}/write-slot"
    ).json()
    assert slot["available"] is False
    assert slot["deferral_reason"] == "runner_write_slot_busy"
    # 두 번째는 살아 있다. 거부되지 않았다.
    assert harness.client.get("/api/runs/run-impl-b").json()["status"] == "pending"


def test_the_advisory_lock_stops_a_second_process_in_the_same_worktree(harness):
    """AC-9: worktree 권고 잠금. **OS 잠금이 아니다.**

    제어부의 직렬화만으로는 같은 호스트의 두 Runner 프로세스를 막지 못하고,
    이 파일만으로는 다른 호스트를 모른다. 둘 다 둔다.
    """
    from runner import workspace as ws

    case, _repo = _ready_case(harness)
    worktree = Path(harness.workspace(case["id"])["worktree_path"])
    squatter = ws.AdvisoryLock(ws.lock_path_for(worktree))
    assert squatter.acquire("다른-프로세스") is True

    assert _impl(harness, case).status_code == 201
    result = harness.agent.poll_once()
    actions = {a["run_id"]: a["action"] for a in result["assignments"]}
    # **실행하지 않고 사유와 함께 끝난다.** 예외로 죽으면 실행이 `assigned` 로
    # 멈춘 채 남고 그 Case 의 쓰기 자리도 영영 비지 않는다(P3-01 라이브의 교훈).
    assert actions["run-impl-w"] == "refused_workspace_busy"
    run = harness.client.get("/api/runs/run-impl-w").json()
    assert run["status"] == "finished"
    assert run["outcome"] == "failed"
    assert run["workspace_effect"] is None

    squatter.release()
    # 잠금이 풀리면 다시 배정된다. 자리가 영구히 막히지 않는다.
    assert _impl(harness, case, run_id="run-impl-again").status_code == 201


# ------------------------------------------------------------------ AC-10


def test_a_change_outside_the_workspace_is_detected_not_prevented(harness):
    """AC-10: **감지한다. 막았다고 하지 않는다.**

    worktree 는 파일 배치의 분리이며 OS 격리가 아니다(D-44). CLI 는 원래 저장소를
    고칠 수 있고, 우리가 할 수 있는 것은 실행 전후를 대조해 드러내는 것뿐이다.
    """
    case, repo = _ready_case(harness)
    original = harness.agent.cli_executor.execute

    def execute_and_escape(**kwargs):
        (repo / "escaped.txt").write_text("작업공간 밖에 썼다\n", encoding="utf-8")
        return original(**kwargs)

    harness.agent.cli_executor.execute = execute_and_escape
    harness.agent.cli_executor.write_files = {"reader.py": "# 고침\n"}
    assert _impl(harness, case).status_code == 201
    harness.agent.poll_once()

    effect = harness.client.get("/api/runs/run-impl-w").json()["workspace_effect"]
    assert effect["outside_workspace_observed"] is True
    assert effect["outside_workspace_changed"] is True
    assert harness.workspace(case["id"])["outside_workspace_changed"] is True
    # 되돌리지 않는다. 사용자의 파일일 수 있다.
    assert (repo / "escaped.txt").exists()


def test_the_system_does_not_claim_os_isolation(harness):
    """AC-10: 화면이 읽을 한계 문구가 **값으로** 온다.

    화면이 이 문장을 지어내면 언젠가 "격리됨"으로 바뀐다.
    """
    case, _repo = _ready_case(harness)
    workspace = harness.workspace(case["id"])
    assert workspace["isolation"] == "worktree_file_layout_only"
    assert "OS 격리가 아니" in workspace["isolation_note"]


# ------------------------------------------------------------------ AC-11


def test_an_unexpected_external_edit_is_surfaced_and_kept(harness):
    """AC-11: 사람이 직접 고친 것을 **드러내되 되돌리지 않는다**(FR-26)."""
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.write_files = {"reader.py": "# 1차\n"}
    assert _impl(harness, case, run_id="run-impl-a").status_code == 201
    harness.agent.poll_once()

    worktree = Path(harness.workspace(case["id"])["worktree_path"])
    (worktree / "human-note.txt").write_text("사람이 직접 남긴 메모\n", encoding="utf-8")

    harness.agent.cli_executor.write_files = {"reader.py": "# 2차\n"}
    assert _impl(harness, case, run_id="run-impl-b").status_code == 201
    harness.agent.poll_once()

    effects = harness.workspace(case["id"])["run_effects"]
    by_run = {e["run_id"]: e for e in effects}
    assert by_run["run-impl-a"]["unexpected_external_change"] is False
    assert by_run["run-impl-b"]["unexpected_external_change"] is True
    assert (worktree / "human-note.txt").exists()


# ------------------------------------------------------------------ AC-12


def test_a_real_implementation_unblocks_the_next_task(harness):
    """AC-12: **구현 Task 가 실제로 끝나 후속 Task 가 열린다.**

    P3-02는 조사 Task 로 이것을 확인했고 구현 Task 는 끝날 수 없었다. 이제 끝난다.
    """
    tasks = [
        {
            "key": "T1",
            "kind": "investigation",
            "purpose": "현재 동작을 확인한다",
            "purpose_summary": "현재 동작 확인",
            "deliverable": "조사 메모",
            "deliverable_summary": "조사 메모",
            "completion": "확인됐다",
            "completion_summary": "확인됨",
            "depends_on": [],
            "criteria": [],
        },
        {
            "key": "T2",
            "kind": "implementation",
            "purpose": "필터를 구현한다",
            "purpose_summary": "필터 구현",
            "deliverable": "reader.py 변경",
            "deliverable_summary": "reader.py 변경",
            "completion": "필터가 동작한다",
            "completion_summary": "필터 동작",
            "depends_on": ["T1"],
            "criteria": [{"key": "C-01", "relation": "implements"}],
        },
        {
            "key": "T3",
            "kind": "verification",
            "purpose": "표본 파일로 확인한다",
            "purpose_summary": "표본 확인",
            "deliverable": "시험 결과",
            "deliverable_summary": "시험 결과",
            "completion": "시험이 돌았다",
            "completion_summary": "시험 실행됨",
            "depends_on": ["T2"],
            "criteria": [{"key": "C-01", "relation": "verifies"}],
        },
    ]
    case, _repo = _agreed_git_case(harness)
    harness.prepare_workspace(case["id"])
    harness.agent.cli_executor.plan_response = fake_preparation_response(
        "계획",
        {
            "tasks": "T1 → T2 → T3",
            "verification": "표본 파일 시험",
            "dependencies": "tasks 의 depends_on",
            "integration_order": "순서대로",
            "human_decision_points": "없음",
            "environment_prerequisites": "Python 3.12",
        },
        tasks=tasks,
    )
    _prepare_both(harness, case["id"])  # T1 까지 끝난다

    # T3 는 아직 막혀 있다. T2 가 끝나지 않았다.
    assert "task_dependencies_unmet" in _refusals(
        _impl(harness, case, run_id="run-t3-early", task_id="T3")
    )

    harness.agent.cli_executor.write_files = {"reader.py": "# 필터\n"}
    assert _impl(harness, case, run_id="run-t2", task_id="T2").status_code == 201
    harness.agent.poll_once()

    states = {t["task_key"]: t["state"] for t in harness.work_graph(case["id"])["tasks"]}
    assert states["T2"] == "done"
    # 이제 T3 가 열린다.
    assert _impl(harness, case, run_id="run-t3", task_id="T3").status_code == 201


def test_a_failed_implementation_does_not_unblock_the_next_task(harness):
    """AC-12: 실패한 구현은 후속을 열지 않는다. **변경 없음도 실패다.**"""
    case, _repo = _ready_case(harness)
    harness.agent.cli_executor.write_files = {}
    assert _impl(harness, case, run_id="run-impl-a").status_code == 201
    harness.agent.poll_once()

    states = {t["task_key"]: t["state"] for t in harness.work_graph(case["id"])["tasks"]}
    assert states["T2"] == "planned"


def test_the_skeleton_executor_cannot_implement_or_verify(harness):
    """AC-6 (보강): **아무 것도 하지 않으면서 정상 종료하는 실행기를 막는다.**

    P2-01의 골격 실행기는 코드를 고치지도 명령을 실행하지도 않지만 `completed` 로
    끝난다. 그 실행이 구현·검증으로 기록되면 아무 것도 하지 않은 실행 하나로
    후속 Task 가 전부 열린다 — 실행 결과에서 완료를 도출한다는 규칙의 빈틈이다.
    """
    case, _repo = _ready_case(harness)
    instruction = harness.submit_artifact(case["id"], "구현해 주세요", summary="구현 요청")
    for purpose, run_id in (
        ("feature_implementation", "run-echo-impl"),
        ("verification_run", "run-echo-verify"),
    ):
        response = harness.client.post(
            f"/api/cases/{case['id']}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": instruction["artifact_id"],
                "purpose": purpose,
                "role": "author",
                "tool_id": "local-echo",
                "mode": "p2-01-local",
                "permission": "read_only",
                "task_id": "T2",
            },
        )
        assert response.status_code == 409, response.text
        assert "tool_is_not_a_coding_cli" in _refusals(response)


def test_the_capability_report_says_os_isolation_is_unsupported(harness):
    """AC-10: **지원하지 않는 것을 지원하지 않는다고 보고한다.**

    감지(`workspace_change_detection`)와 격리(`os_level_isolation`)를 같은 줄에
    두면 "감지한다"가 "막는다"로 읽힌다. 둘을 나눠 하나는 `verified`, 하나는
    `unsupported` 로 올린다(D-44).
    """
    from runner import cli_adapter

    rows = {
        row["capability"]: row
        for row in cli_adapter.capabilities_for("codex")
    }
    if "os_level_isolation" not in rows:
        pytest.skip("이 PC에 codex 가 없어 능력 보고가 설치 여부에서 끝난다")
    assert rows["os_level_isolation"]["state"] == "unsupported"
    assert "OS 격리가 아니다" in rows["os_level_isolation"]["source"]
    assert rows["workspace_change_detection"]["state"] == "verified"


def test_a_second_implementation_that_changes_nothing_is_not_completed(harness):
    """AC-6 (핵심 보강): **"바뀌지 않았다"는 이 실행 기준이다.**

    화면을 보다가 찾은 결함이다. 변경 수(`files_changed`)는 **기준 커밋 대비
    누적**이라, 앞선 실행이 이미 파일을 고쳐 놓았으면 그 뒤의 실행은 아무 것도
    하지 않아도 "바뀜"이 된다. 그러면 "바뀌지 않았으면 완료가 아니다"가 첫
    실행에만 적용되는 규칙이 되고, 두 번째 구현 Task 부터는 빈 실행으로 의존이
    풀린다.

    **상태 줄 목록만으로도 부족하다** — 이미 `M reader.py` 인 파일을 또 고쳐도
    줄 목록은 그대로다. 그래서 작업 트리 **내용의 지문**을 비교한다.
    """
    case, _repo = _ready_case(harness)

    harness.agent.cli_executor.write_files = {"reader.py": "# 1차 구현\n"}
    assert _impl(harness, case, run_id="run-impl-a").status_code == 201
    harness.agent.poll_once()
    first = harness.client.get("/api/runs/run-impl-a").json()
    assert first["outcome"] == "completed"

    # 두 번째 실행은 아무 것도 바꾸지 않는다. 누적 수는 여전히 1이다.
    harness.agent.cli_executor.write_files = {}
    assert _impl(harness, case, run_id="run-impl-b").status_code == 201
    harness.agent.poll_once()

    second = harness.client.get("/api/runs/run-impl-b").json()
    assert second["workspace_effect"]["files_changed"] == 1, "누적 수는 그대로다"
    assert second["workspace_effect"]["changed"] is False, "이 실행은 아무 것도 바꾸지 않았다"
    assert second["outcome"] == "failed"


def test_editing_an_already_modified_file_again_counts_as_a_change(harness):
    """AC-6: 반대 방향도 본다. **이미 고쳐진 파일을 또 고치면 변경이다.**

    상태 줄 목록은 두 경우 모두 `M reader.py` 한 줄이라 구별되지 않는다.
    엄격하게 만들다가 정당한 변경을 실패로 만들면 그것도 같은 크기의 결함이다.
    """
    case, _repo = _ready_case(harness)

    harness.agent.cli_executor.write_files = {"reader.py": "# 1차\n"}
    assert _impl(harness, case, run_id="run-impl-a").status_code == 201
    harness.agent.poll_once()

    harness.agent.cli_executor.write_files = {"reader.py": "# 2차 — 같은 파일을 다시 고친다\n"}
    assert _impl(harness, case, run_id="run-impl-b").status_code == 201
    harness.agent.poll_once()

    second = harness.client.get("/api/runs/run-impl-b").json()
    assert second["workspace_effect"]["entries_before"] == second["workspace_effect"]["entries_after"]
    assert second["workspace_effect"]["changed"] is True
    assert second["outcome"] == "completed"
