"""AC-6 — 원문이 제어부에 남지 않는지 파일 바이트 수준에서 확인한다.

D-51, NFR-12, data-boundary-review.md 1·3절.

방법: 알아볼 수 있는 표식 문자열을 **본문에만** 넣어 제출한 뒤
  - 제어부 SQLite 파일(+ WAL/SHM) 전체 바이트에서 표식을 찾는다 → 없어야 한다
  - 제어부 로그 파일에서 표식을 찾는다 → 없어야 한다
  - Runner 원문 저장소에서 표식을 찾는다 → **있어야 한다**

마지막 확인이 중요하다. 셋 다 없으면 원문이 아예 저장되지 않은 것이므로
경계를 지킨 증거가 되지 않는다.
"""

from __future__ import annotations

from pathlib import Path

MARKER = "MARKER-7f3a9c-원문본문-DO-NOT-PERSIST-ON-CONTROLLER"


def _controller_bytes(harness) -> bytes:
    data = b""
    db = Path(harness.controller_config.db_path)
    for path in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        if path.exists():
            data += path.read_bytes()
    return data


def _runner_bytes(harness) -> bytes:
    data = b""
    for path in Path(harness.runner_config.data_root).rglob("*"):
        if path.is_file():
            data += path.read_bytes()
    return data


