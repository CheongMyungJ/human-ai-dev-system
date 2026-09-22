"""P3-R2 Case × Repository 작업공간·허용·코드 조합 — 자동 시험.

**이 시험들이 지키려는 세 가지:**

    저장소마다 따로 시작하고 따로 보존한다.
    허용을 넓히는 자동 추가는 없다.
    개별 저장소의 통과가 통합의 통과가 되지 않는다.

첫째는 D-39다. 한 Case 가 두 저장소를 고치면 브랜치·기준 커밋·사용자의 미커밋
변경이 저장소마다 따로 있고, 하나로 합치면 어느 쪽을 보존했는지 말할 수 없다.

둘째는 D-38·D-63·D-64다. "기존 허용 안의 저장소는 자동 추가"와 "명시 제외·새
권한은 재판단"은 같은 문장의 앞뒤이며, 앞만 구현하면 자동 추가가 권한 확대 경로가
된다.

셋째는 execution-workspace-review 2.1절이다. 저장소별 검사가 모두 통과해도 공유
API·데이터의 통합 조건을 충족했다고 자동 추정하지 않는다.

**git 은 진짜로 쓴다.** worktree 가 각 저장소의 원래 트리를 건드리지 않는다는 것은
흉내로 확인할 수 없다. 실제 코딩 CLI 는 부르지 않는다(`FakeCliExecutor`).
"""

from __future__ import annotations

from pathlib import Path

from tests.conftest import _git
from tests.test_preparation import FIELDS, _prepare_both
from tests.test_workspace import _agreed_git_case


def _second_repo(harness, project, name: str = "ui", dirty: bool = False) -> dict:
    """같은 Project 에 **두 번째 실제 git 저장소**를 등록한다.

    `dirty=True` 면 사용자의 미커밋·미추적 변경을 남긴다. 그것을 시스템이 정리하지
    않는다는 것이 저장소마다 확인돼야 하는 사실이다(D-39·FR-26).
    """
    repo = harness.tmp_path / f"repo-{name}"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "test")
    (repo / "view.py").write_text("def render():\n    return 'ok'\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "base")
    if dirty:
        (repo / "view.py").write_text(
            "def render():\n    return 'ok'  # 사용자가 쓰던 중\n", encoding="utf-8"
        )
        (repo / "notes.txt").write_text("두 번째 저장소의 사용자 메모\n", encoding="utf-8")
    registered = harness.register_repository(project["id"], name, str(repo))
    return {"repository": registered, "path": repo}


def _refusals(response) -> list[str]:
    return response.json()["detail"]["refusals"]


# ============================================================ AC-2·AC-3
#
# 저장소마다 따로 시작하고 따로 보존한다.


def test_one_case_gets_a_separate_workspace_for_each_repository(harness):
    """AC-2 — 같은 Case 가 두 저장소에 각각 브랜치·worktree·기준 커밋을 갖는다."""
    case, api_repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})

    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])

    harness.prepare_workspace(case["id"], repository_id=primary)
    harness.prepare_workspace(case["id"], repository_id=second["repository"]["id"])

    view = harness.workspace_view(case["id"])
    assert view["repository_count"] == 2
    assert view["all_ready"] is True

    spaces = {w["repository_id"]: w for w in view["workspaces"]}
    first = spaces[primary]
    other = spaces[second["repository"]["id"]]

    # **기준 커밋이 저장소마다 다르다.** 각 저장소의 실제 HEAD 다.
    assert first["base_commit"] == _git(api_repo, "rev-parse", "HEAD").strip()
    assert other["base_commit"] == _git(second["path"], "rev-parse", "HEAD").strip()
    assert first["base_commit"] != other["base_commit"]

    # **worktree 자리가 서로 다르다.** 같은 자리를 쓰면 두 번째 준비가 첫 번째를
    # 남의 것으로 보고 거부한다.
    assert first["worktree_path"] != other["worktree_path"]
    assert Path(first["worktree_path"]).is_dir()
    assert Path(other["worktree_path"]).is_dir()

    # 각 worktree 는 **자기 저장소**의 파일을 담는다.
    assert (Path(first["worktree_path"]) / "reader.py").exists()
    assert (Path(other["worktree_path"]) / "view.py").exists()


