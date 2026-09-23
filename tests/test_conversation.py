"""UI-01 — 대화·요청 기반(plans/UI-PLAN-01.md).

준비 단계 Case, 대화 메시지·정정·자료 참조, 현재 요청과 서버 잠금, 멱등 접수와 접수
대조, 카드 답변의 대상 한정, 논의 응답 실행, 최초 업무화를 **API 로** 본다. 화면의 버튼이
아니라 서버가 잠그는지를 보는 것이 이 파일의 핵심이다 — 모든 거부는 직접 호출로 확인한다.

시험 이름 옆의 AC 번호는 UI-PLAN-01 5절이다.
"""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

import pytest

from controller import db as dbmod
from controller.repository import (
    ConversationRefused,
    Repository,
    RequestNotProcessing,
)
from domain import conversation as convmod
from domain.models import (
    CaseStage,
    ConversationRefusal,
    MessageKind,
    MessageReceipt,
    Permission,
    RequestSettleOutcome,
    RequestState,
    RunOutcome,
    RunPurpose,
    RunRole,
    RunStatus,
    StageSource,
)
from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE, RUNNER_ID

MARKER = "UI01-BODY-MARKER-8b1f"


# ---------------------------------------------------------------- 도우미


def _refusals(response) -> list[str]:
    detail = response.json()["detail"]
    if "admission" in detail:
        return detail["admission"]["refusals"]
    return detail["refusals"]


def _conversation_case(harness, title: str = "새 대화") -> tuple[dict, dict]:
    project = harness.create_project()
    view = harness.create_conversation(project["id"], title)
    return project, view


def _open_request(harness, case_id: str, text: str, cid: str) -> dict[str, Any]:
    """메시지를 보내 요청을 연다. 접수(Runner 저장)까지 진행한다."""
    sent = harness.send_message(case_id, text, cid)
    assert sent["request"]["state"] == RequestState.PROCESSING.value
    return sent


def _db(harness) -> sqlite3.Connection:
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ================================================== 순수 규칙 (domain.conversation)


def test_stage_derivation_names_where_the_stage_came_from():
    """단계 도출. NULL 은 UI-01 이전 Case 이며 업무 단계로 **도출**한다."""
    assert convmod.derive_stage(None, False) == (
        CaseStage.WORK,
        StageSource.CREATED_BEFORE_STAGE,
    )
    assert convmod.derive_stage("discussion", False) == (
        CaseStage.DISCUSSION,
        StageSource.CREATED_AS_DISCUSSION,
    )
    assert convmod.derive_stage("work", True)[1] is StageSource.WORK_STARTED
    assert convmod.derive_stage("work", False)[1] is StageSource.CREATED_AS_WORK


def test_only_a_stored_intake_is_a_received_message():
    assert convmod.receipt_for_intake("stored") is MessageReceipt.STORED
    assert convmod.receipt_for_intake("pending") is MessageReceipt.PENDING
    assert convmod.receipt_for_intake("lost_before_persist") is MessageReceipt.LOST_BEFORE_PERSIST
    # 모르는 상태를 접수로 읽지 않는다.
    assert convmod.receipt_for_intake(None) is MessageReceipt.PENDING


def test_settle_rules_keep_the_lock_while_anything_is_unknown_or_running():
    finished_ok = {"run_id": "r1", "status": RunStatus.FINISHED.value, "outcome": "completed"}
    running = {"run_id": "r2", "status": RunStatus.RUNNING.value, "outcome": None}
    unknown = {"run_id": "r3", "status": RunStatus.FINISHED.value, "outcome": "unknown"}

    refused = convmod.decide_settle(
        RequestSettleOutcome.COMPLETED, MessageReceipt.STORED, [finished_ok, running]
    )
    assert refused.refusal is ConversationRefusal.REQUEST_RUNS_UNFINISHED

    # 실패를 요청해도 결과를 모르는 실행이 있으면 unknown 이다 — 잠금이 풀리지 않는다.
    kept = convmod.decide_settle(
        RequestSettleOutcome.FAILED, MessageReceipt.STORED, [finished_ok, unknown]
    )
    assert kept.refusal is None and kept.state is RequestState.UNKNOWN
    assert convmod.is_locking(kept.state.value)

    not_received = convmod.decide_settle(
        RequestSettleOutcome.COMPLETED, MessageReceipt.PENDING, []
    )
    assert not_received.refusal is ConversationRefusal.REQUEST_ORIGINAL_NOT_STORED
    # 처리하지 못했다는 사실은 적을 수 있다.
    failed = convmod.decide_settle(RequestSettleOutcome.FAILED, MessageReceipt.PENDING, [])
    assert failed.state is RequestState.FAILED

    assert convmod.lost_original_fails_request(
        "processing", MessageReceipt.LOST_BEFORE_PERSIST, 0
    )
    assert not convmod.lost_original_fails_request(
        "processing", MessageReceipt.LOST_BEFORE_PERSIST, 1
    )


# ======================================================= AC-1 준비 Case


def test_a_conversation_starts_without_a_goal_or_a_profile(harness):
    """AC-1 — 목표·Profile 없이 준비 단계 Case 가 생긴다. feature 로 채우지 않는다."""
    project, view = _conversation_case(harness)
    case = harness.client.get(f"/api/cases/{view['case_id']}").json()

    assert case["stage"] == CaseStage.DISCUSSION.value
    assert case["kind"] == "undecided"
    assert case["profile"] is None
    assert case["profile_version"] is None
    assert case["profile_source"] is None
    assert case["status"] == "received"
    assert view["stage_source"] == StageSource.CREATED_AS_DISCUSSION.value
    # 준비 단계는 Autonomy 와 별개다. 기본 행이 다른 Case 와 같게 있다.
    assert case["policy"]["autonomy"] == "ask_on_decision"
    assert case["policy"]["autonomy_source"] == "system_default"
    # R1 이전 Case 의 "기록되지 않음"과 다르게 보인다.
    assert case["policy"]["profile"]["source"] == "not_yet_decided"
    # 질문 없는 휴식은 답변 필요가 아니다.
    assert view["needs_response"] is False
    assert view["send"]["general"]["allowed"] is True

    # 기존 생성 API 는 그대로 업무 단계 Case 를 만든다.
    work = harness.create_case(project["id"], "기존 경로")
    assert work["stage"] == CaseStage.WORK.value
    assert harness.conversation(work["id"])["stage_source"] == StageSource.CREATED_AS_WORK.value

    # 목적 없는 **업무** Case 를 기존 경로로 만들 수 없다.
    refused = harness.client.post(
        f"/api/projects/{project['id']}/cases", json={"title": "x", "kind": "undecided"}
    )
    assert refused.status_code == 409


# ================================================= AC-2 보관은 가시성이다


