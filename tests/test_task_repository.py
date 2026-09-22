"""P3-04 Task × Repository — 자동 시험.

**이 시험들이 지키려는 것 하나:** 두 저장소를 함께 바꾸는 업무에서 *어느 작업이
어느 저장소를 바꾸는가*가 기록되고, 기록과 다른 대상으로 도는 실행이 막힌다.

R2 는 **실행**이 어느 저장소에서 도는지를 물었다(`run.repository_id`). 그 검사는
"대상이 기록됐는가"이고 여기서 더하는 것은 "그 대상이 **맞는가**"다. 저장소가
하나뿐이면 둘은 같은 질문이지만, 두 저장소를 함께 바꾸는 업무에서는 다르다 —
대상을 기록했다는 이유만으로 통과하면 "UI 작업을 한다면서 API 저장소를 고치는
실행"이 열리고, 실행 전후 대조가 엉뚱한 Task 에 붙는다. 그 대조가 우리가 가진
유일한 증거다.

**소급하지 않는 자리가 둘이다.** 저장소가 하나인 Case 와 v12 이전 Task 다. 둘 다
여기서 짝이 되는 시험으로 고정한다 — 새 검사가 진행 중이던 업무를 멈추면 그것은
고친 것이 아니라 부순 것이다.
"""

from __future__ import annotations

from typing import Any

from runner import prompts
from tests.conftest import FAKE_PLAN_SECTIONS, FAKE_TASKS, fake_preparation_response
from tests.test_preparation import FIELDS, _refusals
from tests.test_repositories import _second_repo
from tests.test_workspace import _agreed_git_case


def _tasks_with_repositories(first: str | None, second: str | None) -> list[dict[str, Any]]:
    """`FAKE_TASKS` 와 같은 구조에 저장소를 붙인 계획 Task.

    T1 은 조사, T2 는 구현, T3 은 검증이다. 검증을 별도 Task 로 두는 이유는 계획
    지시문이 요구하는 것과 같다 — 구현 Task 안에 묻으면 무엇이 확인 작업인지
    알 수 없다.
    """

    def task(base: dict[str, Any], repository: str | None) -> dict[str, Any]:
        row = dict(base)
        if repository is not None:
            row["repository"] = repository
        return row

    third = {
        "key": "T3",
        "kind": "verification",
        "purpose": "두 번째 저장소에서 테스트를 돌린다",
        "purpose_summary": "두 번째 저장소 검증",
        "deliverable": "테스트 결과",
        "deliverable_summary": "테스트 결과",
        "completion": "테스트가 통과한다",
        "completion_summary": "테스트가 통과한다",
        "relates_to": "goal",
        "depends_on": ["T2"],
        "criteria": [{"key": "C-01", "relation": "verifies"}],
    }
    return [
        task(FAKE_TASKS[0], first),
        task(FAKE_TASKS[1], first),
        task(third, second),
    ]


def _two_repo_case(
    harness,
    first: str | None = "primary",
    second: str | None = "ui",
    name: str = "taskrepo",
):
    """두 저장소를 모두 고를 수 있고 계획까지 마친 Case.

    계획의 Task 가 **저장소를 적는다.** 그것이 이 시험 묶음의 입력이다.
    """
    case, repo = _agreed_git_case(harness, name=name)
    project = harness.client.get(f"/api/cases/{case['id']}").json()["project_id"]
    other = _second_repo(harness, {"id": project}, name="ui")

    registry = harness.client.get(f"/api/projects/{project}/repositories").json()
    ids = {r["name"]: r["id"] for r in registry["repositories"]}
    for repository_id in ids.values():
        assert harness.select_repository(case["id"], repository_id).status_code == 201

    harness.agent.cli_executor.plan_response = fake_preparation_response(
        "계획", FAKE_PLAN_SECTIONS, tasks=_tasks_with_repositories(first, second)
    )
    assert harness.ai_prepare(
        case["id"], "design", run_id=f"run-{name}-design", repository_id=ids["primary"]
    ).status_code == 201
    assert harness.review_stage(case["id"], "design").status_code == 201
    assert harness.ai_prepare(
        case["id"], "plan", run_id=f"run-{name}-plan", repository_id=ids["primary"]
    ).status_code == 201
    assert harness.review_stage(case["id"], "plan").status_code == 201
    return case, repo, other, ids


def _task(harness, case_id: str, key: str) -> dict[str, Any]:
    graph = harness.work_graph(case_id)
    return next(t for t in graph["tasks"] if t["task_key"] == key)