def test_each_repository_keeps_its_own_uncommitted_user_changes(harness):
    """AC-3 — 저장소마다 사용자의 원래 dirty tree 를 따로 관측하고 **건드리지 않는다.**

    한 저장소만 확인하면 "두 번째 저장소는 정리해도 된다"가 조용히 성립한다.
    """
    project, api_repo = harness.create_git_project(name="demo", dirty=True)
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS)
    primary = harness.project_repository_id(project["id"])
    second = _second_repo(harness, project, dirty=True)

    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])
    harness.prepare_workspace(case["id"], repository_id=primary)
    harness.prepare_workspace(case["id"], repository_id=second["repository"]["id"])

    spaces = {w["repository_id"]: w for w in harness.workspace_view(case["id"])["workspaces"]}
    # 관측은 **저장소마다** 남는다. 합쳐 세지 않는다.
    assert spaces[primary]["user_tree_dirty"] is True
    assert spaces[primary]["user_tree_entries"] == 2
    assert spaces[second["repository"]["id"]]["user_tree_dirty"] is True
    assert spaces[second["repository"]["id"]]["user_tree_entries"] == 2

    # **두 저장소의 사용자 변경이 그대로 있다.** 커밋·stash·삭제하지 않았다.
    assert "사용자가 쓰던 중" in (api_repo / "reader.py").read_text(encoding="utf-8")
    assert (api_repo / "scratch.txt").exists()
    assert "사용자가 쓰던 중" in (second["path"] / "view.py").read_text(encoding="utf-8")
    assert (second["path"] / "notes.txt").exists()
    # 기준 커밋은 **커밋된 상태**이므로 미커밋 변경을 담지 않는다.
    assert spaces[primary]["base_commit"] == _git(api_repo, "rev-parse", "HEAD").strip()


# ================================================================== AC-4·AC-6
#
# 선택·쓰기 허용이 실제로 무엇을 막는다.


def test_an_unselected_repository_gets_no_workspace(harness):
    """AC-4·AC-6 — 등록 저장소가 둘 이상인데 선택 기록이 없으면 거부한다."""
    case, _repo = _agreed_git_case(harness)
    _second_repo(harness, {"id": case["project_id"]})

    refused = harness.request_workspace(case["id"])
    assert refused.status_code == 409, refused.text
    assert _refusals(refused) == ["repository_selection_required"]
    assert harness.workspace_view(case["id"]) is None


def test_an_excluded_repository_gets_no_workspace(harness):
    """AC-4 — 명시 제외한 저장소에는 작업공간이 만들어지지 않는다.

    **행이 없는 것과 다르다.** 없음은 아직 판단하지 않은 것이고 제외는 판단이다.
    """
    case, _repo = _agreed_git_case(harness)
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(
        case["id"],
        second["repository"]["id"],
        code_write_allowed=False,
        selection_source="excluded",
    )

    refused = harness.request_workspace(
        case["id"], repository_id=second["repository"]["id"]
    )
    assert refused.status_code == 409, refused.text
    assert _refusals(refused) == ["repository_explicitly_excluded"]


def test_a_selected_repository_without_write_allowance_gets_no_workspace(harness):
    """AC-4 — 선택했다고 코드를 바꿔도 되는 것은 아니다(D-63).

    선택 집합과 쓰기 허용 집합이 하나로 합쳐지면 이 경계가 사라진다.
    """
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    harness.select_repository(case["id"], primary, code_write_allowed=False)

    refused = harness.request_workspace(case["id"], repository_id=primary)
    assert refused.status_code == 409, refused.text
    assert _refusals(refused) == ["repository_not_selected_for_code"]