def test_archiving_is_list_visibility_and_changes_nothing_else(harness):
    """AC-2 — 보관·복원이 종료 상태·요청·잠금을 바꾸지 않고 이력을 남긴다."""
    project, view = _conversation_case(harness)
    case_id = view["case_id"]
    sent = _open_request(harness, case_id, "아이디어 하나 이야기해 볼게요.", "c-arch-1")
    other = harness.create_conversation(project["id"], "다른 대화")

    archived = harness.client.post(f"/api/cases/{case_id}/archive", json={"actor": "owner"})
    assert archived.status_code == 200 and archived.json()["archived"] is True
    # 같은 동작의 재전송이 이력을 늘리지 않는다.
    again = harness.client.post(f"/api/cases/{case_id}/archive", json={"actor": "owner"})
    assert len(again.json()["history"]) == 1

    after = harness.conversation(case_id)
    assert after["status"] == "received"
    assert after["current_request"]["id"] == sent["request"]["id"]
    assert after["current_request"]["state"] == RequestState.PROCESSING.value
    # 보관해도 잠금은 그대로다 — 보관이 요청을 끝내지 않는다.
    assert harness.post_message(case_id, "또", "c-arch-2").status_code == 409

    listed = harness.client.get(f"/api/projects/{project['id']}/conversations").json()
    assert {c["id"] for c in listed} == {case_id, other["case_id"]}
    active_only = harness.client.get(
        f"/api/projects/{project['id']}/conversations?archived=exclude"
    ).json()
    assert [c["id"] for c in active_only] == [other["case_id"]]
    only = harness.client.get(f"/api/projects/{project['id']}/cases?archived=only").json()
    assert [c["id"] for c in only] == [case_id]
    assert only[0]["current_request_state"] == RequestState.PROCESSING.value
    assert only[0]["effective_stage"] == CaseStage.DISCUSSION.value

    restored = harness.client.post(f"/api/cases/{case_id}/restore", json={"actor": "owner"})
    assert restored.json()["archived"] is False
    assert [e["action"] for e in restored.json()["history"]] == ["archive", "restore"]


# ============================================ AC-3·4 메시지·참조·접수 상태


def test_a_message_keeps_order_and_a_reference_but_never_the_body(harness):
    """AC-3·AC-4 — 순번·원문 참조·요약만 제어부에 남고 접수는 Runner 저장 뒤다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]

    response = harness.post_message(
        case_id, f"본문 {MARKER} 입니다.", "c-body-1", summary="첫 메시지"
    )
    assert response.status_code == 202
    body = response.json()
    assert body["created"] is True
    # **202 는 접수가 아니다.**
    assert body["receipt"] == MessageReceipt.PENDING.value
    assert body["message"]["seq"] == 1

    harness.agent.persist_pending_intakes()
    message = harness.conversation(case_id)["messages"][0]
    assert message["receipt"] == MessageReceipt.STORED.value
    assert message["author"] == "user" and message["message_kind"] == "general"
    assert message["summary"] == "첫 메시지"

    marker = MARKER.encode("utf-8")
    data = b""
    base = Path(harness.controller_config.db_path)
    for path in (base, Path(str(base) + "-wal"), Path(str(base) + "-shm")):
        if path.exists():
            data += path.read_bytes()
    assert marker not in data, "메시지 본문이 제어부 DB 에 남았다"
    runner_data = b"".join(
        p.read_bytes() for p in Path(harness.runner_config.data_root).rglob("*") if p.is_file()
    )
    assert marker in runner_data, "본문이 Runner 에도 없다 — 경계 확인이 무의미하다"


def test_references_pin_the_version_and_refuse_what_is_not_this_case(harness):
    """AC-3 — 자료 참조는 그 시점의 버전·해시·위치를 고정하고, 없는 대상은 거부한다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "참조 대상", kind="analysis")
    other = harness.create_case(project["id"], "다른 Case", kind="analysis")
    artifact = harness.submit_artifact(case["id"], "참조될 문서", summary="문서")
    foreign = harness.submit_artifact(other["id"], "다른 Case 문서", summary="남의 문서")
    repo_id = harness.project_repository_id(project["id"])

    sent = harness.send_message(
        case["id"],
        "이 문서의 3절과 이 파일을 봐 주세요.",
        "c-ref-1",
        references=[
            {
                "kind": "artifact",
                "artifact_id": artifact["artifact_id"],
                "revision": 1,
                "location": "3절",
            },
            {
                "kind": "project_file",
                "repository_id": repo_id,
                "path": "src/app.py",
                "location": "12-18행",
                "observed_hash": "sha256:abc",
            },
        ],
    )
    refs = sent["message"]["references"]
    assert refs[0]["artifact_id"] == artifact["artifact_id"]
    assert refs[0]["artifact_hash"] == artifact["content_hash"]
    assert refs[0]["location"] == "3절"
    assert refs[1]["path"] == "src/app.py" and refs[1]["repository_id"] == repo_id
    harness.settle(case["id"], sent["request"]["id"])

    before = harness.intake_count()
    for bad in (
        {"kind": "artifact", "artifact_id": foreign["artifact_id"], "revision": 1},
        {"kind": "artifact", "artifact_id": "art-none", "revision": 1},
        {"kind": "project_file", "repository_id": "repo-none", "path": "a.py"},
        {"kind": "project_file", "repository_id": repo_id, "path": "  "},
    ):
        refused = harness.post_message(case["id"], "참조", f"c-bad-{len(bad)}-{bad['kind']}"
                                       + str(bad.get("artifact_id") or bad.get("repository_id")),
                                       references=[bad])
        assert refused.status_code == 409, refused.text
        assert _refusals(refused) == [ConversationRefusal.REFERENCE_INVALID.value]
    # **거부된 전송은 원문을 남기지 않는다.**
    assert harness.intake_count() == before


def test_a_hash_mismatch_is_not_a_received_message(harness):
    """AC-4 — PC 가 다른 내용을 보고하면 접수가 아니다. 대기에 머문다."""
    _project, view = _conversation_case(harness)
    response = harness.post_message(view["case_id"], "원래 본문", "c-hash-1")
    intake_id = response.json()["message"]["intake_id"]
    wrong = harness.client.post(
        f"/api/runner/intakes/{intake_id}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": "sha256:not-the-same"},
    )
    assert wrong.status_code == 409
    message = harness.conversation(view["case_id"])["messages"][0]
    assert message["receipt"] == MessageReceipt.PENDING.value


def test_the_body_is_relayed_before_the_intake_becomes_visible(harness, monkeypatch):
    """AC-4 — 새 경로는 **기록보다 먼저** 중계 버퍼에 본문을 넣는다.

    P2 경로는 커밋 뒤에 버퍼에 넣었다. 그 사이 Runner 폴링이 끼면 본문 없는 접수가
    유실로 표시된다. 여기서는 커밋 직후(응답 전)의 순간을 붙잡아 그때 이미 버퍼에
    본문이 있는지, 그리고 그 순간 Runner 가 폴링해도 유실되지 않는지를 본다.
    """
    _project, view = _conversation_case(harness)
    relay = harness.client.app.state.relay
    seen: dict[str, Any] = {}
    original = Repository._message_result

    def spy(self, message):
        seen["state_at_commit"] = self.get_intake(message["intake_id"])["state"]
        seen["body_ready"] = relay.get(message["intake_id"]) is not None
        return original(self, message)

    monkeypatch.setattr(Repository, "_message_result", spy)
    response = harness.post_message(view["case_id"], "경합 시험", "c-race-relay")
    assert response.status_code == 202
    assert seen == {"state_at_commit": "pending", "body_ready": True}
    harness.agent.persist_pending_intakes()
    assert harness.conversation(view["case_id"])["messages"][0]["receipt"] == "stored"


# ================================================= AC-5 멱등·접수 대조


