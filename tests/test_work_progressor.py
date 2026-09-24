"""P4-05 — 업무 단계 자동 진행(plans/P4-PLAN-05.md).

업무화 뒤 의도 초안 → QG-01 → 질문·동의 → 준비 → 작업 그래프 → 구현·검증 → 기준 판정 → 완료를
**제품이** 잇는다. 사람이 필요한 곳에서만 멈추고 그 동안만 전송이 열린다(D-70).

이 파일이 지키는 것:

    진행기는 진입 검사를 우회하지 않는다   거부되면 그 사유로 멈춘다
    진행기는 사람의 결정을 만들지 않는다   동의·확인·인수·예외는 사람 경로에서만 기록된다
    통과할 때까지 돌리지 않는다            재작성·재시도 상한(기본 2회·1회, P4-05b 부터 설정) 뒤 사람에게 넘긴다
    기준 판정은 구조 검사를 지난 보고다    연결되지 않은 기준·명령 없는 검증은 적지 않는다

시험 이름 옆의 AC 번호는 P4-PLAN-05 5절이다.
"""

from __future__ import annotations

import json
import threading
import time
from typing import Any

import pytest

from controller.repository import Repository
from controller.work_progressor import WorkProgressor
from domain import work_flow as workflow
from domain.models import AdmissionRefusal
from tests.conftest import (
    FAKE_COMBINED_VERIFIED,
    FAKE_DRAFT_RESPONSE,
    FAKE_PLAN_VERIFIED,
)

WORK_BLOCK = '```hads-interpretation\n{{"kind": "work_request", "profile": "{profile}"}}\n```'

#: 의도 단계 질문 하나가 있는 초안.
DRAFT_WITH_QUESTION = FAKE_DRAFT_RESPONSE.replace(
    '"questions": []',
    '"questions": [{"key": "q1", "text": "대소문자를 구분합니까?", "summary": "대소문자 구분",'
    ' "decide_at": "intent"}]',
)

#: 조사 Profile 의 분석 응답 — 기준별 결론을 낸다.
ANALYSIS_DETERMINED = """원인을 확인했습니다. 로그 형식의 문제는 수준 표시가 없기 때문입니다.

```json
{"criteria": [
  {"key": "C-01", "verdict": "met", "conclusion": "determined", "summary": "형식 비교로 확정"},
  {"key": "C-02", "verdict": "met", "conclusion": "determined", "summary": "경로 확인"}
]}
```
"""

ANALYSIS_INCONCLUSIVE = ANALYSIS_DETERMINED.replace('"conclusion": "determined"', '"conclusion": "inconclusive"')

VERIFICATION_ONE_FAILS = """확인했습니다.

```json
{
  "commands": [
    {"command": "python -m pytest tests/test_reader.py -k filter", "summary": "필터 시험", "exit_code": 0},
    {"command": "python -m pytest tests/test_reader.py -k path", "summary": "경로 시험", "exit_code": 1}
  ],
  "result_summary": "시험 2건 중 1건이 실패했다",
  "criteria": [
    {"key": "C-01", "verdict": "met", "summary": "출력 줄 수 비교 통과"},
    {"key": "C-02", "verdict": "not_met", "summary": "로컬 경로 시험 실패"}
  ],
  "detail": "C-02 가 실패했다"
}
```
"""


# ---------------------------------------------------------------- 도우미


def _repo(h) -> Repository:
    return Repository(h.client.app.state.conn, auto_process_requests=True)


