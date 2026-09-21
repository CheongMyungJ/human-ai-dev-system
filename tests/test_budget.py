"""예산 예약·집계·정지(P3-R3).

R1은 한도를 **기록**했고 R2는 저장소 선택을 강제로 바꿨다. 예산은 지금까지 아무
것도 막지 않았다. 여기서 보는 것은 네 가지다.

1. 배정 전에 **원자적으로** 예약하는가 — 마지막 한 칸을 둘이 함께 통과하지 못하는가
2. 소비가 Case 하나로 **누적**되는가 — 역할·Task·재배정·재시작으로 초기화되지 않는가
3. hard 도달이 **새 실행만** 막고 기존 결과를 보존하는가
4. 강제할 수 있는 것과 없는 것을 **구분해 표시**하는가

마지막이 가장 중요하다. hard 한도를 건 사람은 "이제 초과하지 않는다"고 믿는다.
실행 수에는 그 약속을 지킬 수 있고 실행 시간에는 지킬 수 없다 — 돌고 있는 CLI 를
초 단위로 끊을 능력이 없다(P1-03 `cancel_confirmed = unknown`). 같은 모양으로
표시하면 없는 보장을 판 것이 된다(D-61).
"""

from __future__ import annotations

import sqlite3
import threading
from typing import Any

from controller import db as dbmod
from controller.repository import Repository
from domain.models import BudgetMetric, RunPurpose, RunRole

from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE, RUNNER_ID


# ---------------------------------------------------------------- 도우미


def _budget(harness, case_id: str) -> dict[str, Any]:
    return harness.client.get(f"/api/cases/{case_id}/budget").json()


def _set_limit(
    harness,
    case_id: str,
    metric: str,
    value: float,
    threshold_kind: str = "hard",
    expect: int = 201,
):
    response = harness.client.put(
        f"/api/cases/{case_id}/budget",
        json={
            "metric": metric,
            "threshold_kind": threshold_kind,
            "limit_value": value,
            "set_by": "owner",
        },
    )
    assert response.status_code == expect, response.text
    return response


