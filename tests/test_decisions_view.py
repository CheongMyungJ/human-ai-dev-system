"""UI-04a — 결정 사항 패널·프로젝트 규칙 화면이 쓰는 조회(plans/UI-PLAN-04a.md 3.1절, AC-3·AC-10).

새 화면은 **보고·이동**하는 자리다. 서버는 그것을 위해 출처 대화의 제목과 메시지 순번, 그리고 이 Case 실행들의
지식 Manifest 집계를 더할 뿐이다.

이 파일이 지키는 것:

    본문을 옮기지 않는다            조회에 더한 것은 제목·순번·수뿐이고 지식 원문 표식은 `knowledge_body` 에만 있다
    제공만 제공이다                  Manifest 집계는 `provided` 만 세고 나머지는 사유별 수다
    기록 전은 없음이 아니다          Manifest 기록 전 실행은 `runs_unrecorded` 로 따로 센다
    정책은 그대로다                  새 조회는 권한·진입·권위 규칙을 건드리지 않는다(스키마 v24 그대로)

시험 이름 옆의 AC 번호는 UI-PLAN-04a 4절이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tests.conftest import FAKE_VERIFICATION_RESPONSE
from tests.test_knowledge import _knowledge_reply, _manifest, _register, _start_in, marker_tables
from tests.test_knowledge_extraction import (
    _block,
    _candidate,
    _item,
    _knowledge,
    _registrations,
    _run_to_completion,
)
from tests.test_work_progressor import _agree, _drive, _runs

MARK = "DVIEW-4a71-MARKER"


def _use(h, case_id: str) -> dict[str, Any]:
    response = h.client.get(f"/api/cases/{case_id}/knowledge-use")
    assert response.status_code == 200, response.text
    return response.json()


def test_the_registry_and_the_cards_point_back_to_the_source_conversation_and_message(processing_harness):
    """AC-10 — 사용자 말 등록은 출처 대화 제목·권위 메시지 순번·응답 순번을, AI 제안은 응답 순번만, 작업 실행의
    후보는 대화 제목만 가진다(메시지 없음). 근거 행도 출처 대화 제목을 가진다. 본문은 어디에도 없다."""
    h = processing_harness
    project, _path = h.create_git_project("dv-source")
    talk = h.create_conversation(project["id"], "규칙 이야기")["case_id"]
    rule = {
        "kind": "constraint", "obligation": "required", "summary": "오류 로그에 시각 없음",
        "content": f"{MARK} 오류 로그 줄에 시각을 덧붙이지 않는다.", "repository": None, "paths": [],
        "activities": [], "supersedes": None,
    }
    h.agent.cli_executor.discussion_response = _knowledge_reply([rule])
    h.send_message(talk, "이 프로젝트에서는 앞으로 오류 로그에 시각을 붙이지 마", "c-1")
    h.agent.poll_once()
    [statement] = _registrations(h, talk)
    assert (statement["origin"], statement["knowledge_key"]) == ("statement", "K-001")
    assert (statement["source_message_seq"], statement["reply_seq"]) == (1, 2)
    current = _item(_knowledge(h, project["id"]), "K-001")["current"]
    assert (current["source_case_title"], current["source_message_seq"]) == ("규칙 이야기", 1)

    # AI 제안(논의 응답) — 권위 메시지가 없으므로 순번은 응답 것뿐이다.
    proposal = dict(_candidate(summary="AI 관찰", content=f"{MARK}-P 시험은 루트에서 돈다", proposal=True), repository=None)
    h.agent.cli_executor.discussion_response = (
        "정리했습니다." + _block([proposal]) + '\n\n```hads-interpretation\n{"kind": "discussion"}\n```'
    )
    h.send_message(talk, "이 업무에서 배운 것을 정리해줘", "c-2")
    h.agent.poll_once()
    rows = _registrations(h, talk)
    assert [(r["origin"], r["source_message_seq"], r["reply_seq"]) for r in rows] == [
        ("statement", 1, 2), ("proposal", None, 4)
    ]
    proposed = _item(_knowledge(h, project["id"]), "K-002")["current"]
    assert (proposed["source_case_title"], proposed["source_message_seq"]) == ("규칙 이야기", None)

    # 작업 실행의 후보 — 메시지가 없다(대화 제목만). `supports` 는 K-001 의 근거 행이 되고 그 행도 제목을 가진다.
    executor = h.agent.cli_executor
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block(
        [_candidate(content=f"{MARK}-C 표본 관찰", repository="primary"),
         _candidate(summary="뒷받침", content=f"{MARK}-S 시각 없는 로그 확인", relates_to="K-001", relation="supports")]
    )
    work = _run_to_completion(h, project)
    extraction = _registrations(h, work, "extraction")
    assert [(r["intake_state"], r["source_message_seq"], r["reply_seq"]) for r in extraction] == [
        ("registered", None, None), ("evidence", None, None)
    ]
    view = _knowledge(h, project["id"])
    candidate = _item(view, "K-003")["current"]
    assert (candidate["source_case_title"], candidate["source_message_seq"]) == ("필터 기능", None)
    [evidence] = _item(view, "K-001")["evidence"]
    assert (evidence["kind"], evidence["source_case_title"], evidence["source_case_id"]) == ("supports", "필터 기능", work)

    # 본문은 어느 조회에도 없다 — 표식은 `knowledge_body` 에만.
    for payload in (view, h.conversation(talk), h.conversation(work), _use(h, work)):
        assert MARK not in json.dumps(payload, ensure_ascii=False)
    assert marker_tables(Path(h.controller_config.db_path), MARK) == {"knowledge_body"}


def test_the_case_knowledge_use_counts_provided_manifests_per_version(processing_harness):
    """AC-3·AC-10 — 이 업무의 실행들에 제공된 규칙을 버전별로 센다: `provided` 만 제공, 비적용은 사유별 수,
    실행 수는 Manifest 와 같다. 기록 전 실행이 없으면 `runs_unrecorded = 0`. 없는 Case 는 404."""
    h = processing_harness
    project, _path = h.create_git_project("dv-use")
    talk = h.create_conversation(project["id"], "규칙 등록")["case_id"]
    required = _register(h, talk, f"{MARK} 모든 작업에 적용되는 필수 규칙", "필수 규칙")
    reference = _register(
        h, talk, f"{MARK} 검증에서만 참고할 사실", "검증 참고", kind="operation", obligation="reference",
        activities=["verification"],
    )
    assert (required["state"], reference["state"]) == ("active", "active")

    work = _run_to_completion(h, project)
    runs = _runs(h, work)
    assert any(r["purpose"] == "verification_run" for r in runs)
    use = _use(h, work)
    assert (use["runs_recorded"], use["runs_unrecorded"]) == (len(runs), 0)
    assert "준수의 증거가 아니다" in use["note"]
    by_key = {i["knowledge_key"]: i for i in use["items"]}
    assert set(by_key) == {"K-001", "K-002"}

    # Manifest 와 대조 — 실행마다 `provided` 인 버전을 세면 같은 수가 나온다.
    provided: dict[str, int] = {}
    skipped: dict[str, dict[str, int]] = {}
    last_provided: dict[str, str] = {}
    for run in runs:
        for row in _manifest(h, run["run_id"])["items"]:
            key = row["knowledge_key"]
            if row["decision"] == "provided":
                provided[key] = provided.get(key, 0) + 1
                last_provided[key] = run["run_id"]
            else:
                skipped.setdefault(key, {})
                skipped[key][row["decision"]] = skipped[key].get(row["decision"], 0) + 1
    for key in ("K-001", "K-002"):
        assert by_key[key]["provided_runs"] == provided.get(key, 0), key
        assert by_key[key]["skipped"] == skipped.get(key, {}), key
        assert by_key[key]["last_run_id"] == last_provided.get(key), key
        assert by_key[key]["version"] == 1 and by_key[key]["state"] == "active"
    # 필수(모든 작업 활동)는 참고(검증만)보다 많은 실행에 들어갔고, 참고는 검증 실행에만 들어갔다.
    assert by_key["K-001"]["provided_runs"] > by_key["K-002"]["provided_runs"] >= 1
    assert by_key["K-002"]["last_run_purpose"] == "verification_run"
    assert by_key["K-002"]["skipped"].get("not_applicable_activity", 0) >= 1
    assert (by_key["K-001"]["obligation"], by_key["K-002"]["obligation"]) == ("required", "reference")

    # 규칙을 말한 대화 자체에는 작업 실행이 없다 — 논의 응답 하나가 Manifest 를 기록했을 뿐 제공 항목은 없다.
    talk_use = _use(h, talk)
    assert talk_use["items"] == [] and talk_use["runs_unrecorded"] == 0
    missing = h.client.get("/api/cases/case-does-not-exist/knowledge-use")
    assert missing.status_code == 404


def test_the_use_view_keeps_the_version_that_was_provided_after_a_revision(processing_harness):
    """AC-3 — 개정 뒤에도 집계는 **당시 제공된 버전**을 가리킨다(v1). 새 버전은 다음 실행부터 따로 센다."""
    h = processing_harness
    project, _path = h.create_git_project("dv-rev")
    talk = h.create_conversation(project["id"], "규칙 등록")["case_id"]
    first = _register(h, talk, f"{MARK} 첫 내용", "규칙 A")
    case_a = _start_in(h, project)
    _drive(h, case_a)
    _agree(h, case_a)
    _drive(h, case_a)
    revised = h.client.post(
        f"/api/knowledge/{first['knowledge_id']}/versions",
        json={"reason_summary": "표현을 다듬음", "summary": "규칙 A(개정)"},
    )
    assert revised.status_code == 201, revised.text
    assert revised.json()["version"]["version"] == 2
    # `state` 는 제공 당시(활성), `state_now` 는 지금(대체됨) — 당시 기록을 지금 값으로 다시 쓰지 않는다.
    use_a = _use(h, case_a)
    assert [(i["knowledge_key"], i["version"], i["state"], i["state_now"]) for i in use_a["items"]] == [
        ("K-001", 1, "active", "superseded")
    ]
    assert use_a["items"][0]["provided_runs"] >= 1

    case_b = _run_to_completion(h, project, "오류 줄 필터를 구현해줘 (둘째)")
    use_b = _use(h, case_b)
    assert [(i["knowledge_key"], i["version"], i["state"], i["state_now"]) for i in use_b["items"]] == [
        ("K-001", 2, "active", "active")
    ]
