"""AC-11: AI가 의도 초안을 작성한다 (P2-02에서 이월한 항목).

P2-02가 검증하지 못한 것은 여섯 항목의 존재가 아니라 **역할 분리**였다.
초안을 사람이 쓰면 "AI가 제시하고 사람이 검토한다"(FR-03)가 성립하지 않는다.

여기서 확인하는 것:

  초안이 **Runner에서 태어나** 의도 버전이 된다 (P2-02와 방향이 반대다)
  문서와 제어부 기록이 **실제 작성 주체**를 말한다
  사람 입력 경로가 **그대로 남아 있다**
  형식을 못 맞춘 응답은 추측으로 고치지 않고 실패로 남는다

실제 코딩 CLI는 부르지 않는다. 가짜 실행기를 쓰고, 실제 CLI 실행 증거는
라이브 검증에 있다(p2/evidence/P2-03-results.md).
"""

from __future__ import annotations

import json

from domain.models import AuthoringMode
from tests.conftest import FAKE_TOOL_ID


def test_ai_writes_the_draft_and_it_becomes_an_intent_version(harness):
    project = harness.create_project()
    case = harness.create_case(project["id"])

    created = harness.ai_draft(case["id"], "로그에서 오류 줄만 뽑아 주세요.")
    assert created["created"] is True
    assert created["admission"]["outcome"] == "admitted"
    assert created["admission"]["profile"] == "intent_production"

    state = harness.intent_state(case["id"])
    latest = state["latest_intent_version"]
    assert latest is not None, "AI 실행이 의도 버전을 만들지 않았다"

    # 작성 주체가 제어부 기록에 남는다.
    assert latest["authoring_mode"] == AuthoringMode.AI_DRAFTED.value
    assert latest["author_run_id"] == "run-draft-1"

    # 여섯 항목이 모두 보고됐고, 사람이 쓴 것이 아니라는 사실이 출처에 드러난다.
    fields = {f["field"]: f for f in latest["fields"]}
    assert len(fields) == 6
    assert fields["goal"]["origin"] == "user_requirement"
    assert fields["open_questions"]["origin"] == "ai_assumption"
    # AI가 스스로 사용자 확정을 적지 않는다.
    assert all(f["state"] != "user_confirmed" for f in fields.values())

    # 원문은 Runner에 있고 그 문서가 작성 주체를 말한다.
    body = harness.agent.store.get(latest["artifact_id"], latest["artifact_rev"])
    doc = json.loads(body.decode("utf-8"))
    assert doc["authoring_mode"] == AuthoringMode.AI_DRAFTED.value
    assert doc["author_run_id"] == "run-draft-1"
    assert "AI 실행이 작성" in doc["authoring_note"]
    assert doc["authored_by"].startswith(FAKE_TOOL_ID)


def test_the_human_path_still_writes_human_drafts(harness):
    """AI 경로가 생겨도 사람이 직접 쓰는 길은 없어지지 않는다.

    두 경로가 같은 문서 형식과 같은 표를 쓰되 **작성 주체 표기가 다르다.**
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])

    harness.submit_intent_draft(
        case["id"], {"goal": {"text": "사람이 직접 쓴 목표", "origin": "user_requirement"}}
    )
    latest = harness.latest_intent(case["id"])
    assert latest["authoring_mode"] == AuthoringMode.HUMAN_TYPED.value
    assert latest["author_run_id"] is None

    body = harness.agent.store.get(latest["artifact_id"], latest["artifact_rev"])
    doc = json.loads(body.decode("utf-8"))
    assert doc["authoring_mode"] == AuthoringMode.HUMAN_TYPED.value
    assert "사람이 화면에서 직접 입력" in doc["authoring_note"]
    # P2-02의 문구가 그대로 남아 있으면 안 된다. 그 문구는 이제 거짓이다.
    assert "P2-03 이후" not in doc["authoring_note"]


def test_both_paths_can_coexist_in_one_case(harness):
    """AI 초안 → 사람이 고친 새 버전. 버전마다 작성 주체가 따로 기록된다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])

    harness.ai_draft(case["id"])
    harness.submit_intent_draft(
        case["id"],
        {
            "goal": {"text": "사람이 다듬은 목표", "origin": "user_requirement"},
            "exclusions": {"text": "로그 회전은 제외", "origin": "user_requirement"},
        },
    )

    versions = harness.client.get(f"/api/cases/{case['id']}").json()["intent_versions"]
    by_revision = {v["revision"]: v for v in versions}
    assert by_revision[1]["authoring_mode"] == AuthoringMode.AI_DRAFTED.value
    assert by_revision[2]["authoring_mode"] == AuthoringMode.HUMAN_TYPED.value


def test_a_malformed_ai_response_does_not_become_an_intent_version(harness):
    """형식을 못 맞춘 응답을 추측으로 고쳐 진행하지 않는다.

    지어낸 의도에 사람이 동의하게 만들지 않기 위해서다. CLI가 정상 종료해도
    산출물이 없으면 **완료가 아니다**(FR-28).
    """
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.agent.cli_executor.draft_response = "죄송합니다, JSON 없이 설명만 드릴게요."

    harness.ai_draft(case["id"])

    state = harness.intent_state(case["id"])
    assert state["latest_intent_version"] is None
    assert state["agreement_state"] == "no_intent"

    run = harness.client.get("/api/runs/run-draft-1").json()
    assert run["outcome"] == "failed", "산출물이 없는데 완료로 보고했다"
    assert run["status"] == "finished"


def test_the_controller_never_sees_the_ai_draft_body(harness):
    """AC-12: AI가 쓴 초안 본문은 제어부 파일 바이트에 없다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])

    marker = "ZZMARKER-AI-DRAFT-BODY"
    harness.agent.cli_executor.draft_response = json.dumps(
        {
            "fields": {"goal": {"text": f"{marker} 오류 줄만 뽑기", "origin": "user_requirement"}},
            "questions": [],
        },
        ensure_ascii=False,
    )
    harness.ai_draft(case["id"])

    latest = harness.latest_intent(case["id"])
    assert latest is not None

    # Runner 저장소에는 있다.
    body = harness.agent.store.get(latest["artifact_id"], latest["artifact_rev"])
    assert marker.encode("utf-8") in body

    # 제어부의 어떤 파일에도 없다.
    root = harness.controller_config.data_root
    checked = 0
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        checked += 1
        assert marker.encode("utf-8") not in path.read_bytes(), f"본문이 {path} 에 남았다"
    assert checked > 0, "검사한 제어부 파일이 없다"


def test_the_run_level_constraint_is_marked_as_not_part_of_the_intent():
    """라이브에서 찾은 결함: **실행의 제약이 의도의 제약으로 새어 나갔다.**

    지시문은 "지금 이 실행에서는 코드를 바꾸지 마라"고 말하는데, 라이브에서 codex
    가 그것을 의도 문서의 `constraints` 에 `user_requirement` 로 적었고 QG-01 이
    "함수를 추가한다는 목표와 정면으로 충돌한다"고 막았다. 지시문이 그 둘을
    구별해 주지 않으면 같은 일이 반복된다.

    **지시문의 문장 자체를 시험한다.** 이것은 AI의 출력이 아니라 우리가 보내는
    입력이고, 입력은 결정적으로 확인할 수 있다.
    """
    from runner import prompts

    for template in (
        prompts.INTENT_AUTHORING_PROMPT,
        prompts.DESIGN_AUTHORING_PROMPT,
        prompts.PLAN_AUTHORING_PROMPT,
    ):
        assert "지금 이 실행" in template
        assert "이 실행의 규칙" in template or "의도가 아니다" in template
