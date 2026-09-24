"""UI-03 — 요청 처리기와 AI 해석에 의한 최초 업무화(plans/UI-PLAN-03.md).

사람·하네스가 하던 "요청 처리"를 제어부의 처리기가 한다: 저장된 사용자 요청마다 **읽기 전용
논의 응답 하나**를 만들고 그 결과로 요청을 끝낸다. 준비 단계의 응답은 AI 가 사용자의 마지막
메시지를 어떻게 읽었는지 보고하고, 명확한 업무 요청이면 같은 Case 에서 업무화한다(D-69).

이 파일이 지키는 것:

    처리기는 **판정하지 않는다**   진입 검사·요청 종료·업무화 조건은 기존 경로가 한다
    처리기는 **읽기 전용 하나만**  업무 단계의 다음 작업을 시작하지 않는다
    해석은 **권한이 아니다**       위임 근거는 사용자 메시지 원문이고, 해석에는 본문이 없다

시험 이름 옆의 AC 번호는 UI-PLAN-03 5절이다.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

from controller.app import create_app
from controller.repository import Repository
from controller.request_processor import RequestProcessor, reply_run_id
from domain import conversation as convmod
from domain.models import (
    CaseProfile,
    InterpretationKind,
    InterpretationRefusal,
    InterpretationStatus,
    RequestSettleOutcome,
    RunOutcome,
)
from runner import prompts
from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE, RUNNER_ID

MARKER = "UI03-BODY-MARKER-4c7e"

WORK_BLOCK = '```hads-interpretation\n{"kind": "work_request", "profile": "research"}\n```'
DISCUSSION_BLOCK = '```hads-interpretation\n{"kind": "discussion"}\n```'


# ---------------------------------------------------------------- 도우미


def _db(harness) -> sqlite3.Connection:
    conn = sqlite3.connect(harness.controller_config.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _conversation(harness, title: str = "새 대화") -> tuple[dict, str]:
    project = harness.create_project()
    view = harness.create_conversation(project["id"], title)
    return project, view["case_id"]


def _request_of(harness, case_id: str, client_id: str) -> dict[str, Any]:
    view = harness.conversation(case_id)
    message = next(m for m in view["messages"] if m["client_message_id"] == client_id)
    return next(r for r in view["requests"] if r["id"] == message["request_id"])


def _runs(harness, case_id: str) -> list[dict[str, Any]]:
    return harness.client.get(f"/api/cases/{case_id}").json()["runs"]


def _set_reply(harness, text: str) -> None:
    harness.agent.cli_executor.discussion_response = text


# ================================================== 순수 규칙 (domain.conversation)


def test_the_interpretation_block_is_split_from_the_reply():
    """AC-5 — 블록은 기계용이다. 사람에게 붙는 것은 나머지 글뿐이다."""
    text, parsed = convmod.split_interpretation(f"조사하겠습니다.\n\n{WORK_BLOCK}\n")
    assert text == "조사하겠습니다."
    assert (parsed.status, parsed.kind, parsed.profile) == (
        InterpretationStatus.REPORTED,
        InterpretationKind.WORK_REQUEST,
        CaseProfile.RESEARCH,
    )
    # 없으면 missing — 논의로 바꿔 읽지 않는다.
    text, parsed = convmod.split_interpretation("그냥 답입니다.")
    assert (text, parsed.status, parsed.kind) == ("그냥 답입니다.", InterpretationStatus.MISSING, None)
    # 형식이 틀리면 invalid. 글은 남는다.
    for broken in (
        "```hads-interpretation\n{not json}\n```",
        '```hads-interpretation\n{"kind": "work_request"}\n```',  # Profile 없는 업무 요청
        '```hads-interpretation\n{"kind": "work_request", "profile": "hobby"}\n```',
        '```hads-interpretation\n{"kind": "maybe"}\n```',
        f"{DISCUSSION_BLOCK}\n{WORK_BLOCK}",  # 둘 — 어느 쪽이 판단인지 모른다
    ):
        text, parsed = convmod.split_interpretation(f"답\n{broken}")
        assert text == "답"
        assert parsed.status is InterpretationStatus.INVALID, broken


def test_a_reported_interpretation_is_rechecked_on_the_controller():
    """AC-5 — 제어부는 Runner 의 판정을 그대로 믿지 않는다."""
    ok = convmod.interpretation_from_report(
        {"status": "reported", "kind": "work_request", "profile": "defect_fix"}
    )
    assert ok.profile is CaseProfile.DEFECT_FIX
    forged = convmod.interpretation_from_report(
        {"status": "reported", "kind": "work_request", "profile": "everything"}
    )
    assert forged.status is InterpretationStatus.INVALID
    assert convmod.interpretation_from_report("work!").status is InterpretationStatus.INVALID
    assert convmod.interpretation_from_report({"status": "missing"}).status is (
        InterpretationStatus.MISSING
    )


def test_only_a_completed_reported_work_request_is_applied():
    """AC-6 — 적용을 시도하는 조건은 셋뿐이다: 보고됨·업무 요청·응답 완료."""
    work = convmod.Interpretation(
        InterpretationStatus.REPORTED, InterpretationKind.WORK_REQUEST, CaseProfile.FEATURE
    )
    talk = convmod.Interpretation(InterpretationStatus.REPORTED, InterpretationKind.DISCUSSION)
    missing = convmod.Interpretation(InterpretationStatus.MISSING)
    assert convmod.interpretation_refusal(work, "completed") is None
    assert convmod.interpretation_refusal(work, "failed") is InterpretationRefusal.REPLY_NOT_COMPLETED
    assert convmod.interpretation_refusal(talk, "completed") is (
        InterpretationRefusal.NOT_A_WORK_REQUEST
    )
    assert convmod.interpretation_refusal(missing, "completed") is (
        InterpretationRefusal.NOT_REPORTED
    )


def test_the_processor_asks_completed_only_for_an_answer_the_person_can_see():
    """AC-2 — 응답이 완료되고 대화에 붙었을 때만 `completed` 를 요청한다."""
    assert convmod.processor_settle_outcome("completed", True) is RequestSettleOutcome.COMPLETED
    assert convmod.processor_settle_outcome("completed", False) is RequestSettleOutcome.FAILED
    assert convmod.processor_settle_outcome("failed", False) is RequestSettleOutcome.FAILED
    assert convmod.processor_settle_outcome(None, False) is RequestSettleOutcome.FAILED


def test_the_rule_is_added_only_to_discussion_stage_replies():
    """AC-5 — 업무 단계 응답의 해석은 쓰이지 않으므로 규칙을 붙이지 않는다."""
    discussion = prompts.build("discussion_reply", b"hi", conversation_stage="discussion")
    work = prompts.build("discussion_reply", b"hi", conversation_stage="work")
    assert "hads-interpretation" in discussion
    assert "hads-interpretation" not in work
    assert discussion.startswith(prompts.DISCUSSION_REPLY_PROMPT[:40])
    # 사용자의 말은 규칙 **뒤에** 온다 — 규칙이 사용자의 말 안에 섞이지 않는다.
    assert discussion.index("hads-interpretation") < discussion.index("hi")


# ================================================== AC-1 시작


def test_a_stored_request_gets_exactly_one_read_only_reply_run(processing_harness):
    """AC-1 — 저장 보고 뒤 응답 하나. 저장 전에는 만들지 않고 재보고에도 늘지 않는다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    response = h.post_message(case_id, f"어떻게 나눌까요? {MARKER}", "c-1")
    assert response.status_code == 202
    assert _runs(h, case_id) == []  # 접수 대기 — 받지 않은 말은 처리하지 않는다

    h.agent.persist_pending_intakes()
    request = _request_of(h, case_id, "c-1")
    runs = _runs(h, case_id)
    assert [r["run_id"] for r in runs] == [reply_run_id(request["id"])]
    run = runs[0]
    assert (run["purpose"], run["permission"], run["role"]) == (
        "discussion_reply", "read_only", "author"
    )
    assert (run["tool_id"], run["mode"]) == (FAKE_TOOL_ID, FAKE_TOOL_MODE)
    opening = h.conversation(case_id)["messages"][0]
    detail = h.client.get(f"/api/runs/{run['run_id']}").json()
    assert (detail["instruction_artifact_id"], detail["instruction_artifact_rev"]) == (
        opening["artifact_id"], opening["artifact_rev"]
    )
    assert detail["request_id"] == request["id"]

    # 같은 저장 보고의 재전송이 두 번째 응답을 만들지 않는다.
    again = h.client.post(
        f"/api/runner/intakes/{opening['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": opening["content_hash"]},
    )
    assert again.status_code == 200, again.text
    assert len(_runs(h, case_id)) == 1