def _analysis_case(harness) -> tuple[dict[str, Any], str]:
    """실행 배관만 보는 Case. 기능 개발 진입 조건을 통과시키지 않아도 된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    artifact = harness.submit_artifact(case["id"], "조사 지시")["artifact_id"]
    return case, artifact


def _set_assigned_at(harness, run_id: str, when: str) -> None:
    """배정 시각을 기록된 값으로 바꾼다.

    시험이 실제로 몇 초를 기다리게 하지 않기 위해서다. 바꾸는 것은 **관측 기록**
    이고 계산은 제품 코드가 그대로 한다.
    """
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        conn.execute("UPDATE run SET assigned_at = ? WHERE run_id = ?", (when, run_id))
        conn.commit()
    finally:
        conn.close()


def _request_run(
    harness,
    case_id: str,
    artifact: str,
    run_id: str,
    role: str = "author",
    purpose: str = "limited_analysis",
    tool_id: str = "local-echo",
    mode: str = "p2-01-local",
    task_id: str = "task-1",
):
    """Run 생성을 **상태 코드를 판정하지 않고** 요청한다.

    `Harness.create_run` 은 201/200 을 단언하므로 거부를 볼 수 없다. 거부가 이
    시험의 대상이다.
    """
    return harness.client.post(
        f"/api/cases/{case_id}/runs",
        json={
            "run_id": run_id,
            "instruction_artifact_id": artifact,
            "purpose": purpose,
            "role": role,
            "tool_id": tool_id,
            "mode": mode,
            "permission": "read_only",
            "task_id": task_id,
        },
    )


# =========================================================== 기본 무제한


def test_an_unlimited_case_is_never_blocked_by_budget(harness):
    """AC-1 — 한도를 설정하지 않으면 예산으로 아무 것도 막히지 않는다(D-56).

    **새 강제가 기본 동작을 바꾸지 않는 것이 첫 조건이다.** 전체 예산은 기본
    무제한이고, 예약 표가 생겼다는 이유로 실행이 줄어들면 안 된다.
    """
    case, artifact = _analysis_case(harness)
    for i in range(4):
        assert _request_run(harness, case["id"], artifact, f"run-free-{i}").status_code == 201

    budget = _budget(harness, case["id"])
    assert budget["unlimited"] is True
    assert budget["stop"]["stopped"] is False
    # 재고는 있다. 막지 않을 뿐이다.
    assert budget["usage"]["run_count"]["exposure"] == 4.0
    refusals = [r for c in harness.admission_checks(case["id"]) for r in c["refusals"]]
    assert not [r for r in refusals if "budget" in r]


# ======================================================= 예약과 원자성


def test_a_reservation_is_recorded_when_the_run_is_created(harness):
    """AC-16 — 실행 하나가 무엇을 얼마나 잡았는지 남는다.

    `context_bytes` 는 **제어부가 만들어 전달한 패키지의 크기**다. CLI 가 안에서
    더 읽은 자료를 측정했다고 주장하지 않는다(autonomy-budget-policy 7절).
    """
    case, artifact = _analysis_case(harness)
    _request_run(harness, case["id"], artifact, "run-res-1")

    reservations = {r["metric"]: r for r in _budget(harness, case["id"])["reservations"]}
    assert reservations["run_count"]["reserved_value"] == 1.0
    assert reservations["run_count"]["state"] == "held"
    assert reservations["run_count"]["source"] == "reserved"
    # 시간은 **끝나야 안다.** 예약값이 0 이 아니라 NULL(=모름)이다.
    assert reservations["execution_seconds"]["reserved_value"] is None
    assert reservations["execution_seconds"]["reservation_kind"] == "open_ended_per_run"

    # 지시 원문의 실제 크기와 같다. 지어낸 수가 아니다.
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        byte_size = conn.execute(
            "SELECT byte_size FROM artifact_ref WHERE artifact_id = ?", (artifact,)
        ).fetchone()[0]
    finally:
        conn.close()
    assert reservations["context_bytes"]["reserved_value"] == float(byte_size)

    # 검토 축은 작성 실행에 붙지 않는다.
    assert "review_run_count" not in reservations


def test_the_last_slot_is_won_by_exactly_one_of_two_concurrent_requests(harness):
    """AC-3 — 마지막 한 칸을 두 요청이 동시에 노려도 정확히 하나만 만들어진다.

    **이 시험이 "원자적으로 검사한다"(D-61)의 실제 내용이다.** 검사와 Run 생성이
    다른 트랜잭션이면 둘 다 같은 잔여량을 읽고 함께 통과한다.

    연결을 **둘** 쓴다. 한 연결로 두 스레드를 돌리면 SQLite 가 어차피 직렬화해
    아무 것도 확인하지 못한다 — 실제로 막는 것은 `BEGIN IMMEDIATE` 이고 그것은
    연결이 둘일 때만 시험된다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 1)

    path = harness.controller_config.db_path
    ready = threading.Barrier(2)
    results: dict[str, Any] = {}

    def attempt(name: str) -> None:
        conn = dbmod.connect(path)
        repo = Repository(conn)
        try:
            ready.wait(timeout=10)
            run, created, result, _ = repo.admit_and_create_run(
                case_id=case["id"],
                run_id=f"run-race-{name}",
                task_id="task-1",
                purpose=RunPurpose.LIMITED_ANALYSIS,
                role=RunRole.AUTHOR,
                tool_id="local-echo",
                mode="p2-01-local",
                permission=harness_permission(),
                instruction_artifact_id=artifact,
                instruction_artifact_rev=1,
            )
            results[name] = (run is not None and created, result.refusals if result else [])
        except Exception as exc:  # 경쟁에서 진 쪽도 기록으로 남아야 한다
            results[name] = ("error", repr(exc))
        finally:
            conn.close()

    threads = [threading.Thread(target=attempt, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    created = [name for name, (ok, _) in results.items() if ok is True]
    assert len(created) == 1, results
    loser = [name for name in results if name not in created][0]
    assert any(
        r.value == "budget_hard_limit_reached" for r in results[loser][1]
    ), results[loser]

    # **실제로 Run 은 하나다.** 판정이 아니라 표를 본다.
    runs = harness.client.get(f"/api/cases/{case['id']}").json()["runs"]
    assert len(runs) == 1, [r["run_id"] for r in runs]
    assert _budget(harness, case["id"])["usage"]["run_count"]["exposure"] == 1.0


def harness_permission():
    from domain.models import Permission

    return Permission.READ_ONLY


# ========================================================== 정지의 의미


def test_a_stopped_case_still_accepts_results_from_runs_already_in_flight(harness):
    """AC-4 — 정지 중에도 진행 중 실행의 결과·이벤트는 받는다.

    hard 는 "새 비용 발생 실행 금지"이지 "기존 결과 폐기"가 아니다(D-61). 결과를
    받지 않으면 이미 지불한 비용의 산출물을 버리는 것이고, 그 실행은 예약을 잡은
    채로 영원히 남는다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 1)
    assert _request_run(harness, case["id"], artifact, "run-flight-1").status_code == 201

    # 한도가 찼다. 새 실행은 막힌다.
    assert _budget(harness, case["id"])["stop"]["stopped"] is True
    assert _request_run(harness, case["id"], artifact, "run-flight-2").status_code == 409

    # 그런데 진행 중 실행은 그대로 끝난다.
    harness.agent.poll_once()
    run = harness.client.get("/api/runs/run-flight-1").json()
    assert run["status"] == "finished"
    assert run["outcome"] == "completed"

    usage = _budget(harness, case["id"])["usage"]["run_count"]
    assert usage["settled"] == 1.0
    assert usage["runs_in_flight"] == 0


def test_reaching_a_hard_limit_does_not_close_or_cancel_the_case(harness):
    """AC-5 — hard 도달은 완료도 취소도 아니다.

    "소진은 대기·중단이며 성공이나 기준 완화가 아니다"(D-56). Case 상태를 바꾸면
    그 다음에 필요한 것이 "되돌리기"가 되고, 되돌리기는 사람의 기록을 고치는 일이다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 1)
    _request_run(harness, case["id"], artifact, "run-open-1")
    _request_run(harness, case["id"], artifact, "run-open-2")

    after = harness.client.get(f"/api/cases/{case['id']}").json()
    assert after["status"] not in ("closed", "cancelled")
    assert after["status"] == case["status"]

    stop = _budget(harness, case["id"])["stop"]
    assert stop["stopped"] is True
    assert "보존" in stop["detail"]
    assert stop["metrics"][0]["metric"] == "run_count"


def test_raising_the_limit_resumes_and_there_is_no_continue_bypass(harness):
    """AC-6 — 재개는 **한도 변경으로만** 한다(D-61).

    `continue` 를 hard 한도의 예외로 묵시 적용하지 않는다. 그런 인자가 없다는 것을
    요청 본문으로 확인한다 — 모르는 필드는 거부되거나 무시되며, 어느 쪽이든 그것으로
    실행이 열리지 않는다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 1)
    _request_run(harness, case["id"], artifact, "run-resume-1")
    assert _request_run(harness, case["id"], artifact, "run-resume-2").status_code == 409

    # **우회 시도.** 같은 요청에 예외 인자를 붙여도 열리지 않는다.
    bypass = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-resume-2",
            "instruction_artifact_id": artifact,
            "purpose": "limited_analysis",
            "role": "author",
            "tool_id": "local-echo",
            "mode": "p2-01-local",
            "permission": "read_only",
            "task_id": "task-1",
            "continue_past_budget": True,
            "ignore_budget": True,
        },
    )
    assert bypass.status_code in (409, 422), bypass.text

    # 한도를 올리면 그 순간 다시 배정된다. 별도의 "재개" 명령이 없다.
    _set_limit(harness, case["id"], "run_count", 3)
    assert _budget(harness, case["id"])["stop"]["stopped"] is False
    assert _request_run(harness, case["id"], artifact, "run-resume-2").status_code == 201


def test_a_budget_stop_does_not_relax_gates_criteria_or_permissions(harness):
    """AC-18 — 예산 소진이 필수 기준·검증·권한을 완화하지 않는다.

    "예산 때문에 필수 기준·검증·컨텍스트의 핵심 제약을 삭제하거나 미검증을 완료로
    표시하지 않는다"(autonomy-budget-policy 8절). 정지는 **덜 엄격해지는** 상태가
    아니라 **더 적게 실행하는** 상태다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 1)
    _request_run(harness, case["id"], artifact, "run-strict-1")
    harness.agent.poll_once()
    _request_run(harness, case["id"], artifact, "run-strict-2")

    # 쓰기 권한은 여전히 목적·작업공간 조건으로 거부된다. 예산 사유가 다른 사유를
    # 대체하거나 면제하지 않는다.
    blocked = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-strict-3",
            "instruction_artifact_id": artifact,
            "purpose": "intent_authoring",
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "workspace_write",
            "task_id": "task-1",
        },
    )
    assert blocked.status_code == 409
    refusals = blocked.json()["detail"]["admission"]["refusals"]
    assert "permission_not_allowed_in_stage" in refusals
    assert "budget_hard_limit_reached" in refusals

    # 완료 경로도 열리지 않는다. 결과는 여전히 기준으로 판정된다.
    result = harness.client.get(f"/api/cases/{case['id']}/result").json()
    assert result["criteria"] == [] or all(
        c["verdict"] != "met" for c in result["criteria"]
    )


