"""UI-04c — 활성 목적·Profile 이행(D-86)(plans/UI-PLAN-04c.md 4·5절).

같은 문제의 미완료 업무에서 목적이 더해지거나 유형이 바뀌면 **같은 Case 에서** Profile 을 개정하고
의도를 새 버전으로 다시 쓴다. 이전 기준·판정·결정·예약·시도 수·위임 근거는 그대로다.

이 파일이 지키는 것:

    개정은 기록이다              Case 행과 개정 행만 바뀌고 나머지는 값이 같다
    유지 항목이 대상을 지킨다      이전 Profile 의 의미 항목이 새 문서에 남고 그 기준의 의무는 그 Profile 의 것이다
    이전 목적은 사라지지 않는다    유지 목적이 선언 목적에 합쳐져 양쪽을 요구한다(P4-03 계약 그대로)
    개정은 권한이 아니다          제품 쓰기는 진입 검사가 그대로 본다. 새 버전은 검토·동의를 다시 지난다
    해석은 근거가 아니다          AI 해석 경로의 근거는 사용자 메시지 원문이다

시험 이름 옆의 AC 번호는 UI-PLAN-04c 4절이다.
"""

from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from controller import db
from controller.db import utc_now
from controller.repository import Repository
from domain import conversation as convmod
from domain import intent_doc, profiles
from domain.completion_meaning import derive_obligation
from domain.models import (
    CaseProfile,
    CriterionObligation,
    InterpretationKind,
    InterpretationRefusal,
    InterpretationStatus,
    ObligationSource,
)
from tests.conftest import FAKE_DRAFT_RESPONSE
from tests.test_progression import _refusals
from tests.test_work_progressor import (
    ANALYSIS_DETERMINED,
    ANALYSIS_INCONCLUSIVE,
    _agree,
    _drive,
    _runs,
    _start,
    _wait_codes,
)

COMMON = ["goal", "expected_outcome", "scope", "exclusions", "constraints", "open_questions"]
RCA_FIELDS = ["phenomenon", "observations", "cause_questions", "conclusion_requirement", "analysis_end_condition"]
FIX_FIELDS = ["observed_behavior", "expected_behavior", "expectation_basis", "occurrence_conditions", "restore_scope"]

#: 개정 뒤 의도 재작성 응답 — 같은 키의 기준은 같은 의무(`cause`)를 적고, 수정 기준 하나를 더한다.
REVISED_DRAFT = (
    FAKE_DRAFT_RESPONSE.replace(
        '{"key": "C-01", "relates_to": "expected_outcome",',
        '{"key": "C-01", "relates_to": "expected_outcome", "obligation": "cause",',
    )
    .replace(
        '{"key": "C-02", "relates_to": "constraints",',
        '{"key": "C-02", "relates_to": "constraints", "obligation": "cause",',
    )
    .replace(
        '"summary": "Windows 로컬 경로를 읽는다", "method_summary": "로컬 경로 한 건 확인"}',
        '"summary": "Windows 로컬 경로를 읽는다", "method_summary": "로컬 경로 한 건 확인"},\n'
        '    {"key": "C-03", "relates_to": "restore_scope", "obligation": "restoration",\n'
        '     "text": "수정 뒤 ERROR 줄만 출력된다", "method": "표본 파일로 다시 확인한다",\n'
        '     "summary": "수정 뒤 정상 출력", "method_summary": "표본으로 재확인"}',
    )
    .replace('"questions": [],', '"questions": [],\n  "objectives": ["cause", "restoration"],')
)
assert '"C-03"' in REVISED_DRAFT and '"objectives"' in REVISED_DRAFT


# ================================================== 순수 규칙