# ============================================================ 기록


def test_a_plan_records_which_repository_each_task_changes(harness):
    """계획이 적은 저장소가 그래프에 **해석돼** 남는다(AC-5).

    이름으로 적어도 등록 저장소의 id 로 해석된다. 화면이 id 만 보면 사람이 어느
    저장소인지 알 수 없으므로 이름도 함께 돌아온다.
    """
    case, _repo, _other, ids = _two_repo_case(harness)

    t2 = _task(harness, case["id"], "T2")
    t3 = _task(harness, case["id"], "T3")
    assert t2["repository_id"] == ids["primary"]
    assert t2["repository_name"] == "primary"
    assert t3["repository_id"] == ids["ui"]
    assert t3["repository_name"] == "ui"
    # **계획이 적은 그대로도 남는다.** 해석 결과가 계획의 문장을 대체하지 않는다.
    assert t2["repository_ref"] == "primary"


def test_a_repository_outside_the_selection_is_not_resolved_and_not_dropped(harness):
    """선택 **밖** 저장소를 가리킨 계획은 해석되지 않고, 버려지지도 않는다(AC-8).

    두 가지를 함께 지킨다. 계획이 이름 하나를 적는 것만으로 허용이 넓어지지
    않고(R2 의 세 경계), 적힌 것이 사라지지도 않는다 — 사라지면 "저장소를 말하지
    않은 계획"과 "선택 밖을 가리킨 계획"이 화면에서 같아진다.
    """
    case, _repo, _other, _ids = _two_repo_case(harness, second="repo-that-was-not-chosen")

    t3 = _task(harness, case["id"], "T3")
    assert t3["repository_id"] is None
    assert t3["repository_ref"] == "repo-that-was-not-chosen"


def test_a_person_added_task_can_name_its_repository(harness):
    """사람이 더하는 Task 도 저장소를 적는다. 비우면 미기록이다."""
    case, _repo, _other, ids = _two_repo_case(harness, name="addtask")

    added = harness.client.post(
        f"/api/cases/{case['id']}/work-graph/tasks",
        json={
            "task": {
                "key": "T9",
                "kind": "implementation",
                "summary": "두 번째 저장소의 표시를 고친다",
                "repository": "ui",
            },
            "reason": "사람이 빠진 작업을 더했다",
            "actor": "owner",
        },
    )
    assert added.status_code == 201, added.text
    assert _task(harness, case["id"], "T9")["repository_id"] == ids["ui"]
    # **다른 Task 의 기록이 재계획으로 지워지지 않는다.** 지워지면 Task 하나를
    # 더한 것만으로 나머지가 전부 미기록이 되어 구현이 막힌다.
    assert _task(harness, case["id"], "T3")["repository_id"] == ids["ui"]
    assert _task(harness, case["id"], "T2")["repository_id"] == ids["primary"]


# ============================================================ 강제


def test_implementing_a_task_in_another_repository_is_refused(harness):
    """대상이 **그 Task 의 저장소가 아니면** 배정하지 않는다(AC-6).

    R2 의 `workspace_target_not_recorded` 와 다른 사유다. 대상은 기록됐고, 틀렸다.
    """
    case, repo, other, ids = _two_repo_case(harness, name="mismatch")
    harness.prepare_workspace(case["id"], repository_id=ids["primary"])
    harness.prepare_workspace(case["id"], repository_id=ids["ui"])
    harness.complete_task(case["id"], "T1", run_id="run-mismatch-t1", repository_id=ids["primary"])

    refused = harness.request_implementation(
        case["id"],
        run_id="run-mismatch-impl",
        permission="workspace_write",
        task_id="T2",
        repository_id=ids["ui"],
    )
    assert refused.status_code == 409
    assert "run_task_repository_mismatch" in _refusals(refused)

    # 같은 요청을 **맞는 저장소로** 보내면 열린다. 축이 서로를 대신하지 않는다.
    allowed = harness.request_implementation(
        case["id"],
        run_id="run-mismatch-impl-ok",
        permission="workspace_write",
        task_id="T2",
        repository_id=ids["primary"],
    )
    assert allowed.status_code == 201, allowed.text