def _start(h, profile: str = "feature", *, git: bool = True, text: str = "오류 줄 필터를 구현해줘"):
    """대화 → 업무 요청 → (응답·해석·업무화·첫 걸음). 반환: (project, case_id, request_id)."""
    if git:
        project, _repo_path = h.create_git_project(f"p-{profile}-{time.time_ns() % 100000}")
    else:
        project = h.create_project()
    view = h.create_conversation(project["id"], "필터 기능")
    case_id = view["case_id"]
    executor = h.agent.cli_executor
    executor.discussion_response = f"알겠습니다. 정리하겠습니다.\n\n{WORK_BLOCK.format(profile=profile)}"
    executor.combined_response = FAKE_COMBINED_VERIFIED
    executor.plan_response = FAKE_PLAN_VERIFIED
    executor.write_files = {"reader.py": "def read(path):\n    return [l for l in open(path) if l.startswith('ERROR')]\n"}
    executor.residual_activity = "none"
    executor.residual_basis = "in_process"
    h.send_message(case_id, text, "c-1")
    h.agent.poll_once()
    conv = h.conversation(case_id)
    request = conv["requests"][0]
    return project, case_id, request["id"]


def _drive(h, case_id: str, *, polls: int = 20) -> dict[str, Any]:
    """진행이 멈출 때까지(사람 대기·막힘·완료) Runner 를 돌린다."""
    for _ in range(polls):
        h.agent.poll_once()
        conv = h.conversation(case_id)
        progress = conv["progress"]
        pending = [r for r in h.client.get(f"/api/cases/{case_id}").json()["runs"] if r["status"] != "finished"]
        if progress and progress["state"] != "running" and not pending:
            return conv
        if progress is None:
            return conv
    return h.conversation(case_id)


def _runs(h, case_id: str) -> list[dict[str, Any]]:
    return list(reversed(h.client.get(f"/api/cases/{case_id}").json()["runs"]))  # 오래된 순


def _agree(h, case_id: str) -> dict[str, Any]:
    intent = h.latest_intent(case_id)
    h.read_intent_original(intent)
    response = h.agree(case_id, intent)
    assert response.status_code == 201, response.text
    return intent


def _wait_codes(conv: dict[str, Any]) -> list[str]:
    return [w["code"] for w in (conv["progress"] or {}).get("wait") or []]


# ================================================== 순수 규칙 (domain.work_flow)


def test_admission_refusals_are_sorted_into_human_transient_and_environment():
    """AC-12 — 사람 사유·일시 사유·환경 사유를 나눈다. 사람 사유가 하나라도 있으면 사람이다."""
    assert workflow.classify_refusals(["intent_not_agreed", "tool_not_available"])[0] == "human"
    assert workflow.classify_refusals(["case_write_in_progress"])[0] == "transient"
    assert workflow.classify_refusals(["budget_hard_limit_reached"])[0] == "environment"
    assert workflow.classify_refusals(["case_already_closed", "intent_not_agreed"])[0] == "done"
    assert workflow.wait_reason_for(["controlled_start_not_confirmed"]) == workflow.WaitReason.CONTROLLED_START
    assert workflow.block_reason_for(["required_context_unavailable"]) == workflow.BlockReason.CONTEXT_UNAVAILABLE
    # 모든 진입 거부 코드가 어느 한쪽에는 들어간다 — 새 코드를 더하면 여기서 드러난다.
    for code in AdmissionRefusal:
        kind, _ = workflow.classify_refusals([code.value])
        assert kind in ("human", "transient", "environment", "done"), code