def test_retained_fields_keep_the_previous_profile_items_after_the_current_ones():
    """AC-3 — 개정 뒤 항목 순서: 공통 여섯 → 현재 Profile → 유지 항목(이전 Profile). 겹치는 것은 없다."""
    retained = profiles.retained_fields([("root_cause_analysis", "2")], ("defect_fix", "2"))
    assert list(retained) == RCA_FIELDS
    order = list(profiles.field_order("defect_fix", "2", retained))
    assert order == COMMON + FIX_FIELDS + RCA_FIELDS
    assert profiles.required_fields("defect_fix", "2", retained) == frozenset(order)
    # 두 번째 개정은 앞선 유지 항목을 누적하고, 현재 Profile 의 항목은 유지 목록에서 빠진다.
    again = profiles.retained_fields([("defect_fix", "2")], ("root_cause_analysis", "2"), retained)
    assert list(again) == FIX_FIELDS
    assert profiles.retained_fields([("defect_fix", "2")], ("defect_fix", "2")) == ()
    assert profiles.field_owner("cause_questions") is CaseProfile.ROOT_CAUSE_ANALYSIS
    assert profiles.field_owner("goal") is None and profiles.field_owner(None) is None
    # 유지 항목이 없으면 이전과 같다(옛 호출자).
    assert profiles.field_order("defect_fix", "2") == profiles.resolve("defect_fix", "2").required_fields


def test_a_retained_field_criterion_keeps_the_owner_profiles_obligation():
    """AC-4 — `cause_questions` 에 걸린 기준은 defect_fix 계약 아래서도 `cause` 로 도출된다. 보고값이 우선이고,
    자기 항목·공통 항목은 현재 계약 그대로다. 판을 모르는 옛 호출자는 현재 계약만 본다."""
    contract = profiles.completion_contract("defect_fix", "2")
    assert derive_obligation(contract, "cause_questions", None, "2") == (
        CriterionObligation.CAUSE, ObligationSource.DERIVED_FROM_FIELD,
    )
    assert derive_obligation(contract, "restore_scope", None, "2")[0] is CriterionObligation.RESTORATION
    assert derive_obligation(contract, "expected_outcome", None, "2")[0] is CriterionObligation.RESTORATION
    assert derive_obligation(contract, "cause_questions", "restoration", "2") == (
        CriterionObligation.RESTORATION, ObligationSource.REPORTED,
    )
    assert derive_obligation(contract, "cause_questions", None)[0] is CriterionObligation.RESTORATION
    assert derive_obligation(None, "cause_questions", "cause", "2") == (None, None)


def test_the_document_keeps_retained_fields_and_their_criteria():
    """AC-3 — v6 문서는 유지 항목을 스스로 적고, 그 항목을 가리키는 기준을 받는다. 유지 항목이 없으면 그 기준은
    거부된다(항목 밖). 옛 문서의 유지 항목은 0건이다."""
    fields = {"goal": {"text": "원인을 찾고 고친다", "origin": "user_requirement"}}
    crit = {
        "key": "C-01", "relates_to": "cause_questions", "text": "원인이 확정된다", "method": "로그 대조",
        "summary": "원인 확정", "method_summary": "로그 대조",
    }
    body = intent_doc.compose(
        fields=fields, questions=[], case_id="c", authored_by="o", criteria=[crit],
        profile="defect_fix", profile_version="2", retained_fields=RCA_FIELDS,
    )
    doc = json.loads(body)
    assert doc["doc_version"] == intent_doc.DOC_VERSION == 6
    assert doc["retained_fields"] == RCA_FIELDS
    assert doc["field_order"] == COMMON + FIX_FIELDS + RCA_FIELDS
    assert doc["fields"]["cause_questions"]["state"] == "undecided"
    assert "obligation" not in doc["criteria"][0]  # 도출값은 문서에 쓰지 않는다
    report = intent_doc.structure(body)
    assert report["retained_fields"] == RCA_FIELDS
    assert [f["field"] for f in report["fields"]] == COMMON + FIX_FIELDS + RCA_FIELDS
    with pytest.raises(ValueError):
        intent_doc.compose(
            fields=fields, questions=[], case_id="c", authored_by="o", criteria=[crit],
            profile="defect_fix", profile_version="2",
        )
    old = json.loads(body)
    old["doc_version"] = 5
    del old["retained_fields"]
    assert intent_doc.parse(json.dumps(old).encode("utf-8"))["retained_fields"] == []


