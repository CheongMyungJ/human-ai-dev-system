"""UI-04d — 미커밋 포함 시작(D-77)(plans/UI-PLAN-04d.md 4·5절).

새 코드 업무는 현재 브랜치의 마지막 커밋에서 시작한다. 사용자의 원래 트리에 커밋하지 않은 변경이 있으면
**만들지 않고 묻는다** — 목록과 함께 `포함해서 시작 / 커밋된 코드에서 시작`. 포함해도 원래 폴더는 그대로이고
별도 작업공간에 정확한 시작 상태(스냅샷 커밋·지문·수)가 남는다.

이 파일이 지키는 것:

    원래 폴더는 어떤 경로에서도 바뀌지 않는다   상태·HEAD·인덱스·브랜치를 전후로 대조한다
    선택 없이 만들어지지 않는다                 더러운 트리는 `awaiting_basis` 이고 쓰기는 거부된다
    파일 경로는 서버에 남지 않는다               목록은 메모리로만 오고 DB 어디에도 없다
    사람이 본 목록과 다른 것을 포함하지 않는다   지문 대조(409·재질문)
    선택은 권한이 아니다                         저장소 선택·허용·진입 검사는 그대로다

시험 이름 옆의 AC 번호는 UI-PLAN-04d 4절이다. git 은 진짜로 쓴다(흉내로는 원래 트리 보존을 확인할 수 없다).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from controller import db
from controller.db import utc_now
from runner import workspace
from tests.conftest import _git
from tests.test_preparation import _refusals
from tests.test_work_progressor import _agree, _drive, _start, _wait_codes
from tests.test_workspace import _agreed_git_case, _impl, _prepare_both


# ================================================== 도우미


def _db_has(harness, needle: str) -> bool:
    """제어부 DB 의 **모든 표·모든 글 칸**에 이 글이 있는가(WAL 무관 — SQL 로 읽는다)."""
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
        for table in tables:
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                for value in row:
                    if isinstance(value, str) and needle in value:
                        return True
                    if isinstance(value, bytes) and needle.encode("utf-8") in value:
                        return True
        return False
    finally:
        conn.close()


def _tree(repo: Path) -> tuple[str, str, str]:
    return (
        _git(repo, "status", "--porcelain"),
        _git(repo, "rev-parse", "HEAD").strip(),
        _git(repo, "rev-parse", "--abbrev-ref", "HEAD").strip(),
    )


def _uncommitted(harness, case_id: str, repository_id: str) -> dict[str, Any]:
    response = harness.client.get(f"/api/cases/{case_id}/workspaces/{repository_id}/uncommitted")
    assert response.status_code == 200, response.text
    return response.json()


# ================================================== 순수 — 스냅샷 커밋·준비 규칙


def test_a_snapshot_commit_captures_the_dirty_tree_without_touching_it(tmp_path):
    """AC-9(순수) — `snapshot_commit` 은 사용자 트리(수정·미추적, `.gitignore` 제외)를 HEAD 위의 커밋으로 만들 뿐
    작업 트리·인덱스·브랜치·HEAD 를 건드리지 않는다. 어떤 ref 도 옮기지 않는다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "reader.py").write_text("a\n", encoding="utf-8")
    (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    head = _git(repo, "rev-parse", "HEAD").strip()
    (repo / "reader.py").write_text("a\nb\n", encoding="utf-8")
    (repo / "new.txt").write_text("new\n", encoding="utf-8")
    (repo / "noise.log").write_text("ignored\n", encoding="utf-8")
    before = _tree(repo)
    index_before = _git(repo, "ls-files", "--stage")

    snapshot = workspace.snapshot_commit(repo, head, 2)

    assert _tree(repo) == before and _git(repo, "ls-files", "--stage") == index_before
    assert _git(repo, "rev-parse", f"{snapshot}^").strip() == head
    assert _git(repo, "show", f"{snapshot}:reader.py") == "a\nb\n"
    assert _git(repo, "show", f"{snapshot}:new.txt") == "new\n"
    assert "noise.log" not in _git(repo, "ls-tree", "-r", "--name-only", snapshot)
    assert "미커밋 변경 2건" in _git(repo, "log", "-1", "--format=%s", snapshot)
    # ref 는 하나도 옮기지 않았다 — 브랜치 목록은 main 뿐이고 HEAD 는 그대로다.
    assert _git(repo, "branch", "--list").split() == ["*", "main"]
    assert not list((repo / ".git").glob("hads-snapshot-*"))  # 임시 인덱스는 지웠다


def test_prepare_asks_when_the_tree_is_dirty_and_builds_only_with_a_basis(tmp_path):
    """AC-7·9·10(순수) — 더럽고 기준이 없으면 `NeedsBasis`(아무 것도 만들지 않음); 지문이 다르면 `stale`;
    같으면 스냅샷 위에서 만든다; 깨끗하면 묻지 않는다; 다른 ref 와 포함은 거부한다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "reader.py").write_text("a\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    _git(repo, "branch", "other")  # 첫 커밋에 남는 다른 브랜치
    (repo / "second.txt").write_text("둘째 커밋\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "second")
    head = _git(repo, "rev-parse", "HEAD").strip()
    assert _git(repo, "rev-parse", "other").strip() != head
    (repo / "reader.py").write_text("a\nb\n", encoding="utf-8")

    asked = workspace.prepare(repo, tmp_path / "wt", "hads/x")
    assert isinstance(asked, workspace.NeedsBasis)
    assert asked.head == head and asked.entries == (" M reader.py",) and not asked.stale
    assert not (tmp_path / "wt").exists() and "hads/x" not in _git(repo, "branch", "--list")

    stale = workspace.prepare(
        repo, tmp_path / "wt", "hads/x", start_basis="include_uncommitted", expected_tree_digest="not-the-digest"
    )
    assert isinstance(stale, workspace.NeedsBasis) and stale.stale
    assert not (tmp_path / "wt").exists()

    with pytest.raises(workspace.WorkspaceError):
        workspace.prepare(
            repo, tmp_path / "wt", "hads/x", base_ref="other", start_basis="include_uncommitted",
            expected_tree_digest=asked.digest,
        )

    built = workspace.prepare(
        repo, tmp_path / "wt", "hads/x", start_basis="include_uncommitted", expected_tree_digest=asked.digest
    )
    assert isinstance(built, workspace.PreparedWorkspace)
    assert built.start_basis == "include_uncommitted" and built.committed_base == head
    assert built.base_commit != head and _git(repo, "rev-parse", f"{built.base_commit}^").strip() == head
    assert built.included_entries == 1 and built.included_tree_digest == asked.digest
    assert (tmp_path / "wt" / "reader.py").read_text(encoding="utf-8") == "a\nb\n"
    assert (repo / "reader.py").read_text(encoding="utf-8") == "a\nb\n"  # 원래 폴더 그대로(정리하지 않음)
    assert _git(repo, "status", "--porcelain").strip() == "M reader.py"

    # 깨끗한 트리는 묻지 않는다 — 커밋된 코드에서, 기준 없이도 만든다.
    _git(repo, "checkout", "--", "reader.py")
    clean = workspace.prepare(repo, tmp_path / "wt2", "hads/y")
    assert isinstance(clean, workspace.PreparedWorkspace)
    assert (clean.start_basis, clean.committed_base, clean.included_entries) == ("committed", head, 0)


# ================================================== AC-6·7 서버 — 깨끗함·선택 대기


def test_a_clean_tree_starts_at_head_without_asking(harness):
    """AC-6 — 미커밋 변경이 없으면 지금처럼 바로 만들며 `committed`·`committed_base = base_commit`·포함 0 이다."""
    case, repo = _agreed_git_case(harness, name="clean")
    space = harness.prepare_workspace(case["id"], basis=None)
    assert space["state"] == "ready" and space["start_basis"] == "committed"
    assert space["committed_base"] == space["base_commit"] == _git(repo, "rev-parse", "HEAD").strip()
    assert space["included_entries"] == 0 and space["basis_entries"] is None
    assert harness.client.get(
        f"/api/cases/{case['id']}/workspaces/{space['repository_id']}/uncommitted"
    ).json()["available"] is False


def test_a_dirty_tree_waits_for_the_basis_and_the_list_stays_out_of_the_db(harness):
    """AC-7 — Runner 가 만들지 않고 목록을 올린다: 행은 `awaiting_basis`(수·지문·HEAD), 목록은 메모리 조회에만
    있고 DB 에 경로가 없으며, 쓰기 실행은 `workspace_not_ready` 로 거부된다. 원래 폴더는 그대로다."""
    case, repo = _agreed_git_case(harness, dirty=True, name="dirty-wait")
    _prepare_both(harness, case["id"], run_prefix="run-dirty-wait")
    before = _tree(repo)

    asked = harness.prepare_workspace(case["id"], basis=None)
    assert asked["state"] == "awaiting_basis" and asked["start_basis"] is None
    assert asked["basis_entries"] == 2 and asked["user_tree_entries"] == 2 and asked["user_tree_dirty"] is True
    assert asked["committed_base"] == before[1] and len(asked["basis_tree_digest"]) == 64
    assert asked["base_commit"] == "" and asked["worktree_path"] == ""
    assert _tree(repo) == before
    assert f"hads/{case['id']}" not in _git(repo, "branch", "--list")

    listing = _uncommitted(harness, case["id"], asked["repository_id"])
    assert listing["available"] is True and listing["digest"] == asked["basis_tree_digest"]
    assert sorted((e["status"], e["path"]) for e in listing["entries"]) == [("??", "scratch.txt"), ("M", "reader.py")]
    assert listing["truncated"] is False and listing["stale_choice"] is False
    # **파일 경로는 서버 DB 어디에도 없다** — 메모리로만 중계됐다.
    assert not _db_has(harness, "scratch.txt") and not _db_has(harness, "reader.py")

    # 준비되지 않았다 — 쓰기 실행은 거부된다(상태 이름이 사유에 든다).
    refused = _impl(harness, case, run_id="run-dirty-wait-impl")
    assert refused.status_code == 409, refused.text
    assert "workspace_not_ready" in _refusals(refused)
    assert "awaiting_basis" in refused.text
    # 두 번째 요청도 다시 묻기만 한다(만들지 않음).
    harness.agent.prepare_workspaces()
    assert harness.workspace(case["id"])["state"] == "awaiting_basis"
    assert _tree(repo) == before


# ================================================== AC-8·9 서버 — 두 선택


def test_starting_from_committed_code_leaves_the_changes_in_the_original_folder(harness):
    """AC-8 — "커밋된 코드에서 시작": HEAD 에서 만들고 worktree 에 사용자 변경이 없으며 원래 폴더는 그대로,
    행에 기준·주체·시각이 남는다. 그 뒤 구현 실행이 열린다."""
    case, repo = _agreed_git_case(harness, dirty=True, name="committed")
    _prepare_both(harness, case["id"], run_prefix="run-committed")
    before = _tree(repo)
    asked = harness.prepare_workspace(case["id"], basis=None)
    decided = harness.decide_start_basis(case["id"], asked["repository_id"], "committed")
    assert (decided["state"], decided["start_basis"], decided["basis_decided_by"]) == ("requested", "committed", "owner")
    assert decided["basis_decided_at"]
    harness.agent.prepare_workspaces()

    space = harness.workspace(case["id"])
    assert space["state"] == "ready" and space["start_basis"] == "committed"
    assert space["base_commit"] == space["committed_base"] == before[1]
    assert space["included_entries"] == 0 and space["included_tree_digest"] == ""
    worktree = Path(space["worktree_path"])
    assert "사용자가 쓰던 중" not in (worktree / "reader.py").read_text(encoding="utf-8")
    assert not (worktree / "scratch.txt").exists()
    assert _tree(repo) == before and (repo / "scratch.txt").exists()
    # 목록은 만든 뒤 메모리에서 지웠다.
    assert _uncommitted(harness, case["id"], space["repository_id"])["available"] is False
    assert _impl(harness, case, run_id="run-committed-impl").status_code == 201


def test_including_uncommitted_changes_starts_from_a_snapshot_and_keeps_the_original(harness):
    """AC-9 — "포함해서 시작": worktree 에 사용자의 수정·미추적 파일이 있고 원래 폴더(상태·HEAD·브랜치·인덱스)는
    그대로다. `base_commit` = 스냅샷 커밋(부모 = 그때의 HEAD = `committed_base`, Case 브랜치가 가리킴), 포함 수·지문이
    남고, 그 뒤 구현 실행의 효과·누적 수·코드 조합은 스냅샷을 기준으로 한다(사용자 변경을 AI 변경으로 세지 않음)."""
    case, repo = _agreed_git_case(harness, dirty=True, name="include")
    _prepare_both(harness, case["id"], run_prefix="run-include")
    before = _tree(repo)
    index_before = _git(repo, "ls-files", "--stage")
    asked = harness.prepare_workspace(case["id"], basis=None)
    harness.decide_start_basis(case["id"], asked["repository_id"], "include_uncommitted")
    harness.agent.prepare_workspaces()

    space = harness.workspace(case["id"])
    assert space["state"] == "ready" and space["start_basis"] == "include_uncommitted"
    assert space["committed_base"] == before[1] and space["base_commit"] != before[1]
    assert _git(repo, "rev-parse", f"{space['base_commit']}^").strip() == before[1]
    assert _git(repo, "rev-parse", f"hads/{case['id']}").strip() == space["base_commit"]
    assert space["included_entries"] == 2 and space["included_tree_digest"] == asked["basis_tree_digest"]
    worktree = Path(space["worktree_path"])
    assert "사용자가 쓰던 중" in (worktree / "reader.py").read_text(encoding="utf-8")
    assert (worktree / "scratch.txt").read_text(encoding="utf-8") == "사용자의 미추적 메모\n"
    # 원래 폴더·인덱스·브랜치·HEAD 는 그대로다 — 자동 커밋·stash·삭제 없음.
    assert _tree(repo) == before and _git(repo, "ls-files", "--stage") == index_before
    assert "사용자가 쓰던 중" in (repo / "reader.py").read_text(encoding="utf-8")
    assert _git(repo, "stash", "list") == ""
    # 파일 경로는 DB 에 없다(목록은 지워졌고 행에는 수·해시만).
    assert not _db_has(harness, "scratch.txt")

    # 구현 실행 — 효과·누적 수는 **스냅샷 기준**이다. 사용자의 두 변경은 세지 않는다.
    harness.agent.cli_executor.write_files = {"other.py": "# AI 가 더한 파일\n"}
    assert _impl(harness, case, run_id="run-include-impl").status_code == 201
    harness.agent.poll_once()
    view = harness.workspace(case["id"])
    effect = view["run_effects"][-1]["effect"]
    assert effect["base_commit"] == space["base_commit"] and effect["changed"] is True
    assert effect["files_changed"] == 1 and effect["entries_before"] == 0
    composition = harness.client.post(f"/api/cases/{case['id']}/composition").json()
    assert composition["entries"][0]["base_commit"] == space["base_commit"]
    assert "사용자가 쓰던 중" in (worktree / "reader.py").read_text(encoding="utf-8")  # 보존


# ================================================== AC-10 서버 — 동시 편집 보호·거부


def test_a_changed_list_is_asked_again_and_a_stale_choice_is_refused(harness):
    """AC-10 — (a) 옛 지문의 선택은 409 `basis_list_stale`; (b) 선택 뒤 포함 직전에 트리가 바뀌었으면 Runner 가 만들지
    않고 새 목록으로 다시 묻는다(`start_basis` 지움·수 갱신); `awaiting_basis` 가 아닌 행의 선택은 409."""
    case, repo = _agreed_git_case(harness, dirty=True, name="stale")
    asked = harness.prepare_workspace(case["id"], basis=None)
    repo_id = asked["repository_id"]

    wrong = harness.client.post(
        f"/api/cases/{case['id']}/workspaces/{repo_id}/start-basis",
        json={"basis": "include_uncommitted", "actor": "owner", "seen_digest": "0" * 64},
    )
    assert wrong.status_code == 409 and "basis_list_stale" in wrong.text
    assert harness.workspace(case["id"])["state"] == "awaiting_basis"

    harness.decide_start_basis(case["id"], repo_id, "include_uncommitted")
    # 고른 뒤, 만들기 전에 사용자가 또 고친다.
    (repo / "third.txt").write_text("고르는 사이 더한 파일\n", encoding="utf-8")
    harness.agent.prepare_workspaces()
    again = harness.workspace(case["id"])
    assert again["state"] == "awaiting_basis" and again["start_basis"] is None
    assert again["basis_entries"] == 3 and again["basis_tree_digest"] != asked["basis_tree_digest"]
    assert again["base_commit"] == "" and f"hads/{case['id']}" not in _git(repo, "branch", "--list")
    listing = _uncommitted(harness, case["id"], repo_id)
    assert listing["stale_choice"] is True and len(listing["entries"]) == 3
    assert _git(repo, "stash", "list") == "" and (repo / "third.txt").exists()

    # 새 목록으로 고르면 만든다 — 세 항목 전부.
    harness.decide_start_basis(case["id"], repo_id, "include_uncommitted")
    harness.agent.prepare_workspaces()
    space = harness.workspace(case["id"])
    assert space["state"] == "ready" and space["included_entries"] == 3
    assert (Path(space["worktree_path"]) / "third.txt").exists()
    # 준비된 행에는 선택을 보낼 수 없다.
    late = harness.client.post(
        f"/api/cases/{case['id']}/workspaces/{repo_id}/start-basis",
        json={"basis": "committed", "actor": "owner", "seen_digest": space["basis_tree_digest"]},
    )
    assert late.status_code == 409 and "workspace_not_awaiting_basis" in late.text
    assert harness.client.post(
        f"/api/cases/{case['id']}/workspaces/{repo_id}/start-basis",
        json={"basis": "whatever", "actor": "owner", "seen_digest": space["basis_tree_digest"]},
    ).status_code == 422


# ================================================== AC-7·11 진행기 — 사람 대기 카드에서 멈추고 이어 간다


def test_the_progressor_waits_at_the_basis_card_and_continues_after_the_choice(processing_harness):
    """AC-7·8 — 진행기가 작업공간 걸음에서 `workspace_start_basis` 사람 대기로 요청을 끝내고(카드 값: 저장소·수·HEAD),
    사람이 고르면 이어서 구현·검증까지 간다. 선택은 권한이 아니다 — 저장소 선택·허용은 그대로다."""
    h = processing_harness
    project, case_id, _request = _start(h, "feature")
    repo = Path(project["repo_path"])
    (repo / "reader.py").write_text("def read(path):\n    return open(path).read()  # 사용자가 쓰던 중\n", encoding="utf-8")
    (repo / "scratch.txt").write_text("메모\n", encoding="utf-8")
    before = _tree(repo)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["workspace_start_basis"], conv["progress"]
    wait = conv["progress"]["wait"][0]
    assert wait["entries"] == 2 and wait["head"] == before[1] and wait["repository_id"]
    assert conv["current_request"] is None  # 사람 대기 — 전송이 열렸다
    assert _tree(repo) == before

    h.decide_start_basis(case_id, wait["repository_id"], "include_uncommitted")
    progress = h.conversation(case_id)["progress"]
    assert progress["state"] == "running" and progress["step"] == "workspace_pending"
    conv = _drive(h, case_id)
    runs = h.client.get(f"/api/cases/{case_id}").json()["runs"]
    assert conv["progress"]["state"] == "done", (
        conv["progress"]["wait"],
        [(r["run_id"], r["outcome"], (r.get("workspace_effect") or {}).get("changed")) for r in runs],
    )
    space = h.workspace(case_id)
    assert space["start_basis"] == "include_uncommitted" and space["included_entries"] == 2
    assert _tree(repo) == before
    events = [e["action"] for e in conv["progress"]["events"] if e["step"] == "workspace_start_basis"]
    assert events == ["waiting_human", "decided"]
    policy = h.client.get(f"/api/cases/{case_id}/policy").json()
    assert policy["repositories"]["selected"] == [] and policy["repositories"]["implicit_single_repository"]


# ================================================== AC-12 이행


def test_a_v26_database_gets_the_basis_columns_and_old_rows_stay_unrecorded(tmp_path):
    """AC-12 — v27 은 `case_workspace` 컬럼 여덟뿐이다. v26 DB 를 올리면 옛 행의 `start_basis` 는 NULL(기록 없음 —
    `committed` 가 아니다)·기본값이고 멱등이다. 새 표는 없다(검색 표 없음)."""
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    db.migrate(conn)
    tables_after = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    for column in (
        "start_basis", "basis_decided_by", "basis_decided_at", "committed_base",
        "included_entries", "included_tree_digest", "basis_tree_digest", "basis_entries",
    ):
        conn.execute(f"ALTER TABLE case_workspace DROP COLUMN {column}")
    conn.execute("DELETE FROM schema_version WHERE version >= 27")
    now = utc_now()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1', 'prj-1', 'old', 'feature', 'received', ?, ?)", (now, now),
    )
    conn.execute(
        "INSERT INTO project_repository (id, project_id, name, repo_path, source, registered_by, registered_at)"
        " VALUES ('repo-1', 'prj-1', 'old', 'C:/tmp/old', 'registered', 'test', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO case_workspace (case_id, repository_id, project_id, state, branch, runner_id, repo_path,"
        " worktree_path, base_commit, base_ref, user_tree_dirty, user_tree_entries, requested_at, ready_at)"
        " VALUES ('case-1', 'repo-1', 'prj-1', 'ready', 'hads/case-1', NULL, 'C:/tmp/old', 'C:/tmp/wt',"
        " 'abcdef1234567890', 'HEAD', 1, 3, ?, ?)", (now, now),
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    row = dict(conn.execute("SELECT * FROM case_workspace WHERE case_id = 'case-1'").fetchone())
    assert row["start_basis"] is None and row["basis_decided_by"] is None
    assert row["committed_base"] == "" and row["included_entries"] is None and row["basis_entries"] is None
    assert row["base_commit"] == "abcdef1234567890" and row["user_tree_dirty"] == 1  # 옛 사실 그대로
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 27
    db.migrate(conn)  # 멱등
    assert {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")} == tables_after
    assert not any("search" in t for t in tables_after)
    conn.close()
