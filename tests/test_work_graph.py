"""P3-02 작업 그래프·질문 — 자동 시험.

**이 시험들이 지키려는 한 가지:** 좁히는 것이 느슨해지는 것이 되어서는 안 된다.

P3-01에서 이월 질문 하나는 Case 전체를 막았다. P3-02는 그것을 "그 결정에 의존하는
Task 만 막는다"로 좁혔다. 좁히기가 우회가 되지 않는다는 것을 확인하는 시험이
AC-7이며, 그것이 이 파일에서 가장 중요한 시험이다.

**실제 CLI를 부르지 않는다.** `conftest` 의 `FakeCliExecutor` 를 쓴다. 실제 CLI
연결의 증거는 라이브 검증에서 따로 만든다.
"""

from __future__ import annotations

import pytest

from controller import work_graph
from tests.conftest import (
    FAKE_TASKS,
    fake_preparation_response,
)
from tests.test_preparation import _agreed_case, _prepare_both, _refusals


def _plan_with(tasks, questions=None, sections=None):
    """Task 목록을 바꾼 계획 응답을 만든다."""
    return fake_preparation_response(
        "계획",
        sections
        or {
            "tasks": "작업 목록은 tasks 에 있다",
            "verification": "표본 파일 시험 1건",
            "dependencies": "tasks 의 depends_on 을 따른다",
            "integration_order": "T1 → T2",
            "human_decision_points": "없음",
            "environment_prerequisites": "Python 3.12",
        },
        questions=questions,
        tasks=tasks,
    )


def _graph_case(harness, tasks=None, plan_questions=None):
    """동의된 Case 에 설계·계획을 만들고 그래프까지 세운다."""
    case, _intent = _agreed_case(harness)
    if tasks is not None or plan_questions is not None:
        harness.agent.cli_executor.plan_response = _plan_with(
            FAKE_TASKS if tasks is None else tasks, plan_questions
        )
    _prepare_both(harness, case["id"], finish_first_task=False)
    return case


# ------------------------------------------------------------------- AC-1


def test_a_reviewed_plan_with_tasks_creates_a_work_graph(harness):
    """AC-1: 개발계획이 Task 를 정의하면 작업 그래프 리비전이 만들어진다."""
    case = _graph_case(harness)
    graph = harness.work_graph(case["id"])

    assert graph["present"] is True
    assert graph["graph"]["revision"] == 1
    assert graph["graph"]["source"] == "plan_artifact"
    # 그래프는 그 계획·의도 버전에 묶인다.
    plan = harness.preparation(case["id"])["plan"]["artifact"]
    assert graph["graph"]["plan_preparation_id"] == plan["id"]
    assert graph["graph"]["intent_version_id"] == harness.latest_intent(case["id"])["id"]
    assert [t["task_key"] for t in graph["tasks"]] == ["T1", "T2"]
    # 왜 이 계획인지가 비어 있지 않다.
    assert graph["graph"]["reason_summary"]


def test_a_plan_without_tasks_creates_no_graph(harness):
    """AC-1: **Task 0건은 그래프를 만들지 않는다.**

    v1 계획 문서에는 Task 가 없다. 빈 그래프를 만들어 두면 `work_graph_missing`
    과 "Task 가 전부 취소된 그래프"를 구별할 수 없다.
    """
    case = _graph_case(harness, tasks=[])
    assert harness.work_graph(case["id"])["present"] is False

    refusals = _refusals(harness.request_implementation(case["id"], task_id="T1"))
    assert "work_graph_missing" in refusals


# ------------------------------------------------------------------- AC-2