def test_criteria_reports_are_filtered_by_structure_not_by_trust():
    """AC-9 — 연결된 기준·완료 실행·성공한 명령만 `met` 이 된다. 미충족은 그대로 적힌다."""
    criteria = [
        {"id": "c1", "criterion_key": "C-01", "obligation": "behavior", "verdict": "unverified"},
        {"id": "c2", "criterion_key": "C-02", "obligation": "behavior", "verdict": "unverified"},
        {"id": "c3", "criterion_key": "C-03", "obligation": "cause", "conclusion_rule": None,
         "verdict": "unverified"},
    ]
    run = {"run_id": "r", "purpose": "verification_run", "outcome": "completed"}
    report = [
        {"key": "C-01", "verdict": "met"},
        {"key": "C-02", "verdict": "not_met", "summary": "실패"},
        {"key": "C-09", "verdict": "met"},
    ]
    decisions = workflow.decide_criteria(
        report=report, run=run, commands=[{"exit_code": 0}], criteria=criteria,
        linked_ids={"c1"}, product_change_observed=True, contract_applies=True,
    )
    by_key = {d.key: d for d in decisions}
    assert (by_key["C-01"].record, by_key["C-01"].verdict, by_key["C-01"].satisfaction) == (
        True, "met", "changed_and_verified"
    )
    assert (by_key["C-02"].record, by_key["C-02"].reason) == (False, "unlinked")
    assert (by_key["C-09"].record, by_key["C-09"].reason) == (False, "unknown_criterion")
    # 성공한 명령이 없으면 met 을 적지 않는다.
    none_ok = workflow.decide_criteria(
        report=[{"key": "C-01", "verdict": "met"}], run=run, commands=[{"exit_code": 1}],
        criteria=criteria, linked_ids={"c1"}, product_change_observed=True, contract_applies=True,
    )
    assert (none_ok[0].record, none_ok[0].reason) == (False, "no_successful_command")
    # 조사 결론: 확정 필수 기준의 판단 불가는 not_met 이다.
    inconclusive = workflow.decide_criteria(
        report=[{"key": "C-03", "verdict": "met", "conclusion": "inconclusive"}],
        run={"run_id": "a", "purpose": "limited_analysis", "outcome": "completed"},
        commands=[], criteria=criteria, linked_ids=None, product_change_observed=False,
        contract_applies=True,
    )
    assert (inconclusive[0].verdict, inconclusive[0].satisfaction, inconclusive[0].conclusion) == (
        "not_met", "investigated", "inconclusive"
    )
    # 보고 형식: 모르는 판정은 버린다.
    assert workflow.parse_criteria_report([{"key": "C-01", "verdict": "maybe"}, "x"]) == []


# ================================================== AC-1·3·4·7·8·9·10 대표 흐름


