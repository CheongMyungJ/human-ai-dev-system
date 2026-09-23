"""P4-04 — 문맥·재개(plans/P4-PLAN-04.md).

긴 문맥·세션 교체·부분 복원에서 **핵심 입력이 조용히 빠지지 않고, 빠진 것이 성공으로
보이지 않는지**를 본다(AC-39). 계획(무엇을 주려 했는가)·영수증(무엇을 실제로 읽었는가)·
최신성(고정 뒤 무엇이 새로 생겼는가)·시작하지 않은 실행의 정산·재시작 뒤 사용량 복구를
전부 **API 와 실제 Runner 경로로** 확인한다.

시험 이름 옆의 AC 번호는 P4-PLAN-04 5절이다.
"""

from __future__ import annotations

import dataclasses
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from controller.repository import Repository
from domain import context as ctxmod
from domain.budget import SettleSource
from domain.models import (
    ContextInclusion,
    ContextReceiptStatus,
    ContextTier,
    RunContextState,
    RunOutcome,
)
from runner import prompts
from tests.conftest import FAKE_TOOL_ID, FAKE_TOOL_MODE, RUNNER_ID
from tests.test_conversation import _conversation_case, _open_request
from tests.test_preparation import _agreed_case, _refusals
from tests.test_quality_gates import _failure, _record

REPO_ROOT = Path(__file__).resolve().parent.parent
P1_EVIDENCE = REPO_ROOT / "p1" / "evidence"
#: 실제 codex 0.154.0 의 원시 출력(P1-02). `turn.completed.usage` 가 있다.
CODEX_RAW = P1_EVIDENCE / "codex-read-v2-347eb670.stdout.jsonl"
#: 실제 Claude Code 의 원시 출력(P1-02). `result.usage` 가 있다.
CLAUDE_RAW = P1_EVIDENCE / "claude-read-v2-5f612ab5.stdout.jsonl"
#: 실제로 **강제 종료**한 codex 실행의 원시 출력(P1-03). 사용량 줄이 없다.
KILLED_RAW = P1_EVIDENCE / "p103-kill-d435ff68.stdout.jsonl"

MARKER = "P404-BODY-MARKER-5c2e"


# ---------------------------------------------------------------- 도우미


def _set_limit(harness, limit: int) -> None:
    """실행당 인라인 한도를 바꾼다. 제어부 설정 그대로 — 시험만을 위한 경로가 아니다."""
    app = harness.client.app
    app.state.config = dataclasses.replace(app.state.config, context_inline_limit_bytes=limit)


def _sizes(harness, case_id: str) -> dict[str, int]:
    detail = harness.client.get(f"/api/cases/{case_id}").json()
    return {a["artifact_id"]: int(a["byte_size"]) for a in detail["artifacts"]}


def _run(
    harness,
    case_id: str,
    run_id: str,
    instruction: dict[str, Any],
    purpose: str,
    role: str = "author",
    request_id: str | None = None,
):
    body: dict[str, Any] = {
        "run_id": run_id,
        "instruction_artifact_id": instruction["artifact_id"],
        "purpose": purpose,
        "role": role,
        "tool_id": FAKE_TOOL_ID,
        "mode": FAKE_TOOL_MODE,
        "permission": "read_only",
    }
    if "artifact_rev" in instruction:
        body["instruction_artifact_rev"] = instruction["artifact_rev"]
    if request_id is not None:
        body["request_id"] = request_id
    return harness.client.post(f"/api/cases/{case_id}/runs", json=body)


def _run_view(harness, run_id: str) -> dict[str, Any]:
    response = harness.client.get(f"/api/runs/{run_id}")
    assert response.status_code == 200, response.text
    return response.json()


def _reservations(harness, case_id: str, run_id: str) -> dict[str, dict[str, Any]]:
    budget = harness.client.get(f"/api/cases/{case_id}/budget").json()
    return {r["metric"]: r for r in budget["reservations"] if r["run_id"] == run_id}


def _draft_case(harness) -> tuple[dict, dict]:
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.ai_draft(case["id"])
    return case, harness.latest_intent(case["id"])


def _simulate_crash_after_start(harness, run_id: str, raw: Path | None) -> None:
    """Runner 가 실행을 **시작한 뒤** 결과를 보고하기 전에 죽은 상태를 만든다.

    원장에 착수를 적고(실행 전 원장 기록은 실제 경로와 같다) CLI 원시 출력을 제자리에
    둔다. 원시 출력은 **실제 CLI 가 쓴 파일**이다(P1 증거).

    UI-02 원장 v2 에서는 "시작한 뒤"가 **시작 기록**(`launch`)까지를 뜻한다 — 착수만 있고
    시작 기록이 없으면 CLI 가 재개되지 않은 실행이다. 이 시험들이 보는 것은 P4-04 의 사용량
    복구이므로 **트리 제어 없이 시작된** 기록을 둔다(job 이름·pid 없음). 그러면 잔류는
    지금처럼 확인할 수 없다(`unknown`). job 으로 확인하는 경로는 `test_run_control.py` 가 본다.
    """
    harness.agent.ledger.claim(run_id, 1)
    harness.agent.ledger.record_launch(run_id, {"pid": None, "kill_on_close": False})
    if raw is not None:
        target = harness.runner_config.raw_dir / f"{run_id}.stdout.jsonl"
        shutil.copyfile(raw, target)