def test_the_controller_keeps_only_task_summaries(harness):
    """AC-2: **Task 의 본문이 제어부에 오지 않는다.**

    목적·산출물·완료 조건의 서술은 개발계획 원문에 있고, 여기에는 짧은 요약만
    온다. 요약이 없으면 자리표시 문구를 쓰고 본문을 잘라 쓰지 않는다.
    """
    marker = "TASKBODY-" + "9f3c2a" * 4
    tasks = [
        {
            "key": "T1",
            "kind": "implementation",
            "purpose": f"{marker} 이 문자열이 제어부에 남으면 안 된다",
            "purpose_summary": "필터 함수 구현",
            "deliverable": f"{marker} 산출물 서술",
            "completion": "",
        }
    ]
    case = _graph_case(harness, tasks=tasks)
    graph = harness.work_graph(case["id"])
    task = graph["tasks"][0]

    assert task["summary"] == "필터 함수 구현"
    assert marker not in task["summary"]
    assert marker not in task["deliverable_summary"]
    # **비운 것을 채우지 않는다.** 완료 조건이 비었다는 사실이 그대로 보인다.
    assert "비어 있음" in task["completion_summary"]


# ------------------------------------------------------------------- AC-3


def test_dependencies_are_recorded(harness):
    """AC-3: 의존 관계가 기록된다."""
    case = _graph_case(harness)
    tasks = {t["task_key"]: t for t in harness.work_graph(case["id"])["tasks"]}
    assert tasks["T1"]["depends_on"] == []
    assert tasks["T2"]["depends_on"] == ["T1"]


def test_a_dependency_cycle_is_refused(harness):
    """AC-3: **순환은 거부한다.**

    받아 두면 두 Task 가 영구히 `unmet` 이 되고 사람은 이유를 알 수 없다.
    """
    cycle = [
        {"key": "A", "purpose": "A", "depends_on": ["B"]},
        {"key": "B", "purpose": "B", "depends_on": ["A"]},
    ]
    case, _intent = _agreed_case(harness)
    harness.agent.cli_executor.plan_response = _plan_with(cycle)
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    # 계획 작성 실행 자체는 일어나고, 구조 보고에서 그래프 구성이 거부된다.
    harness.ai_prepare(case["id"], "plan")

    # **그래프가 만들어지지 않았다.** 잘못된 그래프를 저장하면 그 뒤의 모든 차단
    # 판정이 그 위에서 이루어진다.
    assert harness.work_graph(case["id"])["present"] is False


def test_a_dependency_on_an_unknown_task_is_refused(harness):
    """AC-3: 없는 Task 를 가리키는 의존도 거부된다.

    조용히 버리면 "의존이 없는 Task"가 되어 오히려 먼저 실행된다.
    """
    with pytest.raises(work_graph.WorkGraphError):
        work_graph.validate_dependencies(
            [work_graph.TaskNode(key="A", kind="implementation", depends_on=("Z",))]
        )


# ------------------------------------------------------------------- AC-4


def test_tasks_link_to_success_criteria(harness):
    """AC-4: 구현·검증 Task 가 성공 기준에 연결되고 미연결 기준이 드러난다."""
    tasks = [
        {
            "key": "T1",
            "kind": "implementation",
            "purpose": "필터 구현",
            "criteria": [{"key": "C-01", "relation": "implements"}],
        },
        {
            "key": "T2",
            "kind": "verification",
            "purpose": "표본 파일로 확인",
            "depends_on": ["T1"],
            "criteria": [{"key": "C-01", "relation": "verifies"}],
        },
    ]
    case = _graph_case(harness, tasks=tasks)
    coverage = {c["criterion_key"]: c for c in harness.work_graph(case["id"])["criteria_coverage"]}

    assert coverage["C-01"]["implemented_by"] == ["T1"]
    assert coverage["C-01"]["verified_by"] == ["T2"]
    assert coverage["C-01"]["has_verification_task"] is True
    # **확인할 작업이 없는 기준이 눈에 보인다.** 판정하지 않고 보이기만 한다 —
    # 배정을 막지 않는 것이 P3-01이 정한 경계다.
    others = [c for c in coverage.values() if c["criterion_key"] != "C-01"]
    assert others and all(c["has_verification_task"] is False for c in others)
    assert harness.request_implementation(case["id"], task_id="T1").status_code == 201


