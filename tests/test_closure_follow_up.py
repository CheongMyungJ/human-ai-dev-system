"""P4-05 — 완료 후 설명(D-87)과 후속 Case(D-33·D-78)(plans/P4-PLAN-05.md AC-15·16·18).

종료된 업무의 대화는 **설명 전용**으로 열린다: 일반 메시지에 읽기 전용 설명 응답이 붙고, 그
소비는 같은 Case 예산에 누적되되 종료 시점 snapshot 과 나뉜다. 다른 실행·정책 변경은 그대로
거부된다. 응답의 해석이 수정 요청이면 그 메시지가 **연결된 새 대화**로 옮겨져 처음부터 잇는다.
"""

from __future__ import annotations

import sqlite3
import subprocess
from typing import Any

import pytest

from controller import db
from controller.db import utc_now
from controller.repository import Repository
from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE, RUNNER_ID
from tests.test_migration import REPO_ROOT, _committed_schema
from tests.test_work_progressor import WORK_BLOCK, _agree, _drive, _runs, _start

DISCUSSION_BLOCK = '```hads-interpretation\n{"kind": "discussion"}\n```'


def _closed_case(h) -> tuple[str, str]:
    """진행기로 끝까지 간 종료 Case. 반환: (case_id, 업무 요청의 request_id)."""
    _project, case_id, request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    _drive(h, case_id)
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed"
    return case_id, request_id


# ================================================== AC-15 설명 전용 진입