def test_a_clear_feature_request_runs_to_auto_completion_with_only_the_agreement(processing_harness):
    """AC-1·3·4·7·8·9·10 — 업무화 뒤 사람이 하는 일은 **의도 동의 하나**다.

    의도 초안 → 가벼운 확인(간소 수준) → 동의 대기 → 동의 → 결합 기록(Fast Lane) → 작업공간 →
    구현 → 검증 → 기준 판정 → 자동 완료. 실행은 전부 요청에 붙고, 전송은 동의 대기에서만 열린다.
    """
    h = processing_harness
    _project, case_id, request_id = _start(h)
    conv = h.conversation(case_id)
    assert conv["stage"] == "work" and conv["progress"]["state"] == "running"
    assert conv["send"]["general"]["allowed"] is False  # 실행 사이에 잠금을 풀지 않는다

    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    assert conv["progress"]["state"] == "waiting_human"
    assert conv["send"]["general"]["allowed"] is True  # 사람을 기다리는 동안에는 열린다
    request = next(r for r in conv["requests"] if r["id"] == request_id)
    assert (request["state"], request["note_summary"]) == ("completed", "waiting: intent_agreement")
    gate = h.gate(case_id)
    assert gate["verdict"] == "pass"
    conformance = h.conformance(case_id)
    assert conformance["method"] == "light"  # 간소 수준 — 실행 없는 가벼운 확인
    runs = _runs(h, case_id)
    assert [r["purpose"] for r in runs] == ["discussion_reply", "intent_authoring"]
    assert all(r["request_id"] == request_id for r in runs)

    _agree(h, case_id)
    conv = h.conversation(case_id)
    # 동의 뒤 시스템이 **진행 요청**을 열어 이어 간다 — 여는 메시지가 없다.
    progress_request = conv["current_request"]
    assert progress_request is not None
    assert (progress_request["origin"], progress_request["opened_by_message_id"]) == (
        "human_decision", None
    )
    assert progress_request["origin_ref"].startswith("agreement:")
    assert conv["send"]["general"]["allowed"] is False

    conv = _drive(h, case_id)
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "closed", conv["progress"]
    assert case["result"]["closure"]["closure_kind"] == "completed"
    candidate = case["result"]["candidate"] or h.client.get(
        f"/api/cases/{case_id}/completion-candidates"
    ).json()[-1]
    assert candidate["acceptance"]["mode"] == "auto_policy"
    assert conv["progress"]["state"] == "done"
    purposes = [r["purpose"] for r in _runs(h, case_id)]
    assert purposes == [
        "discussion_reply", "intent_authoring", "plan_authoring",
        "feature_implementation", "verification_run",
    ]
    # 결합 기록 하나로 갔다(Fast Lane). 설계·계획 두 건이 아니다.
    prep = h.preparation(case_id)
    assert prep["combined"]["artifact"] is not None and prep["design"]["artifact"] is None
    assert prep["combined"]["state"] == "auto_conditions_met"
    # 기준은 검증 실행의 보고로 제품이 적었다 — 근거·방식·주체가 남는다.
    for crit in h.criteria(case_id):
        assert crit["verdict"] == "met"
        assert crit["recorded_by"] == workflow.CRITERIA_RECORDER
        assert crit["evidence_run_id"].startswith("wp-")
        assert crit["satisfaction"] == "changed_and_verified"
    # 실행은 전부 요청에 붙었고, 사람의 결정은 동의 하나뿐이다.
    assert all(r["request_id"] for r in _runs(h, case_id))
    human = [d for d in case["decisions"] if not d["actor"].startswith("policy:")]
    assert [d["kind"] for d in human] == ["intent_agreement"]
    # 진행 요청은 완료로 끝났고 모든 요청이 닫혀 전송이 열린다(종료 뒤 설명 전용).
    assert all(r["state"] == "completed" for r in conv["requests"])
    assert conv["send"]["general"]["note"] == "explanation_only"
    events = [e["action"] for e in conv["progress"]["events"]]
    assert "criteria_recorded" in events and "done" in events


# ================================================== AC-2 질문·카드 답변


def test_intent_questions_stop_the_flow_and_a_card_answer_resumes_it(processing_harness):
    """AC-2 — 열린 질문에서 멈춰 전송이 열리고, 카드 답변 뒤 답을 반영해 다시 쓴다."""
    h = processing_harness
    h.agent.cli_executor.draft_response = DRAFT_WITH_QUESTION
    _project, case_id, request_id = _start(h)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_questions"]
    assert conv["send"]["general"]["allowed"] is True
    assert conv["send"]["card_answer"]["allowed"] is True
    [question] = h.open_questions(case_id)
    intent = h.latest_intent(case_id)

    # 답하면 답을 반영한 재작성이 **진행 요청**에 붙는다. 답이 동의가 되지는 않는다.
    h.agent.cli_executor.draft_response = FAKE_DRAFT_RESPONSE
    h.send_message(case_id, "구분하지 않습니다", "a-1", kind="card_answer",
                   question_id=question["id"], intent_version_id=intent["id"])
    conv = h.conversation(case_id)
    assert conv["current_request"]["origin"] == "human_decision"
    assert conv["progress"]["step"] == "intent_rewrite_answers"
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    assert h.latest_intent(case_id)["revision"] == 2
    assert h.intent_state(case_id)["agreement_state"] == "never_agreed"
    # 재작성 실행의 고정 문맥에 답이 들어갔다.
    rewrite = next(r for r in _runs(h, case_id) if r["purpose"] == "intent_authoring" and r["run_id"].endswith("-1") and "rewrite" in r["run_id"])
    assert any(ref["role"] == "question_answer" for ref in h.context_refs(rewrite["run_id"]))


# ================================================== AC-3 QG-01 repair