def test_a_task_without_a_repository_blocks_when_there_are_two(harness):
    """저장소가 둘인데 계획이 말하지 않았으면 그 Task 로 구현이 열리지 않는다(AC-7)."""
    case, _repo, _other, ids = _two_repo_case(harness, first=None, second=None, name="norepo")
    harness.prepare_workspace(case["id"], repository_id=ids["primary"])
    harness.prepare_workspace(case["id"], repository_id=ids["ui"])
    harness.complete_task(case["id"], "T1", run_id="run-norepo-t1", repository_id=ids["primary"])

    refused = harness.request_implementation(
        case["id"],
        run_id="run-norepo-impl",
        permission="workspace_write",
        task_id="T2",
        repository_id=ids["primary"],
    )
    assert refused.status_code == 409
    assert "task_repository_not_recorded" in _refusals(refused)


def test_a_single_repository_case_never_needs_the_task_repository(harness):
    """저장소가 하나인 Case 는 **아무 것도 달라지지 않는다.**

    소급 금지의 자리다. 고를 것이 없는 Case 에까지 이 검사를 걸면 R2 이전 Case 와
    단일 저장소 Case 의 진행 중 업무가 멈춘다.
    """
    from tests.test_workspace import _ready_case

    case, _repo = _ready_case(harness, name="single")
    allowed = harness.request_implementation(
        case["id"], run_id="run-single-impl", permission="workspace_write", task_id="T2"
    )
    assert allowed.status_code == 201, allowed.text
    assert _task(harness, case["id"], "T2")["repository_id"] is None


def test_the_investigation_of_an_unrecorded_task_is_not_blocked(harness):
    """조사·검토는 저장소 기록을 요구하지 않는다.

    무는 것은 실제로 저장소를 고치거나 그 위에서 검증을 돌리는 목적뿐이다.
    조사까지 막으면 계획을 고치는 데 필요한 사실을 모을 수 없다.
    """
    case, _repo, _other, ids = _two_repo_case(harness, first=None, second=None, name="analysis")
    harness.prepare_workspace(case["id"], repository_id=ids["primary"])
    harness.prepare_workspace(case["id"], repository_id=ids["ui"])

    instruction = harness.submit_artifact(case["id"], "무엇이 있는지 읽어 주세요.")
    response = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-analysis-read",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "limited_analysis",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
            "task_id": "T1",
            "repository_id": ids["ui"],
        },
    )
    assert response.status_code == 201, response.text


# ============================================================ 지시문·배정


def test_the_plan_prompt_names_only_the_repositories_the_case_chose(harness):
    """계획 지시문이 **제어부가 준 목록**만 보여 준다.

    Runner 가 저장소를 찾아 나서면 이 Case 가 고르지 않은 저장소를 계획에 적게
    되고, 그것은 허용을 넓히는 요구가 된다(D-38·D-63).
    """
    rule = prompts._repository_rule([{"name": "primary"}, {"name": "ui"}])
    assert "`primary`" in rule
    assert "`ui`" in rule
    assert "저장소 하나" in rule


def test_the_plan_prompt_says_nothing_when_there_is_one_repository(harness):
    """고를 것이 하나면 고르라고 하지 않는다.

    고를 것이 없는데 고르라고 하면 이름을 지어내고, 지어낸 이름은 해석되지 않아
    그 작업이 막힌다.
    """
    assert prompts._repository_rule([{"name": "primary"}]) == ""
    assert prompts._repository_rule([]) == ""
    assert prompts._repository_rule(None) == ""


def test_the_assignment_carries_the_repositories_the_plan_may_choose(harness):
    """배정이 저장소 목록을 싣는다. **이름과 식별자뿐이다.**

    경로가 들어가면 한 실행이 자기 작업공간 밖을 알게 된다. 이 목록은 계획이
    이름을 고르기 위한 것이지 다른 저장소를 여는 것이 아니다(D-39).
    """
    case, _repo, _other, ids = _two_repo_case(harness, name="assign")
    harness.prepare_workspace(case["id"], repository_id=ids["primary"])

    instruction = harness.submit_artifact(case["id"], "계획을 다시 써 주세요.")
    created = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-assign-plan-again",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "plan_authoring",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
            "repository_id": ids["primary"],
        },
    )
    assert created.status_code == 201, created.text

    assignments = harness.client.post(
        f"/api/runner/{harness.runner_config.runner_id}/assignments"
    ).json()
    payload = next(a for a in assignments if a["run_id"] == "run-assign-plan-again")
    names = {r["name"] for r in payload["case_repositories"]}
    assert names == {"primary", "ui"}
    for row in payload["case_repositories"]:
        assert set(row) == {"repository_id", "name"}


# ============================================================ 데이터 경계


