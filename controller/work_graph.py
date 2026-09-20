"""P3-02 작업 그래프 — 순서·의존·질문 차단의 순수 계산.

**여기에는 DB 접근이 없다.** 입력은 제어부가 읽어 온 값이고 출력은 판정이다.
`controller/sizing.py` 와 같은 자리이며, 같은 이유로 그렇게 둔다 — 차단 규칙은
진입 검사·화면·시험이 모두 같은 함수를 봐야 하고, 그러려면 DB에서 떼어 놓아야 한다.

이 모듈이 지키는 한 가지 규칙:

    **좁히는 것이 느슨해지는 것이 되어서는 안 된다.**

P3-01에서 이월 질문 하나는 Case 전체를 막았다. P3-02는 그것을 "그 결정에 의존하는
Task 만 막는다"로 좁힌다. 좁히기가 우회가 되지 않도록 아래 세 경우는 **전부 막는다.**

    그래프가 없다                     계획이 Task 를 정의하지 않았다
    Task 가 0건이다                   같은 사실의 다른 모습
    열린 질문에 연결된 Task 가 없다   `blocks` 가 비었거나 해석되지 않았다

세 번째가 핵심이다. 연결이 없다는 것은 "아무 것도 막지 않는다"가 아니라 **무엇을
막는지 모른다**는 뜻이고, 모르는 것을 안전한 쪽으로 읽으면 질문 하나를 연결하지
않는 것만으로 모든 차단이 사라진다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from domain.models import TaskState

#: 실행이 Task 를 끝낸 것으로 인정하는 결과.
#:
#: **`unknown` 은 여기 없다.** 실행 불명을 완료로 읽으면 후속 작업이 증거 없이
#: 열린다(FR-28, P2-04가 기준 판정에 쓴 규칙과 같다).
COMPLETED_OUTCOME = "completed"


class WorkGraphError(ValueError):
    """그래프를 구성할 수 없다. 사람이 고쳐야 하는 입력 오류다."""


@dataclass(frozen=True)
class TaskNode:
    key: str
    kind: str
    depends_on: tuple[str, ...]
    cancelled: bool = False


@dataclass
class TaskReadiness:
    """Task 하나의 실행 가능 여부와 그 이유."""

    task_key: str
    state: str
    #: 이 Task 를 막는 사유 코드와 사람이 읽을 설명. 사유는 **모두** 모은다.
    blocked_by: list[tuple[str, str]] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        return not self.blocked_by

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_key": self.task_key,
            "state": self.state,
            "runnable": self.runnable,
            "blocked_by": [{"reason": r, "detail": d} for r, d in self.blocked_by],
        }


def validate_dependencies(tasks: Iterable[TaskNode]) -> None:
    """의존 관계가 그래프로 성립하는지 본다.

    두 가지를 거부한다.

        없는 Task 를 가리키는 의존   그 의존은 영원히 충족되지 않는다.
                                     조용히 버리면 "의존이 없는 Task"가 되어
                                     오히려 먼저 실행된다
        순환                         어느 쪽도 먼저 끝날 수 없다.
                                     받아 두면 두 Task 가 영구히 `unmet` 이 되고
                                     사람은 이유를 알 수 없다

    **경고로 넘기지 않고 거부하는 이유**는, 잘못된 그래프를 저장하면 그 뒤의 모든
    차단 판정이 그 위에서 이루어지기 때문이다.
    """
    nodes = {t.key: t for t in tasks}
    if not nodes:
        return

    for task in nodes.values():
        for dep in task.depends_on:
            if dep not in nodes:
                raise WorkGraphError(
                    f"task {task.key} depends on {dep!r}, which is not a task in this graph"
                )

    # 깊이 우선으로 순환을 찾는다. 재귀 대신 명시적 스택을 쓰는 이유는 큰 계획에서
    # 파이썬 재귀 한도에 걸리지 않게 하기 위해서다.
    WHITE, GREY, BLACK = 0, 1, 2
    color = {key: WHITE for key in nodes}
    for start in nodes:
        if color[start] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(start, 0)]
        path: list[str] = []
        color[start] = GREY
        path.append(start)
        while stack:
            key, index = stack.pop()
            deps = nodes[key].depends_on
            if index < len(deps):
                stack.append((key, index + 1))
                nxt = deps[index]
                if color[nxt] == GREY:
                    cycle = path[path.index(nxt) :] + [nxt]
                    raise WorkGraphError(
                        "task dependencies form a cycle: " + " -> ".join(cycle)
                    )
                if color[nxt] == WHITE:
                    color[nxt] = GREY
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                color[key] = BLACK
                if path and path[-1] == key:
                    path.pop()


def derive_task_state(task: TaskNode, runs: Iterable[dict[str, Any]]) -> str:
    """Task 의 상태를 **실행에서 도출한다.**

    저장된 컬럼을 읽지 않는 이유는, 사람이 "끝났다"고 적는 경로가 곧 실행 증거
    없이 의존을 푸는 문이기 때문이다(FR-09 "미실행을 실행·통과로 표시하지 않는다").

    `failed`·`cancelled`·`unknown` 으로 끝난 실행은 완료가 아니다. 특히 `unknown`
    은 "아마 됐을 것"이 아니라 **모른다**이며, 모르는 것을 완료로 읽으면 후속
    작업이 증거 없이 열린다.
    """
    if task.cancelled:
        return TaskState.CANCELLED.value
    running = False
    for run in runs:
        if run.get("task_id") != task.key:
            continue
        outcome = run.get("outcome")
        if outcome == COMPLETED_OUTCOME:
            return TaskState.DONE.value
        if run.get("status") != "finished":
            running = True
    return TaskState.IN_PROGRESS.value if running else TaskState.PLANNED.value


def evaluate_task(
    *,
    task_key: str,
    tasks: list[TaskNode],
    task_states: dict[str, str],
    open_questions: list[dict[str, Any]],
    question_blocks: dict[str, list[str]],
) -> TaskReadiness:
    """요청한 Task 하나의 차단 사유를 계산한다.

    `open_questions` 는 **최신 의도 버전에 붙은 열린 이월 질문**이고,
    `question_blocks` 는 `question_id → 막는 task_key 목록` 이다. 어떤 질문의
    목록이 비어 있으면 그 질문은 **모든 Task 를 막는다** — 위 모듈 주석의 셋째 규칙.

    질문은 **직접 연결된 Task 만** 막는다. 전이 폐쇄를 질문 쪽에도 넣으면 같은
    차단이 두 사유로 두 번 나와 사람이 무엇을 해야 하는지 흐려진다. 후속 Task 는
    `task_dependencies_unmet` 으로 정확히 그 이유를 받는다.
    """
    nodes = {t.key: t for t in tasks}
    readiness = TaskReadiness(task_key=task_key, state=task_states.get(task_key, ""))

    task = nodes.get(task_key)
    if task is None or task.cancelled:
        readiness.state = task_states.get(task_key, "")
        readiness.blocked_by.append(
            (
                "task_not_in_work_graph",
                f"{task_key!r} 는 현재 작업 그래프의 진행 중인 Task 가 아니다"
                + ("" if task is None else " (취소됨)"),
            )
        )
        return readiness

    unlinked = [q for q in open_questions if not question_blocks.get(q["id"])]
    if unlinked:
        readiness.blocked_by.append(
            (
                "deferred_questions_unresolved",
                "어떤 Task 를 막는지 연결되지 않은 이월 질문이 있어 전부 막는다: "
                + ", ".join(q["question_key"] for q in unlinked),
            )
        )

    mine = [q for q in open_questions if task_key in question_blocks.get(q["id"], [])]
    if mine:
        readiness.blocked_by.append(
            (
                "deferred_questions_unresolved",
                "이 Task 를 막는 사람 결정이 남아 있다: "
                + ", ".join(q["question_key"] for q in mine),
            )
        )

    unmet = [
        dep
        for dep in task.depends_on
        if task_states.get(dep) != TaskState.DONE.value
    ]
    if unmet:
        readiness.blocked_by.append(
            (
                "task_dependencies_unmet",
                "선행 Task 가 아직 완료되지 않았다: "
                + ", ".join(f"{d}({task_states.get(d, 'unknown')})" for d in unmet),
            )
        )

    return readiness


def criteria_coverage(
    criteria: list[dict[str, Any]], links: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """기준마다 구현·검증 Task 가 붙어 있는지 보인다.

    **판정하지 않는다.** 검증 Task 가 없는 기준이 있어도 배정을 막지 않는다 —
    시스템은 산출물의 내용이 충분한지 판정하지 않는다는 P3-01의 경계를 그대로
    유지한다. 연결이 적절한지는 사람 검토와 (P4의) QG-03의 몫이다.
    보이기만 해도 "확인할 작업이 없는 기준"이 사람 눈에 들어온다.
    """
    by_criterion: dict[str, dict[str, list[str]]] = {}
    for link in links:
        entry = by_criterion.setdefault(
            link["criterion_id"], {"implements": [], "verifies": []}
        )
        entry.setdefault(link["relation"], []).append(link["task_key"])

    coverage: list[dict[str, Any]] = []
    for criterion in criteria:
        entry = by_criterion.get(criterion["id"], {"implements": [], "verifies": []})
        coverage.append(
            {
                "criterion_id": criterion["id"],
                "criterion_key": criterion["criterion_key"],
                "summary": criterion["summary"],
                "implemented_by": sorted(entry.get("implements", [])),
                "verified_by": sorted(entry.get("verifies", [])),
                "has_verification_task": bool(entry.get("verifies")),
            }
        )
    return coverage
