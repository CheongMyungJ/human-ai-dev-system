"""P4-05b — 진행 상한 설정(plans/P4-PLAN-05b.md).

재작성(`repair_limit`)·재시도(`task_retry_limit`) 상한이 코드 상수에서 **설정**이 됐다. 시스템
기본값은 제어부 환경 변수, Case 별 조정은 이력으로 남고, 진행기는 걸음마다 그 시점의 값을 읽는다.

이 파일이 지키는 것:

    무제한은 없다                   0~10 밖은 기동·요청 모두 거부한다
    출처가 보인다                   Case 명시 → 시스템 기본값, 조회가 값과 출처를 함께 준다
    이력을 덮어쓰지 않는다          이전 값은 superseded 로 남는다
    시도 수는 초기화하지 않는다     한도를 올리면 한 번 더 가고, 다시 실패하면 새 한도에서 멈춘다
    올리지 않은 계속 진행은 같은 대기다

시험 이름 옆의 AC 번호는 P4-PLAN-05b 4절이다.
"""

from __future__ import annotations

import sqlite3
import subprocess
from typing import Any

import pytest

from controller import db
from controller.config import ENV_REPAIR_LIMIT, ENV_TASK_RETRY_LIMIT, load_config
from controller.db import utc_now
from controller.repository import Repository
from domain import work_flow as workflow
from tests.conftest import FAKE_TASKS_VERIFIED, fake_preparation_response
from tests.test_migration import REPO_ROOT, _committed_schema
from tests.test_work_progressor import WORK_BLOCK, _agree, _drive, _runs, _start, _wait_codes

# ---------------------------------------------------------------- 순수 판정


def _flow(**overrides: Any) -> workflow.FlowState:
    """작업 그래프에 T1(구현) 하나가 배정 가능한 상태. 필요한 칸만 덮어쓴다."""
    base: dict[str, Any] = dict(
        case_id="case-1",
        closed=False,
        stage="work",
        profile="feature",
        paused=False,
        unfinished_runs=[],
        intent={
            "latest_intent_version": {"id": "iv-1"},
            "open_intent_questions": [],
            "agreement_state": "agreed_current",
            "unresolved_feedback": [],
        },
        intent_structure_reported=True,
        answers_after_version=False,
        gate={"verdict": "pass"},
        conformance_required="light",
        pending_deltas=0,
        checkpoint={},
        preparation={
            "level": "light",
            "fast_lane": {"eligible": True},
            "combined": {"artifact": {"id": "p-1"}, "state": "auto_conditions_met"},
            "design": {},
            "plan": {},
            "work_graph": {
                "present": True,
                "tasks": [{"task_key": "T1", "kind": "implementation", "state": "ready",
                           "repository_id": "repo-1"}],
                "readiness": {"T1": {"runnable": True}},
            },
        },
        completion_mode="auto_on_conditions",
        criteria=[],
        unresolved=[],
        unsettled_runs=[],
        candidate=None,
        code_repositories=[{"id": "repo-1", "name": "r"}],
        workspaces={"repo-1": {"present": True, "ready": True, "state": "ready"}},
    )
    base.update(overrides)
    return workflow.FlowState(**base)


def _failed(n: int, task_id: str = "T1", purpose: str = "feature_implementation") -> list[dict[str, Any]]:
    return [
        {"run_id": f"r{i}", "purpose": purpose, "task_id": task_id, "outcome": "failed",
         "status": "finished"}
        for i in range(n)
    ]


@pytest.mark.parametrize(
    "retry_limit, attempts, expected",
    [
        (1, 0, "run"),   # 첫 시도
        (1, 1, "run"),   # 기본값: 한 번 다시
        (1, 2, "wait"),  # 두 번째 실패는 사람 대기
        (0, 1, "wait"),  # 0 = 첫 실패에서 바로 사람
        (3, 3, "run"),
        (3, 4, "wait"),
    ],
)
def test_the_task_retry_limit_counts_retries_not_the_first_try(retry_limit, attempts, expected):
    """AC-7 — `task_retry_limit` 은 **다시 시도한** 횟수다. 첫 시도는 세지 않는다."""
    state = _flow(
        attempts={"task:T1": attempts} if attempts else {},
        finished_runs=_failed(attempts),
        limits=workflow.ProgressLimits(task_retry_limit=retry_limit),
    )
    step = workflow.next_step(state)
    assert step.kind == expected, step
    if expected == "wait":
        assert step.code == workflow.WaitReason.TASK_FAILED
        reason = step.reasons[0]
        assert (reason["limit_key"], reason["limit"], reason["used"]) == (
            "task_retry_limit", retry_limit, attempts - 1
        )
        assert reason["limit_source"] == "system_default"