def test_the_task_repository_is_an_identifier_not_a_path(harness):
    """`task` 에 남는 것은 식별자와 적힌 이름뿐이다. 경로도 본문도 아니다."""
    case, repo, _other, _ids = _two_repo_case(harness, name="boundary")
    graph = harness.work_graph(case["id"])
    for task in graph["tasks"]:
        assert str(repo) not in (task["repository_ref"] or "")
        assert str(repo) not in (task["repository_id"] or "")


def test_intent_fields_are_unchanged_by_the_task_repository(harness):
    """의도 항목 계약은 이 단계에서 바뀌지 않는다."""
    case, _repo, _other, _ids = _two_repo_case(harness, name="fields")
    latest = harness.latest_intent(case["id"])
    assert set(FIELDS) <= {f["field"] for f in latest["fields"]}


def test_the_mismatch_is_caught_even_without_a_prepared_workspace(harness):
    """대조는 **실행이 밝힌 대상**으로 한다. 작업공간 상태에서 끌어내지 않는다.

    끌어내면 준비되지 않은 저장소를 대상으로 적은 요청이 "작업공간이 없다"는
    이유로 대조를 건너뛴다. 그 경우에도 *이 Task 의 저장소가 아니다*는 사실이며,
    사람이 고쳐야 하는 것도 다르다 — 작업공간을 준비하는 것이 아니라 대상을
    바로잡는 것이다.
    """
    case, _repo, _other, ids = _two_repo_case(harness, name="nows")
    harness.prepare_workspace(case["id"], repository_id=ids["primary"])
    harness.complete_task(case["id"], "T1", run_id="run-nows-t1", repository_id=ids["primary"])

    # `ui` 저장소에는 작업공간을 만들지 않았다.
    refused = harness.request_implementation(
        case["id"],
        run_id="run-nows-impl",
        permission="workspace_write",
        task_id="T2",
        repository_id=ids["ui"],
    )
    assert refused.status_code == 409
    codes = _refusals(refused)
    assert "run_task_repository_mismatch" in codes
    # 작업공간이 없다는 사실도 함께 보인다. 한 사유가 다른 사유를 숨기지 않는다.
    assert "workspace_not_ready" in codes


# ============================================================ 질문 답변의 반영
#
# P3-04 라이브가 찾은 것. 여기 두는 이유는 같은 세션이 만든 사실이기 때문이고,
# 다루는 대상(고정 컨텍스트)은 `review-context-contract` 의 계약이다.


def test_an_answered_question_reaches_the_run_that_rewrites_the_draft(harness):
    """AI 가 묻고 사람이 답했으면 **다시 쓰는 AI 가 그 답을 본다.**

    답변은 `intent_question.answer_artifact_id` 로 기록돼 있었지만 어떤 실행의
    입력도 아니었다. 그 상태에서는 "필요한 질문의 답변을 반영하면 자동
    진행한다"(intent-artifacts 104행)가 성립하지 않는다 — 반영할 입력이 없다.

    **라이브에서 그 결과가 실제로 나왔다.** 답이 있는데도 다음 초안이 같은 모순을
    그대로 두었고 QG-01 의 독립 검토가 그것을 잡아냈다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        FIELDS,
        questions=[
            {
                "key": "q1",
                "text": "기존 출력 테스트를 갱신해도 되는가?",
                "summary": "출력 테스트 갱신 여부",
            }
        ],
    )
    question = harness.latest_intent(case["id"])["questions"][0]
    answered = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={
            "content": "갱신해도 된다. 형식 테스트만 새 형식으로 바꾼다.",
            "summary": "형식 테스트만 갱신",
            "target_runner_id": "runner-test-1",
        },
    )
    assert answered.status_code == 202
    harness.agent.persist_pending_intakes()

    # 다시 쓰는 실행의 고정 컨텍스트에 그 답이 들어 있다.
    instruction = harness.submit_artifact(case["id"], "답을 반영해 다시 써 주세요.")
    created = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-redraft",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "intent_authoring",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    )
    assert created.status_code == 201, created.text

    refs = harness.context_refs("run-redraft")
    roles = [r["role"] for r in refs]
    assert "question_answer" in roles, f"답변이 고정 컨텍스트에 없다: {roles}"
    answer_ref = next(r for r in refs if r["role"] == "question_answer")
    assert answer_ref["artifact_id"] == answered.json()["question"]["answer_artifact_id"]

    # **Runner 가 그 원문을 실제로 읽는다.** 참조만 있고 읽히지 않으면 같은 구멍이다.
    result = harness.agent.poll_once()
    action = next(a for a in result["assignments"] if a["run_id"] == "run-redraft")
    assert "question_answer" in action["produced"]["context_read"]


def test_an_unanswered_question_is_not_fixed_as_context(harness):
    """**답하지 않은 질문은 고정하지 않는다.**

    없는 답을 빈 참조로 실어 보내면 지시문이 "답이 있다"고 말하게 되고, 그 자리는
    미정이 아니라 빈칸이 된다. 읽지 못한 참조와 없는 참조는 다른 것이다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        FIELDS,
        questions=[{"key": "q1", "text": "아직 답하지 않은 질문", "summary": "미답"}],
    )
    instruction = harness.submit_artifact(case["id"], "다시 써 주세요.")
    assert harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-redraft-open",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "intent_authoring",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    ).status_code == 201

    roles = [r["role"] for r in harness.context_refs("run-redraft-open")]
    assert "question_answer" not in roles


