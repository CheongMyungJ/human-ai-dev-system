"""P4-02 — 실행 중 설정 변경의 예약, 변경 영향과 부분 재검증, 늦은 결과."""

from __future__ import annotations

from controller import db
from controller.repository import Repository
from domain.models import GateId
from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE
from tests.test_preparation import _agreed_case, _refusals
from tests.test_quality_gates import _by_gate, _failure, _record, _set, _state
from tests.test_work_graph import _graph_case


def _open(harness, case_id: str, gate: str = "QG-06", subject_key: str = "case", **extra):
    body = {
        "gate": gate,
        "subject_key": subject_key,
        "input_hash": "a" * 64,
        "context_refs": ["request@1"],
        "criteria_refs": ["criterion-1"],
        **extra,
    }
    return harness.client.post(f"/api/cases/{case_id}/quality-gate-runs/open", json=body)


def _complete(harness, gate_run_id: str, findings=None, **extra):
    body = {
        "inspection_used": "rule",
        "evidence_refs": [],
        "findings": findings or [],
        **extra,
    }
    return harness.client.post(
        f"/api/quality-gate-runs/{gate_run_id}/complete", json=body
    )


def _change(harness, case_id: str, kind: str, change_ref: str, changed_refs, **extra):
    body = {
        "kind": kind,
        "change_ref": change_ref,
        "changed_refs": changed_refs,
        "summary": "변경 사실을 기록한다",
        "actor": "owner",
        **extra,
    }
    return harness.client.post(
        f"/api/cases/{case_id}/quality-change-events", json=body
    )


def _gate(harness, case_id: str, gate: str = "QG-06", task_key: str = "") -> dict:
    return _by_gate(_state(harness, case_id, task_key))[gate]


# ------------------------------------------------------------------ AC-1·AC-4


def test_a_change_with_no_verification_running_applies_at_once(harness):
    """AC-1·AC-4: 진행 중 검증이 없으면 즉시 적용되고 요청·적용 시각이 남는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])

    assert _set(harness, case["id"], "QG-06", setting="off").status_code == 200
    policy = _gate(harness, case["id"])

    assert policy["setting"] == "off"
    assert policy["apply_boundary"] == "immediate"
    assert policy["applied_at"] is not None
    assert policy["requested_at"] == policy["applied_at"]
    assert policy["reserved"] == []


# ------------------------------------------------------------ AC-2·AC-3·AC-4


def test_a_change_during_a_verification_is_reserved_and_changes_nothing_yet(harness):
    """AC-2·AC-3: 진행 중이면 예약되고 현재 정책·진행 중 검사가 그대로다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    opened = _open(harness, case["id"])
    assert opened.status_code == 201, opened.text
    run = opened.json()
    assert run["status"] == "running"
    assert run["verdict"] == "not_run"

    assert _set(harness, case["id"], "QG-06", setting="off").status_code == 200
    policy = _gate(harness, case["id"])

    # 현재 정책은 바뀌지 않았다.
    assert policy["setting"] == "on"
    assert policy["applied"] is True
    assert policy["policy_revision"] == 0
    # 예약은 따로 보인다. 둘을 합치지 않는다.
    assert len(policy["reserved"]) == 1
    reserved = policy["reserved"][0]
    assert reserved["setting"] == "off"
    assert reserved["apply_boundary"] == "verification_end"
    assert reserved["apply_after_run_id"] == run["id"]
    assert reserved["requested_by"] == "owner"
    assert policy["running_gate_run_id"] == run["id"]

    # 진행 중 검사는 중단되지도, 무효화되지도 않았다.
    still = harness.client.get(f"/api/cases/{case['id']}/quality-gates").json()
    running = _by_gate(still)["QG-06"]["latest_run"]
    assert running["status"] == "running"
    assert running["validity"] == "current"


# ----------------------------------------------------------------- AC-5·AC-6