def test_a_card_answer_opens_no_request_and_starts_nothing(processing_harness):
    """AC-1 — 카드 답변은 요청을 열지 않는다. 처리기가 만들 것이 없다."""
    from tests.test_conversation import _case_with_question

    h = processing_harness
    _project, case, intent, question = _case_with_question(h)
    before = len(_runs(h, case["id"]))
    h.send_message(
        case["id"],
        "범위는 A 입니다",
        "c-card",
        kind="card_answer",
        question_id=question["id"],
        intent_version_id=intent["id"],
    )
    assert len(_runs(h, case["id"])) == before
    assert h.conversation(case["id"])["current_request"] is None


# ================================================== AC-2 끝


def test_the_reply_is_attached_and_the_request_completes(processing_harness):
    """AC-2 — 응답 → AI 메시지 → 요청 completed → 전송이 다시 열린다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    h.send_message(case_id, "두 방향을 비교해 주세요", "c-1")
    assert h.conversation(case_id)["send"]["general"]["allowed"] is False  # 처리 중
    h.agent.poll_once()

    view = h.conversation(case_id)
    assert [m["author"] for m in view["messages"]] == ["user", "assistant"]
    request = view["requests"][0]
    assert (request["state"], request["settled_by"]) == ("completed", "request-processor")
    assert view["current_request"] is None
    assert view["send"]["general"]["allowed"] is True
    assert view["processing"]["auto"] is True
    # 준비 단계 응답이라 해석이 보고됐다(블록 없음 → missing). 업무화하지 않았다.
    assert view["stage"] == "discussion"
    [interp] = view["interpretations"]
    assert (interp["report_status"], interp["applied"], interp["refusal"]) == (
        "missing", False, "not_reported"
    )


def test_a_failed_reply_fails_the_request_and_unlocks(processing_harness):
    """AC-2 — 답을 받지 못했으면 완료로 적지 않는다. 잠금은 풀린다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    h.agent.cli_executor.outcome = RunOutcome.FAILED
    h.agent.cli_executor.residual_activity = "none"
    h.agent.cli_executor.residual_basis = "in_process"
    h.send_message(case_id, "질문", "c-1")
    h.agent.poll_once()
    view = h.conversation(case_id)
    request = view["requests"][0]
    assert (request["state"], request["note_summary"]) == ("failed", "reply_not_completed")
    assert [m["author"] for m in view["messages"]] == ["user"]
    assert view["send"]["general"]["allowed"] is True
    assert view["interpretations"] == []  # 끝나지 않은 응답에는 해석이 없다