def test_the_reviewer_gets_the_request_it_is_asked_to_compare_against(harness):
    """QG-01 은 **요청 정합성 확인**이다. 대조할 것을 주지 않고 대조를 요구하지 않는다.

    의미 검토의 고정 컨텍스트가 비어 있으면 검토자는 초안만 받아 각 항목이
    요청에서 온 것인지 추측해야 한다. 라이브의 첫 검토자가 그것을 그대로 말했고
    ("원래 요청이 제공되지 않아 …검토할 수 없다"), 뒤이은 검토자들은 **요청에 있는
    내용을 근거 없는 가정으로** 판정했다.

    무엇이 그 요청인가는 지어내지 않는다 — 그 초안을 쓴 실행이 받은 지시가 정확히
    그것이다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    request = harness.submit_artifact(case["id"], "요약에 문자 수를 더해 주세요.")
    assert harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-author",
            "instruction_artifact_id": request["artifact_id"],
            "purpose": "intent_authoring",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    ).status_code == 201
    harness.agent.poll_once()

    intent = harness.latest_intent(case["id"])
    assert harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-review",
            "instruction_artifact_id": intent["artifact_id"],
            "instruction_artifact_rev": intent["artifact_rev"],
            "purpose": "intent_gate_review",
            "role": "reviewer",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    ).status_code == 201

    refs = harness.context_refs("run-review")
    original = [r for r in refs if r["role"] == "original_request"]
    assert original, f"검토자에게 요청 원문이 가지 않는다: {[r['role'] for r in refs]}"
    assert original[0]["artifact_id"] == request["artifact_id"]


def test_a_human_typed_intent_has_no_request_artifact_and_none_is_invented(harness):
    """사람이 직접 입력한 초안에는 **작성 실행이 없다.**

    그때 아무 지시 원문이나 요청으로 실어 보내면 검토자가 다른 것을 요청으로
    읽는다. 없는 것은 없는 채로 둔다 — 읽지 못한 참조와 없는 참조는 다르다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_artifact(case["id"], "이 Case 의 다른 지시 원문")
    harness.submit_intent_draft(case["id"], FIELDS)

    intent = harness.latest_intent(case["id"])
    assert harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-review-human",
            "instruction_artifact_id": intent["artifact_id"],
            "instruction_artifact_rev": intent["artifact_rev"],
            "purpose": "intent_gate_review",
            "role": "reviewer",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    ).status_code == 201

    roles = [r["role"] for r in harness.context_refs("run-review-human")]
    assert "original_request" not in roles


def test_a_code_changing_run_is_given_the_plan_it_must_follow(harness):
    """**코드를 바꾸는 실행도 고정 컨텍스트를 받는다**(P3-04).

    여기가 비어 있었다. 구현·검증·실험은 호출자가 지시 원문에 적은 것만 보고
    일했고, 그러면 "무엇을 보고 만들었는가"가 시스템의 기록이 아니라 **호출자가
    넣은 문자열**이 된다 — 고정 컨텍스트 계약이 가장 필요한 단계에서 그 계약이
    없던 셈이다(review-context-contract 2절).

    **라이브가 그 결과를 보여 줬다.** 요청 전체를 지시 원문에 붙이자 AI 가 다음
    작업까지 미리 했고, 그 다음 구현 실행은 바꿀 것이 없어 실패했다.
    """
    from tests.test_workspace import _ready_case

    case, _repo = _ready_case(harness, name="ctx")
    assert harness.request_implementation(
        case["id"], run_id="run-ctx-impl", permission="workspace_write", task_id="T2"
    ).status_code == 201

    roles = {r["role"] for r in harness.context_refs("run-ctx-impl")}
    assert "agreed_intent" in roles, f"동의된 의도가 고정되지 않았다: {roles}"
    assert "current_plan" in roles, f"따라야 할 계획이 고정되지 않았다: {roles}"
    # **설계는 넣지 않는다.** 계획이 이미 설계 위에 세워졌고, 구현이 따라야 하는
    # 것은 계획이 정의한 Task 다. 넣을수록 좋은 것이 아니라 따라야 할 것을 준다.
    assert "current_design" not in roles