def test_resending_the_same_client_message_id_creates_nothing_new(harness):
    """AC-5 — 같은 전송 식별자의 재전송은 같은 결과(200), 다른 내용은 409."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    first = harness.post_message(case_id, "한 번만 받아 주세요.", "c-dup-1")
    assert first.status_code == 202
    count = harness.intake_count()

    # 응답을 받지 못해 다시 보낸 경우. 자기 요청 때문에 409 가 되지 않는다.
    again = harness.post_message(case_id, "한 번만 받아 주세요.", "c-dup-1")
    assert again.status_code == 200, again.text
    assert again.json()["created"] is False
    assert again.json()["message"]["id"] == first.json()["message"]["id"]
    assert again.json()["request"]["id"] == first.json()["request"]["id"]
    assert harness.intake_count() == count
    assert len(harness.conversation(case_id)["requests"]) == 1

    conflict = harness.post_message(case_id, "다른 내용", "c-dup-1")
    assert conflict.status_code == 409
    assert _refusals(conflict) == [ConversationRefusal.CLIENT_MESSAGE_ID_CONFLICT.value]

    # 접수 불명 대조: 받은 전송은 상태와 함께, 받지 않은 전송은 404.
    found = harness.client.get(f"/api/cases/{case_id}/messages/by-client-id/c-dup-1")
    assert found.status_code == 200 and found.json()["receipt"] == "pending"
    harness.agent.persist_pending_intakes()
    found = harness.client.get(f"/api/cases/{case_id}/messages/by-client-id/c-dup-1")
    assert found.json()["receipt"] == "stored"
    missing = harness.client.get(f"/api/cases/{case_id}/messages/by-client-id/c-never")
    assert missing.status_code == 404


# ============================================== AC-6·7 서버 잠금과 경쟁


def test_general_input_is_locked_on_the_server_while_a_request_is_processing(harness):
    """AC-6 — 처리 중에는 일반·정정 메시지, 피드백, 사람 의도 초안이 409 다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "업무 Case")
    harness.ai_draft(case["id"])
    intent = harness.latest_intent(case["id"])
    other = harness.create_conversation(project["id"], "다른 대화")

    sent = _open_request(harness, case["id"], "이 초안에 대해 이야기해요.", "c-lock-1")
    before = harness.intake_count()

    general = harness.post_message(case["id"], "하나 더", "c-lock-2")
    assert general.status_code == 409
    assert _refusals(general) == [ConversationRefusal.REQUEST_IN_PROGRESS.value]
    correction = harness.post_message(
        case["id"], "정정", "c-lock-3", kind="correction",
        corrects_message_id=sent["message"]["id"],
    )
    assert _refusals(correction) == [ConversationRefusal.REQUEST_IN_PROGRESS.value]
    feedback = harness.client.post(
        f"/api/cases/{case['id']}/feedback",
        json={
            "target_intent_version_id": intent["id"],
            "content": "피드백 경로로 우회",
            "summary": "우회",
            "target_runner_id": RUNNER_ID,
        },
    )
    assert feedback.status_code == 409
    assert _refusals(feedback) == [ConversationRefusal.REQUEST_IN_PROGRESS.value]
    draft = harness.client.post(
        f"/api/cases/{case['id']}/intent-drafts",
        json={"summary": "사람 초안", "target_runner_id": RUNNER_ID, "fields": {}},
    )
    assert draft.status_code == 409
    assert _refusals(draft) == [ConversationRefusal.REQUEST_IN_PROGRESS.value]
    # 대기열이 없다 — 거부된 전송은 어디에도 남지 않는다.
    assert harness.intake_count() == before
    assert len(harness.conversation(case["id"])["messages"]) == 1

    view = harness.conversation(case["id"])
    assert view["send"]["general"] == {
        "allowed": False,
        "refusal": ConversationRefusal.REQUEST_IN_PROGRESS.value,
        "detail": view["send"]["general"]["detail"],
        "active_request_id": sent["request"]["id"],
    }
    # 다른 Case 는 막히지 않는다.
    assert harness.post_message(other["case_id"], "여기는 됩니다", "c-other-1").status_code == 202


def test_two_simultaneous_sends_open_exactly_one_request(harness):
    """AC-7 — 두 연결에서 동시에 보낸 일반 메시지 중 하나만 요청을 연다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    path = harness.controller_config.db_path
    ready = threading.Barrier(2)
    results: dict[str, Any] = {}

    def attempt(name: str) -> None:
        conn = dbmod.connect(path)
        repo = Repository(conn)
        try:
            ready.wait(timeout=10)
            result, created = repo.submit_message(
                case_id,
                client_message_id=f"c-race-{name}",
                kind=MessageKind.GENERAL,
                expected_hash=f"sha256:{name}",
                byte_size=3,
                summary=f"경쟁 {name}",
                target_runner_id=RUNNER_ID,
                actor="owner",
                intake_id=f"intake-race-{name}",
            )
            results[name] = ("created", result["request"]["id"])
        except ConversationRefused as exc:
            results[name] = ("refused", [r.value for r in exc.refusals])
        except Exception as exc:  # 경쟁에서 진 쪽도 기록으로 남아야 한다
            results[name] = ("error", repr(exc))
        finally:
            conn.close()

    threads = [threading.Thread(target=attempt, args=(n,)) for n in ("a", "b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    outcomes = sorted(v[0] for v in results.values())
    assert outcomes == ["created", "refused"], results
    loser = next(v for v in results.values() if v[0] == "refused")
    assert loser[1] == [ConversationRefusal.REQUEST_IN_PROGRESS.value]
    conn = _db(harness)
    try:
        assert conn.execute(
            "SELECT COUNT(*) FROM conversation_request WHERE case_id = ?", (case_id,)
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM conversation_message WHERE case_id = ?", (case_id,)
        ).fetchone()[0] == 1
        # 표 차원의 마지막 방어선: 활성 요청 둘을 직접 넣을 수 없다.
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO conversation_request"
                " (id, case_id, opened_by_message_id, state, opened_at)"
                " VALUES ('req-x', ?, 'msg-x', 'processing', 'now')",
                (case_id,),
            )
    finally:
        conn.close()


# ======================================= AC-8·9 Run 사이 잠금과 요청 전이


def test_the_lock_holds_between_runs_and_opens_only_on_an_explicit_settle(harness):
    """AC-8 — 연결 Run 이 끝나도 종료 기록 전까지 잠기고, 미종료 Run 이 있으면 거부된다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    sent = _open_request(harness, case_id, "구조를 어떻게 나눌지 이야기해요.", "c-between-1")
    request_id = sent["request"]["id"]

    first = harness.discussion_reply(case_id, request_id, "run-disc-1")
    assert first.status_code == 201, first.text
    # 첫 실행이 끝났다. 그래도 요청은 끝나지 않았다.
    assert harness.client.get("/api/runs/run-disc-1").json()["status"] == "finished"
    assert harness.post_message(case_id, "다음", "c-between-2").status_code == 409

    second = harness.discussion_reply(case_id, request_id, "run-disc-2", execute=False)
    assert second.status_code == 201, second.text
    unfinished = harness.settle(case_id, request_id)
    assert unfinished.status_code == 409
    assert _refusals(unfinished) == [ConversationRefusal.REQUEST_RUNS_UNFINISHED.value]
    assert harness.post_message(case_id, "다음", "c-between-3").status_code == 409

    harness.agent.poll_once()
    settled = harness.settle(case_id, request_id)
    assert settled.status_code == 200, settled.text
    assert settled.json()["state"] == RequestState.COMPLETED.value
    assert settled.json()["unfinished_runs"] == 0
    assert [r["run_id"] for r in settled.json()["runs"]] == ["run-disc-1", "run-disc-2"]
    # 같은 종료의 재전송은 같은 결과다.
    assert harness.settle(case_id, request_id).json()["state"] == "completed"
    assert _refusals(harness.settle(case_id, request_id, "failed")) == [
        ConversationRefusal.REQUEST_ALREADY_SETTLED.value
    ]

    # 종료 뒤 전송이 열린다. **Case 는 닫히지 않았다** — Case 종료까지 잠그지 않는다.
    assert harness.conversation(case_id)["status"] == "received"
    assert harness.post_message(case_id, "다음 이야기", "c-between-4").status_code == 202


