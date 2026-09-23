"""P4-06b — 지식 원문의 서버 저장(plans/P4-PLAN-06b.md, 사용자 결정 2026-09-24 · D-67 보충).

P4-06 은 지식 원문을 소유 PC 에만 두었고, 그래서 다른 PC 의 실행은 다른 PC 에서 등록한 필수 규칙을 읽지
못해 보류됐다. 사용자 결정으로 **지식만** 원문 PC 경계의 예외가 됐다 — 적용 내용과 자동 등록 규칙의 권위
사용자 메시지 한 건을 서버에 저장하고, 배정에 본문을 실어 어느 PC 의 실행에도 주입한다.

이 파일이 지키는 것:

    두 PC                    PC A 에서 등록한 규칙이 PC B 의 실행에 원문으로 들어간다(영수증 `read`)
    소유 PC 미연결           PC A 가 끊겨도 PC B 의 실행은 시작된다(진입 검사·영수증 모두)
    해시가 맞을 때만          서버 본문이 참조의 해시와 다르면 읽지 못한 것이다 — 자기 저장소로 대신하지 않는다
    서버 본문은 한 표에만     지식 표식·권위 메시지 표식은 `knowledge_body` 에만 있고 로그·다른 표에는 없다
    다른 원문은 그대로        같은 대화의 다른 메시지·응답 본문은 여전히 서버에 없다
    이행은 지어내지 않는다    옛 지식(PC 에만)은 소유 PC 가 연결될 때 올라오고 그 전에는 `runner` 다

P4-06 시험(`tests/test_knowledge.py`)에서 바뀐 단언: AC-15 "서버 DB 에 원문 없음" → "`knowledge_body` 에만
있고 로그에 없음"; AC-6 의 "Runner 파일 삭제" → "서버 본문 삭제"(같은 의미), "저장 전 `pending`" 하위 사례 →
"바로 `available`"(서버 저장에는 저장 보고가 없다). 검사를 지우지 않았다.
"""

from __future__ import annotations

import base64
import sqlite3
from pathlib import Path
from typing import Any

from controller import db
from controller.relay import content_hash
from controller.repository import Repository
from tests.conftest import FAKE_COMBINED_VERIFIED, FAKE_PLAN_VERIFIED, HARNESS_RUNNER_STALE_SECONDS, RUNNER_ID
from tests.test_knowledge import (
    MARK,
    RULE_ITEM,
    _knowledge_reply,
    _manifest,
    _prompt,
    _register,
    _repo,
    _runs,
    forget_server_body,
    marker_tables,
)
from tests.test_work_progressor import WORK_BLOCK, _agree, _drive

RUNNER_B = "runner-test-2"
WORDS = "USER-WORDS-4e2b"


# ---------------------------------------------------------------- 도우미


def _send_as(h, agent, case_id: str, text: str, client_id: str) -> dict[str, Any]:
    """그 PC 를 출처로 메시지를 보내고 그 PC 가 저장할 때까지 진행한다."""
    response = h.post_message(case_id, text, client_id, target_runner_id=agent.config.runner_id)
    assert response.status_code == 202, response.text
    agent.persist_pending_intakes()
    found = h.client.get(f"/api/cases/{case_id}/messages/by-client-id/{client_id}").json()
    assert found["receipt"] == "stored", found
    return found["message"]


def _start_work_on(h, agent, project: dict[str, Any], text: str = "오류 줄 필터를 구현해줘") -> str:
    """그 PC 에서 대화 → 업무 요청 → 업무화(첫 걸음까지). `h.agent` 를 그 PC 로 바꿔 둔다."""
    h.agent = agent
    case_id = h.create_conversation(project["id"], "필터 기능")["case_id"]
    executor = agent.cli_executor
    executor.discussion_response = f"알겠습니다.\n\n{WORK_BLOCK.format(profile='feature')}"
    executor.combined_response = FAKE_COMBINED_VERIFIED
    executor.plan_response = FAKE_PLAN_VERIFIED
    executor.write_files = {"reader.py": "def read(path):\n    return [l for l in open(path) if l.startswith('ERROR')]\n"}
    executor.residual_activity = "none"
    executor.residual_basis = "in_process"
    _send_as(h, agent, case_id, text, f"c-{case_id[-6:]}")
    agent.poll_once()
    return case_id