@pytest.mark.parametrize(
    "repair_limit, writes, expected",
    [
        (2, 1, "run"),   # 첫 작성 뒤 필수 항목이 비었다 → 재작성 1
        (2, 2, "run"),   # 재작성 2 (P4-05 는 여기서 멈췄다 — plan 의 "재작성 2" 보다 한 번 적었다)
        (2, 3, "wait"),
        (0, 1, "wait"),  # 0 = 첫 작성 뒤 바로 사람
    ],
)
def test_preparation_rewrites_count_only_the_rewrites(repair_limit, writes, expected):
    """AC-8 — 준비 산출물의 상한은 첫 작성을 빼고 **다시 쓴** 횟수다."""
    prep = {
        "level": "light",
        "fast_lane": {"eligible": True},
        "combined": {"artifact": {"id": "p-1"}, "state": "pending", "mode": "auto",
                     "missing_required_sections": ["verifiability"]},
        "design": {},
        "plan": {},
        "work_graph": {"present": False},
    }
    state = _flow(
        preparation=prep,
        attempts={"prep:combined": writes},
        limits=workflow.ProgressLimits(repair_limit=repair_limit),
    )
    step = workflow.next_step(state)
    assert step.kind == expected, step
    if expected == "wait":
        assert step.code == workflow.WaitReason.PREPARATION_REPAIR_EXHAUSTED
        assert (step.reasons[0]["limit"], step.reasons[0]["used"]) == (repair_limit, writes - 1)
    else:
        assert step.code == "combined_rewrite"


@pytest.mark.parametrize("repair_limit, repairs, expected", [(2, 1, "run"), (2, 2, "wait"), (0, 0, "wait")])
def test_the_gate_repair_limit_is_read_from_the_state(repair_limit, repairs, expected):
    """AC-7 — QG-01 재작성 상한도 판정 시점의 값이다. 0 이면 첫 지적에서 사람 대기다."""
    state = _flow(
        gate={"verdict": "fail", "rule_verdict": "pass", "ai_verdict": "fail"},
        attempts={"intent_repair": repairs} if repairs else {},
        limits=workflow.ProgressLimits(
            repair_limit=repair_limit, sources=(("repair_limit", "case_setting"),)
        ),
    )
    step = workflow.next_step(state)
    assert step.kind == expected
    if expected == "wait":
        assert step.reasons[0]["limit_source"] == "case_setting"


def test_limits_have_no_unlimited_value():
    """AC-4 — 무제한은 없다. 범위 밖·정수가 아닌 값·모르는 이름은 판정 전에 거부된다."""
    for bad in (-1, 11, 2.5, True, "2"):
        with pytest.raises(ValueError):
            workflow.check_limit("repair_limit", bad)
    with pytest.raises(ValueError):
        workflow.check_limit("forever", 1)
    with pytest.raises(ValueError):
        workflow.ProgressLimits(repair_limit=11)
    assert workflow.ProgressLimits() == workflow.ProgressLimits(2, 1)


# ---------------------------------------------------------------- 기동 설정