# =========================================================== 누적 규칙


def test_a_review_run_is_counted_once_on_each_axis(harness):
    """AC-7 — 검토 실행은 전체 실행 수에도, 검토 실행 수에도 **각각 한 번** 잡힌다.

    "검토는 전체 AI 실행의 부분집합이며 같은 실행을 전체에서 중복 차감하지
    않는다"(autonomy-budget-policy 7절). 전체에서 빼면 검토를 늘릴수록 전체 한도가
    늘어난다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    intent = harness.ai_draft(case["id"])
    assert intent

    usage = _budget(harness, case["id"])["usage"]
    author_runs = usage["run_count"]["exposure"]
    assert author_runs >= 1
    assert usage["review_run_count"]["exposure"] == 0.0

    latest = harness.latest_intent(case["id"])
    review = harness.ai_gate_review(case["id"], latest, run_id="run-rev-1")
    assert review.status_code in (200, 201), review.text

    usage = _budget(harness, case["id"])["usage"]
    assert usage["run_count"]["exposure"] == author_runs + 1
    assert usage["review_run_count"]["exposure"] == 1.0

    by_role = _budget(harness, case["id"])["by_role"]
    assert by_role["reviewer"]["run_count"]["settled"] == 1.0
    assert by_role["reviewer"]["review_run_count"]["settled"] == 1.0
    # **작성 실행에는 검토 축이 아예 없다.** 0 으로 채우지 않는다.
    assert "review_run_count" not in by_role["author"]


def test_splitting_tasks_and_roles_does_not_reset_the_case_budget(harness):
    """AC-8 — Task·역할·세션을 나눠도 소비가 이어진다(D-61).

    "여러 저장소·역할·병렬 Task 에 나누거나 Profile·세션·CLI·Runner 를 바꿔도 소비가
    초기화되지 않는다." 누적 단위는 Case 하나다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 3)

    assert _request_run(
        harness, case["id"], artifact, "run-split-1", task_id="task-1"
    ).status_code == 201
    assert _request_run(
        harness, case["id"], artifact, "run-split-2", task_id="task-2"
    ).status_code == 201
    assert _request_run(
        harness, case["id"], artifact, "run-split-3", task_id="task-3"
    ).status_code == 201
    # 네 번째는 **다른 Task 라는 이유로 열리지 않는다.**
    refused = _request_run(harness, case["id"], artifact, "run-split-4", task_id="task-4")
    assert refused.status_code == 409
    assert refused.json()["detail"]["admission"]["refusals"] == ["budget_hard_limit_reached"]

    by_purpose = _budget(harness, case["id"])["by_purpose"]
    assert by_purpose["limited_analysis"]["run_count"]["rows"] == 3