# ================================================== 순수 규칙 (domain.context)


def test_tiers_come_from_the_role_and_unknown_roles_are_core():
    """AC-1 — 등급은 역할에서 나온다. AI 의 이전 제안만 보조이고 모르는 역할은 핵심이다."""
    assert ctxmod.tier_for("conversation_assistant_message") is ContextTier.SUPPORTING
    for role in (
        "conversation_user_message",
        "original_request",
        "agreed_intent",
        "previous_intent",
        "question_answer",
        "feedback",
        "current_plan",
        "a_role_added_later",
    ):
        assert ctxmod.tier_for(role) is ContextTier.CORE, role


def _ref(role: str, size: int, n: int) -> dict[str, Any]:
    return {"role": role, "artifact_id": f"art-{n}", "revision": 1, "byte_size": size}


def test_the_inline_plan_drops_only_old_supporting_items_and_holds_when_core_overflows():
    """AC-2·AC-3 — 한도 안이면 전부, 넘으면 오래된 보조만, 핵심이 넘으면 보류."""
    refs = [
        _ref("conversation_user_message", 100, 1),
        _ref("conversation_assistant_message", 300, 2),
        _ref("conversation_user_message", 100, 3),
        _ref("conversation_assistant_message", 300, 4),
    ]
    whole = ctxmod.plan_inline(50, refs, 10_000)
    assert not whole.over_limit and not whole.omitted
    assert [r["inclusion"] for r in whole.refs] == ["inline"] * 4
    assert whole.inline_bytes == whole.full_bytes == 850

    # 550 까지: 오래된 AI 제안 하나만 빠진다. 최근 제안·사용자 말은 남는다.
    trimmed = ctxmod.plan_inline(50, refs, 560)
    assert [(r["tier"], r["inclusion"]) for r in trimmed.refs] == [
        ("core", "inline"),
        ("supporting", "omitted_size_limit"),
        ("core", "inline"),
        ("supporting", "inline"),
    ]
    assert trimmed.inline_bytes == 550 and trimmed.inline_bytes <= trimmed.limit
    assert trimmed.summary()["omitted_count"] == 1

    # 지시 + 핵심(250) 만 남아도 넘으면 보류 — 핵심을 자르지 않는다.
    held = ctxmod.plan_inline(50, refs, 200)
    assert held.over_limit
    assert held.core_bytes == 250
    assert all(r["inclusion"] == "inline" for r in held.refs)

    with pytest.raises(ValueError):
        ctxmod.plan_inline(0, refs, 0)


def test_a_receipt_must_match_the_plan():
    """AC-6 — 순번을 빠짐없이, 인라인 참조를 생략으로 주장하지 못한다."""
    refs = [
        {"seq": 1, "role": "agreed_intent", "inclusion": "inline"},
        {"seq": 2, "role": "conversation_assistant_message", "inclusion": "omitted_size_limit"},
    ]
    good = [
        {"seq": 0, "status": "read"},
        {"seq": 1, "role": "agreed_intent", "status": "read"},
        {"seq": 2, "status": "omitted"},
    ]
    assert ctxmod.check_receipt(refs, good) == []
    assert ctxmod.check_receipt(refs, good[:2])  # 빠진 순번
    assert ctxmod.check_receipt(refs, [good[0], {"seq": 1, "status": "omitted"}, good[2]])
    assert ctxmod.check_receipt(refs, [good[0], good[1], {"seq": 2, "status": "read"}])
    assert ctxmod.check_receipt(refs, [*good, {"seq": 9, "status": "read"}])
    assert ctxmod.check_receipt(refs, [{"seq": 0, "status": "omitted"}, *good[1:]])
    assert ctxmod.check_receipt(refs, [good[0], {"seq": 1, "role": "feedback",
                                                  "status": "read"}, good[2]])


def test_the_run_context_state_distinguishes_four_cases():
    """AC-10 — 완전·부분·차단·미보고. 영수증이 없으면 읽음으로 적지 않는다."""
    refs = [
        {"seq": 1, "role": "agreed_intent", "tier": "core"},
        {"seq": 2, "role": "conversation_assistant_message", "tier": None},
    ]
    read = {"seq": 0, "status": "read"}
    assert ctxmod.context_state(refs, []) is RunContextState.NOT_REPORTED
    assert ctxmod.context_state(
        refs, [read, {"seq": 1, "status": "read"}, {"seq": 2, "status": "read"}]
    ) is RunContextState.COMPLETE
    # 옛 행의 등급(NULL)은 역할에서 도출된다 — AI 메시지의 누락은 부분이다.
    assert ctxmod.context_state(
        refs, [read, {"seq": 1, "status": "read"}, {"seq": 2, "status": "missing"}]
    ) is RunContextState.PARTIAL
    assert ctxmod.context_state(
        refs, [read, {"seq": 1, "status": "read"}, {"seq": 2, "status": "omitted"}]
    ) is RunContextState.PARTIAL
    assert ctxmod.context_state(
        refs, [read, {"seq": 1, "status": "hash_mismatch"}, {"seq": 2, "status": "read"}]
    ) is RunContextState.BLOCKED
    assert ctxmod.context_state(
        refs, [{"seq": 0, "status": "missing"}, {"seq": 1, "status": "read"},
               {"seq": 2, "status": "read"}]
    ) is RunContextState.BLOCKED