def test_the_system_default_comes_from_the_environment_and_bad_values_stop_startup(monkeypatch):
    """AC-2 — 환경 변수가 시스템 기본값이다. 이상한 값이면 기동이 실패한다."""
    monkeypatch.delenv(ENV_REPAIR_LIMIT, raising=False)
    monkeypatch.delenv(ENV_TASK_RETRY_LIMIT, raising=False)
    assert load_config().progress_limits == workflow.ProgressLimits(2, 1)
    monkeypatch.setenv(ENV_REPAIR_LIMIT, "0")
    monkeypatch.setenv(ENV_TASK_RETRY_LIMIT, "10")
    assert load_config().progress_limits == workflow.ProgressLimits(0, 10)
    for bad in ("11", "-1", "two", "1.5"):
        monkeypatch.setenv(ENV_REPAIR_LIMIT, bad)
        with pytest.raises(ValueError, match=ENV_REPAIR_LIMIT):
            load_config()
    monkeypatch.setenv(ENV_REPAIR_LIMIT, "2")
    monkeypatch.setenv(ENV_TASK_RETRY_LIMIT, "x")
    with pytest.raises(ValueError, match=ENV_TASK_RETRY_LIMIT):
        load_config()


def test_the_startup_log_records_the_limits(harness):
    """AC-2 — 기동 로그에 유효한 시스템 기본값이 남는다(본문 없음)."""
    log = harness.client.app.state.config.log_path.read_text(encoding="utf-8")
    assert "repair_limit=2 task_retry_limit=1" in log


# ---------------------------------------------------------------- Case 조정·이력


def test_a_case_setting_overrides_the_system_default_and_keeps_its_history(harness):
    """AC-1·3·4 — Case 명시 → 시스템 기본값. 준 키만 바뀌고 이전 값은 superseded 로 남는다."""
    h = harness
    project = h.create_project()
    case = h.create_case(project["id"])
    case_id = case["id"]
    got = h.client.get(f"/api/cases/{case_id}/progress").json()["limits"]
    assert (got["repair_limit"]["value"], got["repair_limit"]["source"]) == (2, "system_default")
    assert (got["task_retry_limit"]["value"], got["task_retry_limit"]["source"]) == (1, "system_default")
    # P4-10 이 수정 사이클 한도·실행 제한 시간(초)을 같은 자리에 더했다.
    assert got["system_default"] == {
        "repair_limit": 2, "task_retry_limit": 1, "remediation_limit": 2, "run_timeout_seconds": 3600,
    }
    assert got["range"] == {"min": 0, "max": 10} and got["history"] == []

    first = h.client.put(
        f"/api/cases/{case_id}/progress/limits",
        json={"repair_limit": 3, "set_by": "owner", "reason_summary": "지적이 많은 업무"},
    )
    assert first.status_code == 200, first.text
    second = h.client.put(
        f"/api/cases/{case_id}/progress/limits", json={"repair_limit": 4, "set_by": "owner"}
    )
    limits = second.json()["limits"]
    assert (limits["repair_limit"]["value"], limits["repair_limit"]["source"]) == (4, "case_setting")
    # 주지 않은 키는 그대로 시스템 기본값이다.
    assert (limits["task_retry_limit"]["value"], limits["task_retry_limit"]["source"]) == (1, "system_default")
    history = limits["history"]
    assert [(r["limit_key"], r["limit_value"], r["state"]) for r in history] == [
        ("repair_limit", 3, "superseded"), ("repair_limit", 4, "current"),
    ]
    assert history[0]["reason_summary"] == "지적이 많은 업무" and history[0]["superseded_at"]
    assert all(r["set_by"] == "owner" for r in history)

    for bad in ({"repair_limit": 11}, {"task_retry_limit": -1}, {"set_by": "owner"}):
        refused = h.client.put(f"/api/cases/{case_id}/progress/limits", json=bad)
        assert refused.status_code == 422, (bad, refused.text)
    # 거부된 요청은 이력을 남기지 않는다.
    assert len(h.client.get(f"/api/cases/{case_id}/progress").json()["limits"]["history"]) == 2


def test_a_closed_case_refuses_a_limit_change(processing_harness):
    """AC-4 — 종료된 Case 는 거부한다(종료 뒤에는 예산 한도만 바꿀 수 있다)."""
    h = processing_harness
    _project, case_id, _request = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    _drive(h, case_id)
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed"
    refused = h.client.put(f"/api/cases/{case_id}/progress/limits", json={"task_retry_limit": 3})
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusals"] == ["case_already_closed"]
    assert h.client.get(f"/api/cases/{case_id}/progress").json()["limits"]["history"] == []


