"""P4-01 — QG-01~07 선택, 조건부 독립 검토, repair 누적."""

from __future__ import annotations

from controller import db
from controller.repository import Repository
from domain.models import GateId
from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE
from tests.test_preparation import _agreed_case, _refusals
from tests.test_work_graph import _graph_case


def _state(harness, case_id: str, task_key: str = "") -> dict:
    suffix = f"?task_key={task_key}" if task_key else ""
    response = harness.client.get(f"/api/cases/{case_id}/quality-gates{suffix}")
    assert response.status_code == 200, response.text
    return response.json()


def _by_gate(state: dict) -> dict[str, dict]:
    return {g["gate"]: g for g in state["gates"]}


def _set(harness, case_id: str, gate: str, **changes):
    body = {
        "actor": "owner",
        "reason_summary": "이 Case의 검증 정책을 명시한다",
        **changes,
    }
    return harness.client.put(
        f"/api/cases/{case_id}/quality-gates/{gate}/policy", json=body
    )


def _record(
    harness,
    case_id: str,
    gate: str = "QG-06",
    subject_key: str = "case",
    findings=None,
    **extra,
):
    body = {
        "gate": gate,
        "subject_key": subject_key,
        "input_hash": "a" * 64,
        "inspection_used": "rule",
        "context_refs": ["request@1"],
        "criteria_refs": ["criterion-1"],
        "evidence_refs": [],
        "findings": findings or [],
        **extra,
    }
    return harness.client.post(
        f"/api/cases/{case_id}/quality-gate-runs", json=body
    )


def _failure():
    return [
        {
            "finding_key": "criterion-1:missing-evidence",
            "criterion": "criterion-1",
            "severity": "required",
            "certainty": "confirmed",
            "target": "result",
            "summary": "필수 기준에 연결된 실행 증거가 없다",
        }
    ]


def test_all_seven_gates_are_selected_without_collapsing_states(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"], profile="feature")

    gates = _by_gate(_state(harness, case["id"]))
    assert set(gates) == {f"QG-0{i}" for i in range(1, 8)}
    assert gates["QG-01"]["setting"] == "required"
    assert gates["QG-01"]["latest_run"]["legacy_qg01"] is True
    assert gates["QG-06"]["setting"] == "on"
    assert gates["QG-06"]["latest_run"] is None  # ON은 통과가 아니다
    assert gates["QG-07"]["setting"] == "not_applicable"


def test_qg01_cannot_be_turned_off_or_weakened(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])

    response = _set(harness, case["id"], "QG-01", setting="off")
    assert response.status_code == 409
    assert "cannot be turned off" in response.json()["detail"]

    _set(harness, case["id"], "QG-01", setting="inherit", inspection="independent")
    response = _set(harness, case["id"], "QG-01", setting="inherit", inspection="light")
    assert response.status_code == 409
    assert "cannot lower" in response.json()["detail"]


def test_task_policy_overrides_case_policy_without_touching_its_sibling(harness):
    case = _graph_case(harness)
    assert _set(harness, case["id"], "QG-04", setting="off").status_code == 200
    assert (
        _set(harness, case["id"], "QG-04", task_key="T2", setting="on").status_code
        == 200
    )

    case_gate = _by_gate(_state(harness, case["id"]))["QG-04"]
    t1_gate = _by_gate(_state(harness, case["id"], "T1"))["QG-04"]
    t2_gate = _by_gate(_state(harness, case["id"], "T2"))["QG-04"]
    assert case_gate["setting"] == "off"
    assert t1_gate["setting"] == "off"
    assert t2_gate["setting"] == "on"
    assert t2_gate["source"] == "task_explicit"