def test_a_profile_change_interpretation_needs_a_profile_and_known_objectives():
    """AC-8 — `profile_change` 는 Profile 이 있어야 하고 목적은 열거값이어야 한다. 모르는 것은 `invalid` 이며
    논의로 바꿔 읽지 않는다. 적용을 시도하는 종류는 `work_request`·`profile_change` 둘이다."""
    parsed = convmod.parse_interpretation(
        {"kind": "profile_change", "profile": "defect_fix", "objectives": ["restoration", "cause", "cause"]}
    )
    assert (parsed.status, parsed.kind, parsed.profile) == (
        InterpretationStatus.REPORTED, InterpretationKind.PROFILE_CHANGE, CaseProfile.DEFECT_FIX,
    )
    assert parsed.objectives == ("restoration", "cause")
    assert parsed.to_dict()["objectives"] == ["restoration", "cause"]
    assert convmod.parse_interpretation({"kind": "profile_change"}).status is InterpretationStatus.INVALID
    bad = convmod.parse_interpretation({"kind": "profile_change", "profile": "defect_fix", "objectives": ["nope"]})
    assert bad.status is InterpretationStatus.INVALID and "nope" in bad.detail
    assert convmod.interpretation_refusal(parsed, "completed") is None
    assert convmod.interpretation_refusal(parsed, "failed") is InterpretationRefusal.REPLY_NOT_COMPLETED
    discussion = convmod.parse_interpretation({"kind": "discussion"})
    assert convmod.interpretation_refusal(discussion, "completed") is InterpretationRefusal.NOT_A_WORK_REQUEST
    text, split = convmod.split_interpretation(
        '수정까지 하겠습니다.\n\n```hads-interpretation\n{"kind": "profile_change", "profile": "defect_fix"}\n```'
    )
    assert text == "수정까지 하겠습니다." and split.kind is InterpretationKind.PROFILE_CHANGE
    assert split.objectives == ()


# ================================================== 도우미


def _repo(h) -> Repository:
    return Repository(h.client.app.state.conn, auto_process_requests=True)


def _rca_waiting(h, *, response: str = ANALYSIS_INCONCLUSIVE):
    """원인 분석 업무를 분석까지 돌려 **미완료(사람 대기)** 로 둔다. 반환: (project, case_id)."""
    h.agent.cli_executor.analysis_response = response
    project, case_id, _request_id = _start(
        h, profile="root_cause_analysis", git=True, text="로그 형식 문제의 원인을 찾아줘"
    )
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    _agree(h, case_id)
    conv = _drive(h, case_id)
    return project, case_id, conv


def _revise(h, case_id: str, **body: Any):
    payload = {
        "profile": "defect_fix",
        "added_objectives": ["restoration"],
        "keep_previous_objectives": True,
        "actor": "owner",
        "reason_summary": "원인을 찾고 수정도 한다",
    }
    payload.update(body)
    return h.client.post(f"/api/cases/{case_id}/profile-revisions", json=payload)


def _snapshot(h, case_id: str) -> dict[str, Any]:
    detail = h.client.get(f"/api/cases/{case_id}").json()
    policy = h.client.get(f"/api/cases/{case_id}/policy").json()
    budget = h.client.get(f"/api/cases/{case_id}/budget").json()
    conv = h.conversation(case_id)
    repo = _repo(h)
    versions = [v["id"] for v in detail["intent_versions"]]
    return {
        "versions": versions,
        "criteria": {
            vid: [(c["criterion_key"], c["verdict"], c["obligation"], c["state"]) for c in repo.list_success_criteria(vid)]
            for vid in versions
        },
        "decisions": [d["id"] for d in detail["decisions"]],
        "basis": policy["delegation_basis"]["current"]["id"] if policy["delegation_basis"]["current"] else None,
        "autonomy": (policy["autonomy"], policy["autonomy_source"]),
        "reservations": sorted((r["run_id"], r["generation"], r["metric"]) for r in budget["reservations"]),
        "run_count_exposure": budget["usage"]["run_count"]["exposure"],
        "attempts": conv["progress"]["attempts"] if conv["progress"] else None,
        "runs": [r["run_id"] for r in detail["runs"]],
    }


def _confirm_pending_deltas(h, case_id: str) -> int:
    pending = list(h.material_deltas(case_id)["pending"])
    for delta in pending:
        response = h.client.post(
            f"/api/cases/{case_id}/material-deltas/{delta['id']}/confirmation",
            json={"actor": "owner", "explicit": True, "note_summary": "개정으로 더한 기준"},
        )
        assert response.status_code == 201, response.text
    return len(pending)