def test_request_transitions_do_not_turn_unknown_or_unreceived_into_success(harness):
    """AC-9 — 원문 미저장은 완료가 아니고, 불명 실행은 잠금을 유지한다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]

    # (1) 여는 메시지가 아직 저장되지 않았다 → 완료로 적지 않는다. 실패는 적을 수 있다.
    pending = harness.post_message(case_id, "아직 저장 전", "c-tr-1").json()
    refused = harness.settle(case_id, pending["request"]["id"])
    assert _refusals(refused) == [ConversationRefusal.REQUEST_ORIGINAL_NOT_STORED.value]
    # 저장 전에는 그 요청으로 실행도 열지 않는다.
    early = harness.discussion_reply(case_id, pending["request"]["id"], "run-tr-early")
    assert early.status_code == 409
    assert ConversationRefusal.REQUEST_ORIGINAL_NOT_STORED.value in _refusals(early)
    failed = harness.settle(case_id, pending["request"]["id"], "failed", note="처리 못 함")
    assert failed.json()["state"] == RequestState.FAILED.value
    assert failed.json()["note_summary"] == "처리 못 함"

    # (2) 결과를 모르는 실행 → unknown, 잠금 유지. 실패로 적어 달라고 해도 그렇다.
    sent = _open_request(harness, case_id, "불명 실행", "c-tr-2")
    harness.agent.cli_executor.outcome = RunOutcome.UNKNOWN
    reply = harness.discussion_reply(case_id, sent["request"]["id"], "run-tr-unknown")
    assert reply.status_code == 201
    harness.agent.cli_executor.outcome = RunOutcome.COMPLETED
    assert harness.client.get("/api/runs/run-tr-unknown").json()["outcome"] == "unknown"
    kept = harness.settle(case_id, sent["request"]["id"], "failed")
    assert kept.status_code == 200
    assert kept.json()["state"] == RequestState.UNKNOWN.value
    assert kept.json()["outcome_reason"] == "run_outcome_unknown"
    assert kept.json()["locking"] is True
    blocked = harness.post_message(case_id, "다음", "c-tr-3")
    assert _refusals(blocked) == [ConversationRefusal.REQUEST_STATE_UNKNOWN.value]
    again = harness.settle(case_id, sent["request"]["id"], "completed")
    assert _refusals(again) == [ConversationRefusal.REQUEST_STATE_UNKNOWN.value]
    # 결과를 모르는 실행은 AI 메시지가 되지 않는다.
    assert [m["author"] for m in harness.conversation(case_id)["messages"]] == ["user", "user"]


def test_a_lost_opening_message_fails_its_request_instead_of_holding_the_lock(harness):
    """AC-9·AC-17 — 저장 전에 유실된 메시지의 요청은 시스템이 실패로 닫는다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    pending = harness.post_message(case_id, "유실될 메시지", "c-lost-1").json()
    repo = Repository(harness.client.app.state.conn)
    repo.mark_intake_lost(pending["message"]["intake_id"])

    after = harness.conversation(case_id)
    assert after["messages"][0]["receipt"] == MessageReceipt.LOST_BEFORE_PERSIST.value
    request = after["requests"][0]
    assert request["state"] == RequestState.FAILED.value
    assert request["outcome_reason"] == "original_lost_before_persist"
    assert request["settled_by"] == "system"
    # 잠금이 풀려 사용자가 다시 보낼 수 있다(초안은 사용자에게 남아 있다).
    assert after["send"]["general"]["allowed"] is True
    # 같은 식별자는 이미 쓰였다 — 유실된 것을 되살리지 않는다. 새 식별자로 보낸다.
    assert harness.post_message(case_id, "유실될 메시지", "c-lost-1").status_code == 200
    assert harness.post_message(case_id, "유실될 메시지", "c-lost-2").status_code == 202