def test_a_link_to_an_unknown_criterion_is_refused(harness):
    """AC-4: 없는 기준·대체된 기준을 가리키는 연결은 거부된다.

    조용히 버리면 "연결했다"는 기록만 남고 실제 연결은 없다.
    """
    tasks = [
        {
            "key": "T1",
            "purpose": "필터 구현",
            "criteria": [{"key": "C-NOPE", "relation": "implements"}],
        }
    ]
    case, _intent = _agreed_case(harness)
    harness.agent.cli_executor.plan_response = _plan_with(tasks)
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    harness.ai_prepare(case["id"], "plan")

    assert harness.work_graph(case["id"])["present"] is False


# ------------------------------------------------------------------- AC-5


def test_question_blocks_resolve_to_task_keys(harness):
    """AC-5: 원문의 자유 문자열 `blocks` 가 Task 키로 해석된다."""
    case = _graph_case(
        harness,
        plan_questions=[
            {
                "key": "p1",
                "text": "대소문자 구분을 켤지 사람이 정해야 한다",
                "summary": "대소문자 구분",
                "decide_at": "plan",
                "blocks": ["T2"],
            }
        ],
    )
    graph = harness.work_graph(case["id"])
    question = next(
        q for q in graph["deferred_open_questions"] if q["question_key"] == "plan:p1"
    )
    assert graph["question_blocks"][question["id"]] == ["T2"]
    assert graph["unresolved_block_refs"] == []


def test_an_unresolved_block_reference_is_kept_not_dropped(harness):
    """AC-5·AC-7: **해석되지 않은 참조는 버리지 않는다.**

    버리면 그 질문이 "아무 것도 막지 않는" 질문이 되어 좁히기가 곧 우회가 된다.
    그래서 해석 실패한 질문은 **연결 없는 질문**으로 취급해 전부 막는다.
    """
    case = _graph_case(
        harness,
        plan_questions=[
            {
                "key": "p1",
                "text": "어느 작업이 기다리는지 잘못 적었다",
                "summary": "잘못된 참조",
                "decide_at": "plan",
                "blocks": ["T-없는작업"],
            }
        ],
    )
    graph = harness.work_graph(case["id"])
    assert [r["raw_ref"] for r in graph["unresolved_block_refs"]] == ["T-없는작업"]
    assert graph["question_blocks"] == {}

    # 독립 Task 인 T1 까지 막힌다 — 무엇을 막는지 모르기 때문이다.
    refusals = _refusals(harness.request_implementation(case["id"], task_id="T1"))
    assert "deferred_questions_unresolved" in refusals


# ------------------------------------------------------------------- AC-6


def test_a_linked_question_blocks_only_its_task(harness):
    """AC-6: **좁히기.** 연결된 질문은 그 Task 만 막고 독립 Task 는 진행한다.

    P3-01에서는 이 상태에서 Case 전체가 막혔다.
    """
    case = _graph_case(
        harness,
        plan_questions=[
            {
                "key": "p1",
                "text": "대소문자 구분을 켤지 사람이 정해야 한다",
                "summary": "대소문자 구분",
                "decide_at": "plan",
                "blocks": ["T2"],
            }
        ],
    )
    # T1 은 막히지 않는다.
    assert harness.task_readiness(case["id"], "T1")["runnable"] is True
    assert harness.request_implementation(case["id"], task_id="T1").status_code == 201

    # T2 는 그 결정을 기다린다.
    refusals = _refusals(
        harness.request_implementation(case["id"], run_id="run-impl-2", task_id="T2")
    )
    assert "deferred_questions_unresolved" in refusals


# ------------------------------------------------------------------- AC-7