def test_the_journal_repository_is_never_a_code_target(harness):
    """AC-9 — 기록 저장소는 지정만으로 어떤 코드 대상에도 들어가지 않는다(D-17·FR-30).

    선택·자동 추가·작업공간 요청 **셋 다** 막혀야 한다. 하나라도 열려 있으면
    "기록 저장소를 자동 체크아웃·코드 쓰기 대상으로 삼지 않는다"가 깨진다.
    """
    case, _repo = _agreed_git_case(harness)
    journal = _second_repo(harness, {"id": case["project_id"]}, name="journal")
    assert (
        harness.client.put(
            f"/api/projects/{case['project_id']}/journal-repository",
            json={"repository_id": journal["repository"]["id"]},
        ).status_code
        == 200
    )

    selected = harness.select_repository(case["id"], journal["repository"]["id"])
    assert selected.status_code == 409
    assert _refusals(selected) == ["journal_repository_not_a_code_target"]

    auto = harness.client.post(
        f"/api/cases/{case['id']}/repositories/auto",
        json={"repository_id": journal["repository"]["id"], "selected_by": "ai"},
    )
    assert auto.status_code == 409
    assert _refusals(auto) == ["journal_repository_not_a_code_target"]

    workspace = harness.request_workspace(
        case["id"], repository_id=journal["repository"]["id"]
    )
    assert workspace.status_code == 409
    assert _refusals(workspace) == ["journal_repository_not_a_code_target"]


def test_a_migrated_single_repository_case_still_works_and_says_why(harness):
    """AC-5 — 선택 기록이 없는 단일 저장소 Case 는 계속 동작한다.

    **소급을 막는 지점이다.** P3-03까지의 Case 는 선택 없이 Project 의 단일
    저장소에서 실제로 작업했고, "선택 기록이 없으니 쓰기 금지"는 새 정책을 기존
    권한에 소급 적용하는 것이다(DEVELOPMENT.md 3절).

    다만 **없던 선택을 만들지는 않는다.** 허용의 출처가 기록에 남는다.
    """
    case, _repo = _agreed_git_case(harness)
    workspace = harness.prepare_workspace(case["id"])

    assert workspace["state"] == "ready"
    assert workspace["allowance_source"] == "implicit_single_repository"
    # 선택 기록은 **여전히 없다.** 이행이 만들지 않은 결정을 만들어 내지 않는다.
    selection = harness.client.get(f"/api/cases/{case['id']}/repositories").json()
    assert selection["selected"] == []
    assert selection["implicit_single_repository"] is not None


# ==================================================================== AC-7·AC-8
#
# 허용 내 자동 추가와 허용 밖 거절.


def test_a_repository_inside_the_existing_allowance_is_added_automatically(harness):
    """AC-7 — 이미 쓰기 허용이 있는 Case 에 관련 저장소를 자동으로 더한다(D-38)."""
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)

    added = harness.client.post(
        f"/api/cases/{case['id']}/repositories/auto",
        json={
            "repository_id": second["repository"]["id"],
            "selected_by": "ai",
            "reason_summary": "같은 목표의 UI 저장소가 함께 바뀐다",
        },
    )
    assert added.status_code == 201, added.text
    state = added.json()
    assert state["auto_selection"]["changed"] is True

    entry = next(
        r for r in state["selected"] if r["repository_id"] == second["repository"]["id"]
    )
    assert entry["selection_source"] == "auto_in_allowance"
    assert entry["code_write_allowed"] == 1
    # **게시 허용은 따라오지 않는다**(D-64).
    assert entry["publish_allowed"] == 0
    assert entry["reason_summary"] == "같은 목표의 UI 저장소가 함께 바뀐다"

    # 자동으로 더해진 저장소에는 작업공간이 열린다 — 허용 안이기 때문이다.
    workspace = harness.prepare_workspace(
        case["id"], repository_id=second["repository"]["id"]
    )
    assert workspace["state"] == "ready"
    assert workspace["allowance_source"] == "case_repository"


def test_auto_add_does_not_create_a_write_allowance_that_did_not_exist(harness):
    """AC-8 — 쓰기 허용이 하나도 없는 Case 에 쓰기를 만들어 주지 않는다.

    이것이 "새 권한"이며 D-38이 재판단을 요구하는 경우다.
    """
    case, _repo = _agreed_git_case(harness)
    second = _second_repo(harness, {"id": case["project_id"]})

    refused = harness.client.post(
        f"/api/cases/{case['id']}/repositories/auto",
        json={"repository_id": second["repository"]["id"], "selected_by": "ai"},
    )
    assert refused.status_code == 409, refused.text
    assert _refusals(refused) == ["auto_add_needs_new_permission"]