def test_the_reservation_lands_when_the_verification_ends_even_on_a_failure(harness):
    """AC-5·AC-6: 실패 판정에서도 예약이 반영되고, OFF 뒤 새 repair 는 거부된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    run = _open(harness, case["id"]).json()
    _set(harness, case["id"], "QG-06", setting="off")

    done = _complete(harness, run["id"], findings=_failure())
    assert done.status_code == 200, done.text
    result = done.json()

    # 1) 현재 결과가 먼저 보존된다. 실패는 실패로 남는다.
    assert result["verdict"] == "fail"
    assert result["status"] == "completed"
    assert result["late_result"] is False
    assert result["validity"] == "current"

    # 2) 그 다음 예약이 반영된다 — 게이트 통과만 기다리는 순환을 만들지 않는다.
    policy = _gate(harness, case["id"])
    assert policy["setting"] == "off"
    assert policy["applied"] is False
    assert policy["apply_boundary"] == "verification_end"
    assert policy["applied_at"] is not None
    assert policy["applied_at"] != policy["requested_at"]
    assert policy["reserved"] == []

    # 3) 실패와 발견, 그리고 수정 주기는 그대로 있다.
    url = f"/api/cases/{case['id']}/quality-gates/QG-06/remediation/case"
    cycle = harness.client.get(url).json()
    assert cycle["used_attempts"] == 0
    assert len(result["findings"]) == 1

    # 4) 그러나 그 게이트만을 위한 새 수정 차수는 배정되지 않는다.
    refused = harness.client.post(f"{url}/attempts", json={"kind": "product_repair"})
    assert refused.status_code == 409
    assert "the gate is off" in refused.json()["detail"]
    # 환경 복구는 게이트 전용 작업이 아니므로 막지 않는다.
    env = harness.client.post(
        f"{url}/attempts", json={"kind": "environment_recovery"}
    )
    assert env.status_code == 201
    assert harness.client.get(url).json()["used_attempts"] == 0


# ---------------------------------------------------------------------- AC-7


def test_toggling_a_gate_off_and_on_reuses_the_existing_pass(harness):
    """AC-7: 토글은 유효한 통과를 지우지 않고 재실행을 요구하지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    passed = _record(harness, case["id"])
    assert passed.json()["verdict"] == "pass"

    assert _set(harness, case["id"], "QG-06", setting="off").status_code == 200
    assert _set(harness, case["id"], "QG-06", setting="on").status_code == 200

    policy = _gate(harness, case["id"])
    assert policy["setting"] == "on"
    latest = policy["latest_run"]
    assert latest["verdict"] == "pass"
    # **재실행 요구가 생기지 않았다.** 검사의 내용·범위가 그대로이기 때문이다.
    assert latest["validity"] == "current"


# ---------------------------------------------------------------------- AC-8