def test_drift_counts_only_inputs_the_run_did_not_see():
    """AC-11 — 새 입력만. 해결되어 빠진 입력·자기 산출물은 drift 가 아니다."""
    pinned = [{"artifact_id": "a", "revision": 1}, {"artifact_id": "fb-old", "revision": 1}]
    current = [
        {"role": "previous_intent", "artifact_id": "mine", "revision": 1},
        {"role": "feedback", "artifact_id": "fb-new", "revision": 1},
        {"role": "previous_intent", "artifact_id": "a", "revision": 1},
    ]
    added = ctxmod.drift(pinned, current, own=[("mine", 1)])
    assert added == [{"role": "feedback", "artifact_id": "fb-new", "revision": 1}]
    record = ctxmod.freshness(added, "t", "at_result")
    assert record["state"] == "drifted" and record["added_count"] == 1
    assert ctxmod.freshness([], "t", "live")["state"] == "current"
    many = [{"role": "feedback", "artifact_id": f"f{i}", "revision": 1} for i in range(80)]
    capped = ctxmod.freshness(many, "t", "at_result")
    assert capped["added_count"] == 80 and len(capped["added"]) == ctxmod.FRESHNESS_LIST_CAP


# ============================================ AC-1·2·4·10·15·16 계획과 영수증


def test_a_run_records_its_plan_and_what_the_runner_actually_read(harness):
    """AC-1·AC-6·AC-10·AC-16 — 등급·인라인·크기·한도가 기록되고 영수증이 읽음을 말한다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    first = _open_request(harness, case_id, "아직 문서는 쓰지 마세요.", "c-plan-1")
    harness.discussion_reply(case_id, first["request"]["id"], "run-plan-1")
    harness.settle(case_id, first["request"]["id"])
    second = _open_request(harness, case_id, "구조를 더 설명해 주세요.", "c-plan-2")
    assert harness.discussion_reply(
        case_id, second["request"]["id"], "run-plan-2"
    ).status_code == 201

    refs = harness.context_refs("run-plan-2")
    assert [(r["role"], r["tier"], r["inclusion"], r["receipt_status"]) for r in refs] == [
        ("conversation_user_message", "core", "inline", "read"),
        ("conversation_assistant_message", "supporting", "inline", "read"),
    ]
    sizes = _sizes(harness, case_id)
    assert all(r["byte_size"] == sizes[r["artifact_id"]] for r in refs)
    assert all(r["tier_recorded"] and r["inclusion_recorded"] for r in refs)

    run = _run_view(harness, "run-plan-2")
    assert run["context_inline_limit"] == ctxmod.DEFAULT_INLINE_LIMIT_BYTES
    context = run["context"]
    assert context["state"] == RunContextState.COMPLETE.value
    assert context["omitted_count"] == 0 and context["unread"] == []
    assert context["receipt_generation"] == 1
    assert context["inline_bytes"] == sizes[second["message"]["artifact_id"]] + sum(
        r["byte_size"] for r in refs
    )
    # 예약한 문맥 크기가 전달한 패키지다.
    reserved = _reservations(harness, case_id, "run-plan-2")["context_bytes"]
    assert reserved["reserved_value"] == context["inline_bytes"]
    # Case 조회의 실행 목록에도 같은 요약이 있다.
    listed = harness.client.get(f"/api/cases/{case_id}").json()["runs"]
    assert next(r for r in listed if r["run_id"] == "run-plan-2")["context"]["state"] == (
        "complete"
    )


def test_a_long_conversation_omits_only_old_ai_messages(harness):
    """AC-2·AC-4·AC-8·AC-15 — AI 말만 오래된 것부터 빠지고 사용자 말(금지)은 남는다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    harness.agent.cli_executor.discussion_response = "첫 제안입니다. " * 20
    u1 = _open_request(harness, case_id, "아직 문서는 쓰지 마세요.", "c-long-1")
    harness.discussion_reply(case_id, u1["request"]["id"], "run-long-1")
    harness.settle(case_id, u1["request"]["id"])
    harness.agent.cli_executor.discussion_response = "두 번째 제안입니다."
    u2 = _open_request(harness, case_id, "캐시는 어때요?", "c-long-2")
    harness.discussion_reply(case_id, u2["request"]["id"], "run-long-2")
    harness.settle(case_id, u2["request"]["id"])
    u3 = _open_request(harness, case_id, "정리해 주세요.", "c-long-3")

    messages = harness.conversation(case_id)["messages"]
    a1, a2 = messages[1], messages[3]
    sizes = _sizes(harness, case_id)
    limit = sum(
        sizes[m["artifact_id"]] for m in (u3["message"], u1["message"], u2["message"], a2)
    )
    assert sizes[a1["artifact_id"]] > sizes[a2["artifact_id"]]
    _set_limit(harness, limit)

    assert harness.discussion_reply(case_id, u3["request"]["id"], "run-long-3").status_code == 201
    refs = harness.context_refs("run-long-3")
    assert [(r["artifact_id"], r["inclusion"], r["receipt_status"]) for r in refs] == [
        (u1["message"]["artifact_id"], "inline", "read"),
        (a1["artifact_id"], "omitted_size_limit", "omitted"),
        (u2["message"]["artifact_id"], "inline", "read"),
        (a2["artifact_id"], "inline", "read"),
    ]
    prompt = harness.agent.cli_executor.calls[-1]["prompt"]
    assert prompts.OMITTED_NOTE in prompt
    assert a1["artifact_id"] in prompt  # 없었다고 하지 않는다 — 참조 id 가 남는다
    assert "첫 제안입니다" not in prompt
    assert "두 번째 제안입니다" in prompt
    assert "아직 문서는 쓰지 마세요" in prompt  # 사용자 금지는 핵심이다

    context = _run_view(harness, "run-long-3")["context"]
    assert context["state"] == RunContextState.PARTIAL.value
    assert context["omitted"] == [
        {"seq": 2, "role": "conversation_assistant_message",
         "artifact_id": a1["artifact_id"], "revision": a1["artifact_rev"]}
    ]
    assert context["limit"] == limit and context["inline_bytes"] == limit
    assert _reservations(harness, case_id, "run-long-3")["context_bytes"][
        "reserved_value"
    ] == limit

    # 업무화 뒤 의도 작성·QG-01 검토도 같은 규칙이다(AC-15).
    harness.settle(case_id, u3["request"]["id"])
    work = _open_request(harness, case_id, "좋아요, 이 범위로 구현해 주세요.", "c-long-4")
    assert harness.start_work(case_id, work["message"]["id"]).status_code == 201
    _set_limit(harness, limit + sizes.get(work["message"]["artifact_id"], 0) + 200)
    drafted = _run(
        harness, case_id, "run-long-draft", work["message"], "intent_authoring",
        request_id=work["request"]["id"],
    )
    assert drafted.status_code == 201, drafted.text
    harness.agent.poll_once()
    draft_refs = harness.context_refs("run-long-draft")
    omitted_roles = {r["role"] for r in draft_refs if r["inclusion"] != "inline"}
    assert omitted_roles <= {"conversation_assistant_message"}
    assert all(
        r["inclusion"] == "inline" for r in draft_refs if r["role"] != "conversation_assistant_message"
    )