def test_auto_add_cannot_cross_an_explicit_exclusion(harness):
    """AC-8 — 명시 제외는 자동 추가가 넘지 못하는 경계다(D-63)."""
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)
    harness.select_repository(
        case["id"],
        second["repository"]["id"],
        code_write_allowed=False,
        selection_source="excluded",
    )

    refused = harness.client.post(
        f"/api/cases/{case['id']}/repositories/auto",
        json={"repository_id": second["repository"]["id"], "selected_by": "ai"},
    )
    assert refused.status_code == 409, refused.text
    assert _refusals(refused) == ["repository_explicitly_excluded"]


def test_auto_add_cannot_grant_publication(harness):
    """AC-8 — 쓰기 허용 저장소 추가는 **게시 허용 확대가 아니다**(D-64)."""
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)

    refused = harness.client.post(
        f"/api/cases/{case['id']}/repositories/auto",
        json={
            "repository_id": second["repository"]["id"],
            "selected_by": "ai",
            "publish_allowed": True,
        },
    )
    # 입력 계약에 `publish_allowed` 가 없으므로 값은 무시되고, 자동 추가는 게시를
    # 주지 않는다. **조용히 게시가 켜지지 않는 것**이 확인할 점이다.
    assert refused.status_code == 201, refused.text
    entry = next(
        r
        for r in refused.json()["selected"]
        if r["repository_id"] == second["repository"]["id"]
    )
    assert entry["publish_allowed"] == 0


def test_the_explicit_selection_path_cannot_forge_an_automatic_one(harness):
    """AC-8 — `auto_in_allowance` 를 명시 선택 경로로 적을 수 없다.

    출처만 바꿔 쓸 수 있으면 허용 검사를 우회해 자동 추가가 새 권한을 만든다.
    """
    case, _repo = _agreed_git_case(harness)
    second = _second_repo(harness, {"id": case["project_id"]})

    refused = harness.select_repository(
        case["id"], second["repository"]["id"], selection_source="auto_in_allowance"
    )
    assert refused.status_code == 409, refused.text


def test_auto_add_does_not_overwrite_a_human_selection(harness):
    """AC-7 — 사람이 명시로 고른 저장소를 자동 기록으로 덮지 않는다."""
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    harness.select_repository(case["id"], primary)

    again = harness.client.post(
        f"/api/cases/{case['id']}/repositories/auto",
        json={"repository_id": primary, "selected_by": "ai"},
    )
    assert again.status_code == 201
    assert again.json()["auto_selection"]["changed"] is False
    entry = next(r for r in again.json()["selected"] if r["repository_id"] == primary)
    assert entry["selection_source"] == "explicit"
    assert entry["selected_by"] == "owner"


# ==================================================================== AC-10
#
# 실행이 어느 저장소에서 도는가.


def test_a_run_without_a_repository_is_refused_when_there_is_more_than_one(harness):
    """AC-10 — 작업공간이 둘 이상인데 대상이 미기록이면 **고르지 않고 거부한다.**"""
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])
    harness.prepare_workspace(case["id"], repository_id=primary)
    harness.prepare_workspace(case["id"], repository_id=second["repository"]["id"])
    _prepare_both(harness, case["id"], run_prefix="run-demo", repository_id=primary)

    refused = harness.request_implementation(
        case["id"], run_id="run-ambiguous", permission="workspace_write"
    )
    assert refused.status_code == 409, refused.text
    assert "workspace_target_not_recorded" in refused.json()["detail"]["admission"]["refusals"]
    # 거부도 진입 검사 기록에 남는다 — 왜 시작되지 않았는지가 사라지면 안 된다.
    recorded = [r for check in harness.admission_checks(case["id"]) for r in check["refusals"]]
    assert "workspace_target_not_recorded" in recorded