# ---------------------------------------------------------------- 진행기 동작


def _impl_runs(h, case_id: str) -> list[dict[str, Any]]:
    return [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]


def test_raising_the_limit_goes_once_more_and_stops_again_at_the_new_limit(processing_harness):
    """AC-5·6 — 상한 대기 → 계속 진행(같은 대기, 새 실행 없음) → 한도를 올림(한 번 더) → 새 한도에서 다시 대기.

    P4-05 문서는 "사람의 계속 진행이 한 번 더 시도한다" 고 적었지만 실제로는 같은 판정을 다시 볼 뿐
    이었다. 이제 한 번 더 가는 길은 한도를 올리는 것이고, 시도 수는 초기화되지 않는다.
    """
    h = processing_harness
    _project, case_id, _request = _start(h)
    _drive(h, case_id)
    h.agent.cli_executor.write_files = {}  # 고쳤다고 적지만 바뀐 것이 없다 → 실패
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"]
    wait = conv["progress"]["wait"][0]
    assert (wait["limit_key"], wait["limit"], wait["used"], wait["limit_source"]) == (
        "task_retry_limit", 1, 1, "system_default"
    )
    assert len(_impl_runs(h, case_id)) == 2
    assert conv["progress"]["limits"]["task_retry_limit"]["value"] == 1

    # 한도를 올리지 않은 계속 진행 — 새 실행이 없고 같은 대기다.
    resumed = h.client.post(f"/api/cases/{case_id}/progress/resume", json={"actor": "owner"})
    assert resumed.status_code == 200, resumed.text
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"] and len(_impl_runs(h, case_id)) == 2
    assert conv["send"]["general"]["allowed"] is True

    # 한도를 올리면 기록 뒤 진행기가 그 자리에서 한 번 더 간다.
    raised = h.client.put(
        f"/api/cases/{case_id}/progress/limits",
        json={"task_retry_limit": 2, "set_by": "owner", "reason_summary": "대기 카드에서 한도를 올림"},
    )
    assert raised.status_code == 200, raised.text
    conv = h.conversation(case_id)
    assert conv["current_request"] is not None
    assert conv["current_request"]["origin"] == "human_decision"
    assert conv["current_request"]["origin_ref"] == "progress_limits"
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"]
    assert len(_impl_runs(h, case_id)) == 3  # 한 번 더 — 시도 수는 초기화되지 않았다
    wait = conv["progress"]["wait"][0]
    assert (wait["limit"], wait["used"], wait["limit_source"]) == (2, 2, "case_setting")
    assert conv["progress"]["attempts"]["task:T1"] == 3

    # 고쳐진 뒤 한도를 올리면 이어서 끝까지 간다.
    h.agent.cli_executor.write_files = {"reader.py": "fixed\n"}
    assert h.client.put(
        f"/api/cases/{case_id}/progress/limits", json={"task_retry_limit": 3}
    ).status_code == 200
    _drive(h, case_id)
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed"


def test_a_zero_retry_limit_waits_on_the_first_failure(processing_harness):
    """AC-7 — `task_retry_limit = 0` 은 자동으로 다시 하지 않고 바로 사람에게다."""
    h = processing_harness
    _project, case_id, _request = _start(h)
    _drive(h, case_id)
    assert h.client.put(
        f"/api/cases/{case_id}/progress/limits", json={"task_retry_limit": 0}
    ).status_code == 200
    h.agent.cli_executor.write_files = {}
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"]
    assert len(_impl_runs(h, case_id)) == 1
    assert (conv["progress"]["wait"][0]["limit"], conv["progress"]["wait"][0]["used"]) == (0, 0)


