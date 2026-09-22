"""P3-04 라이브가 쓰는 **실제 git 저장소 두 개**.

여기서 만드는 것은 흉내가 아니라 진짜 저장소다. worktree 가 사용자의 원래 트리를
건드리지 않는다는 것도, 두 저장소가 서로 맞아야 끝난다는 것도 흉내로는 확인할 수
없기 때문이다(P3-03·P3-R2 가 같은 이유로 실제 저장소를 썼다).

**원격을 붙이지 않는다.** 외부 반영은 P5 이고, 원격이 없으면 실수로도 push 가
일어나지 않는다.

**두 저장소는 코드로 이어져 있지 않다.** 이어 주는 것은 계약 하나다 —
`summarize()` 가 돌려주는 사전의 키 목록. 한 실행은 작업공간 하나만 보므로
(DEVELOPMENT.md 9절) 소비자 저장소를 고치는 실행은 생산자의 코드를 직접 읽지
못하고 계획 산출물이 고정한 계약에 의존한다. 그것이 실제로 충분한지가 P3-04가
관측하려는 것이다.

**사용자의 미커밋 변경을 일부러 남긴다.** 시스템이 그것을 정리하지 않는다는 것이
지켜야 할 첫 번째 기준이다(FR-08·FR-26).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

#: 생산자. 요약 결과의 구조를 정하는 쪽이다.
CORE_NAME = "repo-core"
#: 소비자. 그 구조를 읽어 한 줄로 보고하는 쪽이다.
REPORT_NAME = "repo-report"

CORE_SOURCE = '''"""텍스트 요약."""


def summarize(text):
    """텍스트를 요약해 사전으로 돌려준다.

    돌려주는 키가 이 모듈의 **공개 계약**이다. 키를 더하거나 빼면 이것을 읽는
    쪽(repo-report)이 함께 바뀌어야 한다.
    """
    lines = [line for line in text.splitlines() if line.strip()]
    words = text.split()
    return {"lines": len(lines), "words": len(words)}
'''

#: **의존성 없는 시험 실행기.** pytest 를 요구하지 않는 이유는 라이브가 실제로
#: 거기서 막혔기 때문이다 — CLI 의 sandbox 가 이 저장소의 로컬 가상환경이 가리키는
#: 기반 인터프리터에 닿지 못해 시험이 한 줄도 돌지 않았다. 그 상태에서 기준을
#: `met` 으로 적으면 "실행 불명이 성공"이 된다(FR-28).
RUNNER = '''"""이 저장소의 시험을 돌린다. **외부 의존성이 없다.**

`test_*.py` 를 찾아 그 안의 `test_*` 함수를 부른다. 실패가 있으면 종료 코드 1 이다.
"""

import pathlib
import sys
import traceback


def main():
    here = pathlib.Path(__file__).resolve().parent
    sys.path.insert(0, str(here))
    failed = []
    total = 0
    for path in sorted(here.glob("test_*.py")):
        module = __import__(path.stem)
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            total += 1
            try:
                getattr(module, name)()
                print("ok   %s::%s" % (path.name, name))
            except Exception:
                failed.append("%s::%s" % (path.name, name))
                print("FAIL %s::%s" % (path.name, name))
                traceback.print_exc()
    print("%d passed, %d failed" % (total - len(failed), len(failed)))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
'''

CORE_TEST = '''from summarize import summarize


def test_counts_lines_and_words():
    result = summarize("첫 줄\\n\\n둘째 줄\\n")
    assert result["lines"] == 2
    assert result["words"] == 4


def test_empty_text_has_no_lines():
    assert summarize("") == {"lines": 0, "words": 0}
'''

REPORT_SOURCE = '''"""요약 결과를 한 줄로 보고한다."""


def render(summary):
    """`summarize()` 가 돌려준 사전을 사람이 읽는 한 줄로 만든다.

    입력의 키는 repo-core 가 정한다. 이 모듈은 그 계약을 따른다.
    """
    return "{lines}줄 {words}단어".format(**summary)
'''

REPORT_TEST = '''from report import render


def test_renders_lines_and_words():
    assert render({"lines": 2, "words": 4}) == "2줄 4단어"


def test_renders_an_empty_summary():
    assert render({"lines": 0, "words": 0}) == "0줄 0단어"
'''

#: 사용자가 손대던 것. 시스템은 이것을 커밋하지도 지우지도 않는다.
CORE_DIRTY_EDIT = "\n# TODO(사용자): 문단 수도 세어 볼 것\n"
REPORT_DIRTY_EDIT = "\n# TODO(사용자): 색을 입혀 볼 것\n"
SCRATCH_NAME = "user-scratch.txt"
SCRATCH_BODY = "사용자의 미추적 메모. 시스템이 건드리면 안 된다.\n"


def git(repo: Path, *args: str) -> str:
    """저장소 안에서 git 을 돌리고 stdout 을 돌려준다."""
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return result.stdout


def porcelain(repo: Path) -> str:
    """사용자 작업 트리의 상태. 전후 대조에 쓴다."""
    return git(repo, "status", "--porcelain")


def head(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD").strip()


def _create(repo: Path, files: dict[str, str]) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    git(repo, "init", "-b", "main")
    git(repo, "config", "user.email", "p3-04@example.invalid")
    git(repo, "config", "user.name", "p3-04 live")
    # 시험은 `run_tests.py` 로 돈다. 외부 패키지를 요구하지 않는 이유는 CLI 의
    # sandbox 가 이 개발 저장소의 가상환경에 닿지 못했기 때문이다(라이브 관측).
    for name, body in files.items():
        (repo / name).write_text(body, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-m", "base")


def create_repositories(root: Path, dirty: bool = True) -> dict[str, Path]:
    """두 저장소를 만든다. `dirty` 면 사용자의 미커밋 변경을 남긴다."""
    core = root / CORE_NAME
    report = root / REPORT_NAME

    _create(
        core,
        {"summarize.py": CORE_SOURCE, "test_summarize.py": CORE_TEST, "run_tests.py": RUNNER},
    )
    _create(
        report,
        {"report.py": REPORT_SOURCE, "test_report.py": REPORT_TEST, "run_tests.py": RUNNER},
    )

    if dirty:
        with (core / "summarize.py").open("a", encoding="utf-8") as handle:
            handle.write(CORE_DIRTY_EDIT)
        (core / SCRATCH_NAME).write_text(SCRATCH_BODY, encoding="utf-8")
        with (report / "report.py").open("a", encoding="utf-8") as handle:
            handle.write(REPORT_DIRTY_EDIT)
        (report / SCRATCH_NAME).write_text(SCRATCH_BODY, encoding="utf-8")

    return {CORE_NAME: core, REPORT_NAME: report}