def test_a_run_cannot_join_a_request_that_ended(harness, monkeypatch):
    """AC-9 — 끝난 요청에 실행을 붙이지 않는다. 검사와 생성 사이 경합도 막는다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    sent = _open_request(harness, case_id, "짧은 질문", "c-join-1")
    request_id = sent["request"]["id"]
    harness.discussion_reply(case_id, request_id, "run-join-1")
    assert harness.settle(case_id, request_id).status_code == 200

    late = harness.discussion_reply(case_id, request_id, "run-join-late")
    assert late.status_code == 409
    assert "request_not_processing" in _refusals(late)

    # 경합: 진입 검사는 통과했는데 생성 직전에 요청이 끝난다.
    second = _open_request(harness, case_id, "두 번째", "c-join-2")
    second_id = second["request"]["id"]
    original = Repository.check_admission

    def check_then_settle(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        # 다른 요청 처리자가 그 사이 요청을 실패로 닫았다.
        self.settle_request(case_id, second_id, RequestSettleOutcome.FAILED, "other")
        return result

    monkeypatch.setattr(Repository, "check_admission", check_then_settle)
    raced = harness.discussion_reply(case_id, second_id, "run-join-race", execute=False)
    assert raced.status_code == 409, raced.text
    assert _refusals(raced) == ["request_not_processing"]
    monkeypatch.setattr(Repository, "check_admission", original)
    assert harness.client.get("/api/runs/run-join-race").status_code == 404
    # 거부도 진입 검사 기록에 남는다.
    checks = harness.client.get(f"/api/cases/{case_id}/admission-checks").json()
    assert checks[0]["refusals"] == ["request_not_processing"]

    # 저장 계층에서도 같다 — 트랜잭션 안에서 다시 본다.
    repo = Repository(harness.client.app.state.conn)
    message = harness.conversation(case_id)["messages"][0]
    with pytest.raises(RequestNotProcessing):
        repo.create_run(
            run_id="run-join-direct",
            case_id=case_id,
            task_id="task-1",
            role=RunRole.AUTHOR,
            tool_id=FAKE_TOOL_ID,
            mode=FAKE_TOOL_MODE,
            permission=Permission.READ_ONLY,
            instruction_artifact_id=message["artifact_id"],
            instruction_artifact_rev=1,
            purpose=RunPurpose.DISCUSSION_REPLY,
            request_id=request_id,
        )


# ========================================================= AC-10 카드 답변


_QUESTION = {
    "key": "q-scope",
    "text": "내보내기에 숨긴 열도 포함할까요?",
    "summary": "숨긴 열 포함 여부",
    "decide_at": "intent",
}


def _case_with_question(harness):
    from tests.test_intent import _draft_fields

    project = harness.create_project()
    case = harness.create_case(project["id"], "질문이 있는 업무")
    harness.submit_intent_draft(case["id"], _draft_fields(), questions=[_QUESTION])
    intent = harness.latest_intent(case["id"])
    question = intent["questions"][0]
    return project, case, intent, question


def test_a_card_answer_is_scoped_to_its_question_and_version(harness):
    """AC-10 — 처리 중에도 답할 수 있고, 답은 그 질문·버전의 답일 뿐이다."""
    from tests.test_intent import _draft_fields

    _project, case, intent, question = _case_with_question(harness)
    sent = _open_request(harness, case["id"], "질문 카드가 떴네요.", "c-card-0")

    answered = harness.post_message(
        case["id"],
        "숨긴 열은 빼 주세요.",
        "c-card-1",
        kind="card_answer",
        question_id=question["id"],
        intent_version_id=intent["id"],
    )
    assert answered.status_code == 202, answered.text
    body = answered.json()
    # 요청을 열지 않는다 — 처리 중이던 요청은 맥락으로만 가리킨다.
    assert body["request"] is None
    assert body["message"]["request_id"] == sent["request"]["id"]
    harness.agent.persist_pending_intakes()
    view = harness.conversation(case["id"])
    assert view["current_request"]["id"] == sent["request"]["id"]
    assert view["current_request"]["state"] == RequestState.PROCESSING.value
    assert len(view["requests"]) == 1
    assert harness.latest_intent(case["id"])["questions"][0]["state"] == "answered"
    # 동의·결정·위임 근거를 만들지 않는다.
    detail = harness.client.get(f"/api/cases/{case['id']}").json()
    assert detail["decisions"] == []
    assert detail["policy"]["delegation_basis"]["history"] == []
    assert detail["intent_state"]["agreement_state"] == "never_agreed"

    before = harness.intake_count()
    twice = harness.post_message(
        case["id"], "다시", "c-card-2", kind="card_answer",
        question_id=question["id"], intent_version_id=intent["id"],
    )
    assert _refusals(twice) == [ConversationRefusal.QUESTION_ALREADY_ANSWERED.value]
    missing = harness.post_message(case["id"], "대상 없음", "c-card-3", kind="card_answer")
    assert _refusals(missing) == [ConversationRefusal.CARD_ANSWER_TARGET_MISSING.value]
    assert harness.intake_count() == before

    # 새 버전이 생기면 옛 버전의 질문 카드는 대상이 아니다.
    harness.settle(case["id"], sent["request"]["id"])
    harness.submit_intent_draft(case["id"], _draft_fields(), questions=[_QUESTION])
    newer = harness.latest_intent(case["id"])
    assert newer["id"] != intent["id"]
    # 카드가 옛 버전을 보였다 — 새 버전의 질문이어도 그 카드로는 답하지 않는다.
    stale = harness.post_message(
        case["id"], "옛 카드", "c-card-4", kind="card_answer",
        question_id=newer["questions"][0]["id"], intent_version_id=intent["id"],
    )
    assert _refusals(stale) == [ConversationRefusal.QUESTION_TARGET_STALE.value]
    # 기존 답변 경로도 대체된 버전의 질문을 원문 접수 **전에** 거부한다.
    open_old = harness.client.post(
        f"/api/cases/{case['id']}/questions/{question['id']}/answer",
        json={"content": "옛 질문", "summary": "옛", "target_runner_id": RUNNER_ID},
    )
    assert open_old.status_code == 409
    assert harness.intake_count() == before + 1  # 새 초안 한 건뿐


def test_a_lost_answer_reopens_its_question(harness):
    """AC-10 — PC 에 닿지 않은 답은 해결이 아니다. 질문이 다시 열린다."""
    _project, case, intent, question = _case_with_question(harness)
    response = harness.post_message(
        case["id"], "답변 본문", "c-lost-card", kind="card_answer",
        question_id=question["id"], intent_version_id=intent["id"],
    )
    assert harness.latest_intent(case["id"])["questions"][0]["state"] == "answered"
    Repository(harness.client.app.state.conn).mark_intake_lost(
        response.json()["message"]["intake_id"]
    )
    reopened = harness.latest_intent(case["id"])["questions"][0]
    assert reopened["state"] == "open"
    assert reopened["answer_artifact_id"] is None
    # 답하려 했다는 사실은 대화에 남는다.
    message = harness.conversation(case["id"])["messages"][0]
    assert message["receipt"] == MessageReceipt.LOST_BEFORE_PERSIST.value
    assert message["question_id"] == question["id"]


# ============================================================= AC-11 정정


def test_a_correction_is_a_new_message_and_keeps_the_original(harness):
    """AC-11 — 원본·그 요청·실행을 보존하고 새 요청을 연다."""
    project, view = _conversation_case(harness)
    case_id = view["case_id"]
    first = _open_request(harness, case_id, "CSV 로 내보내 주세요.", "c-cor-1")
    harness.discussion_reply(case_id, first["request"]["id"], "run-cor-1")
    assert harness.settle(case_id, first["request"]["id"]).status_code == 200

    fix = harness.send_message(
        case_id, "아니, TSV 로요.", "c-cor-2", kind="correction",
        corrects_message_id=first["message"]["id"],
    )
    assert fix["message"]["corrects_message_id"] == first["message"]["id"]
    assert fix["request"]["id"] != first["request"]["id"]
    assert fix["request"]["state"] == RequestState.PROCESSING.value

    view = harness.conversation(case_id)
    original = view["messages"][0]
    assert original["id"] == first["message"]["id"]
    assert original["corrected_by"] == [fix["message"]["id"]]
    assert original["content_hash"] == first["message"]["content_hash"]
    old_request = next(r for r in view["requests"] if r["id"] == first["request"]["id"])
    assert old_request["state"] == "completed"
    assert [r["run_id"] for r in old_request["runs"]] == ["run-cor-1"]

    # 처리 중에는 정정도 일반 전송이다.
    busy = harness.post_message(
        case_id, "또 정정", "c-cor-3", kind="correction",
        corrects_message_id=first["message"]["id"],
    )
    assert _refusals(busy) == [ConversationRefusal.REQUEST_IN_PROGRESS.value]
    harness.settle(case_id, fix["request"]["id"], "failed")

    assistant = next(m for m in view["messages"] if m["author"] == "assistant")
    foreign = harness.create_conversation(project["id"], "남의 대화")
    other = _open_request(harness, foreign["case_id"], "남의 메시지", "c-cor-x")
    for target in (assistant["id"], other["message"]["id"], "msg-none"):
        bad = harness.post_message(
            case_id, "정정", f"c-cor-bad-{target[-6:]}", kind="correction",
            corrects_message_id=target,
        )
        assert _refusals(bad) == [ConversationRefusal.CORRECTION_TARGET_INVALID.value]


# ====================================================== AC-12 논의 응답 실행


def test_the_discussion_stage_opens_only_the_discussion_reply(harness):
    """AC-12 — 준비 단계에서는 논의 응답만 열리고 그것도 읽기 전용·요청·원문 조건을 받는다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    sent = _open_request(harness, case_id, "무엇부터 할지 이야기해요.", "c-stage-1")
    message = sent["message"]
    request_id = sent["request"]["id"]

    def run(purpose: str, **extra: Any):
        body = {
            "run_id": f"run-stage-{purpose}-{len(extra)}",
            "instruction_artifact_id": message["artifact_id"],
            "purpose": purpose,
            "role": "reviewer" if purpose == "intent_gate_review" else "author",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "permission": "read_only",
        }
        body.update(extra)
        return harness.client.post(f"/api/cases/{case_id}/runs", json=body)

    for purpose in (
        "intent_authoring",
        "limited_analysis",
        "design_authoring",
        "feature_implementation",
        "local_experiment",
    ):
        refused = run(purpose)
        assert refused.status_code == 409
        assert ConversationRefusal.CASE_IN_DISCUSSION_STAGE.value in _refusals(refused), purpose

    assert _refusals(run("discussion_reply")) == ["request_required"]
    write = run("discussion_reply", request_id=request_id, permission="workspace_write")
    assert "permission_not_allowed_in_stage" in _refusals(write)
    other_art = harness.submit_artifact(case_id, "다른 지시", summary="다른 지시")
    mismatch = harness.client.post(
        f"/api/cases/{case_id}/runs",
        json={
            "run_id": "run-stage-mismatch",
            "instruction_artifact_id": other_art["artifact_id"],
            "purpose": "discussion_reply",
            "tool_id": FAKE_TOOL_ID,
            "mode": FAKE_TOOL_MODE,
            "request_id": request_id,
        },
    )
    assert _refusals(mismatch) == ["request_instruction_mismatch"]
    echo = run("discussion_reply", request_id=request_id, tool_id="local-echo",
               mode="p2-01-local")
    assert "tool_is_not_a_coding_cli" in _refusals(echo)

    # 사람이 쓰는 의도 초안도 준비 단계에서는 받지 않는다(원문 접수 전 거부).
    harness.settle(case_id, request_id)
    before = harness.intake_count()
    draft = harness.client.post(
        f"/api/cases/{case_id}/intent-drafts",
        json={"summary": "초안", "target_runner_id": RUNNER_ID, "fields": {}},
    )
    assert _refusals(draft) == [ConversationRefusal.CASE_IN_DISCUSSION_STAGE.value]
    assert harness.intake_count() == before