def test_an_unknown_reply_keeps_the_lock_as_before(processing_harness):
    """AC-2 — 끝났는지 모르는 응답이면 UI-02 판정 그대로 잠긴다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    h.agent.cli_executor.outcome = RunOutcome.UNKNOWN
    h.send_message(case_id, "질문", "c-1")
    h.agent.poll_once()
    view = h.conversation(case_id)
    assert view["current_request"]["state"] == "unknown"
    assert view["send"]["general"]["refusal"] == "request_state_unknown"


def test_another_unfinished_run_defers_the_settlement(processing_harness):
    """AC-2 — 사람이 같은 요청에 붙인 실행이 끝날 때까지 끝내지 않는다(실행 사이에 풀지 않음)."""
    h = processing_harness
    _project, case_id = _conversation(h)
    h.send_message(case_id, "질문", "c-1")
    request = _request_of(h, case_id, "c-1")
    extra = h.discussion_reply(case_id, request["id"], "run-extra", execute=False)
    assert extra.status_code == 201, extra.text

    hold = threading.Event()
    h.agent.cli_executor.hold = hold
    worker = threading.Thread(target=h.agent.execution_tick)
    worker.start()
    try:
        # 처리기의 응답은 끝나지 않았고 사람이 붙인 실행도 남아 있다 — 처리 중이다.
        assert h.conversation(case_id)["current_request"]["state"] == "processing"
    finally:
        hold.set()
        worker.join(timeout=30)
    assert not worker.is_alive()
    h.agent.cli_executor.hold = None
    h.agent.poll_once()  # 남은 배정이 있으면 마저 돈다

    runs = {r["run_id"]: r for r in _runs(h, case_id)}
    assert set(runs) == {reply_run_id(request["id"]), "run-extra"}
    assert all(r["status"] == "finished" for r in runs.values())
    settled = _request_of(h, case_id, "c-1")
    assert settled["state"] == "completed"
    assert settled["settled_at"] >= max(r["finished_at"] for r in runs.values())


# ================================================== AC-3 만들 수 없음


def test_no_reply_tool_closes_the_request_with_a_reason(processing_harness):
    """AC-3 — 확인된 코딩 CLI 가 없으면 만들지 않고 이유와 함께 끝낸다(잠금이 남지 않는다)."""
    h = processing_harness
    response = h.client.post(
        "/api/projects",
        json={"name": "no-cli", "repo_path": "C:/tmp/demo", "default_tool_id": "claude"},
    )
    project = response.json()
    view = h.create_conversation(project["id"])
    case_id = view["case_id"]
    h.send_message(case_id, "질문", "c-1")
    assert _runs(h, case_id) == []
    request = _request_of(h, case_id, "c-1")
    assert request["state"] == "failed"
    assert request["note_summary"].startswith("reply_tool_unavailable: claude")
    assert h.conversation(case_id)["send"]["general"]["allowed"] is True


def test_an_admission_refusal_closes_the_request_and_is_recorded(processing_harness):
    """AC-3 — 진입 거부(예산 hard)는 진입 검사 기록에 남고 요청은 이유와 함께 끝난다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    response = h.client.put(
        f"/api/cases/{case_id}/budget",
        json={"metric": "run_count", "threshold_kind": "hard", "limit_value": 1, "set_by": "owner"},
    )
    assert response.status_code == 201, response.text
    h.send_message(case_id, "첫 질문", "c-0")  # 한도 1 을 이 응답이 쓴다
    h.agent.poll_once()
    assert _request_of(h, case_id, "c-0")["state"] == "completed"
    h.send_message(case_id, "질문", "c-1")
    assert len(_runs(h, case_id)) == 1
    request = _request_of(h, case_id, "c-1")
    assert request["state"] == "failed"
    assert request["note_summary"].startswith("reply_refused:")
    assert "budget" in request["note_summary"]
    [check] = [
        c for c in h.admission_checks(case_id)
        if c["requested_run_id"] == reply_run_id(request["id"])
    ]
    assert check["outcome"] == "refused"
    assert any("budget" in code for code in check["refusals"])