def test_a_read_only_run_must_also_name_its_repository(harness):
    """AC-10 — **읽기 전용 실행도 대상을 밝혀야 한다.**

    쓰기에만 이 검사를 걸면, 대상을 밝히지 않은 읽기 실행의 배정이 조용히 사용자의
    **원래 저장소**로 떨어진다(작업공간이 둘이면 어느 것도 고를 수 없으므로). 그러면
    설계·검토를 쓰는 실행이 이 Case 가 만들고 있는 코드가 아니라 사용자의 다른 작업을
    읽는다 — 틀린 코드를 읽은 검토는 거부된 검토보다 나쁘다.
    """
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])
    harness.prepare_workspace(case["id"], repository_id=primary)
    harness.prepare_workspace(case["id"], repository_id=second["repository"]["id"])

    refused = harness.ai_prepare(case["id"], "design", run_id="run-design-blind")
    assert refused.status_code == 409, refused.text
    assert (
        "workspace_target_not_recorded"
        in refused.json()["detail"]["admission"]["refusals"]
    )

    # 대상을 밝히면 통과한다. 고치는 것은 "어느 저장소인지 적는 것" 하나다.
    named = harness.ai_prepare(
        case["id"], "design", run_id="run-design-named", repository_id=primary
    )
    assert named.status_code == 201, named.text


def test_a_run_that_names_its_repository_gets_that_workspace(harness):
    """AC-10 — 대상을 밝힌 실행은 **그 저장소의** worktree 에서 돈다."""
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])
    harness.prepare_workspace(case["id"], repository_id=primary)
    target = harness.prepare_workspace(
        case["id"], repository_id=second["repository"]["id"]
    )
    # 이 시험의 구현 Task 는 **두 번째 저장소**의 작업이다(P3-04). 계획이 그것을
    # 말하지 않으면 `task_repository_not_recorded` 로 막힌다 — 그 거부를 확인하는
    # 시험은 `tests/test_task_repository.py` 에 짝으로 있다.
    _prepare_both(
        harness,
        case["id"],
        run_prefix="run-demo",
        repository_id=primary,
        task_repository="ui",
    )

    created = harness.request_implementation(
        case["id"],
        run_id="run-targeted",
        permission="workspace_write",
        repository_id=second["repository"]["id"],
    )
    assert created.status_code == 201, created.text

    assignments = harness.client.post(
        f"/api/runner/{harness.runner_config.runner_id}/assignments"
    ).json()
    assignment = next(a for a in assignments if a["run_id"] == "run-targeted")
    assert assignment["workspace"]["repository_id"] == second["repository"]["id"]
    assert assignment["workspace_path"] == target["worktree_path"]
    assert assignment["workspace"]["base_commit"] == target["base_commit"]


# ==================================================================== AC-11
#
# 부분 준비 실패.


def test_one_repository_failing_to_prepare_leaves_the_other_ready(harness):
    """AC-11 — 한 저장소의 준비 실패가 다른 저장소의 준비를 되돌리지 않는다.

    **실패를 준비됨으로 바꾸지도 않는다.** 부분 준비는 부분 준비로 남아야 화면이
    "왜 아직 시작되지 않는가"를 답할 수 있다.
    """
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    missing = harness.register_repository(
        case["project_id"], "gone", str(harness.tmp_path / "does-not-exist")
    )
    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], missing["id"])

    harness.prepare_workspace(case["id"], repository_id=primary)
    assert harness.request_workspace(
        case["id"], repository_id=missing["id"]
    ).status_code == 201
    harness.agent.prepare_workspaces()

    view = harness.workspace_view(case["id"])
    spaces = {w["repository_id"]: w for w in view["workspaces"]}
    assert spaces[primary]["state"] == "ready"
    assert spaces[missing["id"]]["state"] == "failed"
    assert "저장소가 이 호스트에 없거나" in spaces[missing["id"]]["failure_reason"]
    # **부분 준비를 완전 준비로 읽지 않는다.**
    assert view["all_ready"] is False
    assert view["ready_count"] == 1


# ==================================================================== AC-15
#
# 경합.


def test_two_cases_use_their_own_worktrees_in_the_same_repository(harness):
    """AC-15 — 서로 다른 Case 는 같은 저장소에서 각자의 worktree 를 쓴다.

    worktree 가 다르다는 것이 원격 충돌까지 없앤다는 뜻은 아니다 — 그것은 P5다.
    """
    first, repo = _agreed_git_case(harness, name="demo")
    second = harness.create_case(first["project_id"], title="두 번째")
    harness.submit_intent_draft(second["id"], FIELDS)

    a = harness.prepare_workspace(first["id"])
    b = harness.prepare_workspace(second["id"])

    assert a["worktree_path"] != b["worktree_path"]
    assert a["branch"] != b["branch"]
    assert a["repo_path"] == b["repo_path"] == str(repo)
    # 두 브랜치가 실제로 그 저장소에 있고 서로 다른 자리를 가리킨다.
    listing = _git(repo, "worktree", "list", "--porcelain")
    assert a["branch"] in listing and b["branch"] in listing