def test_no_graph_still_blocks_the_whole_case(harness):
    """AC-7 (가): 그래프가 없으면 전부 막는다.

    그래프가 없다는 것은 계획이 작업을 정의하지 않았다는 뜻이고, 그 상태에서
    구현을 여는 것은 "무엇을 만들지 모르는 채 만들기 시작한다"가 된다.
    """
    case = _graph_case(harness, tasks=[])
    refusals = _refusals(harness.request_implementation(case["id"], task_id="T1"))
    assert "work_graph_missing" in refusals


def test_an_unlinked_question_blocks_every_task(harness):
    """AC-7 (다): **연결이 없는 열린 이월 질문은 전부 막는다.**

    이것이 좁히기가 느슨해지지 않게 하는 지점이다. 연결이 없다는 것은 "아무 것도
    막지 않는다"가 아니라 **무엇을 막는지 모른다**는 뜻이고, 모르는 것을 안전한
    쪽으로 읽으면 질문 하나를 연결하지 않는 것만으로 모든 차단이 사라진다.
    """
    case = _graph_case(
        harness,
        plan_questions=[
            {
                "key": "p1",
                "text": "무엇이 기다리는지 적지 않은 질문",
                "summary": "연결 없는 질문",
                "decide_at": "plan",
            }
        ],
    )
    for key in ("T1", "T2"):
        assert harness.task_readiness(case["id"], key)["runnable"] is False
    refusals = _refusals(harness.request_implementation(case["id"], task_id="T1"))
    assert "deferred_questions_unresolved" in refusals


def test_a_human_can_link_an_unlinked_question(harness):
    """AC-7: 사람이 연결을 고치면 좁혀진다. **답한 것은 아니다.**

    고칠 수단이 없으면 연결 없는 질문 하나가 영원히 전부 막는다. 다만 연결을
    고쳐도 질문은 여전히 `open` 이고 연결된 Task 는 계속 막힌다.
    """
    case = _graph_case(
        harness,
        plan_questions=[
            {
                "key": "p1",
                "text": "무엇이 기다리는지 적지 않은 질문",
                "summary": "연결 없는 질문",
                "decide_at": "plan",
            }
        ],
    )
    question = harness.work_graph(case["id"])["deferred_open_questions"][0]
    response = harness.client.put(
        f"/api/cases/{case['id']}/questions/{question['id']}/blocks",
        json={"task_keys": ["T2"], "reason": "이 결정은 필터 구현만 기다린다", "actor": "owner"},
    )
    assert response.status_code == 201, response.text

    graph = harness.work_graph(case["id"])
    # 질문은 여전히 열려 있다 — 연결은 "누가 기다리는가"이지 "결정됐는가"가 아니다.
    assert graph["deferred_open_questions"][0]["state"] == "open"
    assert graph["readiness"]["T1"]["runnable"] is True
    assert graph["readiness"]["T2"]["runnable"] is False


def test_linking_a_question_to_an_unknown_task_is_refused(harness):
    """AC-7: 없는 Task 로 연결하면 거부된다 — 그렇지 않으면 연결이 사라진다."""
    case = _graph_case(
        harness,
        plan_questions=[
            {"key": "p1", "text": "질문", "summary": "질문", "decide_at": "plan"}
        ],
    )
    question = harness.work_graph(case["id"])["deferred_open_questions"][0]
    response = harness.client.put(
        f"/api/cases/{case['id']}/questions/{question['id']}/blocks",
        json={"task_keys": ["T-없음"], "reason": "잘못된 연결", "actor": "owner"},
    )
    assert response.status_code == 409, response.text


# ------------------------------------------------------------------- AC-8


def test_a_dependent_task_waits_for_its_predecessor(harness):
    """AC-8: 선행 Task 가 끝나지 않으면 후속 Task 가 배정되지 않는다."""
    case = _graph_case(harness)
    refusals = _refusals(harness.request_implementation(case["id"], task_id="T2"))
    assert "task_dependencies_unmet" in refusals
    assert "T1(planned)" in " ".join(
        _reasons(harness, case["id"], "T2")
    )


def _reasons(harness, case_id, task_key):
    return [
        b["detail"] for b in harness.task_readiness(case_id, task_key)["blocked_by"]
    ]