def test_gate_findings_are_repaired_with_the_findings_in_the_assignment_up_to_the_limit(processing_harness):
    """AC-3 — 독립 검토의 지적을 배정에 실어 다시 쓰고, 2회 뒤에도 남으면 사람 대기다."""
    h = processing_harness
    h.agent.cli_executor.review_response = json.dumps(
        {"findings": [{"criterion": "request_missing_or_contradictory", "severity": "required",
                       "certainty": "confirmed", "target": "scope", "summary": "범위가 요청과 다르다"}]}
    )
    project, _repo_path = h.create_git_project("gate")
    view = h.create_conversation(project["id"], "필터")
    case_id = view["case_id"]
    # 이 Case 는 독립 검토를 요구한다(가벼운 확인으로는 못 지난다).
    assert h.client.put(
        f"/api/cases/{case_id}/conformance-policy",
        json={"required": True, "set_by": "owner", "reason": "시험"},
    ).status_code == 200
    h.agent.cli_executor.discussion_response = f"정리합니다.\n{WORK_BLOCK.format(profile='feature')}"
    h.send_message(case_id, "필터를 구현해줘", "c-1")
    h.agent.poll_once()
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["gate_repair_exhausted"]
    purposes = [r["purpose"] for r in _runs(h, case_id)]
    assert purposes.count("intent_gate_review") == 3 and purposes.count("intent_authoring") == 3
    assert conv["progress"]["attempts"]["intent_repair"] == 2
    repair = [r for r in _runs(h, case_id) if "intent-repair" in r["run_id"]][0]
    prompt = next(c["prompt"] for c in h.agent.cli_executor.calls if c["run_id"] == repair["run_id"])
    assert "요청 정합성 확인(QG-01)의 지적" in prompt and "범위가 요청과 다르다" in prompt
    assert h.gate(case_id)["verdict"] != "pass"
    assert conv["send"]["general"]["allowed"] is True
    # 검토 보고는 결과 보고 뒤에 온다 — 그 사이에 요청을 끝내지 않았고, 마지막 대기 코드가 요청에 남았다.
    assert [r["note_summary"] for r in conv["requests"]] == ["waiting: gate_repair_exhausted"]


# ================================================== AC-6 controlled