# ================================================== AC-1·3·4·5·7 개정과 보존


def test_a_revision_records_history_keeps_everything_else_and_carries_the_criteria(processing_harness):
    """AC-1·AC-3·AC-4·AC-5·AC-7 — 미완료 RCA 에 "수정도" 를 더하면 같은 Case 가 defect_fix 로 개정되고, 위임 근거·
    예약·시도 수·이전 버전·기준·판정·결정은 그대로다. 진행기가 의도를 새 버전으로 다시 쓰고(유지 항목·유지 목적·
    직전 기준을 받는다), 같은 키·같은 의무의 기준은 판정이 승계되며 새 버전은 delta 확인·동의를 지난다. 완료는
    `cause` 와 `restoration` 을 함께 요구한다."""
    h = processing_harness
    _project, case_id, conv = _rca_waiting(h)
    assert _wait_codes(conv) == ["criteria_unresolved"]
    before = _snapshot(h, case_id)
    old_version = before["versions"][-1]
    assert {v for _k, v, _o, _s in before["criteria"][old_version]} == {"not_met"}
    assert {o for _k, _v, o, _s in before["criteria"][old_version]} == {"cause"}

    h.agent.cli_executor.draft_response = REVISED_DRAFT
    response = _revise(h, case_id)
    assert response.status_code == 201, response.text
    view = response.json()
    assert (view["profile"], view["profile_version"], view["profile_source"], view["kind"]) == (
        "defect_fix", "2", "revised", "bug",
    )
    [revision] = view["revisions"]
    assert (revision["from_profile"], revision["to_profile"], revision["decided_by"]) == (
        "root_cause_analysis", "defect_fix", "person",
    )
    assert revision["retained_fields"] == RCA_FIELDS
    assert revision["carried_objectives"] == ["cause"]
    assert revision["added_objectives"] == []  # restoration 은 defect_fix 계약이 이미 요구한다
    assert revision["intent_version_id_before"] == old_version
    assert revision["reason_summary"] == "원인을 찾고 수정도 한다"
    assert view["retained_fields"] == RCA_FIELDS and view["carried_objectives"] == ["cause"]
    assert [m["state"] for m in revision["criteria_mapping"]] == ["pending", "pending"]

    # **바뀌지 않은 것** — 개정 직후(새 버전이 아직 없다). 진행기가 의도 개정 실행 하나를 만들었을 뿐이다 —
    # 그 실행의 예약·시도 수는 **더해진** 것이고 이전 것은 값이 같다.
    after = _snapshot(h, case_id)
    for key in ("versions", "criteria", "decisions", "basis", "autonomy"):
        assert after[key] == before[key], key
    added_runs = set(after["runs"]) - set(before["runs"])
    assert set(before["runs"]) <= set(after["runs"]) and len(added_runs) == 1
    [new_run] = added_runs
    assert "intent-revision" in new_run
    assert [r for r in after["reservations"] if r[0] != new_run] == before["reservations"]
    assert after["run_count_exposure"] == before["run_count_exposure"] + 1  # 새 실행의 예약뿐
    assert {k: v for k, v in after["attempts"].items() if k != "intent_revision"} == before["attempts"]
    conv = h.conversation(case_id)
    assert (conv["profile"], conv["profile_source"]) == ("defect_fix", "revised")
    assert [r["revision"] for r in conv["profile_revisions"]] == [1]
    assert conv["progress"]["state"] == "running" and conv["progress"]["step"] == "intent_revision"
    profile = _repo(h).case_profile(case_id)
    assert (profile["source"], profile["retained_fields"], profile["carried_objectives"], profile["revision_count"]) == (
        "revised", RCA_FIELDS, ["cause"], 1,
    )
    assert profile["required_fields"] == COMMON + FIX_FIELDS + RCA_FIELDS

    # 진행기 — 의도 개정 실행이 유지 항목·유지 목적·직전 기준을 받는다.
    conv = _drive(h, case_id)
    runs = _runs(h, case_id)
    assert runs[-1]["purpose"] == "intent_authoring"
    assert "limited_analysis" not in [r["purpose"] for r in runs[len(before["runs"]):]]
    prompt = next(c["prompt"] for c in h.agent.cli_executor.calls if c["run_id"] == runs[-1]["run_id"])
    assert "이전 목적에서 이어지는 항목" in prompt and "cause_questions" in prompt
    assert "계속 충족해야 한다" in prompt and "C-01 · expected_outcome · cause" in prompt
    assert "root_cause_analysis → 지금 defect_fix" in prompt

    detail = h.client.get(f"/api/cases/{case_id}").json()
    assert len(detail["intent_versions"]) == len(before["versions"]) + 1
    latest = h.latest_intent(case_id)
    assert (latest["profile"], latest["retained_fields"]) == ("defect_fix", RCA_FIELDS)
    assert latest["required_fields"] == COMMON + FIX_FIELDS + RCA_FIELDS
    assert {f["field"] for f in latest["fields"]} == set(COMMON + FIX_FIELDS + RCA_FIELDS)
    assert json.loads(_repo(h).get_intent_version(latest["id"])["objectives_json"]) == ["cause", "restoration"]
    # 옛 버전은 자기 항목 집합 그대로다(개정 뒤에도).
    old_detail = _repo(h).get_intent_detail(old_version)
    assert (old_detail["profile"], old_detail["retained_fields"]) == ("root_cause_analysis", [])
    assert old_detail["required_fields"] == COMMON + RCA_FIELDS

    # 기준 승계 — 같은 키·같은 의무는 판정을 잇고(`carried_from`), 새 기준은 미확인이다. 옛 행은 남는다.
    crits = {c["criterion_key"]: c for c in h.criteria(case_id)}
    assert set(crits) == {"C-01", "C-02", "C-03"}
    assert crits["C-01"]["obligation"] == "cause" and crits["C-01"]["obligation_source"] == "reported"
    assert crits["C-01"]["verdict"] == "not_met" and crits["C-01"]["recheck_source"].startswith("carried_from:")
    assert crits["C-02"]["verdict"] == "not_met" and crits["C-02"]["recheck_source"].startswith("carried_from:")
    assert (crits["C-03"]["obligation"], crits["C-03"]["verdict"]) == ("restoration", "unverified")
    mapping = {m["key"]: m for m in h.client.get(f"/api/cases/{case_id}/profile-revisions").json()["revisions"][0]["criteria_mapping"]}
    assert {k: m["state"] for k, m in mapping.items()} == {"C-01": "carried", "C-02": "carried"}
    assert mapping["C-01"]["after"]["carried"] is True and mapping["C-01"]["before_verdict"] == "not_met"
    old_rows = {c["criterion_key"]: c for c in _repo(h).list_success_criteria(old_version)}
    assert {c["state"] for c in old_rows.values()} == {"superseded"}
    assert {c["verdict"] for c in old_rows.values()} == {"not_met"}  # 승계된 판정의 옛 행은 그대로다

    # 완료 의미 — 유지 목적과 새 계약의 의무를 **함께** 요구한다(AC-07 "양쪽 충족").
    meaning = _repo(h).completion_meaning(case_id)
    assert {o["obligation"] for o in meaning["objectives"]} == {"cause", "restoration"}
    assert meaning["declared_objectives"] == ["cause", "restoration"]

    # 새 버전은 기존 의도 단계를 지난다 — 더한 기준의 material delta 확인 → 사람의 동의. 시도 수는 초기화되지 않는다.
    codes = _wait_codes(conv)
    assert codes in (["material_delta"], ["intent_agreement"]), codes
    if codes == ["material_delta"]:
        assert _confirm_pending_deltas(h, case_id) >= 1
        conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    assert conv["progress"]["wait"][0]["intent_version_id"] == latest["id"]
    attempts = conv["progress"]["attempts"]
    assert attempts["analysis"] == before["attempts"]["analysis"] and attempts.get("intent_revision") == 1
    for key, value in before["attempts"].items():
        assert attempts[key] == value, key


