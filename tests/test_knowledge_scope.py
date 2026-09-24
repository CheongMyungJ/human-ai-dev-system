"""P4-09 (f) — 지식 후보의 거부·열람(D-92, 이슈 #5)(plans/P4-PLAN-09.md AC-21~25).

AI 후보(작업 실행의 추출 후보·논의 응답의 `proposal: true`)는 범위(활동·경로) 값이 틀려도 **후보로 받고 AI 가
적은 원래 값을 보존**한다. 그 후보는 주입되지 않고 채택 확인(QG-08)이 `scope_unreadable` 로 막으며, 사람이
활성화 폼에서 활동을 확인하면 풀린다. **사용자 말의 자동 등록(바로 활성)은 지금처럼 거부한다.** 그래도 거부된
항목은 내용(본문·AI 가 적은 범위)과 사유를 사람이 본다. 지시문은 허용 활동 값과 경로 규칙을 명시한다.
"""

from __future__ import annotations

from typing import Any

import pytest

from controller.repository import KnowledgeAdoptionRefused
from domain import knowledge as knowmod
from runner import prompts
from tests.conftest import FAKE_VERIFICATION_RESPONSE
from tests.test_knowledge import _manifest, _repo, _runs
from tests.test_knowledge_extraction import _block, _candidate, _item, _knowledge, _registrations, _run_to_completion

BAD_ACTIVITIES = ["기기 확인", "테스트 환경 조사"]


# ================================================== AC-21 지시문


def test_the_candidate_and_registration_rules_name_every_activity_code_and_the_path_rule():
    """AC-21 — 두 지시문에 활동 코드 여덟과 경로 규칙, '모르면 비워 둔다' 가 있다."""
    for text in (prompts.KNOWLEDGE_EXTRACTION_RULE, prompts.KNOWLEDGE_REGISTRATION_RULE):
        for code in knowmod.ACTIVITIES:
            assert code in text, code
        assert "모르면" in text and "상대 경로" in text and "최대 20" in text


# ================================================== 순수 규칙


def test_parse_report_item_keeps_the_original_scope_for_ai_candidates_and_refuses_user_statements():
    """AI 후보는 원래 값을 `reported_scope` 에 남기고 활동·경로를 비운다. 사용자 말은 `invalid_scope` 다."""
    raw = _candidate(activities=BAD_ACTIVITIES, artifact_id="art-1", revision=1)
    strict, refusal = knowmod.parse_report_item(raw)
    assert strict is None and refusal == "invalid_scope"
    lenient, refusal = knowmod.parse_report_item(raw, lenient_scope=True)
    assert refusal is None and lenient is not None
    assert lenient["activities"] == [] and lenient["reported_scope"]["activities"] == BAD_ACTIVITIES
    assert "unknown activity" in lenient["reported_scope"]["problem"]
    ok, _ = knowmod.parse_report_item(_candidate(artifact_id="art-1", revision=1), lenient_scope=True)
    assert ok is not None and ok["reported_scope"] is None and ok["activities"] == ["verification"]
    # 경로만 있고 저장소가 없는 것도 같다.
    lenient2, _ = knowmod.parse_report_item(
        _candidate(artifact_id="art-1", revision=1, paths=["src/a.py"], repository=None), lenient_scope=True
    )
    assert lenient2 is not None and lenient2["paths"] == [] and lenient2["reported_scope"]["problem"] == "paths_without_repository"
    strict2, refusal2 = knowmod.parse_report_item(
        _candidate(artifact_id="art-1", revision=1, paths=["src/a.py"], repository=None)
    )
    assert strict2 is None and refusal2 == "paths_without_repository"