# ================================================== AC-4 중단·복구·끄기


def test_a_stopped_request_is_left_to_the_controller(processing_harness):
    """AC-4 — 중단이 요청된 요청은 처리기가 끝내지 않는다. UI-02 대로 제어부가 확인 뒤 끝낸다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    h.send_message(case_id, "질문", "c-1")
    request = _request_of(h, case_id, "c-1")
    stopped = h.client.post(
        f"/api/cases/{case_id}/requests/{request['id']}/stop",
        json={"actor": "owner", "reason": "그만"},
    )
    assert stopped.status_code == 200, stopped.text
    request = _request_of(h, case_id, "c-1")
    assert (request["state"], request["outcome_reason"], request["settled_by"]) == (
        "interrupted", "stopped_by_request", "controller"
    )
    [run] = _runs(h, case_id)
    assert (run["outcome"], run["not_started_reason"]) == ("cancelled", "stop_requested")
    h.agent.poll_once()  # 가져갈 것이 없다
    assert h.agent.cli_executor.calls == []


def test_startup_recovery_creates_missing_replies_and_settles_finished_requests(
    harness, tmp_path
):
    """AC-4 — 처리기가 돌기 전에 제어부가 끝났어도 기동 복구가 빠진 단계를 잇는다."""
    h = harness  # 처리기 꺼짐으로 "처리기가 돌지 못한 상태"를 만든다
    _project, first = _conversation(h, "응답 실행이 없는 요청")
    h.send_message(first, "첫째", "c-a")
    project = h.create_project("other")
    second = h.create_conversation(project["id"], "실행이 끝났는데 닫히지 않은 요청")["case_id"]
    h.send_message(second, "둘째", "c-b")
    second_request = _request_of(h, second, "c-b")
    run = h.discussion_reply(second, second_request["id"], "run-manual")
    assert run.status_code == 201
    assert _request_of(h, second, "c-b")["state"] == "processing"  # 끄면 아무도 닫지 않는다

    config = h.controller_config.__class__(
        data_root=h.controller_config.data_root,
        web_dist=None,
        runner_stale_seconds=h.controller_config.runner_stale_seconds,
        auto_process_requests=True,
    )
    with TestClient(create_app(config)) as restarted:
        first_view = restarted.get(f"/api/cases/{first}/conversation").json()
        second_view = restarted.get(f"/api/cases/{second}/conversation").json()
    first_request = first_view["requests"][0]
    assert first_request["state"] == "processing"
    assert [r["run_id"] for r in first_request["runs"]] == [reply_run_id(first_request["id"])]
    assert second_view["requests"][0]["state"] == "completed"
    assert second_view["requests"][0]["settled_by"] == "request-processor"


def test_turning_the_processor_off_keeps_the_manual_contract(harness):
    """AC-4 — 끄면 UI-01 명시 계약 그대로다. 조회가 그 사실을 말한다."""
    h = harness
    _project, case_id = _conversation(h)
    h.send_message(case_id, "질문", "c-1")
    assert _runs(h, case_id) == []
    view = h.conversation(case_id)
    assert view["processing"]["auto"] is False
    assert view["current_request"]["state"] == "processing"


# ================================================== AC-5·6·7 해석과 업무화


def test_a_clear_work_request_starts_work_in_the_same_case(processing_harness):
    """AC-6 — 명확한 업무 요청이면 같은 Case 에서 업무화한다. 위임 근거는 사용자 메시지다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    _set_reply(h, f"로그 형식을 조사해 개선안을 정리하겠습니다. 범위는 서버 로그입니다.\n\n{WORK_BLOCK}")
    h.send_message(case_id, f"서버 로그를 분석해서 개선안을 정리해줘 {MARKER}", "c-1")
    h.agent.poll_once()

    view = h.conversation(case_id)
    request = view["requests"][0]
    reply_id = reply_run_id(request["id"])
    assert (view["stage"], view["profile"], view["profile_source"]) == (
        "work", "research", "work_start"
    )
    work = view["work_start"]
    assert (work["decided_by"], work["interpretation_run_id"], work["actor"]) == (
        "ai_interpretation", reply_id, f"ai:{FAKE_TOOL_ID}"
    )
    assert work["request_message_id"] == view["messages"][0]["id"]
    assert MARKER not in work["summary"]  # 요약은 본문에서 만들지 않는다
    policy = h.client.get(f"/api/cases/{case_id}/policy").json()
    basis = policy["delegation_basis"]["current"]
    assert (basis["basis_kind"], basis["artifact_id"]) == (
        "original_request", view["messages"][0]["artifact_id"]
    )
    [interp] = view["interpretations"]
    assert (interp["report_status"], interp["kind"], interp["profile"], interp["applied"]) == (
        "reported", "work_request", "research", True
    )
    # P4-05. 업무화 자체는 권한·동의를 만들지 않지만, 그 뒤의 첫 걸음(의도 초안 작성)은 **진행기가
    # 같은 요청에** 만든다 — 실행 사이에 잠금을 풀지 않는다(D-70). UI-03 때는 응답 하나로 끝났다.
    assert request["state"] == "processing"
    runs = _runs(h, case_id)  # 최신 순이다
    assert runs[-1]["run_id"] == reply_id
    assert [(r["purpose"], r["request_id"]) for r in runs[:-1]] == [
        ("intent_authoring", request["id"])
    ]
    assert view["progress"]["state"] == "running"
    assert view["progress"]["step"] == "intent_authoring"
    # 규칙을 받았고, 대화에 붙은 글에는 블록이 없다.
    assert "hads-interpretation" in h.agent.cli_executor.calls[-1]["prompt"]
    reply = view["messages"][1]
    _read, body = h.read_original(reply["artifact_id"], reply["artifact_rev"])
    assert "로그 형식을 조사해" in body and "hads-interpretation" not in body