def test_a_revision_does_not_open_product_writes_by_itself(processing_harness):
    """AC-6 — RCA 에서는 구현 실행이 `purpose_outside_case_objective` 로 막힌다. defect_fix 로 개정해도 구현 실행은
    진입 검사(작업공간·동의 …)가 그대로 막는다 — 개정은 권한이 아니다."""
    h = processing_harness
    _project, case_id, _conv = _rca_waiting(h)
    refused = h.request_implementation(case_id, run_id="run-before", permission="workspace_write", task_id="T1")
    assert refused.status_code == 409, refused.text
    assert "purpose_outside_case_objective" in _refusals(refused)

    assert _revise(h, case_id).status_code == 201
    refused = h.request_implementation(case_id, run_id="run-after", permission="workspace_write", task_id="T1")
    assert refused.status_code == 409, refused.text
    codes = _refusals(refused)
    assert codes and "purpose_outside_case_objective" not in codes
    assert not any(r["run_id"] in ("run-before", "run-after") for r in _runs(h, case_id))


# ================================================== AC-2 거부


def test_revisions_are_refused_where_they_would_lie(processing_harness):
    """AC-2 — 준비 단계·v1·같은 Profile 에 추가 목적 없음·끝나지 않은 실행·종료 Case 는 거부되고 아무 것도 저장되지
    않는다."""
    h = processing_harness
    project = h.create_project()

    prep = h.create_conversation(project["id"], "준비")
    refused = _revise(h, prep["case_id"], profile="feature")
    assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["case_not_in_work_stage"]

    same = h.create_case(project["id"], "같은 유형", profile="feature")
    refused = _revise(h, same["id"], profile="feature", added_objectives=[])
    assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["profile_revision_empty"]
    # 같은 Profile 이라도 목적을 더하면 개정이다.
    accepted = _revise(h, same["id"], profile="feature", added_objectives=["cause"], reason_summary="원인도 적는다")
    assert accepted.status_code == 201, accepted.text
    [rev] = accepted.json()["revisions"]
    assert (rev["retained_fields"], rev["carried_objectives"], rev["added_objectives"]) == ([], [], ["cause"])

    v1 = h.create_case(project["id"], "옛 정의판", profile="defect_fix")
    conn = sqlite3.connect(h.controller_config.db_path)
    try:
        conn.execute('UPDATE "case" SET profile_version = ? WHERE id = ?', ("1", v1["id"]))
        conn.commit()
    finally:
        conn.close()
    refused = _revise(h, v1["id"], profile="feature")
    assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["profile_definition_not_current"]

    busy = h.create_case(project["id"], "실행 중", kind="analysis")
    artifact = h.submit_artifact(busy["id"], "조사 지시")["artifact_id"]
    h.create_run(busy["id"], artifact, run_id="run-busy-1")  # 배정 전 — 끝나지 않은 실행
    refused = _revise(h, busy["id"], profile="defect_fix")
    assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["runs_unfinished"]

    for case_id in (prep["case_id"], v1["id"], busy["id"]):
        view = h.client.get(f"/api/cases/{case_id}/profile-revisions").json()
        assert view["revisions"] == [] and view["profile_source"] != "revised"

    _project, closed_id, conv = _rca_waiting(h, response=ANALYSIS_DETERMINED)
    assert h.client.get(f"/api/cases/{closed_id}").json()["status"] == "closed", conv["progress"]
    refused = _revise(h, closed_id)
    assert refused.status_code == 409 and refused.json()["detail"]["refusals"] == ["case_already_closed"]