def test_core_input_over_the_limit_holds_the_run_instead_of_cutting_it(harness):
    """AC-3 — 지시 + 핵심이 한도를 넘으면 실행·예약이 생기지 않는다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    sent = _open_request(harness, case_id, "아주 긴 요청입니다. " * 10, "c-over-1")
    _set_limit(harness, 20)

    refused = harness.discussion_reply(case_id, sent["request"]["id"], "run-over-1")
    assert refused.status_code == 409
    assert _refusals(refused) == ["context_over_inline_limit"]
    reason = refused.json()["detail"]["admission"]["reasons"]["context_over_inline_limit"]
    assert "20 바이트" in reason and "나누거나 한도를 조정" in reason
    assert harness.client.get("/api/runs/run-over-1").status_code == 404
    assert _reservations(harness, case_id, "run-over-1") == {}

    # 한도를 조정하면 같은 요청이 열린다.
    _set_limit(harness, ctxmod.DEFAULT_INLINE_LIMIT_BYTES)
    assert harness.discussion_reply(case_id, sent["request"]["id"], "run-over-2").status_code == 201


def test_a_core_input_that_is_not_stored_holds_the_run(harness):
    """AC-5 — 저장 대기·유실된 핵심 입력으로 실행하지 않는다. 입력을 빼지 않는다."""
    case, intent = _draft_case(harness)
    # 지시 원문을 먼저 접수한다 — 접수 도우미가 대기 중인 원문을 전부 저장하기 때문이다.
    request = harness.submit_artifact(case["id"], "다시 써 주세요.")
    feedback = harness.submit_feedback(
        case["id"], intent["id"], "기준을 더 구체적으로 해 주세요.", persist=False
    )

    pending = _run(harness, case["id"], "run-fb-1", request, "intent_authoring")
    assert pending.status_code == 409
    assert _refusals(pending) == ["required_context_unavailable"]
    reason = pending.json()["detail"]["admission"]["reasons"]["required_context_unavailable"]
    assert f"feedback {feedback['feedback']['artifact_id']}@1=pending" in reason

    harness.agent.persist_pending_intakes()
    assert _run(harness, case["id"], "run-fb-2", request, "intent_authoring").status_code == 201
    harness.agent.poll_once()

    # 유실된 피드백도 빼고 실행하지 않는다.
    lost = harness.submit_feedback(
        case["id"], harness.latest_intent(case["id"])["id"], "하나 더.", persist=False
    )
    Repository(harness.client.app.state.conn).mark_intake_lost(lost["intake_id"])
    refused = _run(harness, case["id"], "run-fb-3", request, "intent_authoring")
    assert _refusals(refused) == ["required_context_unavailable"]
    assert "lost_before_persist" in refused.json()["detail"]["admission"]["reasons"][
        "required_context_unavailable"
    ]


# ============================================= AC-6·7·8·9 영수증과 사전 중단


def test_the_receipt_endpoint_is_idempotent_and_refuses_what_does_not_match(harness):
    """AC-6 — 같은 영수증 재전송은 그대로, 다른 내용·옛 세대·계획과 다른 주장은 409."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    first = _open_request(harness, case_id, "의견 주세요.", "c-rcpt-1")
    harness.discussion_reply(case_id, first["request"]["id"], "run-rcpt-1")
    harness.settle(case_id, first["request"]["id"])
    second = _open_request(harness, case_id, "계속해요.", "c-rcpt-2")
    harness.discussion_reply(case_id, second["request"]["id"], "run-rcpt-2", execute=False)

    url = "/api/runner/runs/run-rcpt-2/context-receipt"
    harness.client.post(f"/api/runner/{RUNNER_ID}/assignments")
    items = [
        {"seq": 0, "role": "instruction", "status": "read"},
        {"seq": 1, "role": "conversation_user_message", "status": "read"},
        {"seq": 2, "role": "conversation_assistant_message", "status": "missing"},
    ]
    body = {"runner_id": RUNNER_ID, "generation": 1, "items": items}
    assert harness.client.post(url, json={**body, "generation": 2}).status_code == 409
    assert harness.client.post(
        url, json={**body, "items": [items[0], {**items[1], "status": "omitted"}, items[2]]}
    ).status_code == 409
    assert harness.client.post(url, json={**body, "items": items[:2]}).status_code == 409
    assert harness.client.post(
        url, json={**body, "runner_id": "someone-else"}
    ).status_code == 409

    recorded = harness.client.post(url, json=body)
    assert recorded.status_code == 200, recorded.text
    assert recorded.json()["state"] == RunContextState.PARTIAL.value
    assert harness.client.post(url, json=body).status_code == 200
    changed = [items[0], items[1], {**items[2], "status": "read"}]
    assert harness.client.post(url, json={**body, "items": changed}).status_code == 409

    # 영수증 표에 본문·경로가 없다.
    columns = {
        r[1] for r in harness.client.app.state.conn.execute(
            "PRAGMA table_info(run_context_receipt)"
        )
    }
    assert columns == {"run_id", "generation", "seq", "role", "status", "runner_id",
                       "reported_at"}