def _bodies(h) -> list[dict[str, Any]]:
    conn = sqlite3.connect(h.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute("SELECT * FROM knowledge_body ORDER BY stored_at").fetchall()]
    finally:
        conn.close()


def _say_rule(h, project: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """PC A 의 대화에서 규칙을 말해 자동 등록시킨다. (대화 id, 응답 실행)"""
    talk = h.create_conversation(project["id"], "규칙 이야기")["case_id"]
    h.agent.cli_executor.discussion_response = _knowledge_reply([RULE_ITEM])
    h.send_message(talk, f"이 프로젝트에서는 앞으로 오류 로그에 시각을 붙이지 마. {WORDS}", "c-rule")
    h.agent.poll_once()
    reply = next(r for r in _runs(h, talk) if r["purpose"] == "discussion_reply")
    assert reply["outcome"] == "completed", reply
    return talk, reply


# ================================================== AC-2·3·4·10·14 두 PC


def test_a_rule_from_one_pc_reaches_work_on_another_pc_even_while_the_first_is_disconnected(processing_harness):
    """AC-2·3·4·10·14 — PC A 의 대화에서 자동 등록된 필수 규칙(옮긴 글 + 권위 메시지)이 서버에 저장되고,
    PC A 가 끊긴 뒤에도 PC B 의 업무 실행 전부에 원문으로 들어간다(영수증 `read`, 지시문·Manifest).
    표식은 DB 의 `knowledge_body` 에만 있고 로그·PC B 저장소에는 없다. 다른 원문의 경계는 그대로다.
    """
    h = processing_harness
    project, _path = h.create_git_project("kn-two-pcs")
    a = h.agent
    talk, reply = _say_rule(h, project)
    other_marker = "OTHER-MSG-9d7c"
    h.send_message(talk, f"그냥 물어볼게. 표식 {other_marker}", "c-other")
    h.agent.cli_executor.discussion_response = "답입니다."
    h.agent.poll_once()

    # AC-2 — Runner 가 결과 전에 올린 두 본문: 옮긴 글(knowledge)과 그 응답의 지시 원문(권위 메시지).
    rows = _bodies(h)
    assert sorted(r["purpose"] for r in rows) == ["authority_message", "knowledge"]
    version = h.client.get(f"/api/projects/{project['id']}/knowledge").json()["items"][0]["current"]
    assert (version["storage"], version["source_storage"]) == ("server", "server")
    by_key = {(r["artifact_id"], r["revision"]): r for r in rows}
    assert by_key[(version["artifact_id"], version["artifact_rev"])]["purpose"] == "knowledge"
    message = next(m for m in h.conversation(talk)["messages"] if m["id"] == version["source_message_id"])
    assert by_key[(message["artifact_id"], message["artifact_rev"])]["purpose"] == "authority_message"
    for ref in rows:
        registered = h.client.get(f"/api/cases/{talk}").json()["artifacts"]
        hash_of = {(x["artifact_id"], x["revision"]): x["content_hash"] for x in registered}
        assert hash_of[(ref["artifact_id"], ref["revision"])] == ref["content_hash"] == content_hash(ref["body"])
    # 새 지식 원문은 PC A 저장소에 가지 않는다(집은 서버). 권위 메시지는 원래 PC A 의 메시지다.
    assert not any(MARK.encode("utf-8") in p.read_bytes() for p in a.store.root.rglob("*.bin"))
    # AC-10 — 표식은 `knowledge_body` 에만. 보고(`run.knowledge_report_json`)·버전·접수에는 없다. 로그에도 없다.
    db_path = Path(h.controller_config.db_path)
    assert marker_tables(db_path, MARK) == {"knowledge_body"}
    assert marker_tables(db_path, WORDS) == {"knowledge_body"}
    assert marker_tables(db_path, other_marker) == set()  # 같은 대화의 다른 말은 여전히 서버에 없다
    log = Path(h.controller_config.log_path).read_bytes()
    for marker in (MARK, WORDS, other_marker):
        assert marker.encode("utf-8") not in log, marker
    assert MARK not in (h.client.get(f"/api/runs/{reply['run_id']}").json().get("knowledge_report_json") or "")

    # PC A 가 끊긴다. PC B 가 같은 Project 의 다른 대화에서 업무를 한다.
    b = h.second_runner(RUNNER_B)
    h.age_heartbeat(HARNESS_RUNNER_STALE_SECONDS * 2, RUNNER_ID)
    assert h.client.get("/api/runners").json()[0]["connection"]["state"] != "connected"
    work = _start_work_on(h, b, project)
    _drive(h, work)
    _agree(h, work)
    _drive(h, work)
    case = h.client.get(f"/api/cases/{work}").json()
    assert case["status"] == "closed", case["result"]
    assert case["result"]["closure"]["closure_kind"] == "completed"
    # AC-14 — 기준은 검증 실행의 보고로 적혔다. 주입이 판정을 만들지 않는다.
    assert all(c["recorded_by"] == "policy:work_progressor" for c in h.criteria(work))

    runs = _runs(h, work)
    work_runs = [r for r in runs if r["purpose"] in (
        "intent_authoring", "plan_authoring", "feature_implementation", "verification_run"
    )]
    assert {r["purpose"] for r in work_runs} == {
        "intent_authoring", "plan_authoring", "feature_implementation", "verification_run"
    }
    for run in work_runs:
        assert run["assigned_runner_id"] == RUNNER_B
        refs = h.context_refs(run["run_id"])
        roles = [r["role"] for r in refs]
        assert roles[-2:] == ["knowledge_required", "knowledge_source"], (run["purpose"], roles)
        for ref in refs[-2:]:
            assert (ref["tier"], ref["receipt_status"], ref["body_source"]) == ("core", "read", "server"), ref
        assert refs[-2]["knowledge"]["key"] == "K-001"
        prompt = _prompt(h, run["run_id"])
        assert MARK in prompt and WORDS in prompt and "권위 원문" in prompt
        assert run["context"]["state"] == "complete"
        manifest = _manifest(h, run["run_id"])
        assert [(i["knowledge_key"], i["decision"]) for i in manifest["items"]] == [("K-001", "provided")]
        assert manifest["items"][0]["source_seq"] == len(refs)
    # AC-3 — PC B 의 저장소에는 그 원문이 없다. 서버가 배정에 실어 준 것이다.
    assert not any(MARK.encode("utf-8") in p.read_bytes() for p in b.store.root.rglob("*.bin"))
    assert not any(WORDS.encode("utf-8") in p.read_bytes() for p in b.store.root.rglob("*.bin"))
    # PC B 의 업무 원문(의도·응답)은 여전히 서버에 없다 — 다른 원문의 경계는 그대로다.
    assert marker_tables(db_path, "오류 줄 필터를 구현해줘") == set()


# ================================================== AC-1·6·9 수동 등록·열람·거부


def test_manual_registration_stores_on_the_server_without_the_pc_and_reads_come_from_the_server(processing_harness):
    """AC-1·6·9 — 수동 등록은 중계 없이 서버에 저장된다(접수 행 없음, 바로 `available`). 소유 PC 가
    끊겨 있어도 등록된다. 열람은 Runner 없이 서버가 바로 채운다. 4,000 자 초과는 422. Runner 끝점은
    해시 불일치·다른 종류·소유 아님을 거부한다.
    """
    h = processing_harness
    project = h.create_project("kn-manual")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    h.send_message(rules, "출처가 될 말", "c-src")
    intakes = h.intake_count()
    h.age_heartbeat(HARNESS_RUNNER_STALE_SECONDS * 2, RUNNER_ID)
    assert h.client.get("/api/runners").json()[0]["connection"]["state"] != "connected"

    version = _register(h, rules, f"{MARK} 서버에 바로 저장되는 규칙", "서버 규칙", persist=False)
    assert (version["state"], version["storage"], version["source_storage"]) == ("active", "server", None)
    assert h.intake_count() == intakes
    artifact = next(
        a for a in h.client.get(f"/api/cases/{rules}").json()["artifacts"]
        if a["artifact_id"] == version["artifact_id"]
    )
    assert (artifact["kind"], artifact["availability"], artifact["owner_runner_id"]) == (
        "knowledge", "available", RUNNER_ID
    )
    [row] = _bodies(h)
    assert row["content_hash"] == artifact["content_hash"] and row["purpose"] == "knowledge"
    assert marker_tables(Path(h.controller_config.db_path), MARK) == {"knowledge_body"}

    # AC-6 — 열람: Runner 가 돌지 않아도 서버가 채운다. 해시가 맞는다.
    request, body = h.read_original(version["artifact_id"], version["artifact_rev"], serve=False)
    assert body is not None and MARK in body
    assert request["state"] == "delivered" and request["content_hash"] == artifact["content_hash"]
    assert h.client.get(f"/api/runner/{RUNNER_ID}/read-requests").json() == []

    # AC-9 — 상한과 거부.
    too_long = h.client.post(
        f"/api/cases/{rules}/knowledge",
        json={"content": "x" * 4001, "summary": "너무 김", "kind": "constraint", "obligation": "required",
              "target_runner_id": RUNNER_ID},
    )
    assert too_long.status_code == 422
    body_bytes = "다른 내용".encode("utf-8")
    payload = {
        "runner_id": RUNNER_ID, "case_id": rules, "kind": "knowledge", "artifact_id": "art-new-1",
        "revision": 1, "content_b64": base64.b64encode(body_bytes).decode("ascii"),
        "content_hash": "sha256:" + "0" * 64, "summary": "s",
    }
    assert h.client.post("/api/runner/knowledge-originals", json=payload).status_code == 409
    payload["content_hash"] = content_hash(body_bytes)
    payload["kind"] = "intent"
    assert h.client.post("/api/runner/knowledge-originals", json=payload).status_code == 409
    payload["kind"] = "knowledge"
    payload["artifact_id"] = version["artifact_id"]  # 이미 다른 해시로 등록된 참조
    assert h.client.post("/api/runner/knowledge-originals", json=payload).status_code == 409
    # 권위 메시지는 소유 Runner 만, 사용자 메시지만, 같은 해시만.
    message = next(m for m in h.conversation(rules)["messages"] if m["author"] == "user")
    original = h.agent.store.get(message["artifact_id"], message["artifact_rev"])
    b = h.second_runner(RUNNER_B)
    refused = h.client.post(
        "/api/runner/knowledge-originals",
        json={"runner_id": b.config.runner_id, "case_id": rules, "kind": "message",
              "artifact_id": message["artifact_id"], "revision": message["artifact_rev"],
              "content_b64": base64.b64encode(original).decode("ascii"), "content_hash": content_hash(original)},
    )
    assert refused.status_code == 409 and "owning runner" in refused.text
    assert len(_bodies(h)) == 1


# ================================================== AC-5 해시 대조


def test_a_server_body_is_used_only_when_its_hash_matches(processing_harness):
    """AC-5 — 서버 본문이 참조의 해시와 다르면 Runner 는 `hash_mismatch` 로 시작하지 않는다 — 이 PC 에
    같은 원문의 사본이 있어도 그것으로 대신하지 않는다. 서버 본문이 없고 이 PC 에도 없으면 `missing`.
    """
    h = processing_harness
    project = h.create_project("kn-hash")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    version = _register(h, rules, "오류 줄은 그대로 둔다", "원문 유지", activities=["discussion"])
    correct = _repo(h).knowledge_body_for(version["artifact_id"], version["artifact_rev"])["body"]
    # 이 PC 에 올바른 사본을 둔다 — 그래도 서버가 준 다른 본문을 사본으로 대신하지 않아야 한다.
    h.agent.store.put(version["artifact_id"], version["artifact_rev"], correct)
    tampered = correct[:-3] + b"XYZ"
    assert len(tampered) == len(correct)
    h.client.app.state.conn.execute(
        "UPDATE knowledge_body SET body = ? WHERE artifact_id = ? AND revision = ?",
        (sqlite3.Binary(tampered), version["artifact_id"], version["artifact_rev"]),
    )
    talk = h.create_conversation(project["id"], "대화")["case_id"]
    h.send_message(talk, "질문", "c-1")
    h.agent.poll_once()
    [reply] = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"]
    assert (reply["outcome"], reply["not_started_reason"]) == ("failed", "required_context_unavailable")
    assert not any(c["run_id"] == reply["run_id"] for c in h.agent.cli_executor.calls)
    [ref] = [r for r in h.context_refs(reply["run_id"]) if r["role"] == "knowledge_required"]
    assert (ref["receipt_status"], ref["body_source"]) == ("hash_mismatch", "server")

    # 서버 본문이 없어지면 소유 PC 의 사본(해시가 맞는)이 다음 제어 루프에서 **다시 올라간다**(이행 경로) —
    # 그 다음 실행은 되돌아온 서버 본문을 읽는다. 변조된 본문은 그대로 있으므로 올리지 않았다(위).
    forget_server_body(h, version["artifact_id"], version["artifact_rev"])
    h.send_message(talk, "다시 질문", "c-2")
    tick = h.agent.poll_once()
    second = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"][-1]
    assert second["outcome"] == "completed"
    [ref] = [r for r in h.context_refs(second["run_id"]) if r["role"] == "knowledge_required"]
    assert (ref["receipt_status"], ref["body_source"]) == ("read", "server")
    restored = _repo(h).knowledge_body_for(version["artifact_id"], version["artifact_rev"])
    assert restored["body"] == correct and restored["stored_by"] == f"runner:{RUNNER_ID}"
    assert tick["assignments"] and len(h.agent.control_tick()["uploaded_knowledge"]) == 0
    # 서버 본문도 사본도 없으면 읽지 못한 것이다 — 지어내지 않는다.
    forget_server_body(h, version["artifact_id"], version["artifact_rev"])
    h.agent.store._path(version["artifact_id"], version["artifact_rev"]).unlink()
    h.send_message(talk, "또 질문", "c-3")
    h.agent.poll_once()
    third = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"][-1]
    assert (third["outcome"], third["not_started_reason"]) == ("failed", "required_context_unavailable")
    [ref] = [r for r in h.context_refs(third["run_id"]) if r["role"] == "knowledge_required"]
    assert (ref["receipt_status"], ref["body_source"]) == ("missing", "runner")


# ================================================== AC-7 이행(PC 에만 있던 옛 원문)


def test_old_knowledge_held_only_by_the_owning_pc_is_uploaded_when_that_pc_connects(processing_harness):
    """AC-7 — v22 방식(원문이 소유 PC 에만)의 지식은 `storage = runner` 이고 다른 PC 는 읽지 못한다
    (P4-06 그대로). 소유 PC 가 돌면 서버가 청한 것을 올리고, 그 뒤 다른 PC 의 실행이 읽는다. 출처
    메시지를 준 수동 등록의 권위 메시지도 같은 길로 온다.
    """
    h = processing_harness
    project = h.create_project("kn-migrate")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    said = _send_as(h, h.agent, rules, f"앞으로 로그 줄을 정규화하지 마. {WORDS}", "c-said")
    # P4-06 방식으로 원문을 PC A 에만 둔다(접수 경로) — 서버 본문 없이 버전을 만든다.
    accepted = h.submit_artifact(rules, f"{MARK} 로그 줄은 정규화하지 않는다", kind="knowledge", summary="옛 원문")
    old = _repo(h).register_knowledge(
        rules, artifact_id=accepted["artifact_id"], artifact_rev=accepted["revision"], kind="constraint",
        obligation="required", summary="정규화 금지", created_by="owner", activities=["discussion"],
        source_message_id=said["id"],
    )
    assert (old["storage"], old["source_storage"]) == ("runner", "runner")
    wanted = h.client.get(f"/api/runner/{RUNNER_ID}/knowledge-uploads").json()
    assert sorted((w["kind"], w["artifact_id"]) for w in wanted) == sorted(
        [("knowledge", accepted["artifact_id"]), ("message", said["artifact_id"])]
    )
    assert all("content_b64" not in w and "body" not in w for w in wanted)
    assert h.client.get(f"/api/runner/{RUNNER_B}/knowledge-uploads").status_code == 404

    # 다른 PC 는 아직 읽지 못한다(P4-06 그대로).
    b = h.second_runner(RUNNER_B)
    talk = h.create_conversation(project["id"], "대화")["case_id"]
    _send_as(h, b, talk, "질문", "c-1")
    b.poll_once()
    [reply] = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"]
    assert (reply["outcome"], reply["not_started_reason"]) == ("failed", "required_context_unavailable")
    [ref] = [r for r in h.context_refs(reply["run_id"]) if r["role"] == "knowledge_required"]
    assert (ref["receipt_status"], ref["body_source"]) == ("missing", "runner")

    # 소유 PC 가 돌면 올린다. 그 뒤 다른 PC 가 읽는다.
    tick = h.agent.poll_once()
    assert len(h.agent.control_tick()["uploaded_knowledge"]) == 0  # 두 번째는 올릴 것이 없다
    rows = _bodies(h)
    assert sorted(r["purpose"] for r in rows) == ["authority_message", "knowledge"]
    assert all(r["stored_by"] == f"runner:{RUNNER_ID}" for r in rows)
    current = h.client.get(f"/api/projects/{project['id']}/knowledge").json()["items"][0]["current"]
    assert (current["storage"], current["source_storage"]) == ("server", "server")
    assert h.client.get(f"/api/runner/{RUNNER_ID}/knowledge-uploads").json() == []
    _send_as(h, b, talk, "다시 질문", "c-2")
    b.poll_once()
    second = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"][-1]
    assert second["outcome"] == "completed"
    refs = [r for r in h.context_refs(second["run_id"]) if r["role"].startswith("knowledge_")]
    assert [(r["role"], r["receipt_status"], r["body_source"]) for r in refs] == [
        ("knowledge_required", "read", "server"), ("knowledge_source", "read", "server")
    ]
    prompt = next(c["prompt"] for c in b.cli_executor.calls if c["run_id"] == second["run_id"])
    assert MARK in prompt and WORDS in prompt
    assert tick["stored_intakes"] == []


# ================================================== AC-8 권위 메시지 정리


def test_the_authority_message_is_kept_only_when_something_was_registered(harness):
    """AC-8 — Runner 는 등록 블록이 있는 응답의 지시 원문(사용자 메시지)을 함께 올린다. 처리기가 그
    보고에서 하나도 등록하지 못하면 그 메시지 본문을 지우고, 하나라도 등록하면 남긴다. 거부된 항목의
    지식 원문은 남는다(P4-06 에서 Runner 에 남던 것과 같다).
    """
    h = harness
    project, _path = h.create_git_project("kn-authority")
    talk = h.create_conversation(project["id"], "대화")["case_id"]
    h.agent.cli_executor.discussion_response = _knowledge_reply([dict(RULE_ITEM, repository="nope")])
    h.send_message(talk, f"앞으로 이렇게 해 {WORDS}", "c-1")
    h.agent.persist_pending_intakes()
    request_id = h.conversation(talk)["requests"][0]["id"]
    h.discussion_reply(talk, request_id, "kr-1")
    assert sorted(r["purpose"] for r in _bodies(h)) == ["authority_message", "knowledge"]  # 올린 직후
    assert [a["refusal"] for a in _repo(h).apply_knowledge_report("kr-1")] == ["unknown_repository"]
    assert [r["purpose"] for r in _bodies(h)] == ["knowledge"]  # 권위가 될 버전이 없다 → 메시지 본문 삭제
    assert marker_tables(Path(h.controller_config.db_path), WORDS) == set()

    # 다른 대화(첫 대화의 요청은 이 하네스에서 사람이 끝내지 않아 처리 중이다).
    other = h.create_conversation(project["id"], "대화 2")["case_id"]
    h.agent.cli_executor.discussion_response = _knowledge_reply([RULE_ITEM])
    h.send_message(other, f"앞으로 정말 이렇게 해 {WORDS}-2", "c-2")
    h.agent.persist_pending_intakes()
    request_id = h.conversation(other)["requests"][-1]["id"]
    h.discussion_reply(other, request_id, "kr-2")
    assert [a["state"] for a in _repo(h).apply_knowledge_report("kr-2")] == ["registered"]
    assert sorted(r["purpose"] for r in _bodies(h)) == ["authority_message", "knowledge", "knowledge"]
    assert marker_tables(Path(h.controller_config.db_path), f"{WORDS}-2") == {"knowledge_body"}
    version = h.client.get(f"/api/projects/{project['id']}/knowledge").json()["items"][0]["current"]
    assert (version["storage"], version["source_storage"]) == ("server", "server")
    assert _repo(h).apply_knowledge_report("kr-2") == []  # 재처리해도 그대로
    assert sorted(r["purpose"] for r in _bodies(h)) == ["authority_message", "knowledge", "knowledge"]


# ================================================== AC-11 이행 v22 → v23


def test_a_v22_database_gets_the_body_table_empty_and_wants_uploads(tmp_path):
    """AC-11 — v22 → v23. `knowledge_body` 가 생기고 비어 있다. 옛 버전은 `storage = runner` 이고 소유 PC
    의 올릴 것 목록에 나온다. 멱등이다. 본문을 지어내지 않는다.
    """
    schema = (Path(db.__file__).parent / "schema.sql").read_text(encoding="utf-8")
    marker = "-- 스키마 v23 (P4-06b)"
    assert marker in schema
    v22 = schema[: schema.index(marker)].rsplit("-- ====", 1)[0]
    assert "knowledge_body" not in v22 and "run_knowledge" in v22
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    conn.executescript(v22)
    now = "2026-09-24T00:00:00+00:00"
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (22, ?)", (now,))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute("INSERT INTO runner (id, name, host, status, registered_at) VALUES ('r-a','a','h','registered',?)", (now,))
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1', 'prj-1', 'old', 'feature', 'received', ?, ?)", (now, now),
    )
    conn.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash, byte_size,"
        " owner_runner_id, availability, summary, created_at)"
        " VALUES ('art-k', 1, 'case-1', 'knowledge', 'sha256:abc', 10, 'r-a', 'available', 'old', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO knowledge_item (id, project_id, knowledge_key, created_by, created_at)"
        " VALUES ('know-1', 'prj-1', 'K-001', 'owner', ?)", (now,)
    )
    conn.execute(
        "INSERT INTO knowledge_version (id, knowledge_id, version, artifact_id, artifact_rev, kind,"
        " obligation, state, summary, scope_kind, authority_kind, source_case_id, created_by, created_at)"
        " VALUES ('knowv-1', 'know-1', 1, 'art-k', 1, 'constraint', 'required', 'active', 'old rule',"
        " 'project', 'user_registration', 'case-1', 'owner', ?)", (now,)
    )
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 23
    assert db.SCHEMA_VERSION >= 23
    assert conn.execute("SELECT COUNT(*) FROM knowledge_body").fetchone()[0] == 0
    repo = Repository(conn)
    version = repo.get_knowledge_version("knowv-1")
    assert (version["storage"], version["source_storage"]) == ("runner", None)
    assert [(w["artifact_id"], w["content_hash"]) for w in repo.knowledge_uploads_for("r-a")] == [("art-k", "sha256:abc")]
    assert repo.knowledge_uploads_for("r-a")[0]["kind"] == "knowledge"
    assert repo.knowledge_body_for("art-k", 1) is None
    db.migrate(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,)
    ).fetchone()[0] == 1