def test_the_same_result_reported_twice_is_not_charged_twice(harness):
    """AC-10 — 동일 결과의 재전송이 소비를 두 번 세지 않는다.

    "동일 결과의 중복 이벤트는 중복 청구하지 않는다"(autonomy-budget-policy 7절).
    """
    case, artifact = _analysis_case(harness)
    created = harness.create_run(case["id"], artifact, run_id="run-dup-1")
    harness.agent.poll_once()

    before = _budget(harness, case["id"])["usage"]["run_count"]["exposure"]
    report = harness.client.post(
        "/api/runner/runs/run-dup-1/result",
        json={
            "runner_id": RUNNER_ID,
            "generation": created["run"]["assignment_generation"],
            "outcome": "completed",
            "exit_code": 0,
            "residual_activity": "none",
        },
    )
    assert report.status_code in (200, 201), report.text
    after = _budget(harness, case["id"])["usage"]["run_count"]["exposure"]
    assert after == before == 1.0
    rows = [
        r
        for r in _budget(harness, case["id"])["reservations"]
        if r["metric"] == "run_count"
    ]
    assert len(rows) == 1


def test_a_reassignment_is_new_consumption_and_needs_budget(harness):
    """AC-11 — 재배정된 실행의 두 번째 호출은 **새 소비**다.

    "재시작된 실제 AI 호출은 새 소비"(autonomy-budget-policy 7절). 같은 `run_id`
    라는 이유로 두 번째 CLI 호출을 공짜로 두면 한도가 재배정 횟수만큼 늘어난다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 2)
    harness.create_run(case["id"], artifact, run_id="run-gen-1")

    bumped = harness.client.post("/api/runs/run-gen-1/reassign", json={})
    assert bumped.status_code in (200, 201), bumped.text
    usage = _budget(harness, case["id"])["usage"]["run_count"]
    assert usage["exposure"] == 2.0, "재배정이 새 소비로 잡히지 않았다"

    # 예산이 없으면 **재배정하지 않는다.**
    again = harness.client.post("/api/runs/run-gen-1/reassign", json={})
    assert again.status_code == 409, again.text
    run = harness.client.get("/api/runs/run-gen-1").json()
    assert run["assignment_generation"] == 2, "거부된 재배정이 세대를 올렸다"


def test_consumption_survives_a_reopened_database(harness):
    """AC-9 — 제어부를 다시 열어도 사용량·예약이 그대로다.

    판단 근거를 전부 DB 에서 다시 읽는다는 규칙이 예산에도 적용된다 — 재시작으로
    한도를 우회할 수 없다(FR-29 수용 기준).
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 2)
    harness.create_run(case["id"], artifact, run_id="run-restart-1")
    harness.agent.poll_once()

    conn = dbmod.connect(harness.controller_config.db_path)
    dbmod.migrate(conn)
    try:
        repo = Repository(conn)
        state = repo.budget_state(case["id"])
        assert state["usage"]["run_count"]["exposure"] == 1.0
        assert state["usage"]["run_count"]["settled"] == 1.0
        # 이행이 다시 돌아도 같은 실행에 행을 더 만들지 않는다.
        assert len([r for r in state["reservations"] if r["metric"] == "run_count"]) == 1
    finally:
        conn.close()


# ================================================= 모르는 것을 모른다고


