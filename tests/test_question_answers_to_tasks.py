"""P4-09 (a) — 이월 질문의 답이 작업 실행의 입력이 된다(이슈 #2, plans/P4-PLAN-09.md AC-1~5).

설계·계획 단계에서 사람에게 물은 질문(이월 질문)에 답하면, 그 답의 **원문**이 그 질문이 막던 Task 의
구현·검증·실험·분석 실행에 고정 컨텍스트(`question_answer`, 핵심)로 들어간다. 그 전에는 답이
`task_question_block` 을 풀 뿐 어떤 작업 실행의 입력도 아니었고, 계획서에는 "사람이 정한다" 만 남아
AI 가 "결정이 없다" 로 `blocked` 를 냈다(2026-09-24 실제 관측).

    답이 그 Task 에 간다            차단 해제 = 답의 내용이 전달됨
    재시도도 같은 입력이다           실패 뒤 다시 만든 실행도 같은 참조를 갖는다
    다른 Task 만 막던 답은 안 간다   연결 없이 전부를 막던 답은 모든 Task 에 간다
    의도 단계 질문은 그대로          이미 의도 버전에 반영된 답을 작업 실행에 다시 주지 않는다
"""

from __future__ import annotations

from typing import Any

from runner import prompts
from tests.conftest import FAKE_COMBINED_SECTIONS, FAKE_TASKS_VERIFIED, fake_preparation_response
from tests.test_preparation import _refusals
from tests.test_work_graph import _graph_case
from tests.test_work_progressor import _agree, _drive, _repo, _runs, _start, _wait_codes

ANSWER_TEXT = "공유 링크 주소는 HTTPS 로 한다 — 토큰은 쿼리가 아니라 경로에 둔다"


def _combined_with_question(blocks: list[str]) -> str:
    return fake_preparation_response(
        "결합",
        FAKE_COMBINED_SECTIONS,
        questions=[
            {
                "key": "d1",
                "text": "공유 링크 주소 형식은 사람이 정한다",
                "summary": "공유 링크 주소 형식",
                "decide_at": "plan",
                "blocks": blocks,
            }
        ],
        tasks=FAKE_TASKS_VERIFIED,
    )


def _question_answer_refs(h, run_id: str) -> list[dict[str, Any]]:
    return [r for r in h.context_refs(run_id) if r["role"] == "question_answer"]


def _prompt_for(h, run_id: str) -> str:
    return next(c["prompt"] for c in h.agent.cli_executor.calls if c["run_id"] == run_id)


# ================================================== AC-1·AC-2 진행기 경유