def test_a_missing_core_input_stops_the_run_before_the_cli_and_costs_nothing(harness):
    """AC-7·AC-9 — 요청 원문 없이 QG-01 검토를 하지 않는다. 시작하지 않은 실행은 소비 0."""
    case, intent = _draft_case(harness)
    # QG-01 검토의 요청 원문은 **첫 초안 실행이 받은 지시**다(P3-04).
    draft_run = _run_view(harness, "run-draft-1")
    request_path = harness.agent.store.path_for(
        draft_run["instruction_artifact_id"], draft_run["instruction_artifact_rev"]
    )
    request_path.write_bytes(b"restored from an older backup")  # 다른 내용으로 돌아왔다
    calls_before = len(harness.agent.cli_executor.calls)
    effects_before = harness.cli_effect_count(case["id"])

    assert harness.ai_gate_review(case["id"], intent, run_id="run-rv-1").status_code == 201
    assert len(harness.agent.cli_executor.calls) == calls_before
    assert harness.cli_effect_count(case["id"]) == effects_before
    run = _run_view(harness, "run-rv-1")
    assert (run["outcome"], run["residual_activity"], run["not_started_reason"]) == (
        "failed", "none", "required_context_unavailable"
    )
    assert run["context"]["state"] == RunContextState.BLOCKED.value
    assert run["context"]["unread"] == [
        {"seq": 1, "role": "original_request", "status": "hash_mismatch"}
    ]
    # 게이트 검토가 생기지 않았다 — 요청 원문 없이 한 검토는 없다.
    assert harness.gate(case["id"])["verdict"] != "pass"

    rows = _reservations(harness, case["id"], "run-rv-1")
    for metric in ("run_count", "review_run_count", "context_bytes", "execution_seconds"):
        assert rows[metric]["actual_value"] == 0, metric
        assert rows[metric]["state"] == "settled"
        assert rows[metric]["settle_source"] == SettleSource.NOT_STARTED.value
    assert not {"input_tokens", "output_tokens", "estimated_cost"} & set(rows)

    # 원장에 확정됐다 — 재배정 재전송이 다시 판단하거나 실행하지 않는다.
    ledger = harness.agent.ledger.read("run-rv-1")
    assert ledger["state"] == "finished"
    assert ledger["result"]["not_started_reason"] == "required_context_unavailable"