def test_a_discussion_reply_becomes_one_assistant_message_and_counts_on_the_case(harness):
    """AC-12 — 완료 응답은 AI 메시지로 한 번만 붙고 소비는 같은 Case 에 쌓인다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    limit = harness.client.put(
        f"/api/cases/{case_id}/budget",
        json={"metric": "run_count", "threshold_kind": "hard", "limit_value": 1,
              "set_by": "owner"},
    )
    assert limit.status_code == 201, limit.text

    sent = _open_request(harness, case_id, "의견을 주세요.", "c-reply-1")
    reply = harness.discussion_reply(case_id, sent["request"]["id"], "run-reply-1")
    assert reply.status_code == 201, reply.text
    assert reply.json()["admission"]["profile"] == "conversation"

    messages = harness.conversation(case_id)["messages"]
    assert [m["author"] for m in messages] == ["user", "assistant"]
    assistant = messages[1]
    assert assistant["message_kind"] == "assistant_reply"
    assert assistant["run_id"] == "run-reply-1"
    assert assistant["request_id"] == sent["request"]["id"]
    assert assistant["receipt"] == MessageReceipt.STORED.value
    run = harness.client.get("/api/runs/run-reply-1").json()
    assert assistant["artifact_id"] == run["output_artifact_id"]
    assert run["request_id"] == sent["request"]["id"]
    assert run["permission"] == "read_only"

    # 결과 재전송이 메시지를 늘리지 않는다.
    repo = Repository(harness.client.app.state.conn)
    repo.report_result("run-reply-1", 1, RunOutcome.COMPLETED)
    assert len(harness.conversation(case_id)["messages"]) == 2

    # hard 한도가 논의 응답에도 적용된다 — 같은 Case 의 소비다.
    blocked = harness.discussion_reply(case_id, sent["request"]["id"], "run-reply-2")
    assert _refusals(blocked) == ["budget_hard_limit_reached"]
    budget = harness.client.get(f"/api/cases/{case_id}/budget").json()
    assert budget["usage"]["run_count"]["exposure"] == 1.0
    assert budget["by_purpose"]["discussion_reply"]["run_count"]["rows"] == 1


# ======================================================== AC-13 최초 업무화


def test_work_starts_in_the_same_case_and_carries_everything_over(harness):
    """AC-13 — 같은 Case ID 에서 Profile v2 를 받고 앞선 기록·정책·소비가 그대로다."""
    project, view = _conversation_case(harness, "로그 도구 이야기")
    case_id = view["case_id"]
    repo_id = harness.project_repository_id(project["id"])
    assert harness.select_repository(case_id, repo_id).status_code == 201
    harness.client.put(
        f"/api/cases/{case_id}/budget",
        json={"metric": "run_count", "threshold_kind": "warn", "limit_value": 50,
              "set_by": "owner"},
    )

    idea = _open_request(harness, case_id, "로그를 좀 더 쉽게 보고 싶어요. 아직 문서는 쓰지 마세요.",
                         "c-ws-1")
    harness.discussion_reply(case_id, idea["request"]["id"], "run-ws-1")
    harness.settle(case_id, idea["request"]["id"])
    work = _open_request(harness, case_id, "좋아요, 오류 줄만 뽑는 기능을 이 범위로 구현해 주세요.",
                         "c-ws-2")

    started = harness.start_work(case_id, work["message"]["id"], profile="feature")
    assert started.status_code == 201, started.text
    body = started.json()
    assert body["case_id"] == case_id
    assert body["stage"] == CaseStage.WORK.value
    assert body["stage_source"] == StageSource.WORK_STARTED.value
    assert body["profile"] == "feature" and body["kind"] == "feature"
    assert body["profile_version"] == "2"
    assert body["profile_source"] == "work_start"
    assert body["work_start"]["request_message_id"] == work["message"]["id"]
    assert body["work_start"]["decided_by"] == "person"

    # 보존: 메시지·요청·실행·저장소 선택·예산·Autonomy.
    assert [m["id"] for m in body["messages"][:2]] == [
        idea["message"]["id"],
        body["messages"][1]["id"],
    ]
    assert len(body["messages"]) == 3
    assert body["current_request"]["id"] == work["request"]["id"]
    detail = harness.client.get(f"/api/cases/{case_id}").json()
    assert [r["run_id"] for r in detail["runs"]] == ["run-ws-1"]
    policy = detail["policy"]
    assert policy["autonomy"] == "ask_on_decision"
    assert [r["repository_id"] for r in policy["repositories"]["selected"]] == [repo_id]
    assert policy["budget"]["usage"]["run_count"]["exposure"] == 1.0
    assert any(s["metric"] == "run_count" for s in policy["budget"]["limits"])

    # 위임 근거는 **업무 요청 메시지 하나**다. 앞선 논의는 근거가 아니다.
    basis = policy["delegation_basis"]
    assert [b["basis_kind"] for b in basis["history"]] == ["original_request"]
    assert basis["current"]["artifact_id"] == work["message"]["artifact_id"]
    assert basis["current"]["content_hash"] == work["message"]["content_hash"]

    # 다시 업무화하지 않는다 — 활성 Case 의 Profile 변경은 다른 경로다(D-86).
    again = harness.start_work(case_id, work["message"]["id"], profile="defect_fix")
    assert _refusals(again) == [ConversationRefusal.CASE_NOT_IN_DISCUSSION_STAGE.value]
    legacy = harness.create_case(project["id"], "기존 업무")
    assert _refusals(harness.start_work(legacy["id"], "msg-x")) == [
        ConversationRefusal.CASE_NOT_IN_DISCUSSION_STAGE.value
    ]


def test_work_start_needs_a_stored_user_message_of_the_current_request(harness):
    """AC-13 — 근거 메시지의 조건과 AI 해석의 근거 실행."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    old = _open_request(harness, case_id, "예전 요청", "c-wsr-1")
    harness.discussion_reply(case_id, old["request"]["id"], "run-wsr-1")
    harness.settle(case_id, old["request"]["id"])
    assistant = next(
        m for m in harness.conversation(case_id)["messages"] if m["author"] == "assistant"
    )

    assert _refusals(harness.start_work(case_id, old["message"]["id"])) == [
        ConversationRefusal.WORK_REQUEST_NOT_CURRENT.value
    ]
    assert _refusals(harness.start_work(case_id, assistant["id"])) == [
        ConversationRefusal.WORK_REQUEST_INVALID.value
    ]
    pending = harness.post_message(case_id, "이 범위로 해 주세요", "c-wsr-2").json()
    assert _refusals(harness.start_work(case_id, pending["message"]["id"])) == [
        ConversationRefusal.WORK_REQUEST_NOT_STORED.value
    ]
    harness.agent.persist_pending_intakes()
    no_run = harness.start_work(case_id, pending["message"]["id"], decided_by="ai_interpretation")
    assert _refusals(no_run) == [ConversationRefusal.INTERPRETATION_RUN_INVALID.value]
    other_request_run = harness.start_work(
        case_id, pending["message"]["id"], decided_by="ai_interpretation",
        interpretation_run_id="run-wsr-1",
    )
    assert _refusals(other_request_run) == [ConversationRefusal.INTERPRETATION_RUN_INVALID.value]

    harness.discussion_reply(case_id, pending["request"]["id"], "run-wsr-2")
    started = harness.start_work(
        case_id, pending["message"]["id"], profile="research",
        decided_by="ai_interpretation", interpretation_run_id="run-wsr-2",
    )
    assert started.status_code == 201, started.text
    assert started.json()["work_start"]["interpretation_run_id"] == "run-wsr-2"
    assert started.json()["kind"] == "research"