def test_the_answer_to_a_plan_question_reaches_the_task_it_blocked_and_its_retry(processing_harness):
    """AC-1·AC-2 — 계획 질문이 T1 을 막음 → 답 → T1 구현 실행의 참조·지시문에 답 원문. 재시도도 같다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    h.agent.cli_executor.combined_response = _combined_with_question(["T1"])
    _drive(h, case_id)
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["deferred_questions"], conv["progress"]
    [question] = h.work_graph(case_id)["deferred_open_questions"]
    assert question["question_key"] == "combined:d1"
    impl_before = [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]
    assert impl_before == []

    # 사람이 카드에서 답한다. 구현은 실패하게 둔다(고쳤다고 적지만 바뀐 것이 없다) — 재시도가 같은 입력을 갖는지 본다.
    h.agent.cli_executor.write_files = {}
    intent = h.latest_intent(case_id)
    h.send_message(case_id, ANSWER_TEXT, "a-1", kind="card_answer",
                   question_id=question["id"], intent_version_id=intent["id"])
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["task_failed"], conv["progress"]
    impl = [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]
    assert len(impl) == 2 and [r["task_id"] for r in impl] == ["T1", "T1"]
    for run in impl:
        [ref] = _question_answer_refs(h, run["run_id"])
        assert ref["tier"] == "core" and ref["inclusion"] == "inline"
        assert ref["question"]["key"] == "combined:d1" and ref["question"]["summary"] == "공유 링크 주소 형식"
        # Runner 가 실제로 읽었고 지시문에 답 원문과 "무엇에 대한 답인지" 가 적혔다.
        assert ref["receipt_status"] == "read"
        prompt = _prompt_for(h, run["run_id"])
        assert ANSWER_TEXT in prompt
        assert prompts.CONTEXT_LABEL["question_answer"] in prompt
        assert "질문 combined:d1: 공유 링크 주소 형식 에 대한 답" in prompt
    # 동의된 의도·계획은 그대로 앞에 있다 — 답은 그 뒤에 더해졌다.
    roles = [r["role"] for r in h.context_refs(impl[0]["run_id"])]
    assert roles.index("question_answer") > roles.index("agreed_intent")


# ================================================== AC-3·AC-4·AC-5 어느 답이 어느 Task 에 가는가


def test_only_the_questions_that_blocked_a_task_reach_it_and_unlinked_ones_reach_every_task(harness):
    """AC-3·AC-5 — 연결된 답은 그 Task 에만, 연결 없이 전부를 막던 답은 모든 Task 에, Task 없는 실행은 전부."""
    case = _graph_case(
        harness,
        plan_questions=[
            {"key": "p1", "text": "대소문자", "summary": "대소문자 구분", "decide_at": "plan", "blocks": ["T2"]},
            {"key": "p2", "text": "출력 형식", "summary": "출력 형식", "decide_at": "plan", "blocks": []},
        ],
    )
    case_id = case["id"]
    questions = {q["question_key"]: q for q in harness.work_graph(case_id)["deferred_open_questions"]}
    answers: dict[str, str] = {}
    for key, text in (("plan:p1", "구분하지 않는다"), ("plan:p2", "JSON 줄 형식")):
        response = harness.client.post(
            f"/api/cases/{case_id}/questions/{questions[key]['id']}/answer",
            json={"content": text, "summary": text, "target_runner_id": harness.agent.config.runner_id},
        )
        assert response.status_code == 202, response.text
        answers[key] = response.json()["question"]["answer_artifact_id"]
    harness.agent.poll_once()  # 답 원문 저장
    repo = _repo(harness)
    latest = repo.latest_intent_version(case_id)

    def keys(task_key: str | None) -> list[str]:
        return [q["question_key"] for q in repo.answered_deferred_questions_for_task(case_id, latest["id"], task_key)]

    assert keys("T1") == ["plan:p2"]  # p1 은 T2 만 막았다
    assert keys("T2") == ["plan:p1", "plan:p2"]
    assert keys(None) == ["plan:p1", "plan:p2"]  # Task 키 없는 작업 실행은 전부

    # 실제 실행: T1(조사) 은 p2 의 답만, T2(구현) 는 둘 다 받는다.
    t1 = harness.request_implementation(case_id, run_id="run-t1", task_id="T1")
    assert t1.status_code == 201, t1.text
    got_t1 = {r["artifact_id"] for r in _question_answer_refs(harness, "run-t1")}
    assert got_t1 == {answers["plan:p2"]}
    harness.complete_task(case_id, "T1")
    t2 = harness.request_implementation(case_id, run_id="run-t2", task_id="T2")
    assert t2.status_code == 201, t2.text
    got_t2 = {r["artifact_id"] for r in _question_answer_refs(harness, "run-t2")}
    assert got_t2 == {answers["plan:p1"], answers["plan:p2"]}
    for ref in _question_answer_refs(harness, "run-t2"):
        assert ref["tier"] == "core" and ref["question"]["key"] in ("plan:p1", "plan:p2")


def test_an_open_question_still_blocks_and_intent_stage_answers_do_not_reach_work_runs(harness):
    """AC-4 — 답하지 않은 이월 질문은 여전히 막고, 의도 단계 질문의 답은 작업 실행에 가지 않는다."""
    case = _graph_case(
        harness,
        plan_questions=[
            {"key": "p1", "text": "대소문자", "summary": "대소문자 구분", "decide_at": "plan", "blocks": ["T2"]},
        ],
    )
    case_id = case["id"]
    harness.complete_task(case_id, "T1")
    refusals = _refusals(harness.request_implementation(case_id, run_id="run-blocked", task_id="T2"))
    assert "deferred_questions_unresolved" in refusals
    repo = _repo(harness)
    latest = repo.latest_intent_version(case_id)
    assert repo.answered_deferred_questions_for_task(case_id, latest["id"], "T2") == []
    # 의도 단계 질문(decide_at = intent)이 답했더라도 여기 오지 않는다 — 의도 버전에 이미 반영됐다.
    intent_questions = [q for q in repo.list_questions(latest["id"]) if q["decide_at"] == "intent"]
    for question in intent_questions:
        assert question["state"] != "open"
    assert all(q["decide_at"] != "intent" for q in repo.answered_deferred_questions_for_task(case_id, latest["id"], None))