def test_a_missing_instruction_is_a_not_started_failure_not_a_stuck_run(harness):
    """AC-7 — 지시 원문이 Runner 에 없으면 원장을 잡은 채 멈추지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-noinst-1")
    harness.agent.store.path_for(art["artifact_id"], 1).unlink()

    actions = harness.agent.poll_once()["assignments"]
    assert [a["action"] for a in actions] == ["refused_context_unavailable"]
    run = _run_view(harness, "run-noinst-1")
    assert run["status"] == "finished" and run["not_started_reason"] == (
        "required_context_unavailable"
    )
    assert harness.effect_count(case["id"]) == 0


def test_a_lost_receipt_report_claims_nothing_and_the_run_is_not_reported_unknown(
    harness, monkeypatch
):
    """AC-6·AC-7 — 영수증 보고가 유실되면 원장을 잡지 않는다.

    원장을 먼저 잡으면 CLI 를 부르지도 않은 실행이 다음 재배정에서 "착수했는데 결과가
    없다"(결과 불명)로 보고된다. 없던 호출을 불명으로 남기지 않는다.
    """
    import httpx

    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-lostrcpt-1",
                       tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE)

    def lost(*_args, **_kwargs):
        raise httpx.TransportError("injected: receipt lost")

    original = harness.agent.client.send_context_receipt
    monkeypatch.setattr(harness.agent.client, "send_context_receipt", lost)
    actions = harness.agent.poll_once()["assignments"]
    assert [a["action"] for a in actions] == ["failed_in_runner"]
    assert harness.agent.ledger.read("run-lostrcpt-1") is None
    assert harness.cli_effect_count(case["id"]) == 0

    monkeypatch.setattr(harness.agent.client, "send_context_receipt", original)
    harness.client.post("/api/runs/run-lostrcpt-1/reassign")
    actions = harness.agent.poll_once()["assignments"]
    assert [a["action"] for a in actions] == ["executed"]
    run = _run_view(harness, "run-lostrcpt-1")
    assert run["outcome"] == "completed" and run["assignment_generation"] == 2
    assert run["context"]["receipt_generation"] == 2
    assert harness.cli_effect_count(case["id"]) == 1


def test_a_missing_ai_message_runs_marked_unread_and_partial(harness):
    """AC-8 — 보조만 못 읽으면 실행하고 지시문·산출물·영수증에 그 사실이 남는다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    first = _open_request(harness, case_id, "아직 문서는 쓰지 마세요.", "c-part-1")
    harness.discussion_reply(case_id, first["request"]["id"], "run-part-1")
    harness.settle(case_id, first["request"]["id"])
    work = _open_request(harness, case_id, "좋아요, 이 범위로 구현해 주세요.", "c-part-2")
    assert harness.start_work(case_id, work["message"]["id"]).status_code == 201
    assistant = harness.conversation(case_id)["messages"][1]
    harness.agent.store.path_for(assistant["artifact_id"], assistant["artifact_rev"]).unlink()

    drafted = _run(harness, case_id, "run-part-draft", work["message"], "intent_authoring",
                   request_id=work["request"]["id"])
    assert drafted.status_code == 201, drafted.text
    action = next(
        a for a in harness.agent.poll_once()["assignments"] if a["run_id"] == "run-part-draft"
    )
    assert action["action"] == "executed"
    assert action["produced"]["context_unread"] == ["conversation_assistant_message"]
    prompt = harness.agent.cli_executor.calls[-1]["prompt"]
    assert prompts.UNREAD_NOTE in prompt
    run = _run_view(harness, "run-part-draft")
    assert run["outcome"] == "completed"
    assert run["context"]["state"] == RunContextState.PARTIAL.value
    assert run["context"]["unread"] == [
        {"seq": 2, "role": "conversation_assistant_message", "status": "missing"}
    ]


def test_not_started_is_accepted_only_for_a_failed_run_with_nothing_left(harness):
    """AC-9 — 결과를 모르거나 무언가 남은 실행을 "시작하지 않았다"로 적지 못한다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-ns-1")
    harness.client.post(f"/api/runner/{RUNNER_ID}/assignments")
    url = "/api/runner/runs/run-ns-1/result"
    base = {"runner_id": RUNNER_ID, "generation": 1, "not_started_reason": "workspace_busy"}
    for outcome, residual in (("unknown", "none"), ("failed", "unknown"), ("completed", "none")):
        bad = harness.client.post(
            url, json={**base, "outcome": outcome, "residual_activity": residual}
        )
        assert bad.status_code == 409, (outcome, residual)
    ok = harness.client.post(url, json={**base, "outcome": "failed", "residual_activity": "none"})
    assert ok.status_code == 200, ok.text
    rows = _reservations(harness, case["id"], "run-ns-1")
    assert rows["run_count"]["actual_value"] == 0
    assert rows["run_count"]["settle_source"] == "not_started"


def test_a_started_run_still_settles_as_before(harness):
    """AC-9 — 시작한 실행의 정산은 바뀌지 않는다(실패여도 호출 1회)."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-started-1",
                       tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE)
    harness.agent.cli_executor.outcome = RunOutcome.FAILED
    harness.agent.poll_once()
    rows = _reservations(harness, case["id"], "run-started-1")
    assert rows["run_count"]["actual_value"] == 1
    assert rows["run_count"]["settle_source"] == "reserved_exact"
    assert _run_view(harness, "run-started-1")["not_started_reason"] is None


# ================================================= AC-11 최신성


def test_freshness_records_inputs_that_arrived_after_the_run_fixed_its_context(harness):
    """AC-11 — 고정 뒤 새 피드백은 drift, 자기 산출물은 아니다. 결과·판정을 바꾸지 않는다."""
    case, intent = _draft_case(harness)
    # 첫 초안 실행은 그 뒤 새 입력이 없었다.
    assert _run_view(harness, "run-draft-1")["context"]["freshness"]["state"] == "current"

    request = harness.submit_artifact(case["id"], "다시 써 주세요.")
    assert _run(harness, case["id"], "run-fresh-1", request, "intent_authoring").status_code == 201
    live = _run_view(harness, "run-fresh-1")["context"]["freshness"]
    assert (live["state"], live["basis"]) == ("current", "live")

    late = harness.submit_feedback(case["id"], intent["id"], "이것도 봐 주세요.")
    live = _run_view(harness, "run-fresh-1")["context"]["freshness"]
    assert live["state"] == "drifted"
    assert live["added"] == [{"role": "feedback", "artifact_id": late["feedback"]["artifact_id"],
                              "revision": 1}]

    harness.agent.poll_once()
    run = _run_view(harness, "run-fresh-1")
    assert run["outcome"] == "completed"  # 최신성은 결과를 바꾸지 않는다
    at_result = run["context"]["freshness"]
    assert at_result["basis"] == "at_result"
    added = {a["artifact_id"] for a in at_result["added"]}
    assert late["feedback"]["artifact_id"] in added
    # 이 실행이 쓴 새 의도 버전은 새 입력이 아니다.
    mine = harness.latest_intent(case["id"])
    assert mine["artifact_id"] not in added