def test_controlled_stops_at_the_start_and_at_the_result_candidate(processing_harness):
    """AC-6 — controlled 는 시작 확인·결과 확인에서 멈추고, 확인 뒤 시스템이 종료를 확정한다."""
    h = processing_harness
    project, _repo_path = h.create_git_project("ctl")
    view = h.create_conversation(project["id"], "필터")
    case_id = view["case_id"]
    assert h.client.put(
        f"/api/cases/{case_id}/autonomy",
        json={"autonomy": "controlled", "set_by": "owner", "reason_summary": "시험"},
    ).status_code == 200
    executor = h.agent.cli_executor
    executor.discussion_response = f"정리합니다.\n{WORK_BLOCK.format(profile='feature')}"
    executor.combined_response = FAKE_COMBINED_VERIFIED
    executor.write_files = {"reader.py": "changed\n"}
    executor.residual_activity = "none"
    executor.residual_basis = "in_process"
    h.send_message(case_id, "필터를 구현해줘", "c-1")
    h.agent.poll_once()
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    intent = _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["controlled_start"]
    wait = conv["progress"]["wait"][0]
    assert (wait["subject_id"], wait["subject_hash"]) == (intent["id"], intent["content_hash"])
    assert conv["send"]["general"]["allowed"] is True
    h.confirm_checkpoint(case_id, "start_scope", intent["id"], subject_type="intent_version",
                         subject_hash=intent["content_hash"])
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["controlled_result"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "waiting_final_acceptance"
    candidate = case["result"]["candidate"]
    assert all(c["verdict"] == "met" for c in h.criteria(case_id))
    h.confirm_checkpoint(case_id, "result_candidate", candidate["id"],
                         subject_type="completion_candidate", subject_hash=candidate["snapshot_hash"])
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "closed"
    assert case["result"]["candidate"]["acceptance"]["mode"] == "human"
    conv = h.conversation(case_id)
    assert conv["progress"]["state"] == "done"


# ================================================== AC-10 예외 수용


def test_unresolved_criteria_wait_for_a_person_and_an_exception_closes(processing_harness):
    """AC-10 — 미충족 기준이 남으면 후보를 만들고 멈춘다. 자동 정책은 예외를 수용하지 않는다.

    P4-10(이슈 #9) 부터 근거 있는 미충족은 먼저 수정 사이클(수정 구현 → 재검증)을 연다. 이 시험은 **사이클을 끈**
    업무(`remediation_limit = 0`)의 사람 대기를 본다 — 사이클 자체는 `tests/test_remediation_cycle.py`."""
    h = processing_harness
    h.agent.cli_executor.verification_response = VERIFICATION_ONE_FAILS
    _project, case_id, _request_id = _start(h)
    response = h.client.put(
        f"/api/cases/{case_id}/progress/limits",
        json={"remediation_limit": 0, "reason_summary": "이 업무는 자동 수정을 하지 않는다"},
    )
    assert response.status_code == 200, response.text
    conv = _drive(h, case_id)
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["criteria_unresolved"]
    remediation = conv["progress"]["wait"][0]["remediation"]
    assert (remediation["status"], remediation["used"], remediation["limit"]) == ("off", 0, 0)
    assert remediation["candidates"] == ["C-02"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == "waiting_final_acceptance"
    verdicts = {c["criterion_key"]: c["verdict"] for c in h.criteria(case_id)}
    assert verdicts == {"C-01": "met", "C-02": "not_met"}
    wait = conv["progress"]["wait"][0]
    assert [c["key"] for c in wait["criteria"]] == ["C-02"]
    auto = h.client.post(f"/api/cases/{case_id}/auto-complete").json()
    assert auto["applied"] is False and "unresolved_criteria" in auto["refusals"]
    # 사람이 예외를 수용하고 인수한다 — 원래 판정은 남는다.
    candidate_id = wait["candidate_id"]
    c2 = next(c for c in h.criteria(case_id) if c["criterion_key"] == "C-02")
    assert h.accept_exception(case_id, candidate_id, c2["id"], "로컬 경로는 다음 업무").status_code == 201
    assert h.accept(case_id, candidate_id).status_code == 201
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "closed_with_exceptions"
    assert {c["criterion_key"]: c["verdict"] for c in h.criteria(case_id)}["C-02"] == "not_met"
    conv = h.conversation(case_id)
    assert conv["progress"]["state"] == "done"


# ================================================== AC-11 조사 Profile


@pytest.mark.parametrize(
    "response, expected",
    [(ANALYSIS_DETERMINED, "closed"), (ANALYSIS_INCONCLUSIVE, "waiting_final_acceptance")],
    ids=["determined", "inconclusive"],
)
def test_a_research_case_reports_its_conclusions_from_the_analysis_run(processing_harness, response, expected):
    """AC-11 — 조사 Profile 은 분석 실행이 기준별 결론을 보고한다. 판단 불가는 확정 필수에서 미충족이다."""
    h = processing_harness
    h.agent.cli_executor.analysis_response = response
    _project, case_id, _request_id = _start(h, profile="research", git=False, text="로그 형식의 문제 원인을 분석해줘")
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    _agree(h, case_id)
    conv = _drive(h, case_id)
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["status"] == expected, conv["progress"]
    purposes = [r["purpose"] for r in _runs(h, case_id)]
    assert purposes == ["discussion_reply", "intent_authoring", "limited_analysis"]
    analysis = _runs(h, case_id)[-1]
    assert analysis["permission"] == "read_only"
    prompt = next(c["prompt"] for c in h.agent.cli_executor.calls if c["run_id"] == analysis["run_id"])
    assert "확인할 성공 기준" in prompt and "C-01" in prompt
    crits = {c["criterion_key"]: c for c in h.criteria(case_id)}
    if expected == "closed":
        assert all(c["verdict"] == "met" and c["satisfaction"] == "investigated" for c in crits.values())
        assert all(c["conclusion"] == "determined" for c in crits.values())
    else:
        assert all(c["verdict"] == "not_met" and c["conclusion"] == "inconclusive" for c in crits.values())
        assert _wait_codes(conv) == ["criteria_unresolved"]


# ================================================== AC-12 실패 재시도·막힘


def test_a_failed_task_is_retried_once_and_then_waits_for_a_person(processing_harness):
    """AC-12 — 구현 실행이 실패하면 한 번 다시 시도하고, 두 번째 실패는 사람 대기다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    h.agent.cli_executor.write_files = {}  # 고쳤다고 적지만 바뀐 것이 없다 → 실패
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"]
    wait = conv["progress"]["wait"][0]
    assert wait["task_key"] == "T1" and len(wait["failures"]) == 2
    impl = [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]
    assert [r["outcome"] for r in impl] == ["failed", "failed"]
    assert conv["send"]["general"]["allowed"] is True
    # 계속 진행만으로는 한 번 더 가지 않는다 — 상한은 초기화되지 않고 같은 대기로 돌아간다.
    # (P4-05 는 "한 번 더" 라고 적었고 이 단언이 `done` 도 받아 차이를 드러내지 못했다. 한 번 더
    # 가는 길은 한도를 올리는 것이다 — P4-05b, tests/test_progress_limits.py.)
    h.agent.cli_executor.write_files = {"reader.py": "fixed\n"}
    resumed = h.client.post(f"/api/cases/{case_id}/progress/resume", json={"actor": "owner"})
    assert resumed.status_code == 200, resumed.text
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"], conv["progress"]
    assert len([r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]) == 2


# ================================================== AC-13 중단·재개·복구


def test_a_stopped_progress_request_pauses_and_resume_continues(processing_harness):
    """AC-13 — 진행 요청을 중단하면 멈춤이 되고 스스로 재개하지 않는다. 계속 진행이 잇는다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    hold = threading.Event()
    h.agent.cli_executor.hold = hold
    _agree(h, case_id)  # 진행 요청이 열리고 결합 기록 실행이 배정된다
    conv = h.conversation(case_id)
    progress_request = conv["current_request"]
    assert progress_request["origin"] == "human_decision"
    worker = threading.Thread(target=h.agent.execution_tick)
    worker.start()
    try:
        deadline = time.monotonic() + 20
        while len(h.agent.cli_executor.calls) < 3 and time.monotonic() < deadline:
            time.sleep(0.02)
        stopped = h.client.post(
            f"/api/cases/{case_id}/requests/{progress_request['id']}/stop",
            json={"actor": "owner", "reason": "잠깐"},
        )
        assert stopped.status_code == 200, stopped.text
    finally:
        hold.set()
        worker.join(timeout=30)
    h.agent.cli_executor.hold = None
    h.agent.poll_once()
    conv = h.conversation(case_id)
    request = next(r for r in conv["requests"] if r["id"] == progress_request["id"])
    assert request["state"] == "interrupted"
    assert conv["progress"]["state"] == "paused"
    assert conv["send"]["general"]["allowed"] is True
    # 스스로 재개하지 않는다.
    h.agent.poll_once()
    assert h.conversation(case_id)["progress"]["state"] == "paused"
    resumed = h.client.post(f"/api/cases/{case_id}/progress/resume", json={"actor": "owner"})
    assert resumed.status_code == 200, resumed.text
    conv = h.conversation(case_id)
    assert conv["current_request"]["origin"] == "system_resume"
    conv = _drive(h, case_id)
    assert h.client.get(f"/api/cases/{case_id}").json()["status"] == "closed", conv["progress"]


def test_recovery_pauses_a_running_progress_whose_request_already_ended(processing_harness):
    """AC-13 — 기동 복구: 요청이 끝나 있으면 멈춤으로 표시하고 새 실행을 만들지 않는다."""
    h = processing_harness
    _project, case_id, request_id = _start(h)
    repo = _repo(h)
    # 진행 중인데 요청이 (예: 중단·불명 뒤 제어부 판정으로) 끝나 있는 모습을 만든다.
    repo.conn.execute(
        "UPDATE conversation_request SET state = 'interrupted', settled_at = ?, settled_by = 'controller',"
        " outcome_reason = 'stopped_by_request' WHERE id = ?",
        ("2026-09-23T00:00:00+00:00", request_id),
    )
    repo.conn.execute("UPDATE run SET status = 'finished', outcome = 'cancelled' WHERE request_id = ?", (request_id,))
    before = len(_runs(h, case_id))
    counts = WorkProgressor(repo, enabled=True).recover()
    assert counts == {"advanced": 0, "paused": 1}
    assert repo.progress_state(case_id)["state"] == "paused"
    assert len(_runs(h, case_id)) == before


# ================================================== AC-14 업무 단계 메시지


def test_a_work_stage_message_gets_a_read_only_reply_and_nothing_else_moves(processing_harness):
    """AC-14 (UI-04c 로 뜻이 넓어짐) — 업무 단계 메시지는 읽기 전용 응답만 받는다. 응답은 목적·유형 변경 규칙
    (D-86)을 받지만 `discussion` 으로 읽으면 아무것도 움직이지 않는다 — 진행은 조건 그대로, Profile 그대로."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["intent_agreement"]
    h.agent.cli_executor.discussion_response = (
        '지금은 동의를 기다리고 있습니다.\n\n```hads-interpretation\n{"kind": "discussion"}\n```'
    )
    h.send_message(case_id, "지금 뭘 기다리는 거야?", "c-2")
    h.agent.poll_once()
    conv = h.conversation(case_id)
    reply = next(r for r in conv["requests"] if r["opened_by_message_id"] == conv["messages"][-2]["id"])
    assert reply["state"] == "completed" and reply["settled_by"] == "request-processor"
    assert conv["messages"][-1]["author"] == "assistant"
    prompt = h.agent.cli_executor.calls[-1]["prompt"]
    assert "hads-interpretation" in prompt and '"profile_change"' in prompt
    assert '"work_request"' not in prompt  # 업무화 규칙이 아니다(이미 업무 단계)
    kinds = [(r["kind"], r["applied"]) for r in conv["interpretations"]]
    assert kinds == [("work_request", True), ("discussion", False)]
    assert conv["profile"] == "feature" and conv.get("profile_revisions") == []
    assert _wait_codes(conv) == ["intent_agreement"]
    assert conv["send"]["general"]["allowed"] is True


# ================================================== AC-17 설정으로 끔


def test_turning_the_processor_off_turns_the_progressor_off(harness):
    """AC-17 — 처리기를 끄면 진행기도 꺼진다. 사람의 업무화 뒤에도 진행 행·실행이 생기지 않는다."""
    h = harness
    project = h.create_project()
    view = h.create_conversation(project["id"], "필터")
    case_id = view["case_id"]
    h.send_message(case_id, "필터를 구현해줘", "c-1")
    message = h.conversation(case_id)["messages"][0]
    assert h.start_work(case_id, message["id"], profile="feature").status_code == 201
    conv = h.conversation(case_id)
    assert conv["progress"] is None
    assert h.client.get(f"/api/cases/{case_id}").json()["runs"] == []
    assert h.client.get(f"/api/cases/{case_id}/progress").json()["auto"] is False
    refused = h.client.post(f"/api/cases/{case_id}/progress/resume", json={"actor": "owner"})
    assert refused.status_code == 409