# ================================================ AC-14 업무화 뒤 기존 경계


def test_after_work_start_the_existing_gates_still_apply(harness):
    """AC-14 — controlled·조사 Profile 차단·v2 완료 계약이 그대로 적용된다."""
    project = harness.create_project()

    # controlled: 논의 중 정한 Autonomy 가 이어지고 시작 확인이 여전히 필요하다.
    controlled = harness.create_conversation(project["id"], "controlled 대화")["case_id"]
    harness.client.put(
        f"/api/cases/{controlled}/autonomy", json={"autonomy": "controlled", "set_by": "owner"}
    )
    ask = _open_request(harness, controlled, "이 범위로 해 주세요.", "c-gate-1")
    assert harness.start_work(controlled, ask["message"]["id"]).status_code == 201
    assert harness.client.get(f"/api/cases/{controlled}/policy").json()["autonomy"] == "controlled"
    design = harness.client.post(
        f"/api/cases/{controlled}/runs",
        json={"run_id": "run-gate-design", "instruction_artifact_id": ask["message"]["artifact_id"],
              "purpose": "design_authoring", "tool_id": FAKE_TOOL_ID, "mode": FAKE_TOOL_MODE},
    )
    assert "controlled_start_not_confirmed" in _refusals(design)

    # 조사 Profile: 업무화가 제품 수정 차단을 풀지 않는다(user_decision 이 없다).
    rca = harness.create_conversation(project["id"], "원인 조사")["case_id"]
    why = _open_request(harness, rca, "왜 느린지 원인을 찾아 주세요.", "c-gate-2")
    assert harness.start_work(rca, why["message"]["id"], profile="root_cause_analysis").status_code == 201
    impl = harness.client.post(
        f"/api/cases/{rca}/runs",
        json={"run_id": "run-gate-impl", "instruction_artifact_id": why["message"]["artifact_id"],
              "purpose": "feature_implementation", "tool_id": FAKE_TOOL_ID,
              "mode": FAKE_TOOL_MODE},
    )
    assert "purpose_outside_case_objective" in _refusals(impl)

    # v2 완료 계약: 업무화 뒤의 의도 초안은 v2 규칙(의무 도출·방식 필수)을 받는다.
    feature = harness.create_conversation(project["id"], "기능")["case_id"]
    req = _open_request(harness, feature, "오류 줄만 뽑아 주세요.", "c-gate-3")
    assert harness.start_work(feature, req["message"]["id"]).status_code == 201
    authoring = harness.client.post(
        f"/api/cases/{feature}/runs",
        json={"run_id": "run-gate-draft", "instruction_artifact_id": req["message"]["artifact_id"],
              "purpose": "intent_authoring", "tool_id": FAKE_TOOL_ID, "mode": FAKE_TOOL_MODE,
              "request_id": req["request"]["id"]},
    )
    assert authoring.status_code == 201, authoring.text
    harness.agent.poll_once()
    criteria = harness.criteria(feature)
    assert criteria and all(c["obligation"] for c in criteria)
    no_method = harness.record_result(feature, criteria[0]["id"], "met")
    assert no_method.status_code == 409
    assert "satisfaction_required" in no_method.text


# ========================================================= AC-15 대화 문맥