def test_a_discussion_keeps_the_discussion_stage(processing_harness):
    """AC-6 — 논의로 읽었으면 업무화하지 않는다. 동의는 그 선택에만 적용된다(D-69)."""
    h = processing_harness
    _project, case_id = _conversation(h)
    _set_reply(h, f"좋습니다, A 방식으로 생각해 보죠.\n{DISCUSSION_BLOCK}")
    h.send_message(case_id, "A 방식이 좋겠어요", "c-1")
    h.agent.poll_once()
    view = h.conversation(case_id)
    assert (view["stage"], view["work_start"]) == ("discussion", None)
    [interp] = view["interpretations"]
    assert (interp["kind"], interp["applied"], interp["refusal"]) == (
        "discussion", False, "not_a_work_request"
    )


def test_a_broken_block_starts_nothing_but_keeps_the_reply(processing_harness):
    """AC-5 — 형식이 틀린 해석은 업무를 열지 않는다. 응답 글은 붙는다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    _set_reply(h, '조사하겠습니다.\n```hads-interpretation\n{"kind": "work_request"}\n```')
    h.send_message(case_id, "분석해줘", "c-1")
    h.agent.poll_once()
    view = h.conversation(case_id)
    assert view["stage"] == "discussion"
    [interp] = view["interpretations"]
    assert (interp["report_status"], interp["kind"], interp["applied"], interp["refusal"]) == (
        "invalid", "work_request", False, "not_reported"
    )
    assert [m["author"] for m in view["messages"]] == ["user", "assistant"]
    assert view["requests"][0]["state"] == "completed"


def test_a_reply_that_is_only_a_block_fails(processing_harness):
    """AC-5 — 떼고 나니 글이 없으면 사람에게 보일 말이 없다. 실행은 실패다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    _set_reply(h, WORK_BLOCK)
    h.send_message(case_id, "분석해줘", "c-1")
    h.agent.poll_once()
    view = h.conversation(case_id)
    assert view["stage"] == "discussion"
    assert view["requests"][0]["state"] == "failed"
    assert view["interpretations"] == []
    [run] = _runs(h, case_id)
    assert run["outcome"] == "failed"