def test_an_unknown_outcome_does_not_release_what_is_still_unknown(harness):
    """AC-12 — 결과가 불명이면 예약을 해제하지 않는다.

    "결과가 불명확하면 실행 여부·사용량을 대조하기 전 예약을 임의 해제하지
    않는다"(autonomy-budget-policy 8절). 해제하면 실제로는 돌고 있는 실행의 비용이
    잔여량으로 되살아난다.

    **다만 결과 불명이 모든 지표를 똑같이 모르게 만들지는 않는다.** 그 실행이
    있었다는 사실과 전달한 패키지의 크기는 잔류 프로세스가 있어도 달라지지 않고,
    실제로 얼마나 오래 돌았는지와 토큰은 달라진다. 지표마다 다르게 판정한다.
    """
    case, artifact = _analysis_case(harness)
    created = harness.create_run(case["id"], artifact, run_id="run-unknown-1")
    # 실제로 배정돼 돌기 시작했다. 배정 시각이 있어야 실행 시간을 도출할 수 있다.
    _set_assigned_at(harness, "run-unknown-1", "2026-09-21T00:00:00.000000+00:00")
    harness.client.post(
        "/api/runner/runs/run-unknown-1/result",
        json={
            "runner_id": RUNNER_ID,
            "generation": created["run"]["assignment_generation"],
            "outcome": "unknown",
            "residual_activity": "unknown",
        },
    )
    budget = _budget(harness, case["id"])
    rows = {r["metric"]: r for r in budget["reservations"]}

    # --- 호출은 실제로 있었다. 그 수는 확정이다 -------------------------
    assert budget["usage"]["run_count"]["settled"] == 1.0
    assert rows["run_count"]["state"] == "settled"

    # --- **시간은 모른다.** 프로세스가 남아 있을 수 있다 ----------------
    seconds = budget["usage"]["execution_seconds"]
    assert seconds["settled"] == 0.0
    assert seconds["runs_unknown"] == 1
    assert seconds["complete"] is False
    assert rows["execution_seconds"]["state"] == "unresolved"
    assert rows["execution_seconds"]["settle_source"] == "outcome_unknown"
    # 그래도 **노출에는 남는다.** 관측한 만큼이 잔여량에서 빠져 있어야 한다.
    assert seconds["exposure"] == seconds["unresolved"]

    # --- 토큰도 모른다. 0 으로 적지 않는다 -------------------------------
    assert rows["input_tokens"]["actual_value"] is None
    assert rows["input_tokens"]["measurement"] == "unavailable"


def test_unreported_tokens_are_unavailable_not_zero(harness):
    """AC-13 — 어댑터가 주지 않은 값을 0 으로 적지 않는다(D-61).

    0 으로 적으면 한도가 영원히 남아 있는 것처럼 보인다. "미제공을 0으로 기록하지
    않는다"는 이 한 줄이 경고선을 쓸모 있게 만든다.
    """
    case, artifact = _analysis_case(harness)
    harness.create_run(case["id"], artifact, run_id="run-tok-1")
    harness.agent.poll_once()

    usage = _budget(harness, case["id"])["usage"]
    assert usage["input_tokens"]["settled"] == 0.0
    assert usage["input_tokens"]["runs_counted"] == 0
    assert usage["input_tokens"]["runs_unknown"] == 1
    assert usage["input_tokens"]["complete"] is False

    row = [
        r
        for r in _budget(harness, case["id"])["reservations"]
        if r["metric"] == "input_tokens"
    ][0]
    assert row["actual_value"] is None
    assert row["measurement"] == "unavailable"
    assert row["settle_source"] == "adapter_not_reported"


def test_reported_tokens_are_aggregated_with_their_measurement(harness):
    """AC-13 — 어댑터가 준 값은 실제로 집계된다. 측정 방식이 함께 남는다."""
    case, artifact = _analysis_case(harness)
    harness.agent.cli_executor.usage = {
        "tokens": {"input_tokens": 1500, "cached_input_tokens": 900, "output_tokens": 220},
        "cost_usd": 0.37,
    }
    harness.agent.cli_executor.residual_activity = "none"
    harness.create_run(
        case["id"],
        artifact,
        run_id="run-tok-2",
        tool_id=FAKE_TOOL_ID,
        mode=FAKE_TOOL_MODE,
    )
    harness.agent.poll_once()

    usage = _budget(harness, case["id"])["usage"]
    assert usage["input_tokens"]["settled"] == 1500.0
    assert usage["output_tokens"]["settled"] == 220.0
    assert usage["estimated_cost"]["settled"] == 0.37
    assert usage["input_tokens"]["complete"] is True
    # **추정은 추정으로 남는다.** 어댑터가 줬다고 exact 가 되지 않는다.
    assert usage["input_tokens"]["measurement"] == "estimated"
    # 합산 규칙을 지어내지 않는다 — `cached_input_tokens` 를 더하지 않았다.
    assert usage["input_tokens"]["settled"] != 2400.0


# ================================================= 보장 범위의 구분