# ================================================== AC-8 AI 해석 경로


def test_an_ai_profile_change_revises_with_the_user_message_as_basis(processing_harness):
    """AC-8 — 업무 단계 응답의 `profile_change` 는 사용자 메시지를 근거로 개정하고(이전 목적 유지), 진행기가 의도
    개정 실행을 잇는다. 형식이 틀린 블록은 `invalid` 로 남고 아무것도 개정하지 않는다."""
    h = processing_harness
    _project, case_id, conv = _rca_waiting(h)
    assert conv["send"]["general"]["allowed"] is True
    h.agent.cli_executor.discussion_response = (
        '알겠습니다. 수정 범위를 더합니다.\n\n```hads-interpretation\n'
        '{"kind": "profile_change", "profile": "defect_fix", "objectives": ["restoration"]}\n```'
    )
    h.agent.cli_executor.draft_response = REVISED_DRAFT
    sent = h.send_message(case_id, "원인을 찾고 수정도 해줘", "c-fix")
    h.agent.poll_once()
    conv = h.conversation(case_id)
    interp = conv["interpretations"][-1]
    assert (interp["kind"], interp["profile"], interp["applied"], interp["refusal"]) == (
        "profile_change", "defect_fix", True, None,
    )
    assert json.loads(interp["objectives_json"]) == ["restoration"]
    [revision] = conv["profile_revisions"]
    assert (revision["decided_by"], revision["to_profile"], revision["carried_objectives"]) == (
        "ai_interpretation", "defect_fix", ["cause"],
    )
    assert revision["request_message_id"] == sent["message"]["id"]
    assert revision["request_message_seq"] == sent["message"]["seq"]
    assert revision["interpretation_run_id"] == interp["run_id"]
    assert conv["profile"] == "defect_fix"
    # 응답 글은 대화에 붙고 블록은 떼어졌다.
    reply = conv["messages"][-1]
    assert reply["author"] == "assistant"
    _read, body = h.read_original(reply["artifact_id"], reply["artifact_rev"])
    assert "hads-interpretation" not in body and "수정 범위를 더합니다" in body

    conv = _drive(h, case_id)
    assert [r["purpose"] for r in _runs(h, case_id)][-1] == "intent_authoring"
    assert _wait_codes(conv) in (["material_delta"], ["intent_agreement"])
    assert h.latest_intent(case_id)["profile"] == "defect_fix"

    # 형식이 틀린 해석 — `invalid`, 개정 없음(개정 수 그대로).
    h.agent.cli_executor.discussion_response = (
        '음.\n\n```hads-interpretation\n{"kind": "profile_change", "profile": "feature", "objectives": ["nope"]}\n```'
    )
    if _wait_codes(conv) == ["material_delta"]:
        _confirm_pending_deltas(h, case_id)
        conv = _drive(h, case_id)
    assert conv["send"]["general"]["allowed"] is True, conv["send"]
    h.send_message(case_id, "그리고 기능도?", "c-bad")
    h.agent.poll_once()
    conv = h.conversation(case_id)
    interp = conv["interpretations"][-1]
    assert (interp["report_status"], interp["applied"], interp["refusal"]) == ("invalid", False, "not_reported")
    assert len(conv["profile_revisions"]) == 1 and conv["profile"] == "defect_fix"