def test_the_adoption_check_blocks_an_unreadable_scope_until_activities_are_named_and_select_skips_it():
    """`scope_unreadable` 은 활동 명시(빈 목록 포함)로 풀린다. 주입 선택은 그 후보를 건너뛴다."""
    candidate = {
        "id": "v1", "knowledge_id": "k1", "knowledge_key": "K-001", "state": "candidate",
        "obligation": "reference", "scope_kind": "project", "repository_id": None, "activities": [],
        "paths": [], "reported_scope": {"activities": BAD_ACTIVITIES, "paths": [], "problem": "x"},
    }
    blocked = knowmod.adoption_check(candidate, evidence_count=1, storage="server", open_conflicts=0, related=None, into=None)
    assert {f.code: f.blocking for f in blocked}[knowmod.ADOPTION_SCOPE_UNREADABLE] is True
    cleared = knowmod.adoption_check(
        candidate, evidence_count=1, storage="server", open_conflicts=0, related=None, into=None,
        requested={"activities": []},
    )
    assert knowmod.ADOPTION_SCOPE_UNREADABLE not in {f.code for f in cleared}
    selection = knowmod.select([candidate], "verification", ["repo-1"])
    assert selection.applied == []
    assert [s["decision"] for s in selection.skipped] == [knowmod.Decision.SCOPE_UNREADABLE.value]


# ================================================== AC-22·23 서버 — 받기·주입 제외·채택 확인·활성화


def test_a_candidate_with_a_wrong_activity_is_registered_kept_out_of_runs_and_activated_after_a_human_names_it(processing_harness):
    """AC-22·AC-23 — 틀린 활동의 추출 후보 → 후보 등록 + 원래 값 보존 + 주입 제외 + 막힘 → 활동 명시로 활성."""
    h = processing_harness
    project, _path = h.create_git_project("ks-cand")
    executor = h.agent.cli_executor
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block(
        [_candidate(repository="primary", activities=BAD_ACTIVITIES, summary="읽기 전용 환경의 adb 기기 조회 제한")]
    )
    case_id = _run_to_completion(h, project)
    [row] = _registrations(h, case_id)
    assert (row["intake_state"], row["knowledge_key"], row["state"]) == ("registered", "K-001", "candidate")
    assert row["reported_scope"]["activities"] == BAD_ACTIVITIES and row["activities"] == []
    view = _knowledge(h, project["id"])
    item = _item(view, "K-001")
    current = item["current"]
    assert current["scope_unreadable"] is True and current["reported_scope"]["activities"] == BAD_ACTIVITIES
    assert current["authority_kind"] == "ai_proposal" and current["state"] == "candidate"

    # 다음 실행에 주입되지 않는다 — Manifest 가 이유를 말한다.
    executor.verification_response = FAKE_VERIFICATION_RESPONSE
    other = _run_to_completion(h, project, "오류 줄 필터를 구현해줘 (둘째)")
    verify = next(r for r in _runs(h, other) if r["purpose"] == "verification_run")
    assert [r for r in h.context_refs(verify["run_id"]) if r["role"] == "knowledge_candidate"] == []
    assert {i["knowledge_key"]: i["decision"] for i in _manifest(h, verify["run_id"])["items"]} == {
        "K-001": "scope_unreadable"
    }

    # 채택 확인이 막고, 활동을 명시하면 풀린다.
    check = h.client.get(f"/api/knowledge/{item['id']}/adoption-check").json()
    assert check["blocked"] and "scope_unreadable" in check["blocked"]
    assert any(f["code"] == "scope_unreadable" and f["blocking"] for f in check["findings"])
    with pytest.raises(KnowledgeAdoptionRefused):
        _repo(h).activate_knowledge(item["id"], "owner", "그대로")
    cleared = h.client.get(
        f"/api/knowledge/{item['id']}/adoption-check", params={"activities": "verification"}
    ).json()
    assert not any(f["code"] == "scope_unreadable" for f in cleared["findings"]), cleared
    activated = h.client.post(
        f"/api/knowledge/{item['id']}/activate",
        json={"actor": "owner", "reason_summary": "활동을 검증으로 확인", "activities": ["verification"]},
    )
    assert activated.status_code == 200, activated.text
    now = _item(_knowledge(h, project["id"]), "K-001")["current"]
    assert now["state"] == "active" and now["activities"] == ["verification"]
    assert now["scope_unreadable"] is False and now["reported_scope"] is None  # 사람이 정한 범위
    assert now["version"] == 2