def test_only_a_stronger_inspection_sends_a_verdict_back_for_recheck(harness):
    """AC-8: 검사 강도 변경만 판정을 내린다. 한도 변경은 내리지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _record(harness, case["id"])

    assert _set(harness, case["id"], "QG-06", repair_limit=3).status_code == 200
    assert _gate(harness, case["id"])["latest_run"]["validity"] == "current"

    assert (
        _set(harness, case["id"], "QG-06", inspection="independent").status_code == 200
    )
    policy = _gate(harness, case["id"])
    assert policy["inspection_required"] == "independent"
    assert policy["latest_run"]["validity"] == "needs_recheck"
    # 판정 자체는 지워지지 않는다. 무엇을 보았는지가 남는다.
    assert policy["latest_run"]["verdict"] == "pass"
    assert policy["latest_run"]["inspection_used"] == "rule"


# ---------------------------------------------------------------------- AC-9


def test_a_reservation_does_not_spread_to_other_tasks_or_the_case(harness):
    """AC-9: Task 범위 예약이 다른 Task 와 Case 전체를 건드리지 않는다."""
    case = _graph_case(harness)
    tasks = harness.work_graph(case["id"])["graph"]["tasks"]
    first, second = tasks[0]["task_key"], tasks[1]["task_key"]

    assert _set(
        harness, case["id"], "QG-04", setting="on", task_key=first
    ).status_code == 200
    run = _open(harness, case["id"], gate="QG-04", subject_key="bundle", task_key=first)
    assert run.status_code == 201, run.text
    assert _set(
        harness, case["id"], "QG-04", setting="off", task_key=first
    ).status_code == 200

    scoped = _gate(harness, case["id"], "QG-04", first)
    assert len(scoped["reserved"]) == 1
    # 다른 Task 와 Case 전체에는 예약이 없다.
    assert _gate(harness, case["id"], "QG-04", second)["reserved"] == []
    assert _gate(harness, case["id"], "QG-04")["reserved"] == []


# --------------------------------------------------------------------- AC-10


def test_a_reservation_can_be_cancelled_and_an_applied_policy_is_not_rolled_back(harness):
    """AC-10: 예약 취소는 기록으로 남고, 이미 적용된 정책은 되돌리지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    run = _open(harness, case["id"]).json()
    _set(harness, case["id"], "QG-06", setting="off")

    cancelled = harness.client.post(
        f"/api/cases/{case['id']}/quality-gates/QG-06/policy/cancel-reservation",
        json={"actor": "owner", "reason_summary": "다시 생각해 보니 유지한다"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["reserved"] == []

    _complete(harness, run["id"])
    policy = _gate(harness, case["id"])
    assert policy["setting"] == "on"  # 취소된 예약은 반영되지 않았다

    row = harness.client.app.state.conn.execute(
        "SELECT state, cancelled_by, cancel_reason FROM quality_gate_policy"
        " WHERE case_id = ? AND gate = 'QG-06'",
        (case["id"],),
    ).fetchone()
    assert row["state"] == "cancelled"
    assert row["cancelled_by"] == "owner"
    assert row["cancel_reason"]

    # 이미 적용된 정책은 취소 대상이 아니다.
    assert _set(harness, case["id"], "QG-06", setting="off").status_code == 200
    again = harness.client.post(
        f"/api/cases/{case['id']}/quality-gates/QG-06/policy/cancel-reservation",
        json={"actor": "owner", "reason_summary": "적용된 것도 지워 달라"},
    )
    assert again.status_code == 404
    assert _gate(harness, case["id"])["setting"] == "off"


# -------------------------------------------------------------- AC-11·AC-12


def test_a_request_change_only_touches_the_checks_that_used_it(harness):
    """AC-11: 바뀐 기준을 입력으로 가진 검사만 재검증 대상이 된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    linked = _record(harness, case["id"], criteria_refs=["criterion-1"]).json()
    other = _record(
        harness,
        case["id"],
        gate="QG-06",
        subject_key="second",
        criteria_refs=["criterion-9"],
    ).json()

    event = _change(harness, case["id"], "request", "intent@2", ["criterion-1"])
    assert event.status_code == 201, event.text
    decisions = {d["gate_run_id"]: d for d in event.json()["decisions"]}

    assert decisions[linked["id"]]["decision"] == "revalidate"
    assert decisions[other["id"]]["decision"] == "reuse"
    # 재사용에도 이유와 참조 버전이 남는다.
    assert decisions[other["id"]]["reason"]
    assert decisions[other["id"]]["referenced_version"] == "a" * 64

    conn = harness.client.app.state.conn
    validity = dict(
        conn.execute(
            "SELECT id, validity FROM quality_gate_run WHERE case_id = ?", (case["id"],)
        ).fetchall()[0]
    )
    assert validity["validity"] in {"current", "needs_recheck"}
    rows = {
        r["id"]: r["validity"]
        for r in conn.execute(
            "SELECT id, validity FROM quality_gate_run WHERE case_id = ?", (case["id"],)
        )
    }
    assert rows[linked["id"]] == "needs_recheck"
    assert rows[other["id"]] == "current"


def test_a_code_change_leaves_evidence_from_other_repositories_alone(harness):
    """AC-12: 그 저장소를 입력으로 본 검사만 대상이 된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    api = _record(
        harness, case["id"], subject_key="api", context_refs=["repo:api@abc123"]
    ).json()
    web = _record(
        harness, case["id"], subject_key="web", context_refs=["repo:web@def456"]
    ).json()

    event = _change(harness, case["id"], "code", "repo:api", ["repo:api@abc123"])
    decisions = {d["gate_run_id"]: d for d in event.json()["decisions"]}
    assert decisions[api["id"]]["decision"] == "revalidate"
    assert decisions[web["id"]]["decision"] == "reuse"


# --------------------------------------------------------------------- AC-13


def test_an_unknown_scope_is_not_recorded_as_unaffected(harness):
    """AC-13: 범위를 모르면 재사용으로 추측하지 않고 `unknown` 으로 남는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    run = _record(harness, case["id"]).json()

    event = _change(
        harness, case["id"], "code", "repo:api", [], scope_known=False
    )
    assert event.status_code == 201
    decision = event.json()["decisions"][0]
    assert decision["decision"] == "unknown"
    assert decision["gate_run_id"] == run["id"]

    # `unknown` 은 재검증 대상이다 — 확인하지 못한 것을 통과로 두지 않는다.
    assert _gate(harness, case["id"])["latest_run"]["validity"] == "needs_recheck"


def test_a_change_asks_a_running_verification_to_stop_instead_of_voiding_it(harness):
    """진행 중 검사는 무효화할 판정이 없다. 취소를 **요청**하고 결과는 보존한다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    run = _open(harness, case["id"]).json()

    _change(harness, case["id"], "request", "intent@2", ["criterion-1"])
    row = harness.client.app.state.conn.execute(
        "SELECT status, stop_requested_at, stop_reason FROM quality_gate_run WHERE id = ?",
        (run["id"],),
    ).fetchone()
    # 상태는 여전히 running 이다. 취소 요청과 실제 종료를 구분한다.
    assert row["status"] == "running"
    assert row["stop_requested_at"] is not None
    assert row["stop_reason"]


# --------------------------------------------------------------------- AC-14


def test_a_permission_change_blocks_the_next_assignment_without_waiting(harness):
    """AC-14: 권한 변경은 검증 종료를 기다리지 않고 기존 판정도 되돌리지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    running = _open(harness, case["id"]).json()
    passed = _record(
        harness,
        case["id"],
        subject_key="scoped",
        criteria_refs=["criterion-write-allowance"],
    ).json()

    event = _change(
        harness,
        case["id"],
        "permission",
        "grant@2",
        ["criterion-write-allowance"],
    )
    assert event.status_code == 201

    conn = harness.client.app.state.conn
    # 게이트 예약과 달리 **바로** 반영됐다. 진행 중 검증을 기다리지 않았다.
    assert conn.execute(
        "SELECT validity FROM quality_gate_run WHERE id = ?", (passed["id"],)
    ).fetchone()["validity"] == "needs_recheck"
    # 그러나 판정 자체는 그대로다 — 되돌리지 않는다.
    assert conn.execute(
        "SELECT verdict FROM quality_gate_run WHERE id = ?", (passed["id"],)
    ).fetchone()["verdict"] == "pass"
    # 진행 중 실행도 취소되지 않았고 상태가 바뀌지 않았다.
    assert conn.execute(
        "SELECT status FROM quality_gate_run WHERE id = ?", (running["id"],)
    ).fetchone()["status"] == "running"


# --------------------------------------------------------------------- AC-15


def test_an_old_assignment_request_does_not_start_after_the_policy_moved(harness):
    """AC-15: 저장과 배정 사이 정책이 바뀌면 옛 요청으로 시작하지 않는다."""
    case, _intent = _agreed_case(harness)
    assert _set(harness, case["id"], "QG-02", setting="on").status_code == 200
    expected = _gate(harness, case["id"], "QG-02")["policy_revision"]
    assert expected == 1
    # 명시 ON 게이트를 통과시켜 두어 이 거부가 **통과 여부와 다른 사유**임을 본다.
    assert _record(harness, case["id"], gate="QG-02").status_code == 201

    # 그 사이 검사 강도가 올라갔다.
    assert _set(
        harness, case["id"], "QG-02", setting="on", inspection="independent"
    ).status_code == 200

    instruction = harness.submit_artifact(
        case["id"], "설계를 작성해 주세요.", kind="instruction", summary="설계 작성 요청"
    )
    refused = harness.client.post(
        f"/api/cases/{case['id']}/runs",
        json={
            "run_id": "run-stale-policy",
            "instruction_artifact_id": instruction["artifact_id"],
            "purpose": "design_authoring",
            "role": "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "read_only",
            "expected_gate_policy": {"QG-02": expected},
        },
    )
    assert refused.status_code == 409, refused.text
    assert "quality_gate_policy_changed" in _refusals(refused)


def test_a_reservation_alone_is_not_an_assignment_refusal(harness):
    """예약은 차단이 아니다. 현재 정책을 바꾸지 않으므로 배정을 막지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    _open(harness, case["id"])
    _set(harness, case["id"], "QG-06", setting="off")

    repo = Repository(harness.client.app.state.conn)
    assert repo.quality_gate_policy_drift(case["id"], {"QG-06": 0}) == []


# -------------------------------------------------------------- AC-16·AC-17


def test_a_late_result_stays_with_its_own_run_and_starts_nothing(harness):
    """AC-16·AC-17: 늦은 결과는 원래 실행에 남고 새 repair·통과를 만들지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    run = _open(harness, case["id"]).json()
    stop = harness.client.post(
        f"/api/quality-gate-runs/{run['id']}/stop-request",
        json={"actor": "owner", "reason_summary": "대상이 바뀌어 중지를 요청한다"},
    )
    assert stop.status_code == 200
    assert stop.json()["status"] == "running"  # 요청이지 종료가 아니다

    late = _complete(harness, run["id"], findings=_failure())
    assert late.status_code == 200, late.text
    result = late.json()

    assert result["verdict"] == "fail"  # 결과는 버리지 않는다
    assert result["late_result"] is True
    assert result["validity"] == "historical"
    assert result["late_reason"]

    # 늦은 실패가 수정 주기를 만들지 않는다.
    url = f"/api/cases/{case['id']}/quality-gates/QG-06/remediation/case"
    assert harness.client.get(url).status_code == 404


def test_a_pass_arriving_after_the_gate_went_off_is_not_the_current_pass(harness):
    """AC-17: OFF 로 바뀐 뒤 도착한 통과는 현재 정책의 통과가 아니다.

    두 대상의 검증이 함께 돌 때 자연히 생긴다. 예약은 **먼저 연 검증**에 붙고,
    그것이 끝나면서 OFF 가 반영된다. 뒤늦게 끝난 쪽의 통과는 이미 OFF 가 된
    정책의 통과로 쓰일 수 없다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    first = _open(harness, case["id"], subject_key="first").json()
    second = _open(harness, case["id"], subject_key="second").json()

    assert _set(harness, case["id"], "QG-06", setting="off").status_code == 200
    assert _gate(harness, case["id"])["reserved"][0]["apply_after_run_id"] == first["id"]

    assert _complete(harness, first["id"]).json()["late_result"] is False
    assert _gate(harness, case["id"])["applied"] is False

    late = _complete(harness, second["id"])
    assert late.status_code == 200, late.text
    assert late.json()["verdict"] == "pass"
    assert late.json()["late_result"] is True
    assert late.json()["validity"] == "historical"
    assert "적용되지 않는" in late.json()["late_reason"]


# --------------------------------------------------------------------- AC-18


def test_an_unaffected_gate_keeps_its_evidence_and_stays_open(harness):
    """AC-18: 영향 없는 검사는 유효한 채로 남고 의존 작업이 멈추지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    untouched = _record(
        harness, case["id"], subject_key="other", context_refs=["repo:web@1"]
    ).json()

    _change(harness, case["id"], "code", "repo:api", ["repo:api@2"])
    row = harness.client.app.state.conn.execute(
        "SELECT validity FROM quality_gate_run WHERE id = ?", (untouched["id"],)
    ).fetchone()
    assert row["validity"] == "current"


# --------------------------------------------------------------------- AC-19


def test_reservations_and_late_results_survive_a_reopened_database(harness, tmp_path):
    """AC-19: 예약·적용 시각·재검증 판정·늦은 결과가 재시작 뒤 복원된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    run = _open(harness, case["id"]).json()
    _set(harness, case["id"], "QG-06", setting="off")
    _change(harness, case["id"], "request", "intent@2", ["criterion-1"])

    harness.client.app.state.conn.close()

    conn = db.connect(harness.controller_config.db_path)
    db.migrate(conn)
    repo = Repository(conn)
    policy = repo.effective_quality_gate_policy(case["id"], GateId.QG_06)
    assert len(policy["reserved"]) == 1
    assert policy["reserved"][0]["apply_after_run_id"] == run["id"]
    assert policy["applied"] is True

    events = repo.list_quality_change_events(case["id"])
    assert len(events) == 1
    assert events[0]["decisions"]

    closed = repo.complete_quality_gate_run(
        run["id"], inspection_used="rule", evidence_refs=[], findings=[]
    )
    assert closed["late_result"] is True  # 취소 요청이 있었다
    assert repo.effective_quality_gate_policy(case["id"], GateId.QG_06)["setting"] == "off"
    conn.close()


# --------------------------------------------------------------------- AC-21


def test_the_new_tables_keep_references_and_short_summaries_not_bodies(harness):
    """AC-21 데이터 경계: 새 두 표에 본문 컬럼이 없고 길이 제한이 있다."""
    conn = harness.client.app.state.conn
    for table in ("quality_change_event", "quality_revalidation"):
        sql = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()["sql"]
        assert "CHECK (length(" in sql
        columns = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        assert not (columns & {"body", "content", "diff", "log", "original_text"})

    project = harness.create_project()
    case = harness.create_case(project["id"])
    _record(harness, case["id"])
    too_long = _change(harness, case["id"], "code", "repo:a", ["x" * 200])
    assert too_long.status_code == 409
    with_newline = _change(harness, case["id"], "code", "repo:a", ["one\ntwo"])
    assert with_newline.status_code == 409


def test_a_closed_case_does_not_get_its_evidence_reopened(harness):
    """종료 후 수정은 연결된 새 Case 다. 닫힌 Case 의 판정을 지금 와서 내리지 않는다."""
    case, _intent = _agreed_case(harness)
    # 기본 ask-on-decision 은 조건을 갖추면 **사람 인수 기록 없이** 스스로 닫는다
    # (D-31). 그래서 여기서 인수를 만들지 않는다 — 없는 확인을 적지 않는다.
    harness.mark_all_criteria_met(case["id"])
    assert harness.client.get(f"/api/cases/{case['id']}").json()["status"] == "closed"

    refused = _change(harness, case["id"], "code", "repo:api", ["repo:api@2"])
    assert refused.status_code == 409
    assert "case_already_closed" in refused.json()["detail"]