# ================================================== AC-15 이행 v25 → v26


def test_a_v25_database_gets_per_version_profiles_and_the_new_tables(tmp_path):
    """AC-15 — v26 은 표 둘·컬럼 셋·해석 표 재구성이다. v25 DB 를 올리면 의도 버전 행에 그 Case 의 Profile 이 채워지고
    (미기록 Case 는 NULL), 개정·열기 요청은 0건, 해석 행은 보존되며 멱등이다. 본문 컬럼은 없다."""
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    db.migrate(conn)
    now = utc_now()
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DROP TABLE case_profile_revision")
    conn.execute("DROP TABLE workspace_open_request")
    for column in ("profile", "profile_version", "retained_fields_json"):
        conn.execute(f"ALTER TABLE intent_version DROP COLUMN {column}")
    conn.execute("DROP TABLE conversation_interpretation")
    conn.execute(
        "CREATE TABLE conversation_interpretation ("
        " run_id TEXT PRIMARY KEY REFERENCES run(run_id), case_id TEXT NOT NULL REFERENCES \"case\"(id),"
        " request_id TEXT NOT NULL REFERENCES conversation_request(id),"
        " opening_message_id TEXT NOT NULL REFERENCES conversation_message(id),"
        " report_status TEXT NOT NULL CHECK (report_status IN ('reported', 'missing', 'invalid')),"
        " kind TEXT CHECK (kind IS NULL OR kind IN ('discussion', 'work_request')),"
        " profile TEXT CHECK (profile IS NULL OR profile IN ('feature', 'defect_fix', 'root_cause_analysis',"
        " 'research', 'refactoring', 'maintenance')),"
        " applied INTEGER NOT NULL DEFAULT 0 CHECK (applied IN (0, 1)),"
        " refusal TEXT CHECK (refusal IS NULL OR length(refusal) <= 64), recorded_at TEXT NOT NULL,"
        " evaluated_at TEXT,"
        " CHECK (applied = 0 OR (report_status = 'reported' AND kind = 'work_request'"
        " AND profile IS NOT NULL AND evaluated_at IS NOT NULL)))"
    )
    conn.execute("DELETE FROM schema_version WHERE version >= 26")
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at, stage, profile, profile_version)'
        " VALUES ('case-v2', 'prj-1', 'v2', 'bug', 'received', ?, ?, 'work', 'defect_fix', '2')",
        (now, now),
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-old', 'prj-1', 'R1 이전', 'feature', 'received', ?, ?)",
        (now, now),
    )
    for intent_id, case_id in (("intent-a", "case-v2"), ("intent-b", "case-old")):
        conn.execute(
            "INSERT INTO intent_version (id, case_id, revision, artifact_id, artifact_rev, status, created_at)"
            " VALUES (?, ?, 1, 'art-1', 1, 'draft', ?)",
            (intent_id, case_id, now),
        )
    # 해석 행이 가리키는 실행·요청·메시지(재구성 뒤 외래 키 검사가 이 표의 참조를 본다).
    conn.execute(
        "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission, instruction_artifact_id,"
        " instruction_artifact_rev, status, assignment_generation, created_at)"
        " VALUES ('run-1', 'case-v2', 'conversation', 'author', 'codex', 'exec', 'read_only', 'art-1', 1,"
        " 'finished', 1, ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO conversation_request (id, case_id, state, opened_at, settled_at, settled_by)"
        " VALUES ('req-1', 'case-v2', 'completed', ?, ?, 'system')",
        (now, now),
    )
    conn.execute(
        "INSERT INTO conversation_message (id, case_id, seq, author, message_kind, actor, client_message_id,"
        " intake_id, artifact_id, artifact_rev, content_hash, summary, created_at)"
        " VALUES ('msg-1', 'case-v2', 1, 'user', 'general', 'owner', 'c-1', 'in-1', 'art-1', 1, 'h', '메시지', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO conversation_interpretation (run_id, case_id, request_id, opening_message_id, report_status,"
        " kind, profile, applied, refusal, recorded_at, evaluated_at)"
        " VALUES ('run-1', 'case-v2', 'req-1', 'msg-1', 'reported', 'discussion', NULL, 0, 'not_a_work_request', ?, ?)",
        (now, now),
    )
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    db.migrate(conn)  # 멱등
    assert conn.execute("SELECT MAX(version) AS v FROM schema_version").fetchone()["v"] == db.SCHEMA_VERSION == 26
    rows = {
        r["id"]: (r["profile"], r["profile_version"], r["retained_fields_json"])
        for r in conn.execute("SELECT id, profile, profile_version, retained_fields_json FROM intent_version")
    }
    assert rows == {"intent-a": ("defect_fix", "2", None), "intent-b": (None, None, None)}
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"case_profile_revision", "workspace_open_request"} <= tables
    assert conn.execute("SELECT COUNT(*) AS n FROM case_profile_revision").fetchone()["n"] == 0
    assert conn.execute("SELECT COUNT(*) AS n FROM workspace_open_request").fetchone()["n"] == 0
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'conversation_interpretation'"
    ).fetchone()["sql"]
    assert "'profile_change'" in ddl and "objectives_json" in ddl
    kept = conn.execute("SELECT run_id, kind, refusal, objectives_json FROM conversation_interpretation").fetchall()
    assert [tuple(r) for r in kept] == [("run-1", "discussion", "not_a_work_request", None)]
    for table in ("case_profile_revision", "workspace_open_request", "conversation_interpretation"):
        columns = {c["name"] for c in conn.execute(f'PRAGMA table_info("{table}")')}
        assert not columns & {"content", "body", "text", "raw", "payload"}, table
    # 조회 — 옛 버전은 자기 행의 Profile 로 읽힌다(값이 채워졌으므로 그 뒤 개정해도 그대로다). 미기록 Case 는 공통 여섯.
    repo = Repository(conn)
    profile_a = repo._intent_version_profile(repo.get_intent_version("intent-a"))
    profile_b = repo._intent_version_profile(repo.get_intent_version("intent-b"))
    assert profile_a == ("defect_fix", "2", ()) and profile_b == (None, None, ())
    assert list(profiles.field_order(*profile_a)) == COMMON + FIX_FIELDS
    assert list(profiles.field_order(*profile_b)) == COMMON
    conn.close()