def test_a_proposal_in_a_reply_is_kept_but_a_user_statement_with_a_bad_scope_is_still_refused(processing_harness):
    """AC-22·AC-24 — 논의 응답: `proposal: true` 는 원래 값을 보존한 후보, 사용자 말 항목은 `invalid_scope` 거부."""
    h = processing_harness
    project, _path = h.create_git_project("ks-prop")
    talk = h.create_conversation(project["id"], "이야기")["case_id"]
    proposal = dict(_candidate(summary="AI 관찰", content="PROP-SCOPE 시험은 루트에서 돈다", proposal=True,
                               activities=["환경 조사"]), repository=None)
    statement = {
        "kind": "constraint", "obligation": "required", "summary": "사용자 규칙",
        "content": "앞으로 로그에 비밀값을 남기지 않는다", "repository": None, "paths": [],
        "activities": ["로그 작업"], "supersedes": None,
    }
    h.agent.cli_executor.discussion_response = (
        "정리했습니다." + _block([proposal, statement]) + '\n\n```hads-interpretation\n{"kind": "discussion"}\n```'
    )
    h.send_message(talk, "이 프로젝트에서는 앞으로 로그에 비밀값을 남기지 마", "c-1")
    h.agent.poll_once()
    rows = _registrations(h, talk)
    assert [(r["origin"], r["intake_state"]) for r in rows] == [("proposal", "registered"), ("statement", "refused")]
    assert rows[0]["reported_scope"]["activities"] == ["환경 조사"] and rows[0]["state"] == "candidate"
    assert rows[1]["refusal"] == "invalid_scope" and "범위" in rows[1]["refusal_text"]


# ================================================== AC-25 열람


def test_a_refused_row_can_be_read_with_its_content_scope_and_reason(processing_harness):
    """AC-25 — 거부 행 열람: 본문(서버에 있으면)·AI 가 적은 범위·사유 코드와 읽을 말. 등록 행도 같은 조회."""
    h = processing_harness
    project, _path = h.create_git_project("ks-read")
    talk = h.create_conversation(project["id"], "이야기")["case_id"]
    statement = {
        "kind": "operation", "obligation": "required", "summary": "adb 조회 제한",
        "content": "READ-MARK 읽기 전용 실행에서는 adb devices 가 mkdir 권한 오류로 실패한다",
        "repository": "primary", "paths": ["tools/adb.md"], "activities": ["기기 확인"], "supersedes": None,
    }
    h.agent.cli_executor.discussion_response = (
        "등록합니다." + _block([statement]) + '\n\n```hads-interpretation\n{"kind": "discussion"}\n```'
    )
    h.send_message(talk, "이 프로젝트에서는 앞으로 adb 조회를 읽기 전용에서 하지 마", "c-1")
    h.agent.poll_once()
    [row] = _registrations(h, talk)
    assert row["intake_state"] == "refused" and row["refusal"] == "invalid_scope"
    detail = h.client.get(f"/api/cases/{talk}/knowledge-intake/{row['run_id']}/{row['report_index']}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["intake_state"] == "refused" and body["refusal"] == "invalid_scope"
    assert body["refusal_text"] == knowmod.REFUSAL_TEXT["invalid_scope"]
    assert body["reported"]["activities"] == ["기기 확인"] and body["reported"]["paths"] == ["tools/adb.md"]
    assert body["reported"]["repository"] == "primary" and body["reported"]["kind"] == "operation"
    assert body["content"] is not None and "READ-MARK" in body["content"]
    # 없는 항목은 404, 다른 Case 의 실행은 404.
    assert h.client.get(f"/api/cases/{talk}/knowledge-intake/{row['run_id']}/9").status_code == 404
    other = h.create_conversation(project["id"], "다른")["case_id"]
    assert h.client.get(f"/api/cases/{other}/knowledge-intake/{row['run_id']}/0").status_code == 404