def test_runs_receive_the_conversation_as_fixed_context_with_roles(harness):
    """AC-15 — 저장된 대화가 역할·순번대로 고정 참조가 된다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    first = _open_request(harness, case_id, "아직 문서는 쓰지 마세요. 구조부터 봐요.", "c-ctx-1")
    harness.discussion_reply(case_id, first["request"]["id"], "run-ctx-1")
    harness.settle(case_id, first["request"]["id"])
    # 유실된 메시지는 접수되지 않은 입력이다. 문맥에 넣지 않는다.
    lost = harness.post_message(case_id, "유실", "c-ctx-lost").json()
    Repository(harness.client.app.state.conn).mark_intake_lost(lost["message"]["intake_id"])
    second = _open_request(harness, case_id, "좋아요, 이 범위로 구현해 주세요.", "c-ctx-2")
    harness.discussion_reply(case_id, second["request"]["id"], "run-ctx-2")

    refs = harness.client.get("/api/runs/run-ctx-2/context-refs").json()
    items = refs if isinstance(refs, list) else refs["refs"]
    assistant = harness.conversation(case_id)["messages"][1]
    assert [(r["role"], r["artifact_id"]) for r in items] == [
        ("conversation_user_message", first["message"]["artifact_id"]),
        ("conversation_assistant_message", assistant["artifact_id"]),
    ]
    prompt = harness.agent.cli_executor.calls[-1]["prompt"]
    assert "대화에서 **사용자가 한 말**" in prompt
    assert "대화에서 **AI 가 한 말**" in prompt
    assert "아직 문서는 쓰지 마세요" in prompt

    assert harness.start_work(case_id, second["message"]["id"]).status_code == 201
    harness.client.post(
        f"/api/cases/{case_id}/runs",
        json={"run_id": "run-ctx-draft", "instruction_artifact_id": second["message"]["artifact_id"],
              "purpose": "intent_authoring", "tool_id": FAKE_TOOL_ID, "mode": FAKE_TOOL_MODE,
              "request_id": second["request"]["id"]},
    )
    harness.agent.poll_once()
    draft_refs = harness.client.get("/api/runs/run-ctx-draft/context-refs").json()
    draft_items = draft_refs if isinstance(draft_refs, list) else draft_refs["refs"]
    roles = [r["role"] for r in draft_items]
    assert roles[:3] == [
        "conversation_user_message",
        "conversation_assistant_message",
        "conversation_assistant_message",
    ]
    # 지시로 받은 업무 요청 메시지는 두 번 주지 않는다.
    assert second["message"]["artifact_id"] not in [r["artifact_id"] for r in draft_items]

    # QG-01 검토의 요청 원문은 업무 요청 메시지다.
    intent = harness.latest_intent(case_id)
    review = harness.ai_gate_review(case_id, intent, run_id="run-ctx-review")
    assert review.status_code == 201, review.text
    review_refs = harness.client.get("/api/runs/run-ctx-review/context-refs").json()
    review_items = review_refs if isinstance(review_refs, list) else review_refs["refs"]
    original = [r for r in review_items if r["role"] == "original_request"]
    assert [r["artifact_id"] for r in original] == [second["message"]["artifact_id"]]
    assert first["message"]["artifact_id"] in [r["artifact_id"] for r in review_items]


def test_a_case_without_a_conversation_keeps_its_old_context(harness):
    """AC-15 — 대화가 없는 Case 의 문맥은 바뀌지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], "기존 흐름")
    harness.ai_draft(case["id"])
    refs = harness.client.get("/api/runs/run-draft-1/context-refs").json()
    items = refs if isinstance(refs, list) else refs["refs"]
    assert not [r for r in items if r["role"].startswith("conversation_")]


# ================================================ AC-20 경계: 본문 없음·권한


def test_new_ui01_tables_have_no_body_columns(harness):
    """AC-20 — 새 표에 본문 컬럼이 없고 요약에는 길이 상한이 있다."""
    conn = _db(harness)
    body_like = {"content", "body", "text", "raw", "payload", "content_text", "full_text",
                 "message", "diff", "log"}
    for table in (
        "conversation_message",
        "conversation_message_ref",
        "conversation_request",
        "case_work_start",
        "case_visibility_event",
    ):
        columns = {r["name"] for r in conn.execute(f'PRAGMA table_info("{table}")')}
        assert columns, f"{table} 이 없다"
        assert not (columns & body_like), f"{table} 에 본문 컬럼이 있다: {columns & body_like}"
    sql = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE name IN"
        " ('conversation_message', 'conversation_request', 'case_work_start')"
    ).fetchall()
    for row in sql:
        assert "<= 200" in row["sql"], row["name"]
    conn.close()


def test_the_conversation_grants_nothing(harness):
    """AC-20 — 대화·업무화가 강제 축·게시 허용을 바꾸지 않는다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    before = harness.client.get(f"/api/cases/{case_id}/policy").json()["enforcement"]
    sent = _open_request(harness, case_id, "이 범위로 해 주세요.", "c-grant-1")
    harness.start_work(case_id, sent["message"]["id"])
    policy = harness.client.get(f"/api/cases/{case_id}/policy").json()
    assert policy["enforcement"] == before
    assert policy["repositories"]["write_allowance_implies_publish"] is False
    assert policy["delegation_basis"]["current"]["basis_kind"] == "original_request"
    assert not policy["delegation_basis"]["current"]["decision_id"]


def test_the_discussion_prompt_forbids_claiming_work_and_labels_who_spoke():
    """AC-12·AC-15 — 논의 지시문은 읽기 전용·하지 않은 작업 주장 금지·금지 유지를 말하고,
    문맥 표지는 사용자의 말과 AI 의 말을 나눈다."""
    from runner import prompts

    assert prompts.has_prompt(RunPurpose.DISCUSSION_REPLY.value)
    built = prompts.build(
        RunPurpose.DISCUSSION_REPLY.value,
        "이 구조가 괜찮을까요?".encode("utf-8"),
        context=[
            {"role": "conversation_user_message", "artifact_id": "art-u", "revision": 1,
             "body": "아직 문서는 쓰지 마세요".encode("utf-8")},
            {"role": "conversation_assistant_message", "artifact_id": "art-a", "revision": 1,
             "body": "두 가지 안이 있습니다".encode("utf-8")},
        ],
    )
    assert "코드를 바꾸지 말고 파일도 만들지 마라" in built
    assert "하지 않은 작업을 시작했거나 끝냈다고 말하지" in built
    assert "금지가 풀리지 않는다" in built
    assert "대화에서 **사용자가 한 말**" in built
    assert "이전 제안일 뿐 사용자의 요구·결정이 아니다" in built
    # 사용자의 마지막 메시지는 문맥 **다음**에 온다.
    assert built.index("고정 컨텍스트 끝") < built.index("이 구조가 괜찮을까요?")


def test_a_read_only_discussion_is_not_blocked_by_the_start_check_or_pending_deltas():
    """AC-12 — 논의 응답은 controlled 시작 확인·미확인 누적 변경에 막히지 않는다.

    둘 다 **작업을 막는** 조건이다. 논의 응답은 읽기 전용이라 아무 것도 바꾸지 않고,
    그것까지 막으면 사람이 시작 범위나 그 변경을 **이야기할** 수단이 없어진다. 같은
    상태에서 쓰기 목적은 여전히 막힌다 — 좁힌 것이 느슨해진 것이 아니다.
    """
    from controller.admission import AdmissionRequest, evaluate
    from domain.models import CaseKind

    def request(purpose: RunPurpose, permission: Permission) -> AdmissionRequest:
        return AdmissionRequest(
            case_id="case-x",
            case_kind=CaseKind.FEATURE,
            case_closed=False,
            run_id="run-x",
            task_id="task-1",
            purpose=purpose,
            role=RunRole.AUTHOR,
            permission=permission,
            tool_id="codex",
            session="new",
            instruction_availability="available",
            intent_state={},
            gate_state={},
            target_intent_version_id=None,
            tool_installed=True,
            permission_mapped=True,
            tool_is_coding_cli=True,
            checkpoint_state={"required": True, "start_confirmed": False},
            material_delta_state={
                "pending": [{"target_key": "C-01"}],
                "blocks_all_tasks": True,
            },
            request_id="req-x",
            request_state={
                "id": "req-x",
                "in_case": True,
                "state": "processing",
                "opening_receipt": "stored",
                "opening_artifact_id": "art-x",
                "opening_artifact_rev": 1,
            },
            instruction_artifact=("art-x", 1),
        )

    discussion = evaluate(request(RunPurpose.DISCUSSION_REPLY, Permission.READ_ONLY))
    assert discussion.admitted, discussion.refusals
    assert discussion.profile.value == "conversation"

    experiment = evaluate(request(RunPurpose.LOCAL_EXPERIMENT, Permission.READ_ONLY))
    codes = [r.value for r in experiment.refusals]
    assert "controlled_start_not_confirmed" in codes
    assert "material_delta_unconfirmed" in codes
