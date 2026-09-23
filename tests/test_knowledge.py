"""P4-06 — 프로젝트 지식 관리·적용(plans/P4-PLAN-06.md).

지식은 원본 참조(Runner 의 원문 = 짧은 적용 내용·조건·예외)·종류·효력(필수/참고)·상태·범위(Project /
저장소·경로)·활동·권위를 가진다. 실행의 활동과 범위에 맞는 현재 버전이 고정 문맥에 들어가고, 실행마다
Manifest 가 무엇을 주고 무엇을 왜 주지 않았는지를 남긴다.

이 파일이 지키는 것:

    필수는 원문으로 준다              링크만으로 제공 완료가 아니다. 못 읽으면 그 실행을 시작하지 않는다
    AI 제안은 규칙이 되지 않는다      후보로만 들어오고 필수로 주입되지 않는다(DB CHECK 까지)
    범위를 모르는 것은 비적용이 아니다 `scope_undetermined` 로 남긴다
    다른 저장소를 섞지 않는다          같은 경로 이름이라도 다른 저장소의 항목은 주지 않는다
    충돌은 사람이 푼다                적용되는 필수 사이의 열린 충돌은 그 작업만 보류한다
    주입은 준수가 아니다              기준 판정·완료 조건이 지식 제공으로 바뀌지 않는다
    원문은 PC 에 있다                 서버 DB·로그에 지식 원문이 없다

시험 이름 옆의 AC 번호는 P4-PLAN-06 4절이다.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from controller import db
from controller.repository import Repository
from domain import knowledge as knowmod
from domain.models import RunPurpose
from tests.conftest import FAKE_COMBINED_VERIFIED, FAKE_PLAN_VERIFIED, RUNNER_ID, _git
from tests.test_work_progressor import WORK_BLOCK, _agree, _drive, _runs, _wait_codes

MARK = "KNOW-7f3a-MARKER"

# ---------------------------------------------------------------- 도우미


def _register(
    h, case_id: str, content: str, summary: str = "규칙", *, kind: str = "constraint",
    obligation: str = "required", persist: bool = True, **extra: Any,
) -> dict[str, Any]:
    body = {
        "content": content, "summary": summary, "kind": kind, "obligation": obligation,
        "target_runner_id": RUNNER_ID, **extra,
    }
    response = h.client.post(f"/api/cases/{case_id}/knowledge", json=body)
    assert response.status_code == 201, response.text
    if persist:
        h.agent.persist_pending_intakes()
    return response.json()["version"]


def _repo(h) -> Repository:
    return Repository(h.client.app.state.conn, auto_process_requests=True)


def _start_in(h, project: dict[str, Any], text: str = "오류 줄 필터를 구현해줘") -> str:
    """이 Project 에서 대화 → 업무 요청 → 업무화(첫 걸음까지)."""
    case_id = h.create_conversation(project["id"], "필터 기능")["case_id"]
    executor = h.agent.cli_executor
    executor.discussion_response = f"알겠습니다.\n\n{WORK_BLOCK.format(profile='feature')}"
    executor.combined_response = FAKE_COMBINED_VERIFIED
    executor.plan_response = FAKE_PLAN_VERIFIED
    executor.write_files = {"reader.py": "def read(path):\n    return [l for l in open(path) if l.startswith('ERROR')]\n"}
    executor.residual_activity = "none"
    executor.residual_basis = "in_process"
    h.send_message(case_id, text, f"c-{case_id[-6:]}")
    h.agent.poll_once()
    return case_id


def _prompt(h, run_id: str) -> str:
    return next(c["prompt"] for c in h.agent.cli_executor.calls if c["run_id"] == run_id)


def _manifest(h, run_id: str) -> dict[str, Any]:
    response = h.client.get(f"/api/runs/{run_id}/knowledge")
    assert response.status_code == 200, response.text
    return response.json()


def _decisions(plan) -> dict[str, str]:
    return {d["knowledge_key"]: d["decision"] for d in plan.knowledge}


def _instruction(h, case_id: str) -> tuple[str, int]:
    """계획 계산에 쓸 지시 원문(저장된 사용자 메시지)."""
    message = h.conversation(case_id)["messages"][0]
    return message["artifact_id"], message["artifact_rev"]


def _git_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    (path / "README.md").write_text("x\n", encoding="utf-8")
    _git(path, "add", "-A")
    _git(path, "commit", "-m", "base")
    return path


# ================================================== 순수 규칙 (domain.knowledge)


def _v(key: str, **kw: Any) -> dict[str, Any]:
    base = {
        "id": f"v-{key}", "knowledge_id": f"k-{key}", "knowledge_key": key, "state": "active",
        "obligation": "required", "scope_kind": "project", "repository_id": None, "paths": [],
        "activities": [],
    }
    base.update(kw)
    return base


def test_selection_follows_activity_and_scope_and_never_reads_unknown_as_not_applicable():
    """AC-4·8 — 활동·범위로 고른다. 저장소를 모르면 저장소 항목은 `scope_undetermined` 다."""
    versions = [
        _v("K-001"),
        _v("K-002", obligation="reference", activities=["verification"]),
        _v("K-003", scope_kind="repository", repository_id="r-a", paths=["src/api"]),
        _v("K-004", scope_kind="repository", repository_id="r-b", paths=["src/api"]),
        _v("K-005", state="candidate"),
        _v("K-006", state="superseded"),
        _v("K-007", state="invalid"),
        _v("K-008", activities=["discussion"]),
    ]
    impl = knowmod.select(versions, "implementation", ["r-a"])
    got = {d["knowledge_key"]: (d["decision"], d["role"], d.get("scope_resolution")) for d in impl.decisions()}
    assert got["K-001"] == ("provided", "knowledge_required", "project")
    assert got["K-002"][0] == "not_applicable_activity"
    assert got["K-003"] == ("provided", "knowledge_required", "paths_unresolved")
    assert got["K-004"] == ("not_applicable_repository", "knowledge_required", "other_repository")
    assert got["K-005"] == ("provided", "knowledge_candidate", "project")
    assert "K-006" not in got and "K-007" not in got  # 대체·무효는 주입 대상이 아니다
    assert got["K-008"][0] == "not_applicable_activity"  # 빈 활동 = 논의를 뺀 모든 작업
    assert [d["knowledge_key"] for d in impl.applied] == ["K-001", "K-003", "K-005"]  # 필수 → 후보
    unknown = knowmod.select(versions, "design", None)
    decisions = {d["knowledge_key"]: d["decision"] for d in unknown.decisions()}
    assert decisions["K-003"] == decisions["K-004"] == "scope_undetermined"
    assert decisions["K-001"] == "provided"
    talk = knowmod.select(versions, "discussion", None)
    assert [d["knowledge_key"] for d in talk.applied] == ["K-008"]
    # 모르는 목적은 모든 항목을 받는다.
    assert knowmod.activity_for("something_new") == knowmod.UNKNOWN_ACTIVITY
    assert knowmod.activity_applies(["verification"], knowmod.UNKNOWN_ACTIVITY)


def test_only_conflicts_between_applied_required_items_block():
    """AC-7 — 두 항목이 모두 적용되고 하나 이상이 필수일 때만 막는다. 무관한 작업은 막지 않는다."""
    applied = knowmod.select(
        [_v("K-001"), _v("K-002"), _v("K-003", obligation="reference"),
         _v("K-004", obligation="reference")],
        "plan", None,
    ).applied
    conflicts = [
        {"id": "c1", "state": "open", "knowledge_a": "k-K-001", "knowledge_b": "k-K-002"},
        {"id": "c2", "state": "open", "knowledge_a": "k-K-003", "knowledge_b": "k-K-004"},
        {"id": "c3", "state": "open", "knowledge_a": "k-K-001", "knowledge_b": "k-K-099"},
        {"id": "c4", "state": "resolved", "knowledge_a": "k-K-001", "knowledge_b": "k-K-003"},
    ]
    assert [c["id"] for c in knowmod.blocking_conflicts(conflicts, applied)] == ["c1"]


def test_an_ai_proposal_is_only_a_candidate():
    """AC-2 — AI 제안은 후보로만. 활성은 사람의 권위다."""
    knowmod.check_authority("ai_proposal", "candidate", "required")
    for state in ("active", "superseded", "invalid"):
        with pytest.raises(ValueError):
            knowmod.check_authority("ai_proposal", state, "required")
    knowmod.check_authority("user_statement", "active", "required")
    with pytest.raises(ValueError):
        knowmod.check_authority("user_registration", "superseded", "reference")
    with pytest.raises(ValueError):
        knowmod.check_activities(["deploy"])
    with pytest.raises(ValueError):
        knowmod.check_paths(["../outside"])
    with pytest.raises(ValueError):
        knowmod.check_paths(["C:/abs"])


def test_the_registration_block_is_split_from_the_reply_and_bad_blocks_are_reported():
    """AC-10·11 — 대화에는 글만 붙는다. 틀린 블록은 조용히 버리지 않고 형식 오류 항목이 된다."""
    reply = (
        "앞으로 그렇게 하겠습니다.\n\n```hads-knowledge\n"
        '{"items": [{"kind": "constraint", "obligation": "required", "summary": "s", "content": "c"},'
        ' {"kind": "constraint", "obligation": "required", "summary": "s"}]}\n```\n'
        "```hads-knowledge\nnot json\n```"
    )
    text, items = knowmod.split_knowledge(reply)
    assert text == "앞으로 그렇게 하겠습니다."
    assert items[0]["content"] == "c"
    assert items[1] == {"format_error": "content missing"}
    assert items[2] == {"format_error": "block is not JSON"}
    assert knowmod.parse_report_item(items[1]) == (None, "format_error")
    assert knowmod.split_knowledge("그냥 답") == ("그냥 답", [])


# ================================================== AC-1·5·9·14 수동 등록 → 주입


def test_registered_rules_reach_every_work_run_as_originals_and_the_manifest_says_so(processing_harness):
    """AC-1·5·9·14·15 — 사람이 등록한 필수 규칙은 재승인 없이 활성이고, Fast Lane(결합 기록)·구현·
    검증 실행의 지시문에 **원문으로** 들어간다(영수증 `read`). 참고는 보조다. 논의 응답에는 가지
    않는다. 기준 판정·완료는 지식 제공으로 바뀌지 않는다. 서버에는 원문이 없다.
    """
    h = processing_harness
    project, _path = h.create_git_project("kn-fast")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    required = _register(
        h, rules, f"{MARK} 오류 줄은 원래 순서를 유지한다. 예외: 빈 줄은 버린다.", "오류 줄 순서 유지"
    )
    assert (required["knowledge_key"], required["version"], required["state"]) == ("K-001", 1, "active")
    assert (required["authority_kind"], required["obligation"]) == ("user_registration", "required")
    reference = _register(
        h, rules, "표본 로그는 samples/ 에 있다", "표본 위치", kind="operation", obligation="reference"
    )
    assert reference["knowledge_key"] == "K-002"
    view = h.client.get(f"/api/projects/{project['id']}/knowledge").json()
    assert [i["current"]["availability"] for i in view["items"]] == ["available", "available"]

    case_id = _start_in(h, project)
    _drive(h, case_id)
    _agree(h, case_id)
    _drive(h, case_id)
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "closed"
    assert case["result"]["closure"]["closure_kind"] == "completed"
    # 주입은 준수 판정을 만들지 않는다 — 기준은 검증 실행의 보고로 적혔다(P4-05 그대로).
    assert all(c["recorded_by"] == "policy:work_progressor" for c in h.criteria(case_id))

    runs = _runs(h, case_id)
    work = [r for r in runs if r["purpose"] in (
        "intent_authoring", "plan_authoring", "feature_implementation", "verification_run"
    )]
    assert {r["purpose"] for r in work} == {
        "intent_authoring", "plan_authoring", "feature_implementation", "verification_run"
    }
    for run in work:
        refs = h.context_refs(run["run_id"])
        req = [r for r in refs if r["role"] == "knowledge_required"]
        ref = [r for r in refs if r["role"] == "knowledge_reference"]
        assert len(req) == 1 and len(ref) == 1, (run["purpose"], refs)
        assert (req[0]["tier"], req[0]["receipt_status"]) == ("core", "read")
        assert req[0]["knowledge"]["key"] == "K-001" and req[0]["knowledge"]["version"] == 1
        assert ref[0]["tier"] == "supporting"
        # 지식 참조는 기존 참조 **뒤에** 온다.
        assert refs[-2]["role"] == "knowledge_required" and refs[-1]["role"] == "knowledge_reference"
        prompt = _prompt(h, run["run_id"])
        assert MARK in prompt and "K-001 v1" in prompt and "제공받았다는 사실은 지켰다는 증거가 아니다" in prompt
        manifest = _manifest(h, run["run_id"])
        assert manifest["recorded"] is True
        assert {i["knowledge_key"]: i["decision"] for i in manifest["items"]} == {
            "K-001": "provided", "K-002": "provided"
        }
    reply = next(r for r in runs if r["purpose"] == "discussion_reply")
    assert {i["knowledge_key"]: i["decision"] for i in _manifest(h, reply["run_id"])["items"]} == {
        "K-001": "not_applicable_activity", "K-002": "not_applicable_activity"
    }
    assert not any(r["role"].startswith("knowledge_") for r in h.context_refs(reply["run_id"]))

    # AC-15 — 서버 DB·로그에 원문이 없다(원문은 Runner 저장소에만 있다).
    root = h.client.app.state.config.data_root
    for path in root.iterdir():
        if path.is_file():
            assert MARK.encode("utf-8") not in path.read_bytes(), path.name
    assert any(MARK.encode("utf-8") in p.read_bytes() for p in h.agent.store.root.rglob("*.bin"))


# ================================================== AC-4·8 저장소·경로 범위


def test_repository_scope_does_not_mix_repositories_and_follows_scope_expansion(harness):
    """AC-4·8 — 같은 경로 이름이라도 다른 저장소의 항목은 주지 않는다. Case 가 저장소를 더하면 다음
    실행이 그 저장소의 항목을 받는다. 저장소를 모르면 저장소 항목은 범위 미확정이다.
    """
    h = harness
    project, _path = h.create_git_project("kn-scope")
    repo_a = h.project_repository_id(project["id"])
    beta = _git_repo(h.tmp_path / "repo-kn-beta")
    repo_b = h.register_repository(project["id"], "beta", str(beta))["id"]
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    _register(h, rules, "api 는 camelCase 로 응답한다", "A api 규칙", repository_id=repo_a, paths=["src/api"])
    _register(h, rules, "api 는 snake_case 로 응답한다", "B api 규칙", repository_id=repo_b, paths=["src/api"])
    _register(h, rules, "모든 저장소에서 로그에 비밀값을 남기지 않는다", "공통 규칙")
    case_id = h.create_case(project["id"])["id"]
    h.send_message(rules, "지시로 쓸 말", "c-x")
    h.agent.persist_pending_intakes()
    instruction = _instruction(h, rules)
    repo = _repo(h)

    plan = repo.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, instruction)
    assert _decisions(plan) == {
        "K-001": "scope_undetermined", "K-002": "scope_undetermined", "K-003": "provided"
    }
    assert h.select_repository(case_id, repo_a).status_code in (200, 201)
    plan = repo.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, instruction)
    assert _decisions(plan) == {
        "K-001": "provided", "K-002": "not_applicable_repository", "K-003": "provided"
    }
    resolution = {d["knowledge_key"]: d["scope_resolution"] for d in plan.knowledge}
    assert resolution["K-001"] == "paths_unresolved"
    # 실행의 저장소가 정해져 있으면 그것만 본다.
    plan_b = repo.plan_context_package(
        case_id, RunPurpose.FEATURE_IMPLEMENTATION, None, instruction, repository_id=repo_b
    )
    assert _decisions(plan_b)["K-001"] == "not_applicable_repository"
    assert _decisions(plan_b)["K-002"] == "provided"
    # 범위 확대 — B 를 더하면 저장소를 정하지 않은 실행이 둘 다 받는다.
    assert h.select_repository(case_id, repo_b).status_code in (200, 201)
    plan = repo.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, instruction)
    assert _decisions(plan) == {"K-001": "provided", "K-002": "provided", "K-003": "provided"}


# ================================================== AC-6 원문 불가·한도


def test_an_unreadable_required_rule_stops_the_run_and_a_reference_does_not(processing_harness):
    """AC-6 — 필수 원문을 Runner 가 읽지 못하면 CLI 를 부르지 않는다(시작하지 않음). 참고 원문을 못
    읽으면 부분 문맥이며 응답은 나간다. 저장 전(`pending`)의 필수는 진입 전에 핵심 미확인이다.
    """
    h = processing_harness
    # 참고 — 막지 않는다.
    project = h.create_project("kn-ref")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    ref = _register(h, rules, "참고 사실", "참고", obligation="reference", activities=["discussion"])
    h.agent.store._path(ref["artifact_id"], ref["artifact_rev"]).unlink()
    talk = h.create_conversation(project["id"], "대화")["case_id"]
    h.send_message(talk, "질문이 있어", "c-1")
    h.agent.poll_once()
    [reply] = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"]
    assert reply["outcome"] == "completed"
    assert reply["context"]["state"] == "partial"

    # 필수 — 시작하지 않는다.
    project = h.create_project("kn-req")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    req = _register(h, rules, "필수 사실", "필수", activities=["discussion"])
    h.agent.store._path(req["artifact_id"], req["artifact_rev"]).unlink()
    talk = h.create_conversation(project["id"], "대화")["case_id"]
    h.send_message(talk, "질문이 있어", "c-1")
    h.agent.poll_once()
    [reply] = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"]
    assert (reply["outcome"], reply["not_started_reason"]) == ("failed", "required_context_unavailable")
    assert not any(c["run_id"] == reply["run_id"] for c in h.agent.cli_executor.calls)
    manifest = _manifest(h, reply["run_id"])
    assert [(i["knowledge_key"], i["decision"]) for i in manifest["items"]] == [("K-001", "provided")]
    receipt = [r for r in h.context_refs(reply["run_id"]) if r["role"] == "knowledge_required"]
    assert receipt[0]["receipt_status"] == "missing"

    # 저장 전 — 진입 검사의 핵심 미확인이다.
    pending = _register(h, rules, "아직 저장 전", "대기", activities=["discussion"], persist=False)
    plan = _repo(h).plan_context_package(
        talk, RunPurpose.DISCUSSION_REPLY, None, _instruction(h, talk)
    )
    unavailable = _repo(h)._unavailable_core(plan)
    assert any(
        u["artifact_id"] == pending["artifact_id"] and u["availability"] == "pending"
        for u in unavailable
    )


def test_required_rules_over_the_inline_limit_hold_the_run(harness):
    """AC-6 — 필수만으로 한도를 넘으면 보류다(자르지 않는다). 참고는 드러내어 생략된다."""
    h = harness
    project = h.create_project("kn-limit")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    _register(h, rules, "x" * 3000, "큰 참고", obligation="reference")
    h.send_message(rules, "지시", "c-1")
    h.agent.persist_pending_intakes()
    case_id = h.create_case(project["id"])["id"]
    small = Repository(h.client.app.state.conn, context_inline_limit=2000)
    plan = small.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, _instruction(h, rules))
    assert plan.over_limit is False
    assert [r["inclusion"] for r in plan.refs if r["role"] == "knowledge_reference"] == ["omitted_size_limit"]
    _register(h, rules, "y" * 3000, "큰 필수")
    plan = small.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, _instruction(h, rules))
    assert plan.over_limit is True


# ================================================== AC-7 충돌


def test_a_conflict_between_applied_required_rules_waits_for_a_person(processing_harness):
    """AC-7 — 적용되는 필수 사이의 열린 충돌은 진입 거부이고 진행기는 사람 대기다. 무관한 대화는
    막지 않는다. 해소하면 이어 간다.
    """
    h = processing_harness
    project, _path = h.create_git_project("kn-conflict")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    a = _register(h, rules, "오류 줄은 그대로 둔다", "원문 유지")
    b = _register(h, rules, "오류 줄은 정규화한다", "정규화")
    conflict = h.client.post(
        f"/api/projects/{project['id']}/knowledge-conflicts",
        json={"knowledge_a": a["knowledge_id"], "knowledge_b": b["knowledge_id"], "reason_summary": "서로 반대"},
    )
    assert conflict.status_code == 201, conflict.text
    case_id = _start_in(h, project)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["knowledge_conflict"]
    assert conv["progress"]["wait"][0]["refusals"] == ["knowledge_conflict_unresolved"]
    assert "K-001" in conv["progress"]["wait"][0]["detail"]
    assert [r["purpose"] for r in _runs(h, case_id)] == ["discussion_reply"]  # 의도 초안을 만들지 않았다
    assert conv["send"]["general"]["allowed"] is True

    resolved = h.client.post(
        f"/api/knowledge-conflicts/{conflict.json()['id']}/resolve",
        json={"reason_summary": "빈 줄만 정규화한다는 뜻으로 정리"},
    )
    assert resolved.status_code == 200, resolved.text
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    assert conv["requests"][-1]["origin_ref"].startswith("knowledge_conflict:")


# ================================================== AC-10·11·12 자동 등록


def _knowledge_reply(items: list[dict[str, Any]], interpretation: bool = True) -> str:
    block = "```hads-knowledge\n" + json.dumps({"items": items}, ensure_ascii=False) + "\n```"
    tail = '\n\n```hads-interpretation\n{"kind": "discussion"}\n```' if interpretation else ""
    return f"앞으로 그렇게 하겠습니다. 프로젝트 규칙으로 등록합니다.\n\n{block}{tail}"


RULE_ITEM = {
    "kind": "constraint", "obligation": "required", "summary": "오류 로그에 시각을 붙이지 않는다",
    "content": f"{MARK} 오류 로그 줄에 시각을 덧붙이지 않는다.", "repository": None, "paths": [],
    "activities": [], "supersedes": None,
}


def test_a_rule_said_in_conversation_is_registered_and_injected_with_the_users_words(processing_harness):
    """AC-10·12·13 — 사용자의 프로젝트 규칙 → 응답 완료 뒤 활성 등록(사용자 발언 권위·출처 메시지).
    대화에는 글만 붙는다. 다른 대화의 업무 실행은 옮긴 글과 **원래 사용자 메시지**를 함께 받는다. 같은
    보고를 다시 처리해도 두 번 등록하지 않는다. 대체 지정은 새 버전이다.
    """
    h = processing_harness
    project, _path = h.create_git_project("kn-auto")
    talk = h.create_conversation(project["id"], "규칙 이야기")["case_id"]
    h.agent.cli_executor.discussion_response = _knowledge_reply([RULE_ITEM])
    said = "이 프로젝트에서는 앞으로 오류 로그에 시각을 붙이지 마. USER-WORDS-9c1"
    h.send_message(talk, said, "c-1")
    h.agent.poll_once()
    conv = h.conversation(talk)
    assistant = [m for m in conv["messages"] if m["author"] == "assistant"]
    assert len(assistant) == 1
    [registration] = conv["knowledge_registrations"]
    assert (registration["intake_state"], registration["knowledge_key"], registration["version"]) == (
        "registered", "K-001", 1
    )
    assert (registration["obligation"], registration["state"]) == ("required", "active")
    view = h.client.get(f"/api/projects/{project['id']}/knowledge").json()
    current = view["items"][0]["current"]
    user_message = next(m for m in conv["messages"] if m["author"] == "user")
    assert current["authority_kind"] == "user_statement"
    assert current["source_message_id"] == user_message["id"]
    assert current["created_by"].startswith("ai:")
    reply_run = next(r for r in _runs(h, talk) if r["purpose"] == "discussion_reply")
    # 대화의 AI 말에는 블록이 없다(본문 열람 중계로 확인).
    _state, body = h.read_original(reply_run["output_artifact_id"], reply_run["output_artifact_rev"])
    assert "hads-knowledge" not in body and "프로젝트 규칙으로 등록합니다" in body
    # 멱등 — 같은 보고를 다시 처리해도 두 번 등록하지 않는다.
    assert _repo(h).apply_knowledge_report(reply_run["run_id"]) == []
    assert len(h.client.get(f"/api/projects/{project['id']}/knowledge").json()["items"][0]["versions"]) == 1

    # 다른 대화의 업무: 의도 초안부터 옮긴 글 + 원래 사용자 메시지를 받는다.
    work = _start_in(h, project)
    _drive(h, work)
    intent_run = next(r for r in _runs(h, work) if r["purpose"] == "intent_authoring")
    refs = h.context_refs(intent_run["run_id"])
    roles = [r["role"] for r in refs]
    assert roles[-2:] == ["knowledge_required", "knowledge_source"]
    assert refs[-1]["tier"] == "core" and refs[-1]["receipt_status"] == "read"
    prompt = _prompt(h, intent_run["run_id"])
    assert MARK in prompt and "USER-WORDS-9c1" in prompt and "권위 원문" in prompt
    manifest = _manifest(h, intent_run["run_id"])
    assert manifest["items"][0]["source_seq"] == len(refs)

    # 그 말이 이미 대화로 들어가는 실행(같은 대화의 의도 초안)에는 권위 원문을 다시 넣지 않는다.
    refs_here, decisions, _conflicts = _repo(h).compose_context(
        talk, RunPurpose.INTENT_AUTHORING, None, None
    )
    assert decisions[0]["source_index"] is None
    keys = [(r["artifact_id"], r["revision"]) for r in refs_here]
    assert len(keys) == len(set(keys))

    # 대체 지정 — 사용자가 규칙을 바꾸면 그 항목의 새 버전이다. 이전 버전은 대체로 남는다.
    changed = dict(RULE_ITEM, obligation="reference", supersedes="K-001",
                   summary="오류 로그 시각은 선택", content="오류 로그 줄의 시각은 선택 사항이다.")
    h.agent.cli_executor.discussion_response = _knowledge_reply([changed])
    h.send_message(talk, "앞으로는 시각을 붙여도 되고 안 붙여도 돼", "c-2")
    h.agent.poll_once()
    versions = h.client.get(f"/api/projects/{project['id']}/knowledge").json()["items"][0]["versions"]
    assert [(v["version"], v["state"], v["obligation"]) for v in versions] == [
        (1, "superseded", "required"), (2, "active", "reference")
    ]
    assert versions[0]["superseded_by"] == versions[1]["id"]
    # 이미 만든 실행의 입력 기록은 그대로다(v1).
    assert _manifest(h, intent_run["run_id"])["items"][0]["version"] == 1


def test_bad_registration_items_are_refused_with_a_reason(harness):
    """AC-11 — 없는 저장소·없는 대체 키·틀린 종류·형식 오류는 등록하지 않고 사유를 남긴다. 완료되지
    않은 응답의 블록은 등록하지 않는다.
    """
    h = harness
    project, _path = h.create_git_project("kn-refuse")
    talk = h.create_conversation(project["id"], "대화")["case_id"]
    items = [
        dict(RULE_ITEM, repository="nope"),
        dict(RULE_ITEM, supersedes="K-099"),
        dict(RULE_ITEM, kind="rule"),
        dict(RULE_ITEM, summary="정상"),
    ]
    reply = _knowledge_reply(items) + "\n```hads-knowledge\n{broken\n```"
    h.agent.cli_executor.discussion_response = reply
    h.send_message(talk, "앞으로 이렇게 해", "c-1")
    h.agent.persist_pending_intakes()
    request_id = h.conversation(talk)["requests"][0]["id"]
    h.discussion_reply(talk, request_id, "kr-1")
    applied = _repo(h).apply_knowledge_report("kr-1")
    assert [(a["state"], a["refusal"]) for a in applied] == [
        ("refused", "unknown_repository"),
        ("refused", "unknown_supersedes_key"),
        ("refused", "invalid_kind_or_obligation"),
        ("registered", None),
        ("refused", "format_error"),
    ]
    view = h.conversation(talk)["knowledge_registrations"]
    assert [r["intake_state"] for r in view] == ["refused", "refused", "refused", "registered", "refused"]

    # 완료되지 않은 응답.
    other = h.create_conversation(project["id"], "대화 2")["case_id"]
    h.agent.cli_executor.discussion_response = _knowledge_reply([RULE_ITEM])
    h.send_message(other, "앞으로 이렇게 해", "c-2")
    h.agent.persist_pending_intakes()
    request_id = h.conversation(other)["requests"][0]["id"]
    h.discussion_reply(other, request_id, "kr-2")
    h.client.app.state.conn.execute("UPDATE run SET outcome = 'failed' WHERE run_id = 'kr-2'")
    assert [a["refusal"] for a in _repo(h).apply_knowledge_report("kr-2")] == ["reply_not_completed"]


# ================================================== AC-2·3 후보·활성화·무효·개정


def test_candidates_activation_invalidation_and_revision_keep_history(harness):
    """AC-2·3 — AI 제안은 후보로만(필수 주입 없음, 활성은 API·DB 모두 거부). 활성화·개정은 새 버전이고
    이전 버전은 대체로 남는다. 무효는 사유와 함께 상태만 바꾸고, 대체·무효는 주입되지 않는다.
    """
    h = harness
    project = h.create_project("kn-life")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    refused = h.client.post(
        f"/api/cases/{rules}/knowledge",
        json={"content": "c", "summary": "s", "kind": "constraint", "obligation": "required",
              "target_runner_id": RUNNER_ID, "authority": "ai_proposal", "state": "active"},
    )
    assert refused.status_code == 409
    candidate = _register(h, rules, "AI 가 반복 관찰한 것", "관찰", authority="ai_proposal", state="candidate")
    assert candidate["state"] == "candidate"
    h.send_message(rules, "지시", "c-1")
    h.agent.persist_pending_intakes()
    case_id = h.create_case(project["id"])["id"]
    repo = _repo(h)
    instruction = _instruction(h, rules)
    plan = repo.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, instruction)
    [ref] = [r for r in plan.refs if r["role"].startswith("knowledge_")]
    assert (ref["role"], ref["tier"]) == ("knowledge_candidate", "supporting")
    # DB 도 막는다 — 활성 필수 AI 제안.
    with pytest.raises(sqlite3.IntegrityError):
        h.client.app.state.conn.execute(
            "UPDATE knowledge_version SET state = 'active' WHERE id = ?", (candidate["id"],)
        )

    kid = candidate["knowledge_id"]
    active = h.client.post(f"/api/knowledge/{kid}/activate", json={"reason_summary": "확인했다"})
    assert active.status_code == 200, active.text
    active = active.json()["version"]
    assert (active["version"], active["state"], active["authority_kind"]) == (2, "active", "user_decision")
    plan = repo.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, instruction)
    assert [r["role"] for r in plan.refs if r["role"].startswith("knowledge_")] == ["knowledge_required"]

    assert h.client.post(f"/api/knowledge/{kid}/invalidate", json={"reason_summary": ""}).status_code == 422
    invalid = h.client.post(f"/api/knowledge/{kid}/invalidate", json={"reason_summary": "반증됐다"})
    assert invalid.status_code == 200 and invalid.json()["version"]["state"] == "invalid"
    plan = repo.plan_context_package(case_id, RunPurpose.DESIGN_AUTHORING, None, instruction)
    assert plan.knowledge == [] and not any(r["role"].startswith("knowledge_") for r in plan.refs)

    revised = h.client.post(
        f"/api/knowledge/{kid}/versions",
        json={"reason_summary": "조건을 좁혀 다시", "content": "새 조건의 규칙", "case_id": rules,
              "target_runner_id": RUNNER_ID, "obligation": "reference"},
    )
    assert revised.status_code == 201, revised.text
    h.agent.persist_pending_intakes()
    versions = h.client.get(f"/api/projects/{project['id']}/knowledge").json()["items"][0]["versions"]
    assert [(v["version"], v["state"]) for v in versions] == [
        (1, "superseded"), (2, "invalid"), (3, "active")
    ]
    assert versions[1]["superseded_by"] == versions[2]["id"]  # 무효는 무효 그대로, 대체 관계만
    assert versions[2]["authority_kind"] == "user_registration"
    assert versions[1]["invalid_reason"] == "반증됐다"


# ================================================== AC-13 다른 Case 의 갱신


def test_an_update_elsewhere_keeps_the_old_input_and_shows_up_as_drift(processing_harness):
    """AC-13 — 실행이 입력을 고정한 뒤 지식이 개정되면 그 실행의 Manifest·참조는 그대로이고, 결과
    시점의 최신성에 새 버전이 드러나며, 다음 실행이 새 버전을 받는다.
    """
    h = processing_harness
    project = h.create_project("kn-drift")
    rules = h.create_conversation(project["id"], "규칙")["case_id"]
    first = _register(h, rules, "v1 내용", "대화 규칙", activities=["discussion"])
    talk = h.create_conversation(project["id"], "대화")["case_id"]
    h.send_message(talk, "첫 질문", "c-1")
    h.agent.persist_pending_intakes()  # 응답 실행이 만들어진다(아직 돌지 않았다)
    [pending] = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"]
    revised = h.client.post(
        f"/api/knowledge/{first['knowledge_id']}/versions",
        json={"reason_summary": "다른 대화에서 고쳤다", "content": "v2 내용", "case_id": rules,
              "target_runner_id": RUNNER_ID},
    )
    assert revised.status_code == 201
    h.agent.poll_once()
    run = h.client.get(f"/api/runs/{pending['run_id']}").json()
    assert run["status"] == "finished"
    assert _manifest(h, pending["run_id"])["items"][0]["version"] == 1
    drift = run["context_freshness"]
    assert drift["state"] == "drifted"
    assert any(a["role"] == "knowledge_required" for a in drift["added"])
    h.send_message(talk, "둘째 질문", "c-2")
    h.agent.poll_once()
    second = [r for r in _runs(h, talk) if r["purpose"] == "discussion_reply"][-1]
    assert _manifest(h, second["run_id"])["items"][0]["version"] == 2


# ================================================== AC-16 이행 v21 → v22


def test_a_v21_database_gets_no_manifest_it_never_had(tmp_path):
    """AC-16 — v21 → v22. 지식 표가 생기고 비어 있다. 옛 실행의 Manifest 는 "기록 전"이다. 멱등이다.

    v21 은 이 세션(S-025)에서 아직 커밋 전이라 git 에서 꺼낼 수 없다 — 현재 `schema.sql` 에서 **v22
    절 앞까지**가 v21 의 스키마다(v22 는 끝에 붙였고 앞 절을 바꾸지 않았다).
    """
    schema = (Path(db.__file__).parent / "schema.sql").read_text(encoding="utf-8")
    marker = "-- 스키마 v22 (P4-06)"
    assert marker in schema
    v21 = schema[: schema.index(marker)].rsplit("-- ====", 1)[0]
    assert "knowledge_item" not in v21 and "progress_limit_setting" in v21
    path = tmp_path / "controller.sqlite3"
    conn = db.connect(path)
    conn.executescript(v21)
    now = "2026-09-01T00:00:00+00:00"
    conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (21, ?)", (now,))
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
    conn.close()

    conn = db.connect(path)
    db.migrate(conn)
    assert conn.execute("SELECT MAX(version) FROM schema_version").fetchone()[0] >= 22
    assert db.SCHEMA_VERSION >= 22
    for table in ("knowledge_item", "knowledge_version", "knowledge_conflict", "knowledge_intake", "run_knowledge"):
        assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    assert "knowledge_report_json" in {r["name"] for r in conn.execute("PRAGMA table_info(run)")}
    view = Repository(conn).run_knowledge_view("old-run")
    assert view["recorded"] is False and view["items"] == []
    db.migrate(conn)
    assert conn.execute(
        "SELECT COUNT(*) FROM schema_version WHERE version = ?", (db.SCHEMA_VERSION,)
    ).fetchone()[0] == 1
