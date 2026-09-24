"""P4-10c (D-97) — 기준을 모두 충족해 닫힌 업무의 **실행하지 않은 작업**을 드러낸다(plans/P4-PLAN-10c.md AC-1·AC-2).

    완료 규칙은 그대로        기준이 모두 충족되면 남은 작업을 기다리지 않고 닫는다(돌리지 않는다)
    남은 작업은 보인다        작업 그래프·대화 조회에 이유(종료 종류)와 함께, 진행 이력에 한 번

**실제 CLI 를 부르지 않는다.** `conftest` 의 가짜 실행기로 진행기 경유 흐름을 돈다.
"""

from __future__ import annotations

from controller.repository import Repository
from tests.conftest import (
    FAKE_COMBINED_SECTIONS,
    FAKE_EXTRA_TASK,
    FAKE_TASKS_VERIFIED,
    fake_preparation_response,
)
from tests.test_work_progressor import VERIFICATION_ONE_FAILS, _agree, _drive, _runs, _start, _wait_codes

EXTRA_PLAN = fake_preparation_response("결합", FAKE_COMBINED_SECTIONS, tasks=[*FAKE_TASKS_VERIFIED, FAKE_EXTRA_TASK])


def _to_work(h) -> str:
    _project, case_id, _request_id = _start(h)
    h.agent.cli_executor.combined_response = EXTRA_PLAN
    h.agent.cli_executor.plan_response = EXTRA_PLAN
    _drive(h, case_id)
    _agree(h, case_id)
    return case_id


def test_a_task_left_when_the_criteria_are_met_is_shown_as_not_run(processing_harness):
    """AC-1 — T1 구현 → T2 검증(기준 전부 충족) → 자동 완료. 기준에 이어지지 않은 T3 은 돌지 않았고(완료 규칙 그대로),
    그래프·대화 조회에 `completed` 이유로 보이며 진행 이력에 한 번 적힌다."""
    h = processing_harness
    case_id = _to_work(h)
    conv = _drive(h, case_id, polls=30)
    assert conv["progress"]["state"] == "done", conv["progress"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"
    assert not [r for r in _runs(h, case_id) if r["task_id"] == "T3"]
    assert conv["unrun_tasks"] == [
        {"task_key": "T3", "kind": "implementation", "summary": "README 갱신", "reason": "completed"}
    ]
    graph = h.client.get(f"/api/cases/{case_id}/work-graph").json()
    assert graph["not_run_at_closure"] == ["T3"] and graph["closure_kind"] == "completed"
    by_key = {t["task_key"]: t for t in graph["tasks"]}
    assert (by_key["T3"]["not_run_at_closure"], by_key["T1"]["not_run_at_closure"], by_key["T2"]["not_run_at_closure"]) == (
        "completed", None, None,
    )
    # 진행기를 한 번 더 불러도(종료된 업무) 이력은 한 번뿐이다.
    h.client.post(f"/api/cases/{case_id}/progress/resume", json={"actor": "owner"})
    events = [e for e in Repository(h.client.app.state.conn).list_progress_events(case_id) if e["step"] == "tasks_not_run"]
    assert len(events) == 1 and events[0]["codes"] == ["T3"] and "completed" in events[0]["detail"]


def test_an_exception_closure_gives_its_own_reason_and_a_finished_plan_has_none(processing_harness):
    """AC-2 — 예외를 수용해 닫으면 이유가 `closed_with_exceptions` 다. 남은 작업이 없는 업무는 빈 목록이다."""
    h = processing_harness
    case_id = _to_work(h)
    assert h.client.put(f"/api/cases/{case_id}/progress/limits", json={"remediation_limit": 0}).status_code == 200
    executor = h.agent.cli_executor
    executor.verification_response = VERIFICATION_ONE_FAILS
    # 기준이 미충족이면 닫히지 않으므로 남은 T3 도 돈다 — 가짜 실행기가 T3 에서 실제로 다른 파일을 쓰게 한다.
    first = dict(executor.write_files)
    for _ in range(30):
        verified = [r for r in _runs(h, case_id) if r["task_id"] == "T2" and r["status"] == "finished"]
        executor.write_files = {**first, "README.md": "# 사용법\n"} if verified else first
        h.agent.poll_once()
    conv = _drive(h, case_id, polls=10)
    assert _wait_codes(conv) == ["criteria_unresolved"], conv["progress"]
    assert [r["outcome"] for r in _runs(h, case_id) if r["task_id"] == "T3"] == ["completed"]
    # 모든 작업이 끝났으니 남은 작업은 없다(예외 수용 종료여도).
    wait = conv["progress"]["wait"][0]
    c2 = next(c for c in h.criteria(case_id) if c["criterion_key"] == "C-02")
    assert h.accept_exception(case_id, wait["candidate_id"], c2["id"], "경로는 다음 업무").status_code == 201
    assert h.accept(case_id, wait["candidate_id"]).status_code == 201
    conv = h.conversation(case_id)
    assert conv["unrun_tasks"] == []

    # 작업이 남은 채 예외 수용으로 닫히면 이유가 `closed_with_exceptions` 다 — T2 에서 미충족 → T3 이 막힌 경우를 만든다.
    blocked = _to_work(h)
    assert h.client.put(f"/api/cases/{blocked}/progress/limits", json={"remediation_limit": 0}).status_code == 200
    executor.write_files = first
    executor.times_out = lambda call: "task-T3" in call["run_id"]  # T3 은 끊겨 남는다(재시도 대신 사람 대기)
    conv = _drive(h, blocked, polls=30)
    assert _wait_codes(conv) == ["run_timed_out"], conv["progress"]
    candidate, _ = Repository(h.client.app.state.conn).build_completion_candidate(blocked)
    c2 = next(c for c in h.criteria(blocked) if c["criterion_key"] == "C-02")
    assert h.accept_exception(blocked, candidate["id"], c2["id"], "경로와 README 는 다음 업무").status_code == 201
    assert h.accept(blocked, candidate["id"]).status_code == 201
    executor.times_out = None
    conv = h.conversation(blocked)
    assert [(t["task_key"], t["reason"]) for t in conv["unrun_tasks"]] == [("T3", "closed_with_exceptions")]

    # 계획의 작업이 전부 끝난 업무 — 남은 작업이 없다.
    _project, plain, _request_id = _start(h)
    h.agent.cli_executor.verification_response = __import__("tests.conftest", fromlist=["x"]).FAKE_VERIFICATION_RESPONSE
    _drive(h, plain)
    _agree(h, plain)
    conv = _drive(h, plain, polls=30)
    assert conv["progress"]["state"] == "done"
    assert conv["unrun_tasks"] == []
    assert h.client.get(f"/api/cases/{plain}/work-graph").json()["not_run_at_closure"] == []