def test_finishing_the_predecessor_unblocks_the_dependent_task(harness):
    """AC-8: 선행이 **실제 실행으로** 완료되면 그 사유가 사라진다.

    사람이 "끝났다"고 적는 경로는 없다. 그것은 실행 증거 없이 의존을 푸는 문이다.
    """
    case = _graph_case(harness)
    assert harness.task_readiness(case["id"], "T2")["runnable"] is False

    harness.complete_task(case["id"], "T1")

    graph = harness.work_graph(case["id"])
    assert graph["readiness"]["T1"]["state"] == "done"
    assert graph["readiness"]["T2"]["runnable"] is True
    assert harness.request_implementation(case["id"], task_id="T2").status_code == 201


def test_a_failed_run_does_not_complete_a_task(harness):
    """AC-8: 실패·불명으로 끝난 실행은 완료가 아니다.

    특히 `unknown` 은 "아마 됐을 것"이 아니라 **모른다**이며, 모르는 것을 완료로
    읽으면 후속 작업이 증거 없이 열린다.
    """
    node = work_graph.TaskNode(key="T1", kind="implementation", depends_on=())
    for outcome in ("failed", "cancelled", "unknown"):
        runs = [{"task_id": "T1", "outcome": outcome, "status": "finished"}]
        assert work_graph.derive_task_state(node, runs) != "done"
    runs = [{"task_id": "T1", "outcome": "completed", "status": "finished"}]
    assert work_graph.derive_task_state(node, runs) == "done"


# ------------------------------------------------------------------- AC-9


def test_auto_proceed_does_not_answer_deferred_questions(harness):
    """AC-9: **단계 자동 진행이 질문을 대신 해결하지 않는다.**

    설계·계획 둘 다 자동 진행이어도 열린 이월 질문은 그대로 막는다
    (intent-artifacts 2절: 자동 진행은 이월한 질문의 사람 결정을 자동으로
    대신하지 않는다).
    """
    case, _intent = _agreed_case(harness)
    harness.agent.cli_executor.plan_response = _plan_with(
        FAKE_TASKS,
        [
            {
                "key": "p1",
                "text": "대소문자 구분을 켤지 사람이 정해야 한다",
                "summary": "대소문자 구분",
                "decide_at": "plan",
                "blocks": ["T2"],
            }
        ],
    )
    for stage in ("design", "plan"):
        assert (
            harness.set_stage_mode(
                case["id"], stage, "auto_proceed", "이 업무는 범위가 좁다"
            ).status_code
            == 200
        )
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert harness.auto_proceed(case["id"], "design").status_code == 201
    assert harness.ai_prepare(case["id"], "plan").status_code == 201
    assert harness.auto_proceed(case["id"], "plan").status_code == 201
    harness.complete_task(case["id"], "T1")

    graph = harness.work_graph(case["id"])
    question = graph["deferred_open_questions"][0]
    # 자동 진행 기록이 질문 상태를 바꾸지 않았다.
    assert question["state"] == "open"
    refusals = _refusals(
        harness.request_implementation(case["id"], task_id="T2")
    )
    assert "deferred_questions_unresolved" in refusals


# ------------------------------------------------------------------ AC-10