def test_an_estimated_metric_still_refuses_a_hard_limit(harness):
    """AC-14 — 토큰·비용의 hard 한도는 여전히 **설정을 받지 않는다**(R1 그대로).

    실제 사용량을 주지 않거나 사후에만 주므로 정확한 상한을 약속할 수 없다. 거부하지
    않고 저장하면 설정한 사람은 상한이 있다고 믿는데 시스템은 지킬 방법이 없다.
    """
    case, _ = _analysis_case(harness)
    for metric in ("input_tokens", "output_tokens", "estimated_cost"):
        response = _set_limit(harness, case["id"], metric, 1000, expect=409)
        assert response.json()["detail"]["refusals"] == ["hard_limit_not_enforceable"]
    assert _budget(harness, case["id"])["unlimited"] is True


def test_a_time_limit_is_accepted_but_not_as_an_absolute_cap(harness):
    """AC-14 — 시간 지표의 hard 한도는 받되 **절대 상한으로 표시하지 않는다**.

    실행 시간은 끝나면 정확히 잴 수 있지만(`exact`) 시작 전에 얼마가 될지는 모르고,
    돌고 있는 CLI 를 초 단위로 끊을 능력도 없다(P1-03 `cancel_confirmed = unknown`).
    그래서 새 배정은 막을 수 있어도 진행 중 실행의 초과 노출은 막을 수 없다.

    **이 구분을 지우면 없는 보장을 판 것이 된다**(D-61).
    """
    case, _ = _analysis_case(harness)
    body = _set_limit(harness, case["id"], "execution_seconds", 600).json()
    limit = [l for l in body["limits"] if l["metric"] == "execution_seconds"][0]
    assert limit["measurement"] == "exact"
    assert limit["enforcement"] == "enforced_no_absolute_cap"
    assert limit["guarantee"] == "no_absolute_cap"

    contract = body["reservation_contract"]
    assert contract["run_count"]["hard_guarantee"] == "absolute"
    assert contract["context_bytes"]["hard_guarantee"] == "absolute"
    assert contract["execution_seconds"]["hard_guarantee"] == "no_absolute_cap"
    assert contract["elapsed_seconds"]["hard_guarantee"] == "no_absolute_cap"
    assert contract["input_tokens"]["hard_guarantee"] == "not_enforceable"
    # 왜 그런지가 같은 자리에 있다. 사람이 코드를 읽게 하지 않는다(FR-14).
    assert "초 단위로" in contract["execution_seconds"]["reason"]


def test_an_overshoot_is_recorded_with_its_cause(harness):
    """AC-15 — 실제 초과가 생기면 값·원인·미확인 범위를 기록한다(D-61).

    시간 한도는 새 배정을 막을 뿐이므로 이미 도는 실행이 한도를 넘길 수 있다.
    그때 표시를 바꿔 넘지 않은 것처럼 만들지 않는다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "execution_seconds", 1)
    created = harness.create_run(case["id"], artifact, run_id="run-over-1")

    # 그 실행이 한도보다 오래 돌았다. 실제 시계 대신 기록된 시각을 바꿔 재현한다 —
    # 시험이 몇 초를 기다리게 하지 않는다.
    _set_assigned_at(harness, "run-over-1", "2026-09-21T00:00:00.000000+00:00")
    harness.client.post(
        "/api/runner/runs/run-over-1/result",
        json={
            "runner_id": RUNNER_ID,
            "generation": created["run"]["assignment_generation"],
            "outcome": "completed",
            "exit_code": 0,
            "residual_activity": "none",
        },
    )

    budget = _budget(harness, case["id"])
    usage = budget["usage"]["execution_seconds"]
    # **초과한 값이 그대로 남는다.** 표시를 바꿔 넘지 않은 것처럼 만들지 않는다.
    assert usage["exposure"] > 1.0, "초과가 기록되지 않았다"
    row = [r for r in budget["reservations"] if r["metric"] == "execution_seconds"][0]
    assert row["actual_value"] > 1.0
    # 가짜 CLI 는 잔류 활동을 `unknown` 으로 보고한다(실제 어댑터와 같다). 그래서
    # 관측값은 남되 최종으로 확정되지 않는다 — 그것이 정직한 상태다.
    assert row["settle_source"] in ("observed_clock", "residual_activity")
    # 초과한 채로 정지 상태가 되고, 그 사실을 보장 범위와 함께 말한다.
    stop = budget["stop"]
    assert stop["stopped"] is True
    reached = [m for m in stop["metrics"] if m["metric"] == "execution_seconds"][0]
    assert reached["guarantee"] == "no_absolute_cap"
    assert reached["exposure"] > reached["limit_value"]

    # 그리고 **새 실행은 막힌다.** 이미 넘었다고 포기하지 않는다.
    assert _request_run(harness, case["id"], artifact, "run-over-2").status_code == 409


def test_a_warning_threshold_shows_but_does_not_block(harness):
    """AC-14 — 경고선은 표시이며 실행을 막지 않는다.

    "경고 자체로 반드시 사람 응답을 기다리지는 않는다"(autonomy-budget-policy 8절).
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 1, threshold_kind="warn")
    assert _request_run(harness, case["id"], artifact, "run-warn-1").status_code == 201
    budget = _budget(harness, case["id"])
    assert budget["warnings"][0]["metric"] == "run_count"
    assert budget["stop"]["stopped"] is False
    # 경고를 넘어서도 계속 배정된다.
    assert _request_run(harness, case["id"], artifact, "run-warn-2").status_code == 201