def test_work_stage_replies_get_no_rule_and_no_interpretation(processing_harness):
    """AC-5·AC-6 — 업무 단계 대화의 응답은 해석하지 않는다. 목적 변경은 D-86(UI-04)."""
    h = processing_harness
    project = h.create_project()
    case = h.create_case(project["id"])  # 업무 단계(기능 개발)
    _set_reply(h, f"진행 상황입니다.\n{WORK_BLOCK}")
    h.send_message(case["id"], "지금 어디까지 됐나요?", "c-1")
    h.agent.poll_once()
    view = h.conversation(case["id"])
    assert view["interpretations"] == []
    assert "hads-interpretation" not in h.agent.cli_executor.calls[-1]["prompt"]
    assert view["requests"][0]["state"] == "completed"
    reply = view["messages"][-1]
    # 규칙을 받지 않은 응답의 글은 건드리지 않는다.
    _read, body = h.read_original(reply["artifact_id"], reply["artifact_rev"])
    assert "hads-interpretation" in body


def test_a_case_that_already_started_work_refuses_the_ai_start(processing_harness):
    """AC-6 — 사람이 먼저 업무화했으면 AI 해석은 적용되지 않고 사유가 남는다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    _set_reply(h, f"정리하겠습니다.\n{WORK_BLOCK}")
    h.send_message(case_id, "분석해서 정리해줘", "c-1")
    request = _request_of(h, case_id, "c-1")

    hold = threading.Event()
    h.agent.cli_executor.hold = hold
    worker = threading.Thread(target=h.agent.execution_tick)
    worker.start()
    try:
        # 응답이 **도는 동안**(배정은 준비 단계에서 받았다) 사람이 같은 메시지로 먼저 업무화한다.
        deadline = time.monotonic() + 20
        while not h.agent.cli_executor.calls and time.monotonic() < deadline:
            time.sleep(0.02)
        assert h.agent.cli_executor.calls, "응답 실행이 시작되지 않았다"
        started = h.start_work(case_id, request["opened_by_message_id"], profile="feature")
        assert started.status_code == 201, started.text
    finally:
        hold.set()
        worker.join(timeout=30)
    assert not worker.is_alive()

    view = h.conversation(case_id)
    assert (view["profile"], view["work_start"]["decided_by"]) == ("feature", "person")
    [interp] = view["interpretations"]
    assert (interp["applied"], interp["refusal"]) == (False, "case_not_in_discussion_stage")
    # P4-05. 사람이 업무화한 Case 도 진행기가 잇는다 — 응답이 끝난 자리에서 의도 초안 실행이 같은
    # 요청에 붙어 요청은 처리 중으로 남는다(UI-03 때는 여기서 `completed` 였다).
    assert view["requests"][0]["state"] == "processing"
    assert view["progress"]["step"] == "intent_authoring"


def test_an_interpretation_cannot_ride_on_another_run(processing_harness):
    """AC-5 — 해석은 요청의 논의 응답에만 붙는다. 다른 실행이 보내면 거부한다."""
    h = processing_harness
    project = h.create_project()
    case = h.create_case(project["id"], kind="analysis")
    artifact = h.submit_artifact(case["id"], "조사 지시")["artifact_id"]
    h.create_run(case["id"], artifact, "run-analysis")
    claimed = h.client.post(f"/api/runner/{RUNNER_ID}/assignments").json()
    assert [a["run_id"] for a in claimed] == ["run-analysis"]
    response = h.client.post(
        "/api/runner/runs/run-analysis/result",
        json={
            "runner_id": RUNNER_ID,
            "generation": 1,
            "outcome": "completed",
            "interpretation": {"status": "reported", "kind": "work_request", "profile": "feature"},
        },
    )
    assert response.status_code == 409, response.text
    assert h.client.get("/api/runs/run-analysis").json()["status"] != "finished"


def test_the_interpretation_record_keeps_no_body(processing_harness):
    """AC-7·AC-20 — 해석 기록에 본문·요약이 없다. 제어부 DB 어디에도 본문이 없다."""
    h = processing_harness
    _project, case_id = _conversation(h)
    _set_reply(h, f"{MARKER} 를 조사하겠습니다.\n{WORK_BLOCK}")
    h.send_message(case_id, f"{MARKER} 분석해서 정리해줘", "c-1")
    h.agent.poll_once()
    conn = _db(h)
    try:
        columns = {r["name"] for r in conn.execute("PRAGMA table_info(conversation_interpretation)")}
        assert columns == {
            "run_id", "case_id", "request_id", "opening_message_id", "report_status", "kind",
            "profile", "applied", "refusal", "recorded_at", "evaluated_at",
        }
    finally:
        conn.close()
    for path in h.controller_config.data_root.rglob("*"):
        if path.is_file():
            assert MARKER.encode("utf-8") not in path.read_bytes(), path


# ================================================== AC-9 조회


def test_lists_carry_activity_attention_and_derived_connection(processing_harness):
    """AC-9 — 목록의 마지막 활동, 프로젝트 주의 수, 서버가 도출한 PC 연결."""
    h = processing_harness
    project, case_id = _conversation(h)
    h.send_message(case_id, "질문", "c-1")
    listed = h.client.get(f"/api/projects/{project['id']}/conversations").json()
    [row] = [r for r in listed if r["id"] == case_id]
    message_at = h.conversation(case_id)["messages"][0]["created_at"]
    assert row["last_activity_at"] >= message_at
    assert (row["current_request_state"], row["current_request_stopping"]) == ("processing", False)

    projects = {p["id"]: p for p in h.client.get("/api/projects").json()}
    # UI-04b 보충: 주의 수에 예산 도달(`budget_stopped`)이 더해졌다 — 한도가 없는 이 대화는 0 이다.
    assert projects[project["id"]]["attention"] == {
        "needs_response": 0, "request_unknown": 0, "processing": 1, "budget_stopped": 0
    }

    runners = {r["id"]: r for r in h.client.get("/api/runners").json()}
    view = h.conversation(case_id)
    assert runners[RUNNER_ID]["connection"]["state"] == view["send"]["runner_connection"]["state"]
    h.age_heartbeat(7200)
    runners = {r["id"]: r for r in h.client.get("/api/runners").json()}
    assert runners[RUNNER_ID]["connection"]["state"] == "disconnected"


# ================================================== 재현 도우미가 제품 규칙과 같은가


def test_the_processor_can_be_driven_directly_on_a_repository(harness):
    """처리기는 이벤트 세 곳에서 부른다. 직접 불러도 같은 판정이다(기동 복구와 같은 경로)."""
    h = harness
    _project, case_id = _conversation(h)
    h.send_message(case_id, "질문", "c-1")
    conn = sqlite3.connect(h.controller_config.db_path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        repo = Repository(conn)
        processor = RequestProcessor(repo, enabled=True)
        request = _request_of(h, case_id, "c-1")
        run = processor.start(request["id"])
        assert run is not None and run["run_id"] == reply_run_id(request["id"])
        assert processor.start(request["id"]) is None  # 두 번째는 만들지 않는다
        assert processor.finish(request["id"]) is None  # 실행이 끝나지 않았다 — 풀지 않는다
        assert RequestProcessor(repo, enabled=False).recover() == {"started": 0, "finished": 0}
    finally:
        conn.close()