def test_an_answered_question_is_not_asked_again_across_revisions(harness):
    """AC-10: **이미 유효한 승인을 다시 요구하지 않는다.**

    답변한 질문은 같은 의도 버전에서 유지되고, 그래프 리비전이 늘어도 다시
    묻지 않는다(FR-13 "막연한 진행 확인을 반복하지 않는다").
    """
    case = _graph_case(
        harness,
        plan_questions=[
            {
                "key": "p1",
                "text": "대소문자 구분을 켤지",
                "summary": "대소문자 구분",
                "decide_at": "plan",
                "blocks": ["T2"],
            }
        ],
    )
    question = harness.work_graph(case["id"])["deferred_open_questions"][0]
    answer = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={
            "content": "대소문자를 구분하지 않는다",
            "summary": "구분하지 않음",
            "target_runner_id": harness.agent.config.runner_id,
        },
    )
    assert answer.status_code == 202, answer.text
    harness.complete_task(case["id"], "T1")
    assert harness.request_implementation(case["id"], task_id="T2").status_code == 201

    # 사람이 Task 를 더해 리비전이 하나 늘어도 그 답변은 그대로다.
    response = harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks",
        json={
            "task": {"key": "T3", "summary": "회귀 확인", "kind": "verification"},
            "reason": "회귀 확인을 빠뜨렸다",
            "actor": "owner",
        },
    )
    assert response.status_code == 201, response.text
    graph = harness.work_graph(case["id"])
    assert graph["graph"]["revision"] == 2
    assert graph["deferred_open_questions"] == []
    assert graph["readiness"]["T2"]["runnable"] is True


def test_rewriting_the_plan_does_not_ask_for_the_design_review_again(harness):
    """AC-10: 계획만 다시 써도 설계 검토를 다시 요구하지 않는다.

    **P3-R4: 두 단계를 사람 검토로 고른 Case 다.** 도출 기본값(자동 진행)에서는 새
    계획의 조건이 갖춰지는 순간 기록이 생겨 검토 사유 자체가 나타나지 않는다.
    확인하려는 성질은 그대로다 — 새 계획은 자기 검토가 필요하고 **설계 검토는
    다시 요구되지 않는다.** 그 구별은 검토가 사람의 것일 때 가장 분명하다.
    """
    case = _graph_case(harness)
    harness.set_stage_mode(case["id"], "design", "human_review", reason="사람이 본다")
    harness.set_stage_mode(case["id"], "plan", "human_review", reason="사람이 본다")
    assert harness.ai_prepare(case["id"], "plan", run_id="run-plan-2").status_code == 201

    refusals = _refusals(harness.request_implementation(case["id"], task_id="T1"))
    assert "design_review_missing" not in refusals
    assert "design_stale" not in refusals
    # 새 계획은 자기 검토가 필요하다 — 그것은 **다른 대상**이라 반복 요구가 아니다.
    assert "plan_review_missing" in refusals


def test_rewriting_the_plan_under_auto_proceed_is_admitted_without_a_person(harness):
    """R4: 자동 진행 기본값에서는 다시 쓴 계획이 **사람 없이** 조건을 갖춘다.

    "명확·저위험 요청이 추가 승인이나 별도 문서 없이 구현·검증된다"(P3-R4 성공
    기준)의 구체적인 모습이다. 설계 검토가 다시 요구되지 않는다는 성질은 위 시험과
    같고, 달라지는 것은 새 계획의 검토를 사람이 하지 않는다는 점이다.
    """
    case = _graph_case(harness)
    assert harness.ai_prepare(case["id"], "plan", run_id="run-plan-2").status_code == 201

    response = harness.request_implementation(case["id"], task_id="T1")
    assert response.status_code in (200, 201), response.text
    # 새 계획의 검토는 **자동 조건 충족**이며 사람 승인이 아니다.
    plan = harness.preparation(case["id"])["plan"]
    assert plan["state"] == "auto_conditions_met"
    assert plan["review"]["decision_id"] is None
    assert plan["review"]["actor"] == "stage-auto-proceed-policy"


# ------------------------------------------------------------------ AC-11


def test_a_task_outside_the_graph_is_refused(harness):
    """AC-11: 그래프에 없는 `task_id` 로는 배정되지 않는다."""
    case = _graph_case(harness)
    refusals = _refusals(harness.request_implementation(case["id"], task_id="task-1"))
    assert "task_not_in_work_graph" in refusals