# ============================================================ AC-12·AC-13·AC-14
#
# 코드 조합.


def test_a_composition_pins_each_repository_and_marks_what_it_did_not_observe(harness):
    """AC-12 — 조합이 저장소별 스냅샷을 고정하고, 관측 없는 저장소를 표시한다.

    **기준 커밋만으로 실제 입력을 설명할 수 없다.** 그 사실을 빈칸이 아니라 값으로
    남긴다(execution-workspace-review 2.1절).
    """
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])
    harness.prepare_workspace(case["id"], repository_id=primary)
    harness.prepare_workspace(case["id"], repository_id=second["repository"]["id"])

    built = harness.client.post(f"/api/cases/{case['id']}/composition")
    assert built.status_code == 201, built.text
    composition = built.json()

    assert [e["repository_id"] for e in composition["entries"]] == sorted(
        [primary, second["repository"]["id"]]
    )
    # 실행이 아직 없다 — 기준 커밋만 있고 지금 상태는 **모른다.**
    assert all(e["source"] == "workspace_base" for e in composition["entries"])
    assert all(e["snapshot_incomplete"] for e in composition["entries"])
    assert composition["snapshot_complete"] is False
    assert all(e["base_commit"] for e in composition["entries"])

    # 같은 상태에서 다시 부르면 **새 revision 을 만들지 않는다.**
    again = harness.client.post(f"/api/cases/{case['id']}/composition").json()
    assert again["revision"] == composition["revision"]
    assert again["id"] == composition["id"]


def test_a_partial_composition_is_not_an_integration_result(harness):
    """AC-14 — 개별 저장소 통과를 통합 통과로 자동 승격하지 않는다.

    조합이 이 Case 의 코드 대상을 전부 담지 않았다면 통합은 **검증되지 않은** 것이다.
    """
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])
    # 한 저장소만 준비했다. 다른 하나는 코드 대상이지만 조합에 들어가지 못한다.
    harness.prepare_workspace(case["id"], repository_id=primary)

    composition = harness.client.post(f"/api/cases/{case['id']}/composition").json()
    assert [e["repository_id"] for e in composition["entries"]] == [primary]
    assert composition["covers_all_code_repositories"] is False
    assert composition["integration_verified"] is False
    assert "전부 담지 않았다" in composition["integration_detail"]


def test_adding_a_code_target_makes_an_earlier_composition_partial(harness):
    """AC-14 — 코드 대상이 늘면 이전 조합은 **전부를 담지 않은 것**이 된다.

    항목이 그대로여도 통합 범위는 달라진다. 지문만 비교해 같은 조합을 돌려주면 옛
    조합이 `integration_verified = true` 인 채로 살아남아, 담지도 않은 저장소의
    통합이 검증됐다고 말하게 된다(2.1절).
    """
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    harness.select_repository(case["id"], primary)
    harness.prepare_workspace(case["id"], repository_id=primary)

    first = harness.client.post(f"/api/cases/{case['id']}/composition").json()
    assert first["covers_all_code_repositories"] is True
    assert first["integration_verified"] is True

    # 작업공간은 늘지 않았다 — **코드 대상만** 늘었다. 항목도 지문도 그대로다.
    second_repo = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], second_repo["repository"]["id"])

    rebuilt = harness.client.post(f"/api/cases/{case['id']}/composition").json()
    assert rebuilt["composition_hash"] == first["composition_hash"], "항목은 그대로여야 한다"
    assert rebuilt["revision"] == first["revision"] + 1, "새 revision 이 생겨야 한다"
    assert rebuilt["covers_all_code_repositories"] is False
    assert rebuilt["integration_verified"] is False

    # 이전 조합은 **지우지 않는다.** 그때 무엇을 검증했는가가 남아야 한다.
    kept = harness.client.get(f"/api/cases/{case['id']}/compositions/{first['id']}")
    assert kept.status_code == 200
    assert kept.json()["state"] == "superseded"