def test_two_threads_on_the_shared_connection_do_not_collide(harness):
    """**공유 연결에 동시 쓰기가 들어와도 한쪽이 죽지 않는다**(P3-04).

    제어부는 연결 하나를 모든 요청이 공유하고(`check_same_thread=False`), FastAPI 는
    동기 엔드포인트를 스레드풀에서 돌린다. P3-R3 이 `BEGIN IMMEDIATE` 를 쓰기
    시작하면서 요청 둘이 같은 연결에 동시에 `BEGIN` 을 보내면 SQLite 가
    `cannot start a transaction within a transaction` 으로 거부한다.

    **라이브에서 실제로 500 이 났다.** Runner 가 실행 결과를 보고하는 동안 다음
    실행을 만들자 죽었다 — 어느 진입 검사로도 설명되지 않는 실패이며 사람이 볼 수
    있는 사유가 없다. 이 시험은 `db.transaction` 의 직렬화를 없애면 실패한다.
    """
    import sqlite3
    import threading

    from controller import db as dbmod

    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    conn = dbmod.connect(harness.controller_config.db_path)
    errors: list[BaseException] = []
    at_the_gate = threading.Barrier(2, timeout=10)

    def write(index: int) -> None:
        try:
            at_the_gate.wait()
            with dbmod.transaction(conn):
                conn.execute(
                    "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind,"
                    " content_hash, byte_size, owner_runner_id, availability, summary,"
                    " created_at) VALUES (?, 1, ?, 'instruction', 'h', 1,"
                    " 'runner-test-1', 'available', 's', '2026-01-01T00:00:00+00:00')",
                    (f"art-race-{index}", case["id"]),
                )
        except BaseException as exc:  # noqa: BLE001 - 시험이 보려는 것이 이것이다
            errors.append(exc)

    threads = [threading.Thread(target=write, args=(i,)) for i in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert not errors, f"공유 연결의 동시 쓰기가 죽었다: {errors}"
    rows = conn.execute(
        "SELECT artifact_id FROM artifact_ref WHERE artifact_id LIKE 'art-race-%'"
    ).fetchall()
    assert len(rows) == 2, "두 쓰기가 모두 남지 않았다"
    conn.close()


def test_a_redraft_review_still_gets_the_first_request_not_the_fix_instruction(harness):
    """다시 쓴 버전의 검토도 **원래 요청**을 받는다(P3-04).

    재작성 실행이 받는 지시는 "이 지적을 고쳐라" 같은 후속 지시다. 그것을 요청으로
    주면 검토자가 다른 것을 원래 요청으로 읽는다 — 라이브의 검토자가 그 어긋남을
    알아챘다("요청 원문 내용이 제공되지 않아 전체 대조를 수행할 수 없다").
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    first = harness.submit_artifact(case["id"], "요약에 문자 수를 더해 주세요.")
    assert harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-author-1",
            "instruction_artifact_id": first["artifact_id"],
            "purpose": "intent_authoring",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    ).status_code == 201
    harness.agent.poll_once()

    # 지적을 고치라는 **후속** 지시로 다시 쓴다.
    fix = harness.submit_artifact(case["id"], "검토 지적만 고쳐 다시 써 주세요.")
    assert harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-author-2",
            "instruction_artifact_id": fix["artifact_id"],
            "purpose": "intent_authoring",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    ).status_code == 201
    harness.agent.poll_once()

    intent = harness.latest_intent(case["id"])
    assert intent["revision"] == 2
    assert harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-review-2",
            "instruction_artifact_id": intent["artifact_id"],
            "instruction_artifact_rev": intent["artifact_rev"],
            "purpose": "intent_gate_review",
            "role": "reviewer",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
        },
    ).status_code == 201

    refs = harness.context_refs("run-review-2")
    original = next(r for r in refs if r["role"] == "original_request")
    assert original["artifact_id"] == first["artifact_id"], "후속 지시를 요청으로 줬다"
    assert original["artifact_id"] != fix["artifact_id"]