# ======================================= AC-12 Runner 재시작의 사용량 복구


def test_a_restarted_runner_recovers_usage_from_the_real_codex_raw_log(harness):
    """AC-12 — CLI 를 다시 부르지 않고 실제 원시 출력에서 사용량·세션을 되찾는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-rec-1",
                       tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE)
    _simulate_crash_after_start(harness, "run-rec-1", CODEX_RAW)

    actions = harness.agent.poll_once()["assignments"]
    assert [a["action"] for a in actions] == ["reported_unknown_without_reexecution"]
    recovered = actions[0]["recovered"]
    assert recovered["raw_log"] == "present" and recovered["usage"] == "recovered"
    assert harness.cli_effect_count(case["id"]) == 0  # 다시 부르지 않았다

    run = _run_view(harness, "run-rec-1")
    assert run["outcome"] == "unknown" and run["residual_activity"] == "unknown"
    assert run["session_ref"] == "01a0be60-7f4b-7331-882e-f1b7e1cefff8"
    assert run["usage"]["tokens"]["input_tokens"] == 32305
    assert run["usage"]["recovered_from"] == "runner_raw_log"
    assert {e["type"] for e in run["events"]} >= {"session_identified", "run_finished"}
    rows = _reservations(harness, case["id"], "run-rec-1")
    assert rows["input_tokens"]["actual_value"] == 32305
    assert rows["output_tokens"]["actual_value"] == 62
    assert rows["input_tokens"]["settle_source"] == SettleSource.RECOVERED_FROM_RUNNER_LOG.value
    assert rows["input_tokens"]["state"] == "settled"
    # 결과를 모르는 실행의 시간은 여전히 확정되지 않는다.
    assert rows["execution_seconds"]["state"] == "unresolved"

    # 원장에 확정했다 — 원시 출력이 지워져도 같은 값을 다시 보낸다.
    (harness.runner_config.raw_dir / "run-rec-1.stdout.jsonl").unlink()
    ledger = harness.agent.ledger.read("run-rec-1")
    assert ledger["state"] == "finished"
    assert ledger["result"]["usage"]["tokens"]["input_tokens"] == 32305


def test_a_killed_run_log_without_usage_stays_not_reported(harness):
    """AC-12 — 실제 강제 종료 로그에는 사용량이 없다. 0 으로 적지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"], kind="analysis")
    art = harness.submit_artifact(case["id"], "지시 원문")
    harness.create_run(case["id"], art["artifact_id"], "run-kill-1",
                       tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE)
    _simulate_crash_after_start(harness, "run-kill-1", KILLED_RAW)
    actions = harness.agent.poll_once()["assignments"]
    assert actions[0]["recovered"]["usage"] == "not_reported"
    run = _run_view(harness, "run-kill-1")
    assert run["outcome"] == "unknown" and run["usage"] == "not_reported"
    rows = _reservations(harness, case["id"], "run-kill-1")
    assert rows["input_tokens"]["actual_value"] is None
    assert rows["input_tokens"]["settle_source"] == SettleSource.OUTCOME_UNKNOWN.value

    # 원시 출력이 아예 없으면 이전과 같다.
    harness.create_run(case["id"], art["artifact_id"], "run-kill-2",
                       tool_id=FAKE_TOOL_ID, mode=FAKE_TOOL_MODE)
    _simulate_crash_after_start(harness, "run-kill-2", None)
    actions = harness.agent.poll_once()["assignments"]
    assert actions[0]["recovered"] == {"raw_log": "absent"}
    assert _run_view(harness, "run-kill-2")["usage"] == "not_reported"


def test_the_claude_raw_log_is_recovered_with_its_own_rules(harness):
    """AC-12 — Claude Code 의 원시 출력도 같은 정규화 규칙으로 읽는다(비용 포함)."""
    target = harness.runner_config.raw_dir / "run-claude-1.stdout.jsonl"
    shutil.copyfile(CLAUDE_RAW, target)
    recovered = harness.agent._recover_from_raw_log(
        {"run_id": "run-claude-1", "tool_id": "claude"}
    )
    assert recovered["summary"]["usage"] == "recovered"
    assert recovered["usage"]["recovered_from"] == "runner_raw_log"
    assert isinstance(recovered["usage"]["tokens"]["input_tokens"], int)
    assert recovered["usage"]["cost_usd"] != "not_reported"
    assert recovered["session_ref"]


# ========================================= AC-13·14 새 세션·부분 복원