def test_a_cancelled_task_is_refused(harness):
    """AC-11: 취소된 Task 도 배정되지 않는다."""
    case = _graph_case(harness)
    response = harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks/T1/cancel",
        json={"reason": "조사 없이도 형태가 확인됐다", "actor": "owner"},
    )
    assert response.status_code == 201, response.text
    refusals = _refusals(harness.request_implementation(case["id"], task_id="T1"))
    assert "task_not_in_work_graph" in refusals


def test_limited_analysis_is_checked_against_the_graph_too(harness):
    """AC-11: 조사도 실행이다.

    "하위 작업 `task_id` 가 다르다고 면제되지 않는다"는 FR-29의 규칙은 목적이
    달라도 같게 적용돼야 한다.
    """
    case = _graph_case(harness)
    instruction = harness.submit_artifact(
        case["id"], "조사해 주세요.", kind="instruction", summary="조사"
    )
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-analysis-x",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "limited_analysis",
            "role": "author",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
            "task_id": "task-없음",
        },
    )
    assert response.status_code == 409, response.text
    assert "task_not_in_work_graph" in response.json()["detail"]["admission"]["refusals"]


# ------------------------------------------------------------------ AC-12


def test_a_new_intent_version_makes_the_graph_stale(harness):
    """AC-12: 새 의도 버전이 생기면 그래프가 `stale` 이 되고 재사용되지 않는다."""
    case = _graph_case(harness)
    harness.complete_task(case["id"], "T1")
    assert harness.request_implementation(case["id"], task_id="T2").status_code == 201

    harness.ai_draft(case["id"], "필터에 날짜 조건도 더해 주세요.", run_id="run-draft-2")

    graph = harness.work_graph(case["id"])
    assert graph["stale"] is True
    refusals = _refusals(
        harness.request_implementation(case["id"], run_id="run-impl-9", task_id="T2")
    )
    assert "work_graph_stale" in refusals
    # 이전 리비전은 조회로 보존된다.
    assert len(harness.client.get(f"/api/cases/{case['id']}/work-graph-revisions").json()) == 1


# ------------------------------------------------------------------ AC-13


def test_a_human_added_task_creates_a_new_revision_with_a_reason(harness):
    """AC-13: 사람이 Task 를 더하면 새 리비전이 만들어지고 이유가 남는다."""
    case = _graph_case(harness)
    response = harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks",
        json={
            "task": {"key": "T3", "summary": "회귀 확인", "kind": "verification"},
            "reason": "회귀 확인을 빠뜨렸다",
            "actor": "owner",
        },
    )
    assert response.status_code == 201, response.text
    graph = harness.work_graph(case["id"])
    assert graph["graph"]["revision"] == 2
    assert graph["graph"]["source"] == "human_replanning"
    assert graph["graph"]["reason_summary"] == "회귀 확인을 빠뜨렸다"
    added = next(t for t in graph["tasks"] if t["task_key"] == "T3")
    # 사람이 더한 Task 의 출처는 **사람의 요구**다.
    assert added["origin"] == "user_requirement"


def test_replanning_without_a_reason_is_refused(harness):
    """AC-13: 이유 없는 재계획은 거부된다."""
    case = _graph_case(harness)
    response = harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks",
        json={
            "task": {"key": "T3", "summary": "회귀 확인"},
            "reason": "",
            "actor": "owner",
        },
    )
    assert response.status_code == 422, response.text


def test_a_cancelled_task_is_kept_not_deleted(harness):
    """AC-13: 취소된 Task 는 지워지지 않고 이유와 함께 남는다."""
    case = _graph_case(harness)
    harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks/T1/cancel",
        json={"reason": "조사 없이도 형태가 확인됐다", "actor": "owner"},
    )
    task = next(t for t in harness.work_graph(case["id"])["tasks"] if t["task_key"] == "T1")
    assert task["cancelled"] is True
    assert task["cancel_reason"] == "조사 없이도 형태가 확인됐다"


