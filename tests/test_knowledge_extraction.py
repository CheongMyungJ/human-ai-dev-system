"""P4-07 — 선택적 지식 추출(plans/P4-PLAN-07.md).

작업 실행(검증·분석·실험·구현)이 결과와 함께 남긴 **후보**(AI 제안)를 등록부에 넣고, 같은 내용·뒷받침하는
관측은 기존 항목의 근거로 잇고, 대체 제안·반증은 관계를 가진 새 후보로 둔다. 후보 → 활성은 사람의 결정이며
QG-08 채택 확인(근거·범위·상태·버전·충돌)을 지난다.

이 파일이 지키는 것:

    후보는 규칙이 아니다              AI 제안은 어떤 경로로도 활성 필수가 되지 않는다(DB CHECK 그대로)
    후보 없는 실행은 정상이다          블록이 없으면 아무 것도 기록하지 않고 진행·완료가 그대로다
    대상의 버전 사슬을 건드리지 않는다  대체 제안·반증은 관계로만 남고 기존 활성 버전은 그대로 주입된다
    활성화는 확인을 지난다            막는 항목은 거부, 경고는 새 버전에 기록, 범위는 좁힐 수만 있다
    원문은 서버에만 있다              후보 원문 표식은 `knowledge_body` 에만 있고 로그·다른 표에 없다

시험 이름 옆의 AC 번호는 P4-PLAN-07 4절이다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from controller import db
from controller.repository import Repository
from domain import knowledge as knowmod
from runner import prompts
from tests.conftest import FAKE_VERIFICATION_RESPONSE, RUNNER_ID
from tests.test_knowledge import _manifest, _prompt, _register, _repo, _runs, _start_in, marker_tables
from tests.test_work_progressor import _agree, _drive

MARK = "CAND-51e2-MARKER"
INSTRUCTION = "지시 원문".encode("utf-8")


def _block(items: list[dict[str, Any]]) -> str:
    return "\n\n```hads-knowledge\n" + json.dumps({"items": items}, ensure_ascii=False) + "\n```"


def _candidate(**overrides: Any) -> dict[str, Any]:
    item = {
        "kind": "operation", "obligation": "reference", "summary": "표본 시험 관찰",
        "content": f"{MARK} 이 저장소의 시험은 표본 파일 두 개로 돌고 종료 코드 0 이 정상이다.",
        "basis": "python -m pytest tests/test_reader.py 종료 코드 0", "repository": None, "paths": [],
        "activities": ["verification"], "relates_to": None, "relation": None,
    }
    item.update(overrides)
    return item


def _registrations(h, case_id: str, origin: str | None = None) -> list[dict[str, Any]]:
    rows = h.conversation(case_id)["knowledge_registrations"]
    return [r for r in rows if origin is None or r["origin"] == origin]


def _body_purposes(h) -> list[str]:
    import sqlite3

    conn = sqlite3.connect(h.controller_config.db_path)
    try:
        return sorted(r[0] for r in conn.execute("SELECT purpose FROM knowledge_body").fetchall())
    finally:
        conn.close()


def _knowledge(h, project_id: str) -> dict[str, Any]:
    response = h.client.get(f"/api/projects/{project_id}/knowledge")
    assert response.status_code == 200, response.text
    return response.json()


def _item(view: dict[str, Any], key: str) -> dict[str, Any]:
    return next(i for i in view["items"] if i["knowledge_key"] == key)


def _run_to_completion(h, project: dict[str, Any], text: str = "오류 줄 필터를 구현해줘") -> str:
    """대화 → 업무화 → 동의 → 구현·검증 → 종료까지(P4-06 시험의 경로)."""
    case_id = _start_in(h, project, text)
    _drive(h, case_id)
    _agree(h, case_id)
    _drive(h, case_id)
    return case_id


# ================================================== 순수 규칙 (domain.knowledge)


def test_report_items_carry_relation_basis_and_proposal_and_bad_relations_are_refused():
    """AC-9 — 항목의 관계·근거·제안 표지를 읽는다. 대상 없는 관계·모르는 관계는 거부다."""
    ok, refusal = knowmod.parse_report_item(
        dict(_candidate(relates_to="K-001", relation="supports", proposal=True), artifact_id="a", revision=1)
    )
    assert refusal is None
    assert (ok["relates_to"], ok["relation"], ok["proposal"]) == ("K-001", "supports", True)
    assert ok["basis"].startswith("python -m pytest")
    assert knowmod.parse_report_item(dict(_candidate(relation="supports"), artifact_id="a", revision=1)) == (
        None, "relation_without_target"
    )
    assert knowmod.parse_report_item(
        dict(_candidate(relates_to="K-001", relation="agrees"), artifact_id="a", revision=1)
    ) == (None, "invalid_relation")
    plain, _ = knowmod.parse_report_item(dict(_candidate(), artifact_id="a", revision=1))
    assert (plain["relation"], plain["relates_to"], plain["proposal"]) == (None, None, False)


def _cand(**kw: Any) -> dict[str, Any]:
    base = {
        "id": "v-c", "knowledge_id": "k-c", "knowledge_key": "K-009", "state": "candidate",
        "obligation": "reference", "scope_kind": "repository", "repository_id": "r-a",
        "activities": ["verification"], "relation": None, "relates_to_version": None,
        "observed": {"repository_id": "r-a", "repository_name": "app"},
    }
    base.update(kw)
    return base


def _codes(findings: list[knowmod.AdoptionFinding]) -> dict[str, bool]:
    return {f.code: f.blocking for f in findings}


def test_the_adoption_check_blocks_on_state_content_conflict_and_widening_and_warns_otherwise():
    """AC-5 — 막는 것: 후보 아님·원문 없음·열린 충돌·반증 대상 활성·`into` 대상 무효·범위 확대. 경고: 근거
    없음·관측보다 넓은 범위·필수 승격·관계 대상 버전 변경·독립 검토 없음."""
    clean = knowmod.adoption_check(
        _cand(), evidence_count=1, storage="server", open_conflicts=0, related=None, into=None
    )
    assert knowmod.adoption_blocked(clean) == []
    assert _codes(clean) == {"independent_review_not_run": False}

    blocked = knowmod.adoption_check(
        _cand(state="active"), evidence_count=0, storage="runner", open_conflicts=2,
        related={"id": "v-r", "knowledge_id": "k-r", "knowledge_key": "K-001", "state": "active", "version": 1},
        into={"knowledge_id": "k-x", "knowledge_key": "K-003", "state": "invalid"},
        requested={"scope_kind": "project", "activities": ["verification", "design"]},
    )
    codes = _codes(blocked)
    assert codes["not_a_candidate"] and codes["content_unavailable"] and codes["open_conflict"]
    assert codes["target_not_active"] and codes["scope_widened"] and codes["no_evidence"] is False
    assert sorted(knowmod.adoption_blocked(blocked)) == sorted(
        ["not_a_candidate", "content_unavailable", "open_conflict", "target_not_active", "scope_widened"]
    )

    # 반증 — 대상이 활성이면 막고, 대상 자신의 새 버전으로 적용하면(`into` = 대상) 막지 않는다.
    related = {"id": "v-r2", "knowledge_id": "k-r", "knowledge_key": "K-001", "state": "active", "version": 2}
    contra = _cand(relation="contradicts", relates_to_version="v-r1")
    found = knowmod.adoption_check(contra, evidence_count=1, storage="server", open_conflicts=0, related=related, into=None)
    assert _codes(found)["contradicts_active"] is True and _codes(found)["related_version_changed"] is False
    into_target = {"knowledge_id": "k-r", "knowledge_key": "K-001", "state": "active"}
    found = knowmod.adoption_check(contra, evidence_count=1, storage="server", open_conflicts=0, related=related, into=into_target)
    assert "contradicts_active" not in _codes(found)

    # 경고 — 관측보다 넓은 범위, 필수 승격.
    wide = knowmod.adoption_check(
        _cand(scope_kind="project", repository_id=None), evidence_count=1, storage="server",
        open_conflicts=0, related=None, into=None, requested={"obligation": "required"},
    )
    assert _codes(wide) == {
        "scope_wider_than_observed": False, "obligation_raised": False, "independent_review_not_run": False
    }
    # 축소는 막지 않는다.
    narrow = knowmod.adoption_check(
        _cand(activities=[]), evidence_count=1, storage="server", open_conflicts=0, related=None, into=None,
        requested={"activities": ["verification"], "obligation": "reference"},
    )
    assert knowmod.adoption_blocked(narrow) == []


def test_the_knowledge_head_shows_relation_and_observed_context():
    """AC-7 — 지시문 머리에 관계와 관측(저장소@커밋, Case 브랜치)이 적힌다. 없으면 적지 않는다."""
    head = prompts.knowledge_head(
        {
            "key": "K-004", "version": 1, "state": "candidate", "kind": "operation", "scope": "repository",
            "repository": "app", "activities": ["verification"], "summary": "표본 시험 관찰",
            "relation": "contradicts", "relates_to_key": "K-001",
            "observed": {"repository_name": "app", "base_commit": "abcdef0123456789"},
        }
    )
    assert "← K-001 반증" in head and "관측: 저장소 app@abcdef0 (Case 브랜치)" in head and "후보" in head
    plain = prompts.knowledge_head({"key": "K-001", "version": 1, "state": "active", "obligation": "required",
                                    "kind": "constraint", "scope": "project", "activities": [], "summary": "s"})
    assert "관측" not in plain and "←" not in plain


def test_the_extraction_rule_is_attached_only_to_work_runs_that_got_an_index():
    """AC-1·2 — 후보 규칙은 검증·분석·실험·구현 지시문에, 제어부가 지식 목록을 실었을 때만 붙는다."""
    index = {"items": [{"key": "K-001", "summary": "s", "obligation": "required", "state": "active"}],
             "repositories": ["app"], "run_repository": "app"}
    text = prompts.build("verification_run", INSTRUCTION, knowledge_index=index)
    assert "지식 후보(선택)" in text and '"repository": "app"' in text and "K-001" in text
    assert text.index("지식 후보(선택)") < text.index("--- 지시 원문 ---")
    assert "지식 후보(선택)" not in prompts.build("verification_run", INSTRUCTION, knowledge_index=None)
    assert "지식 후보(선택)" not in prompts.build("quality_gate_review", INSTRUCTION, knowledge_index=index)
    with_criteria = prompts.build("limited_analysis", INSTRUCTION, criteria=[{"key": "C-01"}], knowledge_index=index)
    assert with_criteria.index("criteria") < with_criteria.index("지식 후보(선택)")
    # 논의 응답의 등록 규칙에 제안 표지가 있다.
    assert '"proposal": true' in prompts.build("discussion_reply", INSTRUCTION, knowledge_index={"items": []})


# ================================================== AC-1·2·7·11·14 검증 실행의 후보


def test_a_verification_run_leaves_a_candidate_and_a_run_without_a_block_leaves_nothing(processing_harness):
    """AC-1·2·7·11·14 — 검증 실행의 후보 블록 → 후보(ai_proposal·candidate)·근거·관측 문맥, 원문은
    `knowledge_body` 에만, 실행 결과 원문에 블록 없음, 산출물(명령·기준)은 그대로, 종료도 그대로. 블록이
    없는 실행·Case 는 아무 것도 기록하지 않는다. 후보는 어떤 경로로도 활성 필수가 되지 않는다."""
    h = processing_harness
    project, _path = h.create_git_project("kx-cand")
    executor = h.agent.cli_executor
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block([_candidate(repository="primary")])
    case_id = _run_to_completion(h, project)
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "closed" and case["result"]["closure"]["closure_kind"] == "completed"
    assert all(c["recorded_by"] == "policy:work_progressor" for c in h.criteria(case_id))

    runs = _runs(h, case_id)
    verification = next(r for r in runs if r["purpose"] == "verification_run")
    assert verification["outcome"] == "completed"
    assert "지식 후보(선택)" in _prompt(h, verification["run_id"])
    [registration] = _registrations(h, case_id)
    assert (registration["origin"], registration["intake_state"], registration["knowledge_key"]) == (
        "extraction", "registered", "K-001"
    )
    assert registration["run_id"] == verification["run_id"]
    assert registration["basis"] == "추출 근거: python -m pytest tests/test_reader.py 종료 코드 0"
    view = _knowledge(h, project["id"])
    current = _item(view, "K-001")["current"]
    assert (current["state"], current["authority_kind"], current["obligation"]) == (
        "candidate", "ai_proposal", "reference"
    )
    assert current["source_run_id"] == verification["run_id"] and current["source_report_index"] == 0
    assert current["created_by"] == "ai:codex" and current["scope_kind"] == "repository"
    assert current["storage"] == "server" and current["source_message_id"] is None
    observed = current["observed"]
    assert observed["run_id"] == verification["run_id"] and observed["purpose"] == "verification_run"
    assert observed["repository_name"] == "primary" and observed["base_commit"]
    assert observed["tool_version"] == "codex/fake-for-tests"
    # 실행 결과 원문(대화의 AI 산출물)에는 블록이 없다. 원문 표식은 서버 본문 표에만 있다.
    _state, body = h.read_original(verification["output_artifact_id"], verification["output_artifact_rev"])
    assert body is not None and "hads-knowledge" not in body and MARK not in body
    assert marker_tables(Path(h.controller_config.db_path), MARK) == {"knowledge_body"}
    assert MARK.encode("utf-8") not in Path(h.controller_config.log_path).read_bytes()
    assert not any(MARK.encode("utf-8") in p.read_bytes() for p in h.agent.store.root.rglob("*.bin"))
    # DB 도 막는다 — 활성 필수 AI 제안.
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        h.client.app.state.conn.execute(
            "UPDATE knowledge_version SET state = 'active', obligation = 'required' WHERE id = ?", (current["id"],)
        )
    # 재처리는 아무 것도 더하지 않는다.
    assert _repo(h).apply_extraction_report(verification["run_id"]) == []

    # 다음 실행(다른 대화)에 후보가 보조로 들어가고 머리에 관측이 적힌다.
    executor.verification_response = FAKE_VERIFICATION_RESPONSE
    other = _run_to_completion(h, project, "오류 줄 필터를 구현해줘 (둘째)")
    # 후보의 활동은 verification 이다 — 검증 실행에만 들어가고 구현 실행에는 활동 비적용이다.
    verify = next(r for r in _runs(h, other) if r["purpose"] == "verification_run")
    refs = [r for r in h.context_refs(verify["run_id"]) if r["role"] == "knowledge_candidate"]
    assert len(refs) == 1 and refs[0]["tier"] == "supporting" and refs[0]["receipt_status"] == "read"
    assert refs[0]["knowledge"]["observed"]["repository_name"] == "primary"
    prompt = _prompt(h, verify["run_id"])
    assert MARK in prompt and "관측: 저장소 primary@" in prompt and "후보" in prompt
    assert {i["knowledge_key"]: i["decision"] for i in _manifest(h, verify["run_id"])["items"]} == {"K-001": "provided"}
    impl = next(r for r in _runs(h, other) if r["purpose"] == "feature_implementation")
    assert {i["knowledge_key"]: i["decision"] for i in _manifest(h, impl["run_id"])["items"]} == {
        "K-001": "not_applicable_activity"
    }
    # 블록이 없는 실행·Case: 기록 없음, 완료 그대로.
    assert _registrations(h, other) == []
    assert h.client.get(f"/api/cases/{other}").json()["status"] == "closed"


# ================================================== AC-3·4 근거·중복·관계


def test_supports_and_duplicates_become_evidence_and_supersedes_contradicts_become_related_candidates(
    processing_harness,
):
    """AC-3·4 — `supports` → 새 항목 없이 근거 행. 같은 내용 → 근거 행(duplicate). `supersedes`·
    `contradicts` → 관계를 가진 새 후보이며 대상의 현재 활성 버전은 그대로다."""
    h = processing_harness
    project, _path = h.create_git_project("kx-rel")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    rule = _register(h, rules, "오류 줄은 원래 순서를 유지한다", "순서 유지")
    assert rule["knowledge_key"] == "K-001"
    executor = h.agent.cli_executor
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block([
        _candidate(relates_to="K-001", relation="supports", summary="순서 유지 확인",
                   content="SUPPORT-MARK 순서가 유지되는 것을 시험으로 확인했다"),
        _candidate(relates_to="K-001", relation="supersedes", summary="순서 규칙 대체 제안",
                   content="SUPERSEDE-MARK 순서 유지는 빈 줄을 뺀 뒤에 본다"),
        _candidate(relates_to="K-001", relation="contradicts", summary="순서 반증",
                   content="CONTRA-MARK 시험에서 순서가 바뀌는 경우를 봤다", obligation="required"),
    ])
    case_id = _run_to_completion(h, project)
    rows = _registrations(h, case_id, "extraction")
    assert [(r["intake_state"], r["knowledge_key"], r["relation"], r["relates_to_key"]) for r in rows] == [
        ("evidence", None, None, None),
        ("registered", "K-002", "supersedes", "K-001"),
        ("registered", "K-003", "contradicts", "K-001"),
    ]
    assert rows[0]["evidence"]["kind"] == "supports" and rows[0]["evidence"]["knowledge_key"] == "K-001"
    view = _knowledge(h, project["id"])
    target = _item(view, "K-001")
    assert [(v["version"], v["state"]) for v in target["versions"]] == [(1, "active")]  # 사슬 그대로
    assert [(e["kind"], e["summary"]) for e in target["evidence"]] == [
        ("supports", "python -m pytest tests/test_reader.py 종료 코드 0")
    ]
    assert target["evidence"][0]["storage"] == "server"
    contra = _item(view, "K-003")["current"]
    assert (contra["state"], contra["obligation"], contra["relation"], contra["relates_to_key"]) == (
        "candidate", "required", "contradicts", "K-001"
    )
    assert contra["observed"]["relates_to_version"] == target["current"]["id"]

    # 같은 내용의 재보고 → 근거(duplicate). 항목은 늘지 않는다. 필수 규칙은 그대로 주입된다.
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block([
        _candidate(summary="반증 재관측", content="CONTRA-MARK 시험에서 순서가 바뀌는 경우를 봤다"),
    ])
    other = _run_to_completion(h, project, "오류 줄 필터를 구현해줘 (둘째)")
    [again] = _registrations(h, other, "extraction")
    assert (again["intake_state"], again["evidence"]["kind"], again["evidence"]["knowledge_key"]) == (
        "evidence", "duplicate", "K-003"
    )
    view = _knowledge(h, project["id"])
    assert [i["knowledge_key"] for i in view["items"]] == ["K-001", "K-002", "K-003"]
    assert [e["kind"] for e in _item(view, "K-003")["evidence"]] == ["duplicate"]
    verify = next(r for r in _runs(h, other) if r["purpose"] == "verification_run")
    roles = [r["role"] for r in h.context_refs(verify["run_id"]) if r["role"].startswith("knowledge_")]
    assert roles == ["knowledge_required", "knowledge_candidate", "knowledge_candidate"]
    assert "← K-001 반증" in _prompt(h, verify["run_id"]) and "← K-001 대체 제안" in _prompt(h, verify["run_id"])


# ================================================== AC-5·6 활성화의 확인


def test_activation_passes_the_adoption_check_narrows_only_and_can_apply_into_another_item(processing_harness):
    """AC-5·6 — 막는 항목(반증 대상 활성·범위 확대·열린 충돌·원문 없음)은 409 와 코드. 경고는 새 버전의
    `adoption` 에 남는다. 축소는 반영된다. `into` 는 대상의 새 버전이 되고 후보 버전은 대체로 닫힌다.
    다음 실행에 새 버전이 필수로 들어가고 후보는 들어가지 않는다."""
    h = processing_harness
    project, _path = h.create_git_project("kx-adopt")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    rule = _register(h, rules, "오류 줄은 원래 순서를 유지한다", "순서 유지")
    executor = h.agent.cli_executor
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block([
        _candidate(relates_to="K-001", relation="contradicts", summary="순서 반증",
                   content="CONTRA-MARK 빈 줄 뒤에서는 순서가 바뀐다", repository="primary"),
        _candidate(summary="독립 관찰", content="PLAIN-MARK 시험은 표본 두 개로 돈다", repository="primary",
                   activities=["verification", "implementation"]),
    ])
    case_id = _run_to_completion(h, project)
    view = _knowledge(h, project["id"])
    contra = _item(view, "K-002")
    plain = _item(view, "K-003")

    # 확인만 — 반증 대상이 활성이라 막힌다. 근거는 실행 하나.
    check = h.client.get(f"/api/knowledge/{contra['id']}/adoption-check").json()
    assert check["blocked"] == ["contradicts_active"] and check["evidence_count"] == 1
    assert check["related"] == {"knowledge_key": "K-001", "version": 1, "state": "active"}
    assert check["independent_review"] == "not_run"
    refused = h.client.post(f"/api/knowledge/{contra['id']}/activate", json={"reason_summary": "확인"})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"]["refusals"] == ["contradicts_active"]
    assert any(f["code"] == "contradicts_active" and f["blocking"] for f in refused.json()["detail"]["findings"])
    # 범위 확대는 막힌다.
    widened = h.client.post(
        f"/api/knowledge/{plain['id']}/activate", json={"reason_summary": "확인", "scope_kind": "project"}
    )
    assert widened.status_code == 409 and widened.json()["detail"]["refusals"] == ["scope_widened"]
    # 원문이 없으면 막힌다(시험용으로 서버 본문을 지운다 — 제품 경로 아님).
    from tests.test_knowledge import forget_server_body

    forget_server_body(h, plain["current"]["artifact_id"], plain["current"]["artifact_rev"])
    gone = h.client.post(f"/api/knowledge/{plain['id']}/activate", json={"reason_summary": "확인"})
    assert gone.status_code == 409 and gone.json()["detail"]["refusals"] == ["content_unavailable"]
    h.agent.poll_once()  # 소유 PC 에 사본이 없으므로 복구되지 않는다 — 지어내지 않는다
    assert h.client.get(f"/api/knowledge/{plain['id']}/adoption-check").json()["blocked"] == ["content_unavailable"]

    # 열린 충돌도 막는다.
    conflict = h.client.post(
        f"/api/projects/{project['id']}/knowledge-conflicts",
        json={"knowledge_a": contra["id"], "knowledge_b": rule["knowledge_id"], "reason_summary": "반대"},
    ).json()
    check = h.client.get(f"/api/knowledge/{contra['id']}/adoption-check?into_knowledge_id={rule['knowledge_id']}").json()
    assert check["blocked"] == ["open_conflict"]
    h.client.post(f"/api/knowledge-conflicts/{conflict['id']}/resolve", json={"reason_summary": "후보로 대체"})

    # `into` — K-001 의 새 버전으로 적용(축소: 활동을 verification 으로, 효력 reference 로 낮춤).
    applied = h.client.post(
        f"/api/knowledge/{contra['id']}/activate",
        json={"reason_summary": "반증을 확인해 규칙을 고친다", "into_knowledge_id": rule["knowledge_id"],
              "obligation": "reference", "activities": ["verification"]},
    )
    assert applied.status_code == 200, applied.text
    new = applied.json()["version"]
    assert (new["knowledge_key"], new["version"], new["state"], new["authority_kind"]) == (
        "K-001", 2, "active", "user_decision"
    )
    assert (new["obligation"], new["activities"], new["scope_kind"], new["repository_id"]) == (
        "reference", ["verification"], "repository", h.project_repository_id(project["id"])
    )
    assert new["artifact_id"] == contra["current"]["artifact_id"]  # 원문은 후보의 것
    adoption = applied.json()["adoption"]
    assert adoption["into"] == "K-001" and adoption["from_candidate"] == contra["current"]["id"]
    codes = {f["code"]: f["blocking"] for f in adoption["findings"]}
    assert codes == {"independent_review_not_run": False}
    view = _knowledge(h, project["id"])
    assert [(v["version"], v["state"]) for v in _item(view, "K-001")["versions"]] == [(1, "superseded"), (2, "active")]
    closed = _item(view, "K-002")["current"]
    assert closed["state"] == "superseded" and closed["superseded_by"] == new["id"]
    assert _item(view, "K-001")["versions"][0]["superseded_by"] == new["id"]

    # 다음 실행: K-001 v2 는 검증 실행에만(활동 축소) 참고로, K-002 는 들어가지 않는다. K-003 은 원문이
    # 없어도 후보(보조)라 실행을 막지 않는다.
    executor.verification_response = FAKE_VERIFICATION_RESPONSE
    other = _run_to_completion(h, project, "오류 줄 필터를 구현해줘 (둘째)")
    verification = next(r for r in _runs(h, other) if r["purpose"] == "verification_run")
    decisions = {i["knowledge_key"]: (i["decision"], i["version"]) for i in _manifest(h, verification["run_id"])["items"]}
    assert decisions["K-001"] == ("provided", 2) and "K-002" not in decisions
    impl = next(r for r in _runs(h, other) if r["purpose"] == "feature_implementation")
    assert {i["knowledge_key"]: i["decision"] for i in _manifest(h, impl["run_id"])["items"]} == {
        "K-001": "not_applicable_activity", "K-003": "provided"
    }
    assert h.client.get(f"/api/cases/{other}").json()["status"] == "closed"

    # 경고만 있는 활성화 — 관측보다 넓은 범위·필수 승격이 기록되고 활성이 된다.
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block([
        _candidate(summary="프로젝트 전체 관찰", content="WIDE-MARK 모든 저장소에서 표본 시험이 돈다", repository=None),
    ])
    third = _run_to_completion(h, project, "오류 줄 필터를 구현해줘 (셋째)")
    [row] = _registrations(h, third, "extraction")
    activated = h.client.post(
        f"/api/knowledge/{row['knowledge_id']}/activate",
        json={"reason_summary": "확인했다", "obligation": "required"},
    )
    assert activated.status_code == 200, activated.text
    warnings = {f["code"] for f in activated.json()["adoption"]["findings"]}
    assert warnings == {"scope_wider_than_observed", "obligation_raised", "independent_review_not_run"}
    assert activated.json()["version"]["obligation"] == "required"
    assert activated.json()["version"]["observed"]["repository_name"] == "primary"


# ================================================== AC-8 논의 응답의 제안


def test_a_proposal_in_a_discussion_reply_is_only_a_candidate_without_an_authority_message(processing_harness):
    """AC-8 — `proposal: true` 항목은 후보(ai_proposal, 출처 메시지 없음)이고 권위 메시지 본문은 서버에
    남지 않는다. 같은 응답의 사용자 말 항목은 P4-06 그대로 활성이며 그때는 권위 메시지가 남는다."""
    h = processing_harness
    project, _path = h.create_git_project("kx-prop")
    talk = h.create_conversation(project["id"], "이야기")["case_id"]
    proposal = dict(_candidate(summary="AI 관찰", content="PROP-MARK 시험은 루트에서 돈다", proposal=True),
                    repository=None)
    h.agent.cli_executor.discussion_response = (
        "이 업무에서 배운 것을 정리했습니다." + _block([proposal])
        + '\n\n```hads-interpretation\n{"kind": "discussion"}\n```'
    )
    h.send_message(talk, "이 업무에서 배운 것을 정리해줘 USER-SAID-77", "c-1")
    h.agent.poll_once()
    [row] = _registrations(h, talk)
    assert (row["origin"], row["intake_state"], row["knowledge_key"], row["state"]) == (
        "proposal", "registered", "K-001", "candidate"
    )
    assert row["basis"] == "추출 근거: python -m pytest tests/test_reader.py 종료 코드 0"
    view = _knowledge(h, project["id"])
    current = _item(view, "K-001")["current"]
    assert (current["authority_kind"], current["source_message_id"], current["storage"]) == (
        "ai_proposal", None, "server"
    )
    assert current["source_storage"] is None
    assert _body_purposes(h) == ["knowledge"]  # 권위 메시지 본문 없음
    assert marker_tables(Path(h.controller_config.db_path), "USER-SAID-77") == set()

    # 사용자 말 + 제안이 한 응답에 — 말은 활성(권위 메시지 남음), 제안은 후보.
    statement = {
        "kind": "constraint", "obligation": "required", "summary": "사용자 규칙",
        "content": "STATE-MARK 앞으로 로그에 비밀값을 남기지 않는다", "repository": None, "paths": [],
        "activities": [], "supersedes": None,
    }
    h.agent.cli_executor.discussion_response = (
        "등록합니다." + _block([statement, dict(proposal, content="PROP2-MARK 다른 관찰")])
        + '\n\n```hads-interpretation\n{"kind": "discussion"}\n```'
    )
    h.send_message(talk, "이 프로젝트에서는 앞으로 로그에 비밀값을 남기지 마 USER-SAID-88", "c-2")
    h.agent.poll_once()
    rows = _registrations(h, talk)[1:]
    assert [(r["origin"], r["knowledge_key"], r["state"]) for r in rows] == [
        ("statement", "K-002", "active"), ("proposal", "K-003", "candidate")
    ]
    assert _body_purposes(h) == ["authority_message", "knowledge", "knowledge", "knowledge"]
    assert marker_tables(Path(h.controller_config.db_path), "USER-SAID-88") == {"knowledge_body"}


# ================================================== AC-9 거부


def test_reports_from_other_purposes_incomplete_runs_and_too_many_or_unknown_keys_are_refused(processing_harness):
    """AC-9 — 의도 초안의 보고는 409. 완료되지 않은 검증 실행의 후보는 `run_not_completed`. 4건째부터
    `too_many_items`. 모르는 `relates_to` 는 `unknown_related_key`. 거부도 사유와 함께 남는다."""
    h = processing_harness
    project, _path = h.create_git_project("kx-refuse")
    case_id = _start_in(h, project)
    _drive(h, case_id)
    intent = next(r for r in _runs(h, case_id) if r["purpose"] == "intent_authoring")
    refused = h.client.post(
        f"/api/runner/runs/{intent['run_id']}/result",
        json={"runner_id": RUNNER_ID, "generation": intent["assignment_generation"], "outcome": "completed",
              "knowledge_report": [_candidate()], "residual_activity": "unknown"},
    )
    assert refused.status_code == 409 and "work run" in refused.text

    executor = h.agent.cli_executor
    executor.verification_response = FAKE_VERIFICATION_RESPONSE + _block([
        _candidate(relates_to="K-099", relation="supports", summary="모르는 대상"),
        _candidate(summary="1", content="ONE"), _candidate(summary="2", content="TWO"),
        _candidate(summary="3", content="THREE"),
    ])
    _agree(h, case_id)
    _drive(h, case_id)
    rows = _registrations(h, case_id, "extraction")
    assert [(r["intake_state"], r["refusal"], r["knowledge_key"]) for r in rows] == [
        ("refused", "unknown_related_key", None),
        ("registered", None, "K-001"),
        ("registered", None, "K-002"),
        ("refused", "too_many_items", None),
    ]
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed"

    # 완료되지 않은 실행(명령 없음 → 실패)의 후보는 등록하지 않는다.
    other = _start_in(h, project, "오류 줄 필터를 구현해줘 (둘째)")
    _drive(h, other)
    executor.verification_response = (
        '{"commands": [], "result_summary": "돌리지 못했다", "criteria": [], "detail": ""}'
        + _block([_candidate(summary="실패한 실행의 관찰", content="FAILED-MARK")])
    )
    _agree(h, other)
    _drive(h, other)
    failed = [r for r in _runs(h, other) if r["purpose"] == "verification_run"]
    assert failed and all(r["outcome"] == "failed" for r in failed)
    rows = _registrations(h, other, "extraction")
    assert rows and {r["refusal"] for r in rows} == {"run_not_completed"}
    assert [i["knowledge_key"] for i in _knowledge(h, project["id"])["items"]] == ["K-001", "K-002"]


# ================================================== AC-10 이행 v23 → v24


def test_a_v23_database_gets_the_evidence_table_and_new_columns_empty(tmp_path):
    """AC-10 — v23 → v24. 근거 표가 생기고 비어 있으며, 옛 버전의 새 컬럼은 NULL, `knowledge_intake` 행이
    보존되고 새 CHECK(`evidence`)가 있다. 멱등이다.

    v23 은 현재 `schema.sql` 의 **v24 절 앞까지**다(v24 는 끝에 붙였고 앞 절을 바꾸지 않았다).
    """
    schema = (Path(db.__file__).parent / "schema.sql").read_text(encoding="utf-8")
    marker = "-- 스키마 v24 (P4-07)"
    assert marker in schema
    v23 = schema[: schema.index(marker)].rsplit("-- ====", 1)[0]
    assert "knowledge_evidence" not in v23 and "knowledge_body" in v23
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    conn.executescript(v23)
    now = "2026-09-20T00:00:00+00:00"
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (23, ?)", (now,))
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("INSERT INTO owner VALUES ('own-1', 'local-owner', ?)", (now,))
    conn.execute(
        "INSERT INTO project (id, owner_id, name, repo_path, default_tool_id, created_at)"
        " VALUES ('prj-1','own-1','old','C:/tmp/old','codex',?)", (now,)
    )
    conn.execute(
        'INSERT INTO "case" (id, project_id, title, kind, status, created_at, updated_at)'
        " VALUES ('case-1', 'prj-1', 'old', 'feature', 'received', ?, ?)", (now, now),
    )
    conn.execute(
        "INSERT INTO run (run_id, case_id, task_id, role, tool_id, mode, permission,"
        " instruction_artifact_id, instruction_artifact_rev, status, assignment_generation, created_at)"
        " VALUES ('old-run','case-1','t','author','codex','m','read_only','a',1,'finished',1,?)", (now,),
    )
    conn.execute(
        "INSERT INTO artifact_ref (artifact_id, revision, case_id, kind, content_hash, byte_size,"
        " owner_runner_id, availability, summary, created_at)"
        " VALUES ('k-art', 1, 'case-1', 'knowledge', 'sha256:x', 3, 'runner-1', 'available', 's', ?)", (now,),
    )
    conn.execute(
        "INSERT INTO knowledge_item (id, project_id, knowledge_key, created_by, created_at)"
        " VALUES ('know-1', 'prj-1', 'K-001', 'owner', ?)", (now,),
    )
    conn.execute(
        "INSERT INTO knowledge_version (id, knowledge_id, version, artifact_id, artifact_rev, kind,"
        " obligation, state, summary, scope_kind, paths_json, activities_json, authority_kind,"
        " source_case_id, created_by, created_at)"
        " VALUES ('knowv-1', 'know-1', 1, 'k-art', 1, 'constraint', 'required', 'active', 's', 'project',"
        " '[]', '[]', 'user_registration', 'case-1', 'owner', ?)", (now,),
    )
    conn.execute(
        "INSERT INTO knowledge_intake (run_id, report_index, case_id, state, knowledge_version_id,"
        " refusal, summary, created_at) VALUES ('old-run', 0, 'case-1', 'registered', 'knowv-1', NULL, 's', ?)",
        (now,),
    )
    conn.execute(
        "INSERT INTO knowledge_intake (run_id, report_index, case_id, state, knowledge_version_id,"
        " refusal, summary, created_at) VALUES ('old-run', 1, 'case-1', 'refused', NULL, 'format_error', 's', ?)",
        (now,),
    )
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 24
    assert db.SCHEMA_VERSION >= 24
    assert conn.execute("SELECT COUNT(*) FROM knowledge_evidence").fetchone()[0] == 0
    columns = {r["name"] for r in conn.execute("PRAGMA table_info(knowledge_version)")}
    assert {"relates_to_knowledge_id", "relation", "observed_json", "adoption_json"} <= columns
    old = Repository(conn).get_knowledge_version("knowv-1")
    assert (old["relation"], old["relates_to_key"], old["observed"], old["adoption"]) == (None, None, None, None)
    intakes = conn.execute("SELECT run_id, report_index, state, evidence_id FROM knowledge_intake ORDER BY report_index").fetchall()
    assert [tuple(r) for r in intakes] == [("old-run", 0, "registered", None), ("old-run", 1, "refused", None)]
    sql = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'knowledge_intake'").fetchone()["sql"]
    assert "'evidence'" in sql and "evidence_id" in sql
    import sqlite3

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO knowledge_intake (run_id, report_index, case_id, state, created_at)"
            " VALUES ('old-run', 2, 'case-1', 'evidence', ?)", (now,),
        )
    db.migrate(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,)
    ).fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM knowledge_intake").fetchone()[0] == 2