def test_a_new_session_after_an_unknown_run_resets_nothing(harness):
    """AC-13 — 새 실행이 같은 핵심 입력을 받고 repair·예산·질문·Profile·기준이 그대로다."""
    case, intent = _draft_case(harness)
    harness.submit_feedback(case["id"], intent["id"], "기준을 구체적으로.")
    assert _record(harness, case["id"], findings=_failure()).status_code == 201
    url = f"/api/cases/{case['id']}/quality-gates/QG-06/remediation/case"
    started = harness.client.post(
        f"{url}/attempts",
        json={"kind": "product_repair", "task_key": "t-1", "session_ref": "s-1"},
    )
    assert started.status_code == 201, started.text
    attempt = started.json()["attempts"][-1]
    assert harness.client.post(
        f"/api/remediation-attempts/{attempt['id']}/complete", json={"outcome": "still_failed"}
    ).status_code == 200

    before_case = harness.client.get(f"/api/cases/{case['id']}").json()
    before_criteria = [
        (c["criterion_key"], c.get("obligation"), c.get("conclusion_rule"))
        for c in harness.criteria(case["id"])
    ]
    before_questions = [q["id"] for q in harness.open_questions(case["id"])]
    before_cycle = harness.client.get(url).json()

    request = harness.submit_artifact(case["id"], "다시 써 주세요.")
    assert _run(harness, case["id"], "run-sess-1", request, "intent_authoring").status_code == 201
    _simulate_crash_after_start(harness, "run-sess-1", CODEX_RAW)
    harness.agent.poll_once()
    assert _run_view(harness, "run-sess-1")["outcome"] == "unknown"

    # 새 세션 = 새 실행. 영속 기록에서 **같은 핵심 입력**을 받는다.
    assert _run(harness, case["id"], "run-sess-2", request, "intent_authoring").status_code == 201
    first = [(r["role"], r["artifact_id"]) for r in harness.context_refs("run-sess-1")]
    second = [(r["role"], r["artifact_id"]) for r in harness.context_refs("run-sess-2")]
    assert second == first and ("previous_intent", intent["artifact_id"]) in second

    after_case = harness.client.get(f"/api/cases/{case['id']}").json()
    assert after_case["profile"] == before_case["profile"]
    assert after_case["profile_version"] == before_case["profile_version"] == "2"
    assert [
        (c["criterion_key"], c.get("obligation"), c.get("conclusion_rule"))
        for c in harness.criteria(case["id"])
    ] == before_criteria
    assert [q["id"] for q in harness.open_questions(case["id"])] == before_questions
    cycle = harness.client.get(url).json()
    assert cycle["used_attempts"] == before_cycle["used_attempts"] == 1
    # 불명 실행의 되찾은 토큰이 Case 누적에 남는다 — 새 세션이 지우지 않는다.
    usage = harness.client.get(f"/api/cases/{case['id']}/budget").json()["usage"]
    assert usage["input_tokens"]["settled"] >= 32305
    assert usage["run_count"]["exposure"] >= 3  # 초안·불명·새 실행


def test_partial_restore_blocks_only_runs_that_depend_on_the_missing_original(harness):
    """AC-14 — 사라진 원문에 기대는 실행만 멈추고 다른 Case 는 영향이 없다."""
    case_a, intent_a = _agreed_case(harness)
    project_b = harness.create_project("other")
    case_b = harness.create_case(project_b["id"])
    harness.submit_intent_draft(case_b["id"], {"goal": {"text": "B"}})
    # A 의 동의된 의도 원문만 부분 복원에서 빠졌다.
    harness.agent.store.path_for(intent_a["artifact_id"], intent_a["artifact_rev"]).unlink()

    assert harness.ai_prepare(case_a["id"], "design", run_id="run-pr-a").status_code == 201
    assert _run_view(harness, "run-pr-a")["context"]["state"] == "blocked"
    assert harness.preparation(case_a["id"])["design"]["artifact"] is None

    intent_b = harness.latest_intent(case_b["id"])
    assert harness.ai_gate_review(case_b["id"], intent_b, run_id="run-pr-b").status_code == 201
    run_b = _run_view(harness, "run-pr-b")
    assert run_b["outcome"] == "completed"
    assert run_b["context"]["state"] in ("complete", "not_reported")
    assert run_b["not_started_reason"] is None


# ========================================================= AC-20 경계


def test_p404_records_keep_no_bodies(harness):
    """AC-20 — 계획·영수증·최신성에 본문이 없다."""
    _project, view = _conversation_case(harness)
    case_id = view["case_id"]
    first = _open_request(harness, case_id, f"비밀 문구 {MARKER}", "c-body-1")
    harness.discussion_reply(case_id, first["request"]["id"], "run-body-1")
    harness.settle(case_id, first["request"]["id"])
    second = _open_request(harness, case_id, "계속", "c-body-2")
    harness.discussion_reply(case_id, second["request"]["id"], "run-body-2")
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        for table in ("run_context_ref", "run_context_receipt", "run"):
            for row in conn.execute(f"SELECT * FROM {table}"):
                assert MARKER not in repr(row), table
    finally:
        conn.close()
    view_json = harness.client.get("/api/runs/run-body-2").text
    assert MARKER not in view_json


def test_enforcement_axes_are_unchanged(harness):
    """AC-20 — 새 강제 축을 만들지 않았다. 네 축과 게시 미강제 그대로다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    enforcement = harness.client.get(f"/api/cases/{case['id']}/policy").json()["enforcement"]
    assert {k for k, v in enforcement.items() if v["state"] == "enforced"} == {
        "autonomy", "controlled_checkpoint", "budget", "repository_selection"
    }
    assert enforcement["publish"]["state"] == "not_implemented"