def test_replanning_does_not_reset_the_run_history(harness):
    """AC-13: **재분할이 실행 이력을 초기화하지 않는다**(FR-07 수용 기준).

    `run.task_id` 에 행 id 가 아니라 `task_key` 가 들어가기 때문에 리비전을
    가로질러 이력이 남는다.
    """
    case = _graph_case(harness)
    harness.complete_task(case["id"], "T1")
    before = harness.client.get(f"/api/cases/{case['id']}/tasks/T1/runs").json()
    assert len(before) == 1

    harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks",
        json={
            "task": {"key": "T3", "summary": "회귀 확인"},
            "reason": "회귀 확인을 빠뜨렸다",
            "actor": "owner",
        },
    )
    after = harness.client.get(f"/api/cases/{case['id']}/tasks/T1/runs").json()
    assert [r["run_id"] for r in after] == [r["run_id"] for r in before]
    # 완료 상태도 그대로다 — 이력이 끊기면 여기가 `planned` 로 돌아간다.
    assert harness.work_graph(case["id"])["readiness"]["T1"]["state"] == "done"


# ------------------------------------------------------------------ AC-14


def test_a_complete_graph_does_not_create_write_permission(harness):
    """AC-14 → P3-03 AC-4: **그래프를 갖춰도 작업공간 없이 쓰기는 열리지 않는다.**

    그래프는 "무엇을 어떤 순서로 만드는가"이고 작업공간은 "어디에 만드는가"다.
    둘은 서로를 대신하지 않는다(FR-08·FR-26).
    """
    case = _graph_case(harness)
    harness.complete_task(case["id"], "T1")
    assert harness.request_implementation(case["id"], task_id="T2").status_code == 201

    refusals = _refusals(
        harness.request_implementation(
            case["id"], run_id="run-impl-w", permission="workspace_write", task_id="T2"
        )
    )
    assert "workspace_not_ready" in refusals


def test_a_rewritten_plan_replaces_the_block_links(harness):
    """AC-5: 같은 질문을 다시 보고하면 **이번 원문이 적은 것**이 차단 관계다.

    쌓아 두면 없어진 Task 를 가리키는 옛 참조가 살아남아 그 질문이 영원히
    전부 막는다.
    """
    question = [
        {
            "key": "p1",
            "text": "대소문자 구분을 켤지",
            "summary": "대소문자 구분",
            "decide_at": "plan",
            "blocks": ["T2"],
        }
    ]
    case = _graph_case(harness, plan_questions=question)
    assert harness.task_readiness(case["id"], "T1")["runnable"] is True

    # 계획을 다시 쓰면서 같은 질문이 **T1** 을 막는다고 적는다.
    harness.agent.cli_executor.plan_response = _plan_with(
        FAKE_TASKS, [{**question[0], "blocks": ["T1"]}]
    )
    assert harness.ai_prepare(case["id"], "plan", run_id="run-plan-2").status_code == 201

    graph = harness.work_graph(case["id"])
    q = graph["deferred_open_questions"][0]
    # 옛 T2 참조가 남아 있으면 이 값이 두 개가 된다.
    assert graph["question_blocks"][q["id"]] == ["T1"]
    assert graph["readiness"]["T1"]["runnable"] is False


def test_replanning_a_stale_graph_is_refused(harness):
    """AC-12·AC-13: **오래된 그래프를 손보지 않는다.**

    의도가 바뀌면 그 위의 계획은 이미 대체됐다. 거기에 Task 를 더하면 옛 의도의
    계획이 되살아난다. 고칠 것은 계획이지 그래프가 아니다.
    """
    case = _graph_case(harness)
    harness.ai_draft(case["id"], "필터에 날짜 조건도 더해 주세요.", run_id="run-draft-2")
    assert harness.work_graph(case["id"])["stale"] is True

    response = harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks",
        json={
            "task": {"key": "T3", "summary": "회귀 확인"},
            "reason": "회귀 확인을 빠뜨렸다",
            "actor": "owner",
        },
    )
    assert response.status_code == 409, response.text
    assert "superseded intent version" in response.json()["detail"]