def test_a_closed_case_answers_explanations_and_counts_them_after_the_closure(processing_harness):
    """AC-15 — 종료 Case 의 일반 메시지는 설명 응답을 받는다. 소비는 종료 뒤로 나뉘고 판정은 불변이다."""
    h = processing_harness
    case_id, _request_id = _closed_case(h)
    conv = h.conversation(case_id)
    assert conv["send"]["general"] == {
        **conv["send"]["general"],
        "allowed": True,
        "refusal": None,
        "note": "explanation_only",
    }
    assert conv["send"]["card_answer"]["allowed"] is False
    before = h.client.get(f"/api/cases/{case_id}/budget").json()
    assert before["at_closure"] is not None
    assert before["since_closure"]["run_count"] == 0
    closure_before = h.client.get(f"/api/cases/{case_id}").json()["result"]["closure"]

    h.agent.cli_executor.discussion_response = f"C-01 은 표본 시험으로 확인했습니다.\n{DISCUSSION_BLOCK}"
    h.agent.cli_executor.usage = {"input_tokens": 5, "output_tokens": 3}
    h.send_message(case_id, "C-01 은 어떻게 확인한 거야?", "x-1")
    h.agent.poll_once()
    conv = h.conversation(case_id)
    reply_request = next(r for r in conv["requests"] if r["opened_by_message_id"] == conv["messages"][-2]["id"])
    assert (reply_request["state"], reply_request["settled_by"]) == ("completed", "request-processor")
    assert conv["messages"][-1]["author"] == "assistant"
    prompt = h.agent.cli_executor.calls[-1]["prompt"]
    assert "이미 종료됐다" in prompt and "hads-interpretation" in prompt
    [interp] = [i for i in conv["interpretations"] if i["run_id"] == reply_request["runs"][0]["run_id"]]
    assert (interp["kind"], interp["applied"], interp["refusal"]) == ("discussion", False, "not_a_work_request")
    # 소비는 같은 Case 에 누적되고 종료 뒤 소비로 구분된다. 종료 기록은 그대로다.
    after = h.client.get(f"/api/cases/{case_id}/budget").json()
    assert after["since_closure"]["run_count"] == 1
    assert after["at_closure"] == before["at_closure"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "closed" and case["result"]["closure"] == closure_before
    assert conv["progress"]["state"] == "done"  # 설명은 진행을 다시 열지 않는다
    assert conv["relations"] == []


def test_a_closed_case_still_refuses_work_runs_and_policy_changes_but_takes_a_budget_change(processing_harness):
    """AC-15 — 설명 전용이다. 다른 실행·정책 변경은 종료 거부 그대로이고, 예산 한도만 이력으로 받는다."""
    h = processing_harness
    case_id, _request_id = _closed_case(h)
    # 접수 경로도 종료 guard 그대로다 — 지시는 이미 있는 원문(업무 요청 메시지)을 쓴다.
    intake = h.client.post(
        f"/api/cases/{case_id}/artifacts",
        json={"kind": "instruction", "content": "다시 구현", "summary": "재개 시도",
              "target_runner_id": RUNNER_ID},
    )
    assert intake.status_code == 409, intake.text
    opening = h.conversation(case_id)["messages"][0]
    refused = h.client.post(
        f"/api/cases/{case_id}/runs",
        json={
            "run_id": "run-after-close", "instruction_artifact_id": opening["artifact_id"],
            "instruction_artifact_rev": opening["artifact_rev"],
            "purpose": "limited_analysis", "role": "author", "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE, "permission": "read_only",
        },
    )
    assert refused.status_code == 409 and "case_already_closed" in refused.text
    autonomy = h.client.put(
        f"/api/cases/{case_id}/autonomy",
        json={"autonomy": "controlled", "set_by": "owner", "reason_summary": "x"},
    )
    assert autonomy.status_code == 409
    # 예산 한도는 종료 뒤에도 바꿀 수 있다(D-87). 이력이 남고 종료 기록·판정은 그대로다.
    changed = h.client.put(
        f"/api/cases/{case_id}/budget",
        json={"metric": "run_count", "threshold_kind": "hard", "limit_value": 50, "set_by": "owner",
              "reason_summary": "설명 여유"},
    )
    assert changed.status_code == 201, changed.text
    budget = changed.json()
    assert [c["metric"] for c in budget["changes_after_closure"]] == ["run_count"]
    assert budget["at_closure"]["limits"] == []
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed"


# ================================================== AC-16 후속 Case


def test_a_change_request_after_the_closure_moves_to_a_linked_new_conversation(processing_harness):
    """AC-16 — 종료 Case 의 수정 요청을 AI 가 업무 요청으로 읽으면 연결된 새 대화로 옮겨 처음부터 잇는다."""
    h = processing_harness
    case_id, _request_id = _closed_case(h)
    executor = h.agent.cli_executor
    executor.discussion_response = f"새 업무로 옮깁니다.\n{WORK_BLOCK.format(profile='feature')}"
    h.send_message(case_id, "선택한 열만 내보내는 기능도 추가해줘", "x-2")
    h.agent.poll_once()  # 설명 응답 → 해석(업무 요청) → 새 대화 → 새 대화의 응답 실행 생성
    conv = h.conversation(case_id)
    [relation] = conv["relations"]
    assert relation["direction"] == "successor" and relation["relation"] == "follow_up_change"
    new_id = relation["case_id"]
    interp = conv["interpretations"][-1]
    assert (interp["kind"], interp["applied"]) == ("work_request", True)
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed"

    new_conv = h.conversation(new_id)
    assert new_conv["stage"] == "discussion"  # 이전 동의·Profile·권한을 승계하지 않는다
    moved = new_conv["messages"][0]
    original = conv["messages"][-2]
    assert (moved["artifact_id"], moved["artifact_rev"], moved["receipt"]) == (
        original["artifact_id"], original["artifact_rev"], "stored"
    )
    assert new_conv["relations"][0]["direction"] == "predecessor"
    policy = h.client.get(f"/api/cases/{new_id}/policy").json()
    assert policy["delegation_basis"]["current"] is None
    # 새 대화의 요청에 처리기가 응답을 만들었고, 그 해석으로 새 Case 가 업무화된다.
    executor.discussion_response = f"정리합니다.\n{WORK_BLOCK.format(profile='feature')}"
    h.agent.poll_once()
    new_conv = h.conversation(new_id)
    assert new_conv["stage"] == "work" and new_conv["profile"] == "feature"
    assert new_conv["work_start"]["request_message_id"] == moved["id"]
    assert new_conv["progress"]["state"] == "running"
    assert all(r["case_id"] == new_id for r in _runs(h, new_id))


# ================================================== AC-18 이행 v19 → v20


def _v19_schema() -> str:
    log = subprocess.run(
        ["git", "log", "--format=%H", "-30", "--", "controller/schema.sql"],
        cwd=REPO_ROOT, capture_output=True,
    )
    if log.returncode != 0:
        pytest.skip("git 이력을 읽을 수 없다")
    for commit in log.stdout.decode("utf-8").split():
        schema = _committed_schema(commit)
        if "스키마 v19" in schema and "스키마 v20" not in schema:
            return schema
    pytest.skip("v19 스키마를 가진 커밋을 찾지 못했다")


def test_a_v19_database_gets_no_progress_it_never_had(tmp_path):
    """AC-18 — v19 → v20. 요청 표 재구성이 행·색인을 보존하고 옛 요청은 `user_message` 다.

    커밋된 v19 스키마로 실제 DB 를 만들어(**그때의 DDL 그대로**) 지금 이행 코드로 올린다. 진행
    표는 비어 있고, 옛 종료에 snapshot 을 지어내지 않으며, 반복 이행이 멱등이다.
    """
    committed = _v19_schema()
    assert "case_progress" not in committed and "opened_by_message_id TEXT NOT NULL" in committed
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    conn.executescript(committed)
    now = utc_now()
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (19, ?)", (now,))
    conn.execute("PRAGMA foreign_keys = OFF")
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
    conn.execute(
        "INSERT INTO runner (id, name, host, status, registered_at, last_heartbeat_at)"
        " VALUES ('runner-1','old','old-host','registered',?,?)", (now, now)
    )
    conn.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, owner_runner_id,"
        " content_hash, byte_size, summary, availability, created_at)"
        " VALUES ('art-msg',1,'case-1','message','runner-1','h',10,'s','available',?)", (now,)
    )
    conn.execute(
        "INSERT INTO intake (id, case_id, kind, artifact_id, revision, target_runner_id, state,"
        " expected_hash, byte_size, summary, created_at, stored_at)"
        " VALUES ('int-1','case-1','message','art-msg',1,'runner-1','stored','h',10,'s',?,?)",
        (now, now),
    )
    conn.execute(
        "INSERT INTO conversation_request (id, case_id, opened_by_message_id, state, opened_at,"
        " settled_at, settled_by, outcome_reason)"
        " VALUES ('req-1','case-1','msg-1','completed',?,?,'request-processor','settled')",
        (now, now),
    )
    conn.execute(
        "INSERT INTO conversation_message (id, case_id, seq, author, message_kind, actor,"
        " client_message_id, artifact_id, artifact_rev, content_hash, intake_id, request_id,"
        " summary, created_at) VALUES ('msg-1','case-1',1,'user','general','owner','c-1',"
        " 'art-msg',1,'h','int-1','req-1','사용자 메시지 · 3자',?)",
        (now,),
    )
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    # v21(P4-05b) 이후에도 이 이행의 사실은 같다 — 판의 고정은 각 판의 이행 시험이 한다.
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 20
    assert db.SCHEMA_VERSION >= 20
    request = conn.execute("SELECT * FROM conversation_request WHERE id = 'req-1'").fetchone()
    assert (request["state"], request["origin"], request["origin_ref"], request["opened_by_message_id"]) == (
        "completed", "user_message", None, "msg-1"
    )
    indexes = {r["name"] for r in conn.execute("PRAGMA index_list(conversation_request)")}
    assert "uq_conversation_request_active" in indexes
    assert conn.execute("SELECT COUNT(*) FROM case_progress").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM case_progress_event").fetchone()[0] == 0
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(run)")}
    assert "criteria_report_json" in columns
    assert "snapshot_json" in {r["name"] for r in conn.execute("PRAGMA table_info(closure_record)")}
    # 진행 요청(여는 메시지 없음)이 들어가고, 모르는 출처는 들어가지 않는다.
    conn.execute(
        "INSERT INTO conversation_request (id, case_id, opened_by_message_id, origin, origin_ref,"
        " state, opened_at) VALUES ('req-2','case-1',NULL,'human_decision','dec-1','processing',?)",
        (now,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO conversation_request (id, case_id, opened_by_message_id, origin, state,"
            " opened_at) VALUES ('req-3','case-1',NULL,'robot','completed',?)",
            (now,),
        )
    view = Repository(conn).conversation_view("case-1")
    assert view["progress"] is None and view["relations"] == []
    assert view["current_request"]["origin"] == "human_decision"
    assert view["current_request"]["opening_receipt"] == "stored"
    db.migrate(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,)
    ).fetchone()[0] == 1
    conn.close()