def test_a_review_limit_does_not_block_an_authoring_run(harness):
    """hard 는 **그 한도를 소비하는** 실행만 막는다(autonomy-budget-policy 8절).

    검토 한도가 소진됐다고 Case 전체를 잠그면 남은 작업까지 멈춘다 — 그것은 정지가
    아니라 취소에 가깝다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "review_run_count", 1)

    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        conn.execute(
            "INSERT INTO budget_reservation (id, case_id, run_id, generation, metric,"
            " reserved_value, actual_value, measurement, reservation_kind, role, purpose,"
            " state, source, settle_source, reserved_at, settled_at)"
            " SELECT 'budres-seed', ?, run_id, 1, 'review_run_count', 1.0, 1.0, 'exact',"
            " 'exact_per_run', 'reviewer', 'intent_gate_review', 'settled', 'reserved',"
            " 'reserved_exact', created_at, created_at FROM run LIMIT 1",
            (case["id"],),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()

    # 작성 실행은 그대로 열린다.
    assert _request_run(harness, case["id"], artifact, "run-author-ok").status_code == 201


# ============================================================ 분리 유지


def test_the_budget_model_is_not_a_repair_counter(harness):
    """AC-19 — repair 한도와 예산은 분리된 채 남는다(D-56·D-29).

    "전체 예산이 남아도 repair 한도를 초과할 수 없고, repair 횟수가 남아도 전체
    예산을 초과할 수 없다." 둘은 서로를 대신하지 않으며, 예산 집계를 repair 횟수로
    쓰면 환경 재시도와 결함 수정 차수가 한 수로 섞인다.
    """
    case, _ = _analysis_case(harness)
    budget = _budget(harness, case["id"])
    assert "P4-01" in budget["repair_limit_note"]
    assert "repair" not in budget["usage"]
    assert not any("repair" in m for m in budget["measurement_contract"])
    # 아직 모델이 없는 것을 있다고 표시하지 않는다.
    assert "아직 모델이 없다" in budget["repair_limit_note"]


def test_budget_enforcement_did_not_spread_to_the_other_axes(harness):
    """AC-20 — 한 축을 강제로 바꿨다고 옆 축까지 강제되는 것으로 표시하지 않는다.

    **P3-R4에서 갱신했다.** R3 시점에 남아 있던 세 축 중 둘(`autonomy`·
    `controlled_checkpoint`)이 R4 에서 강제로 바뀌었다. 지키는 성질은 그대로다 —
    **게시는 여전히 P5 이며 네 축이 강제된다고 다섯째까지 번지지 않는다**(D-64).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    enforcement = harness.client.get(f"/api/cases/{case['id']}/policy").json()["enforcement"]
    assert enforcement["budget"]["state"] == "enforced"
    assert enforcement["budget"]["enforced_by"] == "P3-R3"
    assert enforcement["autonomy"]["state"] == "enforced"
    assert enforcement["autonomy"]["enforced_by"] == "P3-R4"
    assert enforcement["controlled_checkpoint"]["state"] == "enforced"
    assert enforcement["repository_selection"]["state"] == "enforced"
    # **번지지 않은 축.** 예산도 Autonomy 도 게시 권한을 만들지 않는다.
    assert enforcement["publish"]["state"] == "not_implemented"
    assert enforcement["publish"]["enforced_by"] == "P5"


def test_every_budget_metric_has_a_reservation_contract():
    """지표를 더하면 계약도 함께 더해야 한다.

    계약이 없는 지표가 생기면 `planned_reservation` 이 조용히 그것을 무시하고, 그
    지표의 한도는 설정만 되고 아무 것도 막지 않는다 — R1이 남긴 바로 그 상태가
    한 지표에만 다시 생긴다.
    """
    from domain.budget import RESERVATION_KIND, RESERVATION_REASON

    for metric in BudgetMetric:
        assert metric in RESERVATION_KIND, metric
        assert RESERVATION_REASON.get(metric), metric


