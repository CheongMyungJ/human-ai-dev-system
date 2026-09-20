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