def test_off_not_applicable_not_run_and_pass_are_different(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"], profile="feature")
    assert _set(harness, case["id"], "QG-04", setting="off").status_code == 200

    gates = _by_gate(_state(harness, case["id"]))
    assert gates["QG-04"]["setting"] == "off"
    assert gates["QG-04"]["latest_run"] is None
    assert gates["QG-07"]["setting"] == "not_applicable"
    assert gates["QG-06"]["setting"] == "on"
    assert gates["QG-06"]["latest_run"] is None

    passed = _record(harness, case["id"])
    assert passed.status_code == 201, passed.text
    assert passed.json()["verdict"] == "pass"
    assert _by_gate(_state(harness, case["id"]))["QG-06"]["latest_run"]["verdict"] == "pass"


def test_an_explicit_gate_is_a_condition_not_just_a_record(harness):
    case, _intent = _agreed_case(harness)
    assert harness.ai_prepare(case["id"], "design").status_code == 201
    assert _set(harness, case["id"], "QG-02", setting="on").status_code == 200

    refused = harness.ai_prepare(case["id"], "plan", run_id="plan-before-qg02")
    assert refused.status_code == 409
    assert "quality_gate_not_passed" in _refusals(refused)

    passed = _record(harness, case["id"], gate="QG-02", subject_key="case")
    assert passed.status_code == 201, passed.text
    assert harness.ai_prepare(case["id"], "plan", run_id="plan-after-qg02").status_code == 201


def test_an_independent_review_needs_a_reviewer_run_and_a_separate_session(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"], profile="research")
    assert _set(
        harness, case["id"], "QG-07", setting="on", inspection="independent"
    ).status_code == 200

    instruction = harness.submit_artifact(case["id"], "연구 결론을 검토한다")
    author = harness.create_run(
        case["id"], instruction["artifact_id"], "quality-author",
        purpose="limited_analysis", role="author", tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE,
    )
    harness.agent.poll_once()
    reviewer = harness.create_run(
        case["id"], instruction["artifact_id"], "quality-reviewer",
        purpose="quality_gate_review", role="reviewer", tool_id=FAKE_TOOL_ID,
        mode=FAKE_TOOL_MODE,
    )
    unfinished = _record(
        harness, case["id"], gate="QG-07", subject_key="research-conclusion",
        inspection_used="independent", author_run_id=author["run"]["run_id"],
        reviewer_run_id=reviewer["run"]["run_id"], evidence_refs=["experiment@1"],
    )
    assert unfinished.status_code == 409
    assert "reviewer run is not successfully completed" in unfinished.json()["detail"]

    harness.agent.poll_once()
    reviewer_state = harness.client.get(
        f"/api/runs/{reviewer['run']['run_id']}"
    ).json()
    assert reviewer_state["status"] == "finished"
    assert reviewer_state["outcome"] == "completed"
    assert reviewer_state["purpose"] == "quality_gate_review"

    missing = _record(
        harness, case["id"], gate="QG-07", subject_key="research-conclusion",
        inspection_used="independent", author_run_id=author["run"]["run_id"],
        evidence_refs=["experiment@1"],
    )
    assert missing.status_code == 409
    assert "reviewer run" in missing.json()["detail"]

    accepted = _record(
        harness, case["id"], gate="QG-07", subject_key="research-conclusion",
        inspection_used="independent", author_run_id=author["run"]["run_id"],
        reviewer_run_id=reviewer["run"]["run_id"], evidence_refs=["experiment@1"],
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["reviewer_session_ref"] != accepted.json()["author_session_ref"]


def test_ai_opinion_without_a_known_criterion_cannot_create_a_required_failure(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = _record(
        harness,
        case["id"],
        findings=[
            {
                "finding_key": "new-rule",
                "criterion": "reviewer-invented-rule",
                "severity": "required",
                "certainty": "confirmed",
                "summary": "원래 기준에 없는 의견",
            }
        ],
    )
    assert response.status_code == 201
    body = response.json()
    assert body["verdict"] == "pass"
    assert body["findings"][0]["severity"] == "advisory"
    assert body["findings"][0]["blocking"] == 0


def test_initial_failure_then_two_repairs_and_no_third(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    failed = _record(harness, case["id"], findings=_failure())
    assert failed.status_code == 201
    assert failed.json()["verdict"] == "fail"

    url = f"/api/cases/{case['id']}/quality-gates/QG-06/remediation/case"
    cycle = harness.client.get(url).json()
    assert cycle["used_attempts"] == 0
    assert cycle["repair_limit"] == 2

    for number in (1, 2):
        started = harness.client.post(
            f"{url}/attempts",
            json={"kind": "product_repair", "task_key": f"split-{number}",
                  "session_ref": f"new-session-{number}"},
        )
        assert started.status_code == 201, started.text
        attempt = started.json()["attempts"][-1]
        assert attempt["repair_no"] == number
        completed = harness.client.post(
            f"/api/remediation-attempts/{attempt['id']}/complete",
            json={"outcome": "still_failed"},
        )
        assert completed.status_code == 200

    refused = harness.client.post(
        f"{url}/attempts", json={"kind": "product_repair", "task_key": "split-3"}
    )
    assert refused.status_code == 409
    assert "repair limit exhausted" in refused.json()["detail"]
    cycle = harness.client.get(url).json()
    assert cycle["used_attempts"] == 2
    assert cycle["state"] == "exhausted"

    # 추가 시도는 "continue"가 아니라 명시적 한도 변경으로만 열린다. 사용량은
    # 0으로 돌아가지 않는다.
    changed = _set(harness, case["id"], "QG-06", setting="on", repair_limit=3)
    assert changed.status_code == 200
    cycle = harness.client.get(url).json()
    assert cycle["used_attempts"] == 2
    assert cycle["repair_limit"] == 3
    assert cycle["state"] == "active"
    third = harness.client.post(
        f"{url}/attempts", json={"kind": "product_repair", "task_key": "split-4"}
    )
    assert third.status_code == 201
    assert third.json()["attempts"][-1]["repair_no"] == 3


def test_environment_recovery_and_gate_toggles_do_not_reset_or_consume_repairs(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _record(harness, case["id"], findings=_failure())
    url = f"/api/cases/{case['id']}/quality-gates/QG-06/remediation/case"

    environment = harness.client.post(
        f"{url}/attempts", json={"kind": "environment_recovery", "session_ref": "env-2"}
    )
    assert environment.status_code == 201
    attempt = environment.json()["attempts"][-1]
    harness.client.post(
        f"/api/remediation-attempts/{attempt['id']}/complete",
        json={"outcome": "service_restored"},
    )
    assert harness.client.get(url).json()["used_attempts"] == 0

    assert _set(harness, case["id"], "QG-06", setting="off").status_code == 200
    assert _set(harness, case["id"], "QG-06", setting="on").status_code == 200
    cycle = harness.client.get(url).json()
    assert cycle["used_attempts"] == 0
    assert len(cycle["attempts"]) == 1


def test_new_quality_tables_keep_references_and_short_summaries_not_bodies(harness):
    conn = harness.client.app.state.conn
    names = {
        "quality_gate_policy",
        "quality_gate_run",
        "quality_gate_finding",
        "remediation_cycle",
        "remediation_attempt",
    }
    for name in names:
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name = ?", (name,)
        ).fetchone()["sql"].lower()
        columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({name})")}
        assert not ({"body", "content", "diff", "log"} & columns)
        if name in {"quality_gate_policy", "quality_gate_finding"}:
            assert "length(" in sql

    project = harness.create_project("body-boundary")
    case = harness.create_case(project["id"])
    response = _record(
        harness,
        case["id"],
        context_refs=["BODY-MARKER-" + "x" * 200],
    )
    assert response.status_code == 409
    assert "reference identifiers, not bodies" in response.json()["detail"]
    assert conn.execute("SELECT COUNT(*) FROM quality_gate_run").fetchone()[0] == 0

    response = _record(
        harness,
        case["id"],
        findings=[
            {
                **_failure()[0],
                "evidence_artifact_id": "BODY-MARKER-" + "x" * 200,
            }
        ],
    )
    assert response.status_code == 409
    assert "evidence_artifact_id" in response.json()["detail"]
    assert conn.execute("SELECT COUNT(*) FROM quality_gate_run").fetchone()[0] == 0


def test_gate_policy_failure_and_repair_survive_a_reopened_database(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    assert _set(
        harness, case["id"], "QG-06", setting="on", repair_limit=3
    ).status_code == 200
    _record(harness, case["id"], findings=_failure())
    url = f"/api/cases/{case['id']}/quality-gates/QG-06/remediation/case"
    started = harness.client.post(f"{url}/attempts", json={"kind": "product_repair"})
    attempt = started.json()["attempts"][-1]
    harness.client.post(
        f"/api/remediation-attempts/{attempt['id']}/complete",
        json={"outcome": "still_failed"},
    )

    reopened = db.connect(harness.controller_config.db_path)
    try:
        db.migrate(reopened)
        repo = Repository(reopened)
        policy = repo.effective_quality_gate_policy(case["id"], GateId.QG_06)
        cycle = repo.remediation_state(case["id"], GateId.QG_06, "case")
        assert policy["setting"] == "on"
        assert policy["latest_run"]["verdict"] == "fail"
        assert cycle["repair_limit"] == 3
        assert cycle["used_attempts"] == 1
        assert cycle["attempts"][0]["outcome"] == "still_failed"
    finally:
        reopened.close()