def test_the_reservation_table_has_no_body_columns(harness):
    """AC-21 — 예약 표에 본문이 들어가지 않는다.

    예산 집계는 **수와 상태와 참조**만 다룬다. 실행이 무엇을 읽고 무엇을 썼는지는
    소유 Runner 에 있고, 여기 들어오면 제어부가 원문을 보관하는 자리가 하나 늘어난다
    (data-boundary-review, NFR-06).
    """
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    try:
        columns = {r["name"] for r in conn.execute('PRAGMA table_info("budget_reservation")')}
        assert columns
        body_like = {"content", "body", "text", "raw", "payload", "prompt", "summary", "note"}
        assert not (columns & body_like), columns & body_like
        # 값은 전부 수·식별자·상태다. 자유 문자열 설명 칸이 없다.
        assert {"reserved_value", "actual_value", "metric", "state"} <= columns
    finally:
        conn.close()


def test_no_prompt_or_output_bytes_reach_the_reservation_rows(harness):
    """AC-21 — 실제 실행을 돌려도 예약 행에 본문 조각이 없다."""
    case, artifact = _analysis_case(harness)
    secret = "예산-경계-표식-9f3a"
    harness.submit_artifact(case["id"], f"{secret} 를 조사해 주세요.")
    harness.create_run(
        case["id"], artifact, run_id="run-bound-1", tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE
    )
    harness.agent.poll_once()

    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        blob = "".join(
            str(v) for row in conn.execute("SELECT * FROM budget_reservation") for v in row
        )
    finally:
        conn.close()
    assert secret not in blob


def test_a_reported_usage_is_settled_even_when_residual_activity_is_unknown(harness):
    """라이브가 찾은 결함의 회귀 시험(P3-R3 9절).

    실제 codex 어댑터는 `residual_activity` 를 **항상** `unknown` 으로 보고한다
    (P1-03 `cancel_confirmed = unknown`). 그것을 확정 조건으로 쓰면, 어댑터가 실제로
    `input_tokens: 30600` 을 줬는데도 집계의 확정값이 0 으로 남는다 — 받은 관측을
    버리고 **모든 실제 실행의 토큰이 영원히 `unresolved`** 가 된다.

    잔류 프로세스가 **더 늘릴 수 있는 것**(실행 시간)과 **이미 보고된 것**(토큰)을
    구분한다.
    """
    case, artifact = _analysis_case(harness)
    harness.agent.cli_executor.usage = {
        "tokens": {"input_tokens": 30600, "cached_input_tokens": 27264, "output_tokens": 135},
        "cost_usd": "not_reported",
    }
    # 실제 어댑터와 같은 보고. 여기가 이 시험의 핵심이다.
    harness.agent.cli_executor.residual_activity = "unknown"
    harness.create_run(
        case["id"], artifact, run_id="run-live-like-1", tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE
    )
    harness.agent.poll_once()

    budget = _budget(harness, case["id"])
    usage = budget["usage"]
    rows = {r["metric"]: r for r in budget["reservations"]}

    # --- 보고된 값은 **확정된다** ----------------------------------------
    assert usage["input_tokens"]["settled"] == 30600.0
    assert usage["output_tokens"]["settled"] == 135.0
    assert rows["input_tokens"]["state"] == "settled"
    assert rows["input_tokens"]["settle_source"] == "adapter_reported"
    # 확정이어도 **추정은 추정으로 남는다.**
    assert rows["input_tokens"]["measurement"] == "estimated"

    # --- 주지 않은 값은 여전히 모른다 ------------------------------------
    assert rows["estimated_cost"]["actual_value"] is None
    assert rows["estimated_cost"]["measurement"] == "unavailable"
    assert usage["estimated_cost"]["complete"] is False

    # --- 시간은 다르다. 잔류 프로세스가 **더 쓸 수 있다** ----------------
    assert rows["execution_seconds"]["state"] == "unresolved"
    assert rows["execution_seconds"]["settle_source"] == "residual_activity"
    # 그래도 관측한 만큼은 노출에 남는다.
    assert usage["execution_seconds"]["exposure"] == usage["execution_seconds"]["unresolved"]


def test_resending_an_existing_run_id_is_not_refused_by_the_budget(harness):
    """멱등성이 예산보다 먼저다(P1 이월 항목).

    같은 `run_id` 의 재전송은 **검사보다 먼저** 처리된다. 이미 만들어진 실행에
    대해서는 "만들어도 되는가"가 아니라 "무엇이 만들어졌는가"가 답이기 때문이다.
    예산이 소진됐다고 재전송을 409 로 바꾸면, 응답을 놓친 호출자가 같은 요청을 다시
    보냈을 때 **이미 도는 실행을 없는 것처럼** 보게 된다.
    """
    case, artifact = _analysis_case(harness)
    _set_limit(harness, case["id"], "run_count", 1)
    first = _request_run(harness, case["id"], artifact, "run-idem-1")
    assert first.status_code == 201

    assert _budget(harness, case["id"])["stop"]["stopped"] is True

    again = _request_run(harness, case["id"], artifact, "run-idem-1")
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    # 하지도 않은 검사를 통과로 적지 않는다.
    assert again.json()["admission"] is None
    # 재전송이 소비를 늘리지 않는다.
    assert _budget(harness, case["id"])["usage"]["run_count"]["exposure"] == 1.0
