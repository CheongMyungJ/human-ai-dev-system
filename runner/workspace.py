"""Case 전용 작업공간 — git worktree 준비와 실행 효과 관측 (P3-03).

**왜 Runner 에 있는가.** 저장소와 파일은 이 호스트에 있다(D-43·FR-27). 제어부가
직접 git 을 부르면 단일 호스트에서만 동작하고 서버+PC 배치에서 무너진다. 제어부로는
식별자(브랜치·경로·커밋 SHA)와 **수**만 올라간다 — diff 와 파일 경로는 여기 남는다.

이 모듈이 지키는 것:

    **사용자의 원래 작업 트리를 건드리지 않는다.** 미커밋·미추적 파일이 있어도
    자동 커밋·stash·reset·삭제를 하지 않는다. `git worktree add` 는 새 경로에
    파일을 펼칠 뿐 원래 트리를 손대지 않으며, 기준 커밋은 **커밋된 상태**다.
    선택되지 않은 사용자 변경을 복사하지도 폐기하지도 않는다
    (execution-workspace-review 2절, FR-08·FR-26).

    **덮어쓰지 않는다.** 같은 이름의 브랜치나 비어 있지 않은 경로가 이미 있으면
    소유 관계를 대조하고, 우리 것으로 확인되지 않으면 거부한다.

    **격리라고 하지 않는다.** worktree 는 파일 배치의 분리이며 다른 경로·공유
    자격증명 접근을 막는 sandbox 가 아니다(D-44). 이 모듈이 할 수 있는 것은
    경계 밖 변경을 **감지해 드러내는 것**뿐이고, 막았다고 적지 않는다.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from domain.models import WorkspaceOwnership

#: 권고 잠금 파일의 접미사. 같은 호스트의 두 Runner 프로세스가 한 worktree 에
#: 동시에 쓰는 것을 줄인다. **OS 잠금이 아니다** — 이 규약을 지키는 프로세스에만
#: 효과가 있고, 다른 경로로 들어오는 쓰기는 막지 못한다.
LOCK_SUFFIX = ".hads-lock"

GIT_TIMEOUT = 120.0


class WorkspaceError(RuntimeError):
    """작업공간을 준비하거나 관측할 수 없다. 사람이 고쳐야 하는 상태다."""


def git(repo: Path, *args: str, check: bool = True) -> str:
    """저장소 안에서 git 을 실행하고 stdout 을 돌려준다.

    **`--no-optional-locks` 를 쓰지 않는다.** 상태 조회가 인덱스를 갱신하더라도
    그것은 git 의 정상 동작이며, 우리가 보려는 것은 "사용자 눈에 보이는 상태"다.
    """
    proc = subprocess.run(
        ["git", *args],
        cwd=str(repo),
        capture_output=True,
        timeout=GIT_TIMEOUT,
    )
    out = proc.stdout.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise WorkspaceError(f"git {' '.join(args)} 실패 (exit {proc.returncode}): {err}")
    return out


@dataclass(frozen=True)
class TreeState:
    """한 작업 트리의 관측값.

    `entries` 는 `git status --porcelain` 의 줄 목록이다. **이 목록은 Runner 에만
    남는다** — 제어부로는 수만 올라간다(D-43).

    `digest` 는 그 시점 작업 트리 **내용**의 지문이다. 상태 줄 목록만으로는
    "이미 고쳐져 있던 파일을 또 고친 것"과 "아무 것도 하지 않은 것"을 구별할 수
    없다 — 둘 다 `M reader.py` 한 줄이기 때문이다. 이 구별이 필요한 이유는
    구현 실행의 완료 판정이 **이 실행이 무엇을 바꿨는가**에 달려 있어서다.
    """

    head: str
    entries: tuple[str, ...]
    digest: str = ""

    @property
    def dirty(self) -> bool:
        return bool(self.entries)

    def to_summary(self) -> dict[str, Any]:
        """제어부로 보낼 수 있는 모양. 파일 경로가 없다."""
        return {"head": self.head, "entry_count": len(self.entries), "dirty": self.dirty}


def lock_path_for(worktree: Path) -> Path:
    """그 worktree 의 권고 잠금 파일 자리.

    **worktree 안이 아니라 옆이다.** 안에 두면 잠금 파일 자체가 미추적 변경으로
    잡혀 "이 실행이 무엇을 바꿨는가"의 답에 섞인다. 관측 수단이 관측 대상을
    바꾸면 안 된다.
    """
    return Path(worktree).parent / f"{Path(worktree).name}{LOCK_SUFFIX}"


def lock_holder(path: Path) -> str | None:
    """그 권고 잠금을 지금 누가 잡고 있는가. 없으면 `None`.

    잡지 않고 **보기만 한다.** 배정을 받은 직후에 이것을 보고 실행을 접으면, 실행이
    `assigned` 로 멈춘 채 남지 않고 사유와 함께 끝난다.
    """
    try:
        return Path(path).read_text(encoding="utf-8").strip() or "unknown"
    except FileNotFoundError:
        return None
    except OSError:
        return "unknown"


def observe(tree: Path) -> TreeState:
    """작업 트리의 현재 HEAD 와 미커밋·미추적 상태를 본다. **바꾸지 않는다.**

    내용 지문도 함께 만든다. 추적되는 변경은 `git diff HEAD` 의 본문에서,
    미추적 파일은 그 내용의 blob 해시에서 가져온다 — 경로와 본문은 여기 남고
    제어부로는 **지문 비교의 결과(bool)만** 올라간다.
    """
    head = git(tree, "rev-parse", "HEAD").strip()
    status = git(tree, "status", "--porcelain")
    entries = tuple(line for line in status.splitlines() if line.strip())

    hasher = hashlib.sha256()
    hasher.update(head.encode("utf-8"))
    hasher.update(git(tree, "diff", "HEAD", check=False).encode("utf-8", "replace"))
    for line in git(tree, "ls-files", "--others", "--exclude-standard", check=False).splitlines():
        name = line.strip()
        if not name:
            continue
        hasher.update(name.encode("utf-8"))
        # 내용이 바뀌면 해시가 바뀐다. 읽지 못하면 그 사실을 지문에 남긴다 —
        # 읽지 못한 것을 "같다"로 읽지 않는다.
        blob = git(tree, "hash-object", "--", name, check=False).strip()
        hasher.update((blob or "unreadable").encode("utf-8"))
    return TreeState(head=head, entries=entries, digest=hasher.hexdigest())


def is_git_repo(path: Path) -> bool:
    if not path.is_dir():
        return False
    proc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(path),
        capture_output=True,
        timeout=GIT_TIMEOUT,
    )
    return proc.returncode == 0


def branch_exists(repo: Path, branch: str) -> bool:
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"],
        cwd=str(repo),
        capture_output=True,
        timeout=GIT_TIMEOUT,
    )
    return proc.returncode == 0


def worktree_paths(repo: Path) -> dict[str, str]:
    """이 저장소에 등록된 worktree 경로 → 브랜치.

    **등록된 것만 우리 것일 수 있다.** 경로에 파일이 있다고 해서 우리가 만든
    worktree 라고 보지 않는다.
    """
    out = git(repo, "worktree", "list", "--porcelain")
    result: dict[str, str] = {}
    current: str | None = None
    for line in out.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree ") :].strip()
        elif line.startswith("branch ") and current:
            result[os.path.normcase(os.path.abspath(current))] = line[len("branch ") :].strip()
    return result


def ownership(repo: Path, path: Path, branch: str) -> WorkspaceOwnership:
    """이미 있는 경로·브랜치가 **누구 것인가.**

    이름이 같다고 우리 것으로 간주하지 않는다. 등록된 worktree 목록에서 그 경로가
    정확히 그 브랜치를 가리킬 때만 재사용한다 — 그래야 사람이 같은 이름으로 만든
    브랜치를 빼앗지 않는다.
    """
    registered = worktree_paths(repo)
    key = os.path.normcase(os.path.abspath(str(path)))
    if key in registered:
        if registered[key] == f"refs/heads/{branch}":
            return WorkspaceOwnership.SYSTEM_OWNED
        return WorkspaceOwnership.FOREIGN
    if path.exists() and any(path.iterdir()):
        return WorkspaceOwnership.FOREIGN
    if branch_exists(repo, branch):
        # 브랜치는 있는데 이 경로의 worktree 가 아니다. 사람이 만든 것일 수 있다.
        return WorkspaceOwnership.FOREIGN
    return WorkspaceOwnership.ABSENT


@dataclass
class PreparedWorkspace:
    repo_path: str
    worktree_path: str
    branch: str
    base_commit: str
    base_ref: str
    #: 준비 시점의 **사용자 원래 작업 트리**. 시스템이 정리하지 않았다는 기록이다.
    user_tree: TreeState | None = None
    reused: bool = False
    #: UI-04d(D-77). 어떤 코드에서 시작했는가(`committed` | `include_uncommitted`). 재사용이면 처음 것.
    start_basis: str | None = None
    #: 그때 기준 ref 의 커밋(HEAD). 포함이면 `base_commit` 은 이 위의 스냅샷 커밋이다.
    committed_base: str = ""
    #: 포함한 미커밋 항목 수와 그 트리의 지문. 경로는 여기(Runner)에만 있다.
    included_entries: int = 0
    included_tree_digest: str = ""


@dataclass(frozen=True)
class NeedsBasis:
    """만들지 않았다(UI-04d, D-77) — 사용자의 원래 트리에 커밋하지 않은 변경이 있어 **사람이 고른다.**

    `entries` 는 `git status --porcelain` 줄이며 **이 Runner 에만 남고** 제어부로는 메모리 중계로만 간다.
    `stale` 은 이미 고른 기준으로 만들려다 목록 때의 지문과 달라 멈췄다는 뜻이다 — 사람이 본 목록과
    다른 것을 포함하지 않는다.
    """

    head: str
    entries: tuple[str, ...]
    digest: str
    stale: bool = False


#: 미커밋 포함 시작의 스냅샷 커밋 작성자. 사용자의 이름·설정을 쓰지 않는다 — 시스템이 만든 커밋이다.
SNAPSHOT_AUTHOR = {
    "GIT_AUTHOR_NAME": "hads",
    "GIT_AUTHOR_EMAIL": "hads@local",
    "GIT_COMMITTER_NAME": "hads",
    "GIT_COMMITTER_EMAIL": "hads@local",
}


def snapshot_commit(repo: Path, head: str, entry_count: int) -> str:
    """사용자의 현재 작업 트리(미커밋·미추적 포함, `.gitignore` 존중)를 **스냅샷 커밋**으로 만든다(UI-04d, D-77).

    **원래 트리·인덱스·브랜치·HEAD 를 건드리지 않는다.** 임시 인덱스 파일(`GIT_INDEX_FILE`)에 HEAD 를 읽어
    들이고 `add -A` 로 작업 트리를 얹어 `write-tree` → `commit-tree`(부모 = HEAD) 한다. 그 결과는 객체
    저장소에 더해진 커밋 하나이며 어떤 ref 도 옮기지 않는다 — Case 브랜치가 그 커밋을 가리키게 되는 것은
    호출자의 `worktree add` 다. 사용자에게는 `git log` 의 브랜치 첫 커밋으로 보인다(감추지 않는다).
    """
    repo = Path(repo)
    index = repo / ".git" / f"hads-snapshot-{os.getpid()}-{int(time.time() * 1000)}.index"
    git_dir = git(repo, "rev-parse", "--git-dir").strip()
    index = (repo / git_dir).resolve() / index.name
    env = {**os.environ, "GIT_INDEX_FILE": str(index), **SNAPSHOT_AUTHOR}

    def run(*args: str) -> str:
        proc = subprocess.run(
            ["git", *args], cwd=str(repo), capture_output=True, timeout=GIT_TIMEOUT, env=env
        )
        if proc.returncode != 0:
            err = proc.stderr.decode("utf-8", errors="replace").strip()
            raise WorkspaceError(f"git {' '.join(args)} 실패 (exit {proc.returncode}): {err}")
        return proc.stdout.decode("utf-8", errors="replace")

    try:
        run("read-tree", head)
        run("add", "-A")
        tree = run("write-tree").strip()
        message = f"hads: 미커밋 변경 {entry_count}건을 포함해 시작 (스냅샷, 원래 폴더는 그대로)"
        return run("commit-tree", tree, "-p", head, "-m", message).strip()
    finally:
        try:
            index.unlink()
        except OSError:
            pass


def prepare(
    repo_path: Path,
    worktree_path: Path,
    branch: str,
    base_ref: str = "HEAD",
    known_base_commit: str = "",
    start_basis: str | None = None,
    expected_tree_digest: str = "",
) -> PreparedWorkspace | NeedsBasis:
    """Case 전용 브랜치와 worktree 를 만든다.

    순서가 중요하다.

      1. 저장소인지 확인한다. **없는 저장소를 빈 디렉터리로 만들어 주지 않는다** —
         프로젝트가 가리키는 코드가 이 호스트에 없다는 사실을 가리게 된다
      2. 사용자의 원래 작업 트리를 **관측만** 한다. 정리하지 않는다
      3. 기준 커밋을 해석한다. `HEAD` 는 커밋된 상태이며 미커밋 변경을 담지 않는다
      4. 소유 관계를 대조한다. 우리 것이면 재사용하고, 남의 것이면 거부한다
      5. (UI-04d, D-77) 트리가 더럽고 시작 기준이 정해지지 않았으면 **만들지 않고 묻는다**(`NeedsBasis`).
         `include_uncommitted` 면 목록 때의 지문과 같을 때만 스냅샷 커밋을 만들어 그 위에서 편다
      6. `git worktree add` 로 새 경로에 브랜치를 펼친다

    `known_base_commit` 은 앞선 준비가 이미 정한 기준이다. 재사용할 때 그 값을
    다시 쓰는 이유는, 재사용 시점의 HEAD 로 바꾸면 **이미 한 변경이 기준에 섞여**
    "무엇이 바뀌었는가"를 답할 수 없기 때문이다.
    """
    repo_path = Path(repo_path)
    worktree_path = Path(worktree_path)

    if not is_git_repo(repo_path):
        raise WorkspaceError(f"저장소가 이 호스트에 없거나 git 저장소가 아니다: {repo_path}")

    user_tree = observe(repo_path)
    base_commit = git(repo_path, "rev-parse", f"{base_ref}^{{commit}}").strip()

    owned = ownership(repo_path, worktree_path, branch)
    if owned is WorkspaceOwnership.FOREIGN:
        raise WorkspaceError(
            f"이미 있는 브랜치 또는 경로를 덮어쓰지 않는다: branch={branch},"
            f" path={worktree_path}. 소유 관계를 확인할 수 없다"
        )
    if owned is WorkspaceOwnership.SYSTEM_OWNED:
        existing = observe(worktree_path)
        # **기준 커밋은 처음 만든 그 커밋이다.** 기록이 있으면 그것을 쓰고, 없으면
        # 갈라진 지점(merge-base)으로 되찾는다. 둘 다 안 되면 현재 HEAD 를 쓰되
        # 그 경우 이미 한 변경은 기준에 포함된다 — 지어낸 값을 쓰지는 않는다.
        recovered = known_base_commit.strip() or git(
            repo_path, "merge-base", branch, base_commit, check=False
        ).strip()
        return PreparedWorkspace(
            repo_path=str(repo_path),
            worktree_path=str(worktree_path),
            branch=branch,
            base_commit=recovered or existing.head,
            base_ref=base_ref,
            user_tree=user_tree,
            reused=True,
            start_basis=start_basis,
        )

    # UI-04d(D-77). **더러운 트리는 사람이 고른 뒤에만 만든다.** 깨끗하면 묻지 않는다(HEAD 기본).
    if user_tree.dirty and not start_basis:
        return NeedsBasis(head=user_tree.head, entries=user_tree.entries, digest=user_tree.digest)

    included = 0
    included_digest = ""
    committed_base = base_commit
    start_commit = base_commit
    chosen = start_basis or "committed"
    if chosen == "include_uncommitted":
        if base_commit != user_tree.head:
            # 사용자 트리는 HEAD 위의 변경이다 — 다른 기준과 합칠 수 없다. 조용히 다른 것을 만들지 않는다.
            raise WorkspaceError(
                f"미커밋 포함 시작은 현재 HEAD 기준에서만 뜻이 있다: base_ref={base_ref} 는"
                f" HEAD 가 아니다"
            )
        if user_tree.digest != (expected_tree_digest or ""):
            # 목록을 올린 뒤 트리가 바뀌었다. 사람이 본 것과 다른 것을 포함하지 않는다 — 다시 묻는다.
            return NeedsBasis(
                head=user_tree.head, entries=user_tree.entries, digest=user_tree.digest, stale=True
            )
        if user_tree.dirty:
            start_commit = snapshot_commit(repo_path, user_tree.head, len(user_tree.entries))
            included = len(user_tree.entries)
            included_digest = user_tree.digest
        else:
            # 고르는 사이 사용자가 직접 커밋해 트리가 깨끗해졌을 수는 없다(지문이 같다) — 여기 오면 목록이 비어
            # 있었던 것이므로 커밋된 코드와 같다.
            chosen = "committed"
    elif chosen != "committed":
        raise WorkspaceError(f"모르는 시작 기준: {start_basis}")

    worktree_path.parent.mkdir(parents=True, exist_ok=True)
    git(repo_path, "worktree", "add", "-b", branch, str(worktree_path), start_commit)
    return PreparedWorkspace(
        repo_path=str(repo_path),
        worktree_path=str(worktree_path),
        branch=branch,
        base_commit=start_commit,
        base_ref=base_ref,
        user_tree=user_tree,
        reused=False,
        start_basis=chosen,
        committed_base=committed_base,
        included_entries=included,
        included_tree_digest=included_digest,
    )


def diff_numbers(tree: Path, base_commit: str) -> dict[str, int]:
    """기준 커밋 대비 변경의 **수**. 파일 경로도 diff 본문도 넣지 않는다.

    미추적 파일까지 세기 위해 `--no-index` 가 아니라 두 경로로 나눠 센다 —
    `git diff --numstat` 은 추적되는 변경만 보고, 새로 만든 파일은 `status` 에만
    나오기 때문이다. 둘을 합치지 않으면 "파일을 새로 만든 구현"이 변경 없음으로
    보인다.
    """
    files = insertions = deletions = 0
    numstat = git(tree, "diff", "--numstat", base_commit, check=False)
    for line in numstat.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        added, removed = parts[0], parts[1]
        files += 1
        insertions += int(added) if added.isdigit() else 0
        deletions += int(removed) if removed.isdigit() else 0
    untracked = git(tree, "ls-files", "--others", "--exclude-standard", check=False)
    for line in untracked.splitlines():
        if not line.strip():
            continue
        files += 1
        path = tree / line.strip()
        try:
            with path.open("rb") as fh:
                insertions += sum(1 for _ in fh)
        except OSError:
            # 읽을 수 없는 파일을 0줄로 적지 않는다. 파일 수에는 이미 셌다.
            pass
    return {"files": files, "insertions": insertions, "deletions": deletions}


def compose_effect(
    before: TreeState,
    after: TreeState,
    base_commit: str,
    numbers: dict[str, int],
    repo_before: TreeState | None = None,
    repo_after: TreeState | None = None,
    last_tree_digest: str | None = None,
    last_effect_run_id: str | None = None,
) -> dict[str, Any]:
    """제어부로 올릴 작업공간 효과. **식별자와 수만 들어간다.**

    `outside_workspace_changed` 는 **감지했다는 뜻이지 막았다는 뜻이 아니다.**
    worktree 는 OS 격리가 아니므로(D-44) CLI 는 원래 저장소를 고칠 수 있고, 우리가
    할 수 있는 것은 실행 전후를 대조해 드러내는 것뿐이다.

    `last_tree_digest` 는 제어부가 실어 준 **이 저장소의 직전 실행이 남긴 트리 지문**이다(UI-04c,
    D-89). 이 실행이 시작할 때 본 지문과 다르면 그 사이에 **외부 변경**(사람의 편집기 등)이 있었다 —
    `external_change_before_run` 으로 드러내되 되돌리지 않는다(FR-26). 직전 실행이 없으면 `None`
    (모른다)이지 `False` 가 아니다.
    """
    # **이 실행이 바꾼 것만 본다.** `numbers` 는 기준 커밋 대비 **누적**이라
    # 앞선 실행이 이미 바꿔 놓았으면 아무 것도 하지 않은 실행까지 "바뀜"이 된다.
    # 그러면 "바뀌지 않았으면 완료가 아니다"가 첫 실행에만 적용되는 규칙이 된다.
    changed = (
        before.head != after.head
        or before.entries != after.entries
        or before.digest != after.digest
    )
    effect: dict[str, Any] = {
        "base_commit": base_commit,
        "head_before": before.head,
        "head_after": after.head,
        "entries_before": len(before.entries),
        "entries_after": len(after.entries),
        # **트리 내용의 지문.** 코드 조합이 이 값으로 스냅샷을 고정한다(P3-R2,
        # execution-workspace-review 2.1절). 해시이며 본문이 아니다 — 파일 경로도
        # diff 도 들어 있지 않고, `artifact_ref.content_hash` 와 같은 성격이다.
        # 이것이 없으면 HEAD 가 같은 두 시점의 미커밋 상태를 구별할 수 없어
        # "무엇을 검증했는가"를 커밋 하나로만 말하게 된다.
        "tree_digest_before": before.digest,
        "tree_digest_after": after.digest,
        # **이 실행이 무엇인가 바꿨는가.** 아래 수와 다르다 — 수는 누적이다.
        "changed": changed,
        # 기준 커밋 대비 **누적** 변경. 이 실행만의 것이 아니다.
        "files_changed": numbers.get("files", 0),
        "insertions": numbers.get("insertions", 0),
        "deletions": numbers.get("deletions", 0),
        "numbers_are_cumulative": True,
        # 관측 한계를 값으로 남긴다. "격리했다"가 아니라 "이만큼 봤다"이다.
        "isolation": "worktree_file_layout_only",
    }
    if repo_before is not None and repo_after is not None:
        effect["outside_workspace_changed"] = (
            repo_before.head != repo_after.head or repo_before.entries != repo_after.entries
        )
        effect["outside_workspace_observed"] = True
    else:
        effect["outside_workspace_changed"] = None
        effect["outside_workspace_observed"] = False
    # UI-04c(D-89). 직전 실행이 남긴 지문과 이 실행 전의 지문을 대조한다. **확인일 뿐이다** — worktree 는
    # 초기화되지 않으므로 외부 변경은 그대로 보존된 채 이 실행의 입력이 됐다.
    if last_tree_digest is None:
        effect["external_change_before_run"] = None
    else:
        effect["external_change_before_run"] = before.digest != last_tree_digest
    effect["external_change_basis_run_id"] = last_effect_run_id
    return effect


@dataclass
class AdvisoryLock:
    """worktree 권고 잠금.

    **OS 잠금이 아니다.** 이 규약을 지키는 Runner 프로세스에만 효과가 있으며,
    다른 도구가 같은 경로에 쓰는 것을 막지 못한다. 제어부의 배정 직렬화와 함께
    두는 이유는, 한쪽만으로는 각각 다른 경우를 놓치기 때문이다 — 제어부는 같은
    호스트의 두 Runner 프로세스를 모르고, 이 파일은 다른 호스트를 모른다.
    """

    path: Path
    acquired: bool = False
    holder: str = field(default="")

    def acquire(self, owner: str) -> bool:
        try:
            fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                self.holder = self.path.read_text(encoding="utf-8").strip()
            except OSError:
                self.holder = "unknown"
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(f"{owner}\t{os.getpid()}\t{time.time()}\n")
        self.acquired = True
        return True

    def release(self) -> None:
        if not self.acquired:
            return
        try:
            self.path.unlink()
        except OSError:
            pass
        self.acquired = False