def test_raw_body_is_not_persisted_on_the_controller(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    content = f"목표: 무언가\n{MARKER}\n제약: 없음\n"

    # summary 는 호출자가 주는 짧은 표시 문구다. 본문 표식을 넣지 않는다.
    harness.submit_artifact(case["id"], content, kind="intent", summary="의도 초안 v1")

    marker = MARKER.encode("utf-8")
    assert marker not in _controller_bytes(harness), "원문이 제어부 DB에 남았다"

    log = Path(harness.controller_config.log_path)
    assert log.exists()
    assert marker not in log.read_bytes(), "원문이 제어부 로그에 남았다"

    assert marker in _runner_bytes(harness), "원문이 Runner에도 없다 — 경계 확인이 무의미하다"


def test_controller_keeps_only_the_reference_fields(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    accepted = harness.submit_artifact(case["id"], f"본문 {MARKER}", summary="지시")

    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    ref = detail["artifacts"][0]
    assert set(ref) == {
        "artifact_id",
        "revision",
        "case_id",
        "kind",
        "content_hash",
        "byte_size",
        "owner_runner_id",
        "availability",
        "summary",
        "created_at",
    }
    assert ref["content_hash"] == accepted["content_hash"]
    assert MARKER not in ref["summary"]


def test_relay_buffer_is_emptied_after_the_runner_stores_the_body(harness):
    """중계 본문은 Runner 저장 보고 직후 버린다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])

    harness.client.post(
        f"/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": f"본문 {MARKER}",
            "summary": "지시",
            "target_runner_id": harness.runner_config.runner_id,
        },
    )
    assert harness.client.get("/api/health").json()["relay_buffered"] == 1

    harness.agent.persist_pending_intakes()
    assert harness.client.get("/api/health").json()["relay_buffered"] == 0


def test_pending_intake_is_not_reported_as_saved(harness):
    """Runner가 저장하기 전에는 저장 완료가 아니다(NFR-01)."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    response = harness.client.post(
        f"/api/cases/{case['id']}/artifacts",
        json={
            "kind": "intent",
            "content": "아직 저장되지 않은 의도",
            "summary": "의도",
            "target_runner_id": harness.runner_config.runner_id,
        },
    )
    assert response.status_code == 202  # 201/200 이 아니다: 저장 완료가 아니다
    accepted = response.json()
    assert accepted["availability"] == "pending"

    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    assert detail["artifacts"][0]["availability"] == "pending"


def test_artifact_store_rejects_path_traversal(harness):
    """원문 조회를 임의 경로 열람 기능으로 만들지 않는다(NFR-12)."""
    import pytest

    for bad in ("../escape", "a/b", "C:\\Windows\\system32", ""):
        with pytest.raises(ValueError):
            harness.agent.store.put(bad, 1, b"x")


# ===================================================================== P2-02
#
# 새로 생긴 본문 경로가 세 개다. 각각 표식을 달리해 어디로 갔는지 구별한다.
#   - 의도 초안 본문(정규 문서로 묶여 중계)
#   - 피드백 본문 · 질문 답변 본문
#   - **열람**: 원문이 Runner → 제어부 메모리 → 브라우저로 한 번 더 지나간다

INTENT_MARKER = "MARKER-i1-의도본문-DO-NOT-PERSIST"
FEEDBACK_MARKER = "MARKER-f1-피드백본문-DO-NOT-PERSIST"
ANSWER_MARKER = "MARKER-a1-답변본문-DO-NOT-PERSIST"


def test_intent_feedback_answer_and_read_bodies_never_persist_on_the_controller(harness):
    """AC-9 — 의도·피드백·답변·열람 본문이 제어부에 남지 않는다.

    열람까지 수행하는 것이 중요하다. 열람은 본문이 제어부를 **한 번 더** 지나는
    경로이고, 그 때 DB나 로그에 흘리기 가장 쉽다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])

    accepted = harness.submit_intent_draft(
        case["id"],
        {
            "goal": {
                "text": f"목표 본문 {INTENT_MARKER}",
                "state": "proposed",
                "origin": "user_requirement",
            }
        },
        questions=[
            {
                "key": "q1",
                "text": f"질문 본문 {INTENT_MARKER}-q",
                "summary": "행 범위 결정",
                "decide_at": "intent",
            }
        ],
        summary="의도 초안 v1",
    )
    intent = harness.latest_intent(case["id"])

    harness.submit_feedback(
        case["id"], intent["id"], f"피드백 본문 {FEEDBACK_MARKER}", summary="피드백"
    )
    question = intent["questions"][0]
    harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={
            "content": f"답변 본문 {ANSWER_MARKER}",
            "summary": "답변",
            "target_runner_id": "runner-test-1",
        },
    )
    harness.agent.persist_pending_intakes()

    # 열람 한 바퀴 — 본문이 제어부를 한 번 더 지난다.
    _request, content = harness.read_original(accepted["artifact_id"], accepted["revision"])
    assert content is not None and INTENT_MARKER in content

    controller_bytes = _controller_bytes(harness)
    log_bytes = Path(harness.controller_config.log_path).read_bytes()
    runner_bytes = _runner_bytes(harness)

    for marker in (INTENT_MARKER, FEEDBACK_MARKER, ANSWER_MARKER):
        raw = marker.encode("utf-8")
        assert raw not in controller_bytes, f"{marker} 가 제어부 DB에 남았다"
        assert raw not in log_bytes, f"{marker} 가 제어부 로그에 남았다"
        # 셋 다 없으면 애초에 저장되지 않은 것이므로 경계 확인이 무의미하다.
        assert raw in runner_bytes, f"{marker} 가 Runner에도 없다"

    # 질문 요약은 제어부에 있어도 되지만(intent-artifacts 3절) 본문 표식은 아니다.
    stored_question = harness.latest_intent(case["id"])["questions"][0]
    assert stored_question["summary"]
    assert INTENT_MARKER not in stored_question["summary"]


def test_new_p2_02_tables_have_no_body_columns(harness):
    """상태 표에 본문 컬럼이 생기지 않았는지 스키마로 확인한다.

    "요약 컬럼에 본문을 밀어 넣는" 우회를 막기 위해 길이 제한도 함께 본다.
    """
    import sqlite3

    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    body_like = {"content", "body", "text", "raw", "payload", "content_text", "full_text"}
    for table in (
        "intent_field",
        "intent_question",
        "feedback",
        "intent_view",
        "artifact_read_request",
    ):
        columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        assert columns, f"{table} 이 없다"
        assert not (columns & body_like), f"{table} 에 본문 컬럼이 있다: {columns & body_like}"

    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name IN ('intent_question','feedback')"
    ).fetchall()
    for row in sql:
        assert "length(summary) <= 200" in row["sql"]
    conn.close()


def test_the_controller_never_parses_the_intent_document(harness):
    """제어부는 의도 본문을 **해석하지 않는다.**

    항목별 상태는 Runner의 보고로만 들어온다. Runner가 보고하기 전에는
    제어부가 본문을 갖고 있었더라도 항목 상태를 만들어 내지 못한다.
    이것이 "제어부는 compose 만 하고 parse/structure 는 부르지 않는다"의 관측 가능한 형태다.
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(
        case["id"],
        {"goal": {"text": "목표", "state": "proposed", "origin": "user_requirement"}},
        persist=False,  # Runner가 저장·보고하지 않은 상태
    )
    intent = harness.latest_intent(case["id"])
    assert intent["fields"] == [], "제어부가 본문에서 항목을 만들어 냈다"
    assert intent["questions"] == []
    assert intent["availability"] == "pending"
