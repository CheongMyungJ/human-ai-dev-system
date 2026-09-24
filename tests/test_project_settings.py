"""UI-04b — 프로젝트 기본값 층(plans/UI-PLAN-04b.md 3.1~3.4절, AC-2·3·4·9).

정책 문서(autonomy-budget-policy 5절)의 `Case 명시 → Project 기본값 → 시스템 기본값` 중 Project 층을
만든다. 설정은 **이력**이고 적용 시점은 **그 뒤에 만든 대화·실행**이다.

이 파일이 지키는 것:

    소급하지 않는다            설정 전에 만든 Case 의 정책·예산 행과 실행의 한도 기록은 그대로다
    출처를 지어내지 않는다      값이 어느 층에서 왔는지가 조회에 그대로 나타난다(`project_default`·
                               `project_setting`·`system_default`)
    설정은 권한이 아니다        진입 검사·예산 강제·확인 지점 코드는 건드리지 않는다 — 기존 시험이 그것을 본다
    지킬 수 없는 한도를 받지 않는다   강제 불가한 hard 예산 기본값은 422 이고 아무 것도 저장되지 않는다
    복귀는 새 기록이다          Autonomy 복귀는 새 리비전, 상한 복귀는 현재 행 닫기, 예산 복귀는 다시 적용

시험 이름 옆의 AC 번호는 UI-PLAN-04b 4절이다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from controller import db
from controller.db import utc_now
from domain import context as ctxmod
from domain import project_settings as ps
from tests.test_conversation import _conversation_case, _open_request
from tests.test_context import _run_view
from tests.test_work_progressor import _agree, _drive, _start

# ================================================== 순수 규칙 (domain.project_settings)


def test_setting_keys_are_checked_and_unknown_or_bad_values_are_refused():
    """AC-3 — 아는 키만, 값은 Case 설정과 같은 규칙으로(상한 0~10, 양의 한도, 강제 불가 hard 거부)."""
    assert ps.check_setting("default_autonomy", "controlled") == "controlled"
    assert ps.check_setting("repair_limit", 3) == 3
    assert ps.check_setting("task_retry_limit", 0) == 0
    assert ps.check_setting("context_inline_limit_bytes", 4096) == 4096
    assert ps.check_setting("default_tool_id", " codex ") == "codex"
    assert ps.check_setting("budget:run_count:hard", 5) == 5.0
    # 경고선은 추정 지표에도 받는다(표시일 뿐이다).
    assert ps.check_setting("budget:input_tokens:warn", 1000) == 1000.0
    bad = [
        ("default_autonomy", "fast"),
        ("repair_limit", 11),
        ("repair_limit", "2"),
        ("repair_limit", True),
        ("context_inline_limit_bytes", 0),
        ("context_inline_limit_bytes", "big"),
        ("budget:run_count:hard", 0),
        ("budget:input_tokens:hard", 5),  # 강제 불가한 정확한 hard 한도(D-61)
        ("budget:nope:hard", 1),
        ("budget:run_count", 1),
        ("whatever", 1),
        ("default_tool_id", "  "),
        ("default_tool_id", "x" * 61),
    ]
    for key, value in bad:
        with pytest.raises(ValueError):
            ps.check_setting(key, value)
    assert ps.is_known_key("budget:execution_seconds:hard")
    assert not ps.is_known_key("budget:x:y") and not ps.is_known_key("model")
    assert ps.budget_key("run_count", "hard") == "budget:run_count:hard"
    assert ps.parse_budget_key("budget:review_run_count:warn")[0].value == "review_run_count"


def test_resolve_prefers_case_then_project_then_system():
    """AC-3 — 층 합치기. 0 은 값이다(없음이 아니다)."""
    assert ps.resolve(3, 2, 1) == (3, "case_setting")
    assert ps.resolve(None, 2, 1) == (2, "project_setting")
    assert ps.resolve(None, None, 1) == (1, "system_default")
    assert ps.resolve(0, None, 1) == (0, "case_setting")
    assert ps.resolve(None, 0, 1) == (0, "project_setting")


# ================================================== 서버 — 적용 시점·우선순위·복귀


def _settings(h, project_id: str) -> dict[str, Any]:
    response = h.client.get(f"/api/projects/{project_id}/settings")
    assert response.status_code == 200, response.text
    return response.json()


def _put(h, project_id: str, values: dict[str, Any], **extra: Any):
    body = {"values": values, "set_by": "owner", **extra}
    return h.client.put(f"/api/projects/{project_id}/settings", json=body)


def _policy(h, case_id: str) -> dict[str, Any]:
    response = h.client.get(f"/api/cases/{case_id}/policy")
    assert response.status_code == 200, response.text
    return response.json()


def _limits(h, case_id: str) -> dict[str, Any]:
    return h.client.get(f"/api/cases/{case_id}/progress").json()["limits"]


def _budget_rows(h, case_id: str) -> list[tuple[str, str, float, str]]:
    state = h.client.get(f"/api/cases/{case_id}/budget").json()
    return sorted((r["metric"], r["threshold_kind"], r["limit_value"], r["set_by"]) for r in state["limits"])


def test_project_defaults_apply_to_new_conversations_and_runs_but_not_to_existing_ones(harness):
    """AC-1·2·3 — 설정 전 대화는 시스템 기본값 그대로, 설정 뒤 대화는 프로젝트 기본값(출처 `project_default`)·
    기본 예산 행(`set_by = project_default`), 그 뒤의 실행은 프로젝트 인라인 한도. 진행 상한은 조회 때 계산되므로
    Case 설정이 없는 두 대화에 모두 프로젝트 층이 보인다."""
    h = harness
    project, view = _conversation_case(h, "설정 전")
    before = view["case_id"]
    first = _open_request(h, before, "먼저 물어볼게요", "c-b0")
    h.discussion_reply(before, first["request"]["id"], "run-b0")
    h.settle(before, first["request"]["id"])

    initial = _settings(h, project["id"])
    assert initial["settings"]["default_autonomy"] == {
        "value": "ask_on_decision", "source": "system_default", "setting": None, "system_default": "ask_on_decision",
    }
    assert (initial["settings"]["repair_limit"]["value"], initial["settings"]["repair_limit"]["source"]) == (2, "system_default")
    assert initial["settings"]["context_inline_limit_bytes"]["value"] == ctxmod.DEFAULT_INLINE_LIMIT_BYTES
    assert (initial["settings"]["default_tool_id"]["value"], initial["settings"]["default_tool_id"]["source"]) == ("codex", "registration")
    assert initial["budget_defaults"] == [] and initial["history"] == []
    # 모델·깊이는 프로젝트 기본값이 없다 — 그 사실이 값이다.
    assert initial["model"]["value"] is None and "CLI" in initial["model"]["note"]
    assert initial["depth"]["value"] is None and "수준 판단" in initial["depth"]["note"]
    # 이 도구를 확인한 PC(가짜 능력 보고 — 확인됨).
    assert [(r["host"], r["state"]) for r in initial["tool_verified_on"]] == [("test-host", "verified")]

    changed = _put(
        h, project["id"],
        {"default_autonomy": "controlled", "repair_limit": 1, "context_inline_limit_bytes": 4096,
         "budget:run_count:hard": 3, "budget:input_tokens:warn": 500},
        reason_summary="시험 기본값",
    )
    assert changed.status_code == 200, changed.text
    view = changed.json()
    autonomy = view["settings"]["default_autonomy"]
    assert (autonomy["value"], autonomy["source"]) == ("controlled", "project_setting")
    assert (autonomy["setting"]["set_by"], autonomy["setting"]["reason_summary"], autonomy["setting"]["state"]) == (
        "owner", "시험 기본값", "current"
    )
    assert autonomy["setting"]["created_at"]  # 적용 시점 — 이 뒤에 만든 대화부터
    assert [(b["metric"], b["threshold_kind"], b["limit_value"], b["guarantee"]) for b in view["budget_defaults"]] == [
        ("input_tokens", "warn", 500.0, "display_only"), ("run_count", "hard", 3.0, "absolute"),
    ]
    assert [(r["setting_key"], r["value"], r["state"]) for r in view["history"]] == [
        ("default_autonomy", "controlled", "current"), ("repair_limit", 1, "current"),
        ("context_inline_limit_bytes", 4096, "current"), ("budget:run_count:hard", 3.0, "current"),
        ("budget:input_tokens:warn", 500.0, "current"),
    ]

    after = h.create_conversation(project["id"], "설정 뒤")["case_id"]
    policy_after = _policy(h, after)
    assert (policy_after["autonomy"], policy_after["autonomy_source"], policy_after["autonomy_recorded"]) == (
        "controlled", "project_default", True
    )
    assert (policy_after["effective_autonomy"], policy_after["default_autonomy"], policy_after["default_autonomy_source"]) == (
        "controlled", "controlled", "project_default"
    )
    assert _budget_rows(h, after) == [
        ("input_tokens", "warn", 500.0, "project_default"), ("run_count", "hard", 3.0, "project_default"),
    ]
    # **설정 전 대화는 그대로다** — 정책 행·예산 행에 프로젝트 기본값을 지어 넣지 않는다. 복귀하면 무엇이
    # 되는가(`default_autonomy`)만 지금의 프로젝트 기본값이다.
    policy_before = _policy(h, before)
    assert (policy_before["autonomy"], policy_before["autonomy_source"]) == ("ask_on_decision", "system_default")
    assert (policy_before["default_autonomy"], policy_before["default_autonomy_source"]) == ("controlled", "project_default")
    assert _budget_rows(h, before) == [] and h.client.get(f"/api/cases/{before}/budget").json()["unlimited"]

    # 진행 상한 — 저장된 값이 없는 두 대화 모두 프로젝트 층이 보인다(조회 때 계산).
    for case_id in (before, after):
        limits = _limits(h, case_id)
        assert (limits["repair_limit"]["value"], limits["repair_limit"]["source"], limits["repair_limit"]["setting"]) == (1, "project_setting", None)
        assert (limits["task_retry_limit"]["value"], limits["task_retry_limit"]["source"]) == (1, "system_default")
        assert limits["project_default"] == {"repair_limit": 1, "task_retry_limit": None}
        assert limits["system_default"] == {"repair_limit": 2, "task_retry_limit": 1}

    # 인라인 한도 — 설정 전의 실행 기록은 그대로, 설정 뒤의 새 실행(설정 전 대화의 것이라도)은 프로젝트 값.
    assert _run_view(h, "run-b0")["context_inline_limit"] == ctxmod.DEFAULT_INLINE_LIMIT_BYTES
    second = _open_request(h, before, "다시 물어볼게요", "c-b1")
    assert h.discussion_reply(before, second["request"]["id"], "run-b1").status_code == 201
    assert _run_view(h, "run-b1")["context_inline_limit"] == 4096
    assert _run_view(h, "run-b0")["context_inline_limit"] == ctxmod.DEFAULT_INLINE_LIMIT_BYTES

    # Case 명시가 프로젝트 층보다 앞선다 — 준 키만.
    put = h.client.put(f"/api/cases/{after}/progress/limits", json={"repair_limit": 4, "set_by": "owner"})
    assert put.status_code == 200, put.text
    limits = _limits(h, after)
    assert (limits["repair_limit"]["value"], limits["repair_limit"]["source"]) == (4, "case_setting")
    assert (limits["task_retry_limit"]["value"], limits["task_retry_limit"]["source"]) == (1, "system_default")


def test_bad_project_settings_are_refused_atomically_and_reverting_closes_the_row(harness):
    """AC-1·3 — 잘못된 키·값은 422 이고 함께 준 올바른 값도 저장되지 않는다. `null` 은 복귀(현재 행 닫힘,
    이력 보존, 시스템 기본값 유효). 도구 변경은 `project.default_tool_id` 와 이력 둘 다에 남는다."""
    h = harness
    project = h.create_project("bad-settings")
    for values in (
        {"default_autonomy": "fast"},
        {"repair_limit": 11, "default_autonomy": "controlled"},
        {"budget:input_tokens:hard": 5},
        {"budget:run_count:hard": 0},
        {"context_inline_limit_bytes": -1},
        {"model": "gpt"},
        {},
    ):
        refused = _put(h, project["id"], values)
        assert refused.status_code == 422, (values, refused.text)
    assert _settings(h, project["id"])["history"] == []

    assert _put(h, project["id"], {"default_autonomy": "controlled", "task_retry_limit": 0}).status_code == 200
    reverted = _put(h, project["id"], {"default_autonomy": None}, reason_summary="다시 기본으로").json()
    assert reverted["settings"]["default_autonomy"] == {
        "value": "ask_on_decision", "source": "system_default", "setting": None, "system_default": "ask_on_decision",
    }
    assert (reverted["settings"]["task_retry_limit"]["value"], reverted["settings"]["task_retry_limit"]["source"]) == (0, "project_setting")
    assert [(r["setting_key"], r["value"], r["state"], bool(r["superseded_at"])) for r in reverted["history"]] == [
        ("default_autonomy", "controlled", "superseded", True), ("task_retry_limit", 0, "current", False),
    ]
    # 복귀 뒤 만든 대화는 시스템 기본값이다.
    case_id = h.create_conversation(project["id"], "복귀 뒤")["case_id"]
    assert (_policy(h, case_id)["autonomy"], _policy(h, case_id)["autonomy_source"]) == ("ask_on_decision", "system_default")

    # 도구 변경 — 컬럼과 이력. 확인한 PC 가 없는 도구도 막지 않는다(진입 검사가 실행 때 본다).
    tool = _put(h, project["id"], {"default_tool_id": "claude"}).json()
    assert (tool["default_tool_id"], tool["settings"]["default_tool_id"]["source"]) == ("claude", "project_setting")
    assert h.client.get(f"/api/projects/{project['id']}").json()["default_tool_id"] == "claude"
    assert [(r["host"], r["state"]) for r in tool["tool_verified_on"]] == [("test-host", "not_reported")]
    assert h.client.put(f"/api/projects/{project['id']}/settings", json={"values": {"x": 1}, "set_by": ""}).status_code == 422
    assert h.client.get("/api/projects/nope/settings").status_code == 404


def test_a_case_returns_to_its_defaults_with_new_records_and_closed_cases_keep_the_policy_refusal(processing_harness):
    """AC-4 — Autonomy 복귀는 새 리비전(출처 = 프로젝트/시스템 기본값, 주체 사람, 이전 행 대체, 확인 지점 규칙
    그대로), 상한 복귀는 현재 행 닫기(상위 층 유효·이력 보존), 예산 복귀는 프로젝트 기본값 다시 적용. 종료 Case 는
    Autonomy·상한이 409 이고 예산은 된다(D-87)."""
    h = processing_harness
    project, case_id, _request = _start(h)
    assert _put(h, project["id"], {"default_autonomy": "controlled", "repair_limit": 0, "budget:run_count:hard": 9}).status_code == 200

    # Autonomy: 명시 → 복귀(프로젝트 기본값 controlled) → 프로젝트 기본값 지움 → 복귀(시스템 기본값).
    assert h.client.put(f"/api/cases/{case_id}/autonomy", json={"autonomy": "ask_on_decision", "set_by": "owner"}).status_code == 200
    reset = h.client.post(f"/api/cases/{case_id}/autonomy/reset", json={"set_by": "owner", "reason_summary": "기본으로"})
    assert reset.status_code == 200, reset.text
    policy = reset.json()
    assert (policy["autonomy"], policy["autonomy_source"], policy["effective_autonomy"]) == ("controlled", "project_default", "controlled")
    revisions = h.client.get(f"/api/cases/{case_id}/policy-revisions").json()
    assert [(r["revision"], r["autonomy"], r["autonomy_source"], r["set_by"], r["state"]) for r in revisions] == [
        (1, "ask_on_decision", "system_default", "system", "superseded"),
        (2, "ask_on_decision", "case_explicit", "owner", "superseded"),
        (3, "controlled", "project_default", "owner", "current"),
    ]
    assert revisions[2]["reason_summary"] == "기본으로"
    # controlled 로 돌아오면 확인 지점이 요구된다(set_autonomy 와 같은 경로).
    assert [c["state"] for c in policy["checkpoints"]] == ["required", "required"]
    assert _put(h, project["id"], {"default_autonomy": None}).status_code == 200
    policy = h.client.post(f"/api/cases/{case_id}/autonomy/reset", json={"set_by": "owner"}).json()
    assert (policy["autonomy"], policy["autonomy_source"], policy["revision"]) == ("ask_on_decision", "system_default", 4)
    assert policy["checkpoints"] == []

    # 진행 상한: Case 설정 → 복귀(닫힘) → 프로젝트 층이 유효, 이력 보존. 모르는 키는 409.
    assert h.client.put(f"/api/cases/{case_id}/progress/limits", json={"repair_limit": 5, "set_by": "owner"}).status_code == 200
    cleared = h.client.delete(f"/api/cases/{case_id}/progress/limits/repair_limit")
    assert cleared.status_code == 200, cleared.text
    limits = cleared.json()["limits"]
    assert (limits["repair_limit"]["value"], limits["repair_limit"]["source"], limits["repair_limit"]["setting"]) == (0, "project_setting", None)
    assert [(r["limit_value"], r["state"]) for r in limits["history"]] == [(5, "superseded")]
    assert h.client.delete(f"/api/cases/{case_id}/progress/limits/nope").status_code == 409
    # 이미 상위 층이면 아무 것도 하지 않는다(이력 그대로).
    assert len(h.client.delete(f"/api/cases/{case_id}/progress/limits/repair_limit").json()["limits"]["history"]) == 1

    # 예산: 업무화 전에 만든 대화라 기본 예산 행이 없다 → 다시 적용 → 사람이 바꿈 → 다시 적용(대체).
    assert _budget_rows(h, case_id) == []
    applied = h.client.post(f"/api/cases/{case_id}/budget/project-defaults", json={"set_by": "owner"})
    assert applied.status_code == 200, applied.text
    assert applied.json()["applied"] == 1
    assert _budget_rows(h, case_id) == [("run_count", "hard", 9.0, "project_default")]
    assert h.client.put(
        f"/api/cases/{case_id}/budget",
        json={"metric": "run_count", "threshold_kind": "hard", "limit_value": 20, "set_by": "owner"},
    ).status_code == 201
    assert _budget_rows(h, case_id) == [("run_count", "hard", 20.0, "owner")]
    h.client.post(f"/api/cases/{case_id}/budget/project-defaults", json={"set_by": "owner"})
    assert _budget_rows(h, case_id) == [("run_count", "hard", 9.0, "project_default")]
    history = h.client.get(f"/api/cases/{case_id}/budget").json()["history"]
    assert [(r["limit_value"], r["set_by"], r["state"]) for r in history] == [
        (9.0, "project_default", "superseded"), (20.0, "owner", "superseded"), (9.0, "project_default", "current"),
    ]

    # 종료 Case — Autonomy·상한 변경·복귀는 409, 예산 복귀는 된다.
    _drive(h, case_id)
    _agree(h, case_id)
    _drive(h, case_id)
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed"
    for call in (
        lambda: h.client.post(f"/api/cases/{case_id}/autonomy/reset", json={"set_by": "owner"}),
        lambda: h.client.delete(f"/api/cases/{case_id}/progress/limits/repair_limit"),
    ):
        refused = call()
        assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["case_already_closed"]
    assert h.client.post(f"/api/cases/{case_id}/budget/project-defaults", json={"set_by": "owner"}).status_code == 200


def test_the_project_default_budget_does_not_admit_more_than_it_says(processing_harness):
    """AC-2·10 — 프로젝트 기본 예산은 새 대화의 **실제 Case 한도**다. run_count hard 1 이면 논의 응답 하나 뒤
    다음 실행이 예산으로 거부된다(R3 의 예약·정지 그대로 — 설정이 새 강제 축을 만들지 않는다)."""
    h = processing_harness
    project = h.create_project("budget-default")
    assert _put(h, project["id"], {"budget:run_count:hard": 1}).status_code == 200
    case_id = h.create_conversation(project["id"], "한도 1")["case_id"]
    assert _budget_rows(h, case_id) == [("run_count", "hard", 1.0, "project_default")]
    h.send_message(case_id, "첫 질문", "c-1")
    h.agent.poll_once()
    conv = h.conversation(case_id)
    assert conv["requests"][0]["state"] == "completed"
    budget = h.client.get(f"/api/cases/{case_id}/budget").json()
    assert budget["stop"]["stopped"] and [m["metric"] for m in budget["stop"]["metrics"]] == ["run_count"]
    policy = _policy(h, case_id)
    assert policy["enforcement"]["budget"]["state"] == "enforced"
    # UI-04b 보충(AC-13) — 목록 행과 프로젝트 주의에 예산 도달이 실린다. 한도 없는 대화는 계산하지 않고 False 다.
    rows = {r["id"]: r for r in h.client.get(f"/api/projects/{project['id']}/conversations").json()}
    assert rows[case_id]["budget_stopped"] is True
    assert _put(h, project["id"], {"budget:run_count:hard": None}).status_code == 200
    free = h.create_conversation(project["id"], "한도 없음")["case_id"]
    rows = {r["id"]: r for r in h.client.get(f"/api/projects/{project['id']}/conversations").json()}
    assert (rows[case_id]["budget_stopped"], rows[free]["budget_stopped"]) == (True, False)
    attention = next(p for p in h.client.get("/api/projects").json() if p["id"] == project["id"])["attention"]
    assert attention["budget_stopped"] == 1
    # 한도를 올리면 풀린다 — 저장된 상태가 아니라 도출이다.
    assert h.client.put(
        f"/api/cases/{case_id}/budget",
        json={"metric": "run_count", "threshold_kind": "hard", "limit_value": 5, "set_by": "owner"},
    ).status_code == 201
    rows = {r["id"]: r for r in h.client.get(f"/api/projects/{project['id']}/conversations").json()}
    assert rows[case_id]["budget_stopped"] is False


# ================================================== 이행 v24 → v25


def test_a_v24_database_gets_no_project_setting_it_never_had(tmp_path):
    """AC-9 — v25 는 표 하나만 더한다. v24 DB(현재 이행에서 그 표를 뺀 것)를 올리면 표가 생기고 행은 없으며,
    옛 프로젝트의 조회는 시스템 기본값이다. 멱등이고 본문 컬럼이 없다."""
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    db.migrate(conn)
    conn.execute("DROP TABLE project_setting")
    conn.execute("DELETE FROM schema_version WHERE version = 25")
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (24, ?)", (utc_now(),))
    now = utc_now()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at, stage)'
        " VALUES ('case-1', 'prj-1', 'old', 'undecided', 'received', ?, ?, 'discussion')",
        (now, now),
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    db.migrate(conn)  # 멱등
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert "project_setting" in tables
    assert conn.execute("SELECT COUNT(*) AS n FROM project_setting").fetchone()["n"] == 0
    assert conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] == 25
    columns = {c["name"] for c in conn.execute('PRAGMA table_info("project_setting")')}
    assert not columns & {"content", "body", "text", "raw", "payload"}
    from controller.repository import Repository

    repo = Repository(conn)
    view = repo.project_settings_view("prj-1")
    assert view["settings"]["default_autonomy"]["source"] == "system_default" and view["history"] == []
    limits = repo.progress_limits_view("case-1")
    assert (limits["repair_limit"]["source"], limits["project_default"]) == ("system_default", {"repair_limit": None, "task_retry_limit": None})
    assert repo.effective_policy("case-1")["default_autonomy_source"] == "system_default"
    conn.close()