def test_a_zero_repair_limit_waits_on_the_first_gate_finding(processing_harness):
    """AC-7 — `repair_limit = 0` 이면 QG-01 의 첫 지적에서 재작성 없이 사람 대기다."""
    h = processing_harness
    h.agent.cli_executor.review_response = (
        '{"findings": [{"criterion": "request_missing_or_contradictory", "severity": "required",'
        ' "certainty": "confirmed", "target": "scope", "summary": "범위가 요청과 다르다"}]}'
    )
    project, _repo_path = h.create_git_project("gate0")
    view = h.create_conversation(project["id"], "필터")
    case_id = view["case_id"]
    assert h.client.put(
        f"/api/cases/{case_id}/conformance-policy",
        json={"required": True, "set_by": "owner", "reason": "시험"},
    ).status_code == 200
    assert h.client.put(
        f"/api/cases/{case_id}/progress/limits", json={"repair_limit": 0}
    ).status_code == 200
    h.agent.cli_executor.discussion_response = f"정리합니다.\n{WORK_BLOCK.format(profile='feature')}"
    h.send_message(case_id, "필터를 구현해줘", "c-1")
    h.agent.poll_once()
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["gate_repair_exhausted"]
    purposes = [r["purpose"] for r in _runs(h, case_id)]
    assert purposes.count("intent_authoring") == 1 and purposes.count("intent_gate_review") == 1
    wait = conv["progress"]["wait"][0]
    assert (wait["limit_key"], wait["limit"], wait["used"]) == ("repair_limit", 0, 0)


def test_preparation_rewrites_run_up_to_the_setting(processing_harness):
    """AC-8 — 필수 항목이 빈 결합 기록은 첫 작성 뒤 **재작성 2회**(기본값)를 하고 사람 대기다."""
    h = processing_harness
    _project, case_id, _request = _start(h)
    _drive(h, case_id)
    incomplete = fake_preparation_response(
        "결합",
        {"change_summary": "필터를 더한다", "tasks": "T1 → T2", "verification": "시험 1건"},
        tasks=FAKE_TASKS_VERIFIED,
    )
    h.agent.cli_executor.combined_response = incomplete
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["preparation_repair_exhausted"], conv["progress"]
    plans = [r for r in _runs(h, case_id) if r["purpose"] == "plan_authoring"]
    assert len(plans) == 3  # 첫 작성 1 + 재작성 2
    wait = conv["progress"]["wait"][0]
    assert (wait["limit_key"], wait["limit"], wait["used"]) == ("repair_limit", 2, 2)
    assert "verifiability" in wait["missing_sections"]


# ---------------------------------------------------------------- 이행 v20 → v21


def _v20_schema() -> str:
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT, capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v20" in schema and "스키마 v21" not in schema:
            return schema
    pytest.skip("v20 스키마를 가진 커밋을 찾지 못했다")


def test_a_v20_database_gets_no_limit_it_never_had(tmp_path):
    """AC-9 — v20 → v21. 이력 표가 생기고 비어 있다. 옛 Case 는 시스템 기본값 출처이며 멱등이다."""
    committed = _v20_schema()
    assert "progress_limit_setting" not in committed and "case_progress" in committed
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    conn.executescript(committed)
    now = utc_now()
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (20, ?)", (now,))
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1', 'prj-1', 'old', 'feature', 'received', ?, ?)",
        (now, now),
    )
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    # v22(P4-06) 이후에도 이 이행의 사실은 같다 — 판의 고정은 각 판의 이행 시험이 한다.
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 21
    assert db.SCHEMA_VERSION >= 21
    assert conn.execute("SELECT COUNT(*) FROM progress_limit_setting").fetchone()[0] == 0
    repo = Repository(conn, progress_limits=workflow.ProgressLimits(3, 0))
    view = repo.progress_limits_view("case-1")
    assert (view["repair_limit"]["value"], view["repair_limit"]["source"]) == (3, "system_default")
    assert (view["task_retry_limit"]["value"], view["task_retry_limit"]["source"]) == (0, "system_default")
    # 범위 밖 값은 DB 도 받지 않는다(마지막 방어선).
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO progress_limit_setting (id, case_id, revision, limit_key, limit_value,"
            " set_by, state, created_at) VALUES ('x','case-1',1,'repair_limit',11,'o','current',?)",
            (now,),
        )
    db.migrate(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,)
    ).fetchone()[0] == 1