def test_a_change_in_an_unrelated_repository_does_not_invalidate_the_evidence(harness):
    """AC-13 — 조합에 **들어 있는** 저장소가 바뀐 것만 stale 이다.

    무관한 Repo 변경으로 모든 증거를 폐기하지 않는다(2.1절). 폐기하면 두 저장소
    Project 에서 어느 근거도 오래 살아남지 못한다.

    **변화를 아는 길은 관측뿐이다.** 제어부는 git 을 보지 않으므로 저장소가
    움직였다는 사실은 실행이 보고한 효과로 들어온다 — 그래서 여기서도 실제 구현
    실행으로 트리를 바꾼다.
    """
    case, _repo = _agreed_git_case(harness)
    primary = harness.project_repository_id(case["project_id"])
    second = _second_repo(harness, {"id": case["project_id"]})
    harness.select_repository(case["id"], primary)
    harness.select_repository(case["id"], second["repository"]["id"])
    harness.prepare_workspace(case["id"], repository_id=primary)
    _prepare_both(
        harness,
        case["id"],
        run_prefix="run-demo",
        repository_id=primary,
        task_repository="primary",
    )

    harness.agent.cli_executor.write_files = {"filter.py": "def only_errors(x):\n    return x\n"}
    assert harness.request_implementation(
        case["id"],
        run_id="run-comp-1",
        permission="workspace_write",
        repository_id=primary,
    ).status_code == 201
    harness.agent.poll_once()

    # 첫 저장소를 **관측한** 조합. 이것이 그때의 근거가 가리키는 대상이다.
    composition = harness.client.post(f"/api/cases/{case['id']}/composition").json()
    entry = composition["entries"][0]
    assert entry["repository_id"] == primary
    assert entry["source"] == "run_effect"
    assert entry["tree_digest"], "관측했는데 트리 지문이 비어 있다"
    assert entry["snapshot_incomplete"] is False

    def validity() -> dict:
        response = harness.client.get(
            f"/api/cases/{case['id']}/compositions/{composition['id']}"
        )
        assert response.status_code == 200, response.text
        return response.json()["validity"]

    before = validity()
    assert before["stale"] is False
    assert before["changed_repositories"] == []

    # 조합에 **없는** 저장소가 준비돼 상태가 늘어난다. 이 근거와 무관하다.
    harness.prepare_workspace(case["id"], repository_id=second["repository"]["id"])
    assert validity()["stale"] is False, "조합에 없는 저장소의 변경이 근거를 무효로 만들었다"

    # 조합에 **있는** 저장소가 다시 바뀌면 stale 이다.
    harness.agent.cli_executor.write_files = {"filter.py": "def only_errors(x):\n    return []\n"}
    assert harness.request_implementation(
        case["id"],
        run_id="run-comp-2",
        permission="workspace_write",
        repository_id=primary,
    ).status_code == 201
    harness.agent.poll_once()

    moved = validity()
    assert moved["stale"] is True
    assert moved["changed_repositories"] == [primary]


# ==================================================================== AC-16
#
# 정본 경로.


def test_the_registry_is_the_source_of_truth_for_repository_paths(harness):
    """`project_repository` 가 경로의 정본이고 v1 컬럼의 어긋남을 드러낸다(P3-R2).

    조용히 어긋난 값을 남겨 두면 어느 경로에서 실제로 작업했는지 말할 수 없다.
    """
    project, repo = harness.create_git_project(name="demo")
    view = harness.client.get(f"/api/projects/{project['id']}/repositories").json()

    assert view["canonical_source"] == "project_repository"
    assert view["legacy_repo_path"] == str(repo)
    assert view["legacy_repo_path_matches_registry"] is True

    second = _second_repo(harness, project)
    view = harness.client.get(f"/api/projects/{project['id']}/repositories").json()
    # 저장소가 둘이 되어도 v1 컬럼은 하나뿐이다. 그 한계가 값으로 보인다.
    assert len(view["repositories"]) == 2
    assert second["repository"]["repo_path"] not in [view["legacy_repo_path"]]
