"""UI-05a (이슈 #7) — 새 화면으로 옮긴 작업 그래프 수정의 서버 보강(plans/UI-PLAN-05a.md AC-3·AC-5·AC-6).

관리 화면에만 있던 Task 추가·취소와 어느 화면에도 없던 질문↔Task 연결 고치기를 새 화면(`작업` 탭)으로 옮기면서 서버가
두 가지를 더한다.

    수정 뒤 진행기가 본다      추가·취소·연결은 사람의 결정이다 — 다른 결정(동의·확인·한도)처럼 기록 뒤 진행기가
                              다음 걸음을 본다. 그 전에는 `다시 시도` 나 다음 사건까지 아무 일도 없었다
    종료된 업무는 고치지 않는다  종료·취소된 Case 의 그래프에 새 리비전을 만들지 않는다(D-33 — 종료 뒤 수정은
                              연결된 새 Case). 화면이 폼을 감추는 것은 잠금이 아니다

**실제 CLI 를 부르지 않는다.** `conftest` 의 가짜 실행기로 진행기 경유 흐름을 돈다.
"""

from __future__ import annotations

from tests.conftest import FAKE_COMBINED_SECTIONS, FAKE_TASKS_VERIFIED, fake_preparation_response
from tests.test_work_progressor import _agree, _drive, _repo, _runs, _start, _wait_codes


def _combined_with_unlinked_question() -> str:
    """결합 기록에 **연결 없는** 계획 질문 하나 — 모든 작업을 막는다."""
    return fake_preparation_response(
        "결합",
        FAKE_COMBINED_SECTIONS,
        questions=[
            {
                "key": "d1",
                "text": "출력 형식은 사람이 정한다",
                "summary": "출력 형식",
                "decide_at": "plan",
                "blocks": [],
            }
        ],
        tasks=FAKE_TASKS_VERIFIED,
    )


def _blocked_by_an_unlinked_question(h) -> tuple[str, dict]:
    _project, case_id, _request_id = _start(h)
    h.agent.cli_executor.combined_response = _combined_with_unlinked_question()
    _drive(h, case_id)
    _agree(h, case_id)
    conv = _drive(h, case_id)
    assert _wait_codes(conv) == ["deferred_questions"], conv["progress"]
    [question] = h.work_graph(case_id)["deferred_open_questions"]
    assert h.work_graph(case_id)["question_blocks"] == {}
    return case_id, question


def _impl_runs(h, case_id: str) -> list[dict]:
    return [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]


def test_linking_the_question_lets_the_progressor_start_the_task_it_no_longer_blocks(processing_harness):
    """AC-4·AC-5 — 연결 없는 질문이 전부 막던 업무에서 질문을 T2 에만 연결하면, 사람이 `다시 시도` 를 누르지 않아도
    진행기가 T1 구현을 연다. 질문은 여전히 열려 있고(답이 아니다) T2 는 계속 그 결정을 기다린다."""
    h = processing_harness
    case_id, question = _blocked_by_an_unlinked_question(h)
    assert _impl_runs(h, case_id) == []
    revision_before = h.work_graph(case_id)["graph"]["revision"]

    response = h.client.put(
        f"/api/cases/{case_id}/questions/{question['id']}/blocks",
        json={"task_keys": ["T2"], "reason": "출력 형식은 검증 작업만 기다린다", "actor": "owner"},
    )
    assert response.status_code == 201, response.text
    graph = h.work_graph(case_id)
    assert graph["graph"]["revision"] == revision_before + 1
    assert graph["question_blocks"] == {question["id"]: ["T2"]}
    [still_open] = graph["deferred_open_questions"]
    assert still_open["state"] == "open"  # 연결은 답이 아니다

    # 연결을 기록한 그 호출에서 진행기가 다음 걸음을 봤다 — 그 리비전을 출처로 진행 요청이 열렸다.
    last = h.conversation(case_id)["requests"][-1]
    assert (last["origin"], last["origin_ref"]) == ("human_decision", f"replan:{revision_before + 1}")

    conv = _drive(h, case_id)
    impl = _impl_runs(h, case_id)
    assert [r["task_id"] for r in impl] == ["T1"]
    # T1 은 끝났고 T2(검증)는 그 결정을 기다린다 — 다시 사람 대기.
    assert _wait_codes(conv) == ["deferred_questions"], conv["progress"]
    t2 = next(t for t in h.work_graph(case_id)["tasks"] if t["task_key"] == "T2")
    assert [b["reason"] for b in t2["readiness"]["blocked_by"]] == ["deferred_questions_unresolved"]


def test_cancelling_and_adding_a_task_is_seen_by_the_progressor(processing_harness):
    """AC-3·AC-5 — 막힌 업무에서 사람이 작업을 취소·추가하면 새 리비전(이유 보존)이 생기고 진행기가 그 자리에서 본다."""
    h = processing_harness
    case_id, question = _blocked_by_an_unlinked_question(h)
    events_before = len(h.conversation(case_id)["progress"]["events"])

    added = h.client.post(
        f"/api/cases/{case_id}/work-graph/tasks",
        json={
            "task": {"key": "T3", "kind": "verification", "summary": "경계 입력 시험", "depends_on": ["T1"]},
            "reason": "빈 파일 경계를 따로 확인한다",
            "actor": "owner",
        },
    )
    assert added.status_code == 201, added.text
    cancelled = h.client.post(
        f"/api/cases/{case_id}/work-graph/tasks/T3/cancel",
        json={"reason": "T2 가 이미 덮는다", "actor": "owner"},
    )
    assert cancelled.status_code == 201, cancelled.text
    revisions = {r["revision"]: r["reason_summary"] for r in h.client.get(f"/api/cases/{case_id}/work-graph-revisions").json()}
    rev_added, rev_cancelled = added.json()["revision"], cancelled.json()["revision"]
    assert rev_cancelled == rev_added + 1
    assert (revisions[rev_added], revisions[rev_cancelled]) == ("빈 파일 경계를 따로 확인한다", "T2 가 이미 덮는다")
    t3 = next(t for t in h.work_graph(case_id)["tasks"] if t["task_key"] == "T3")
    assert t3["cancelled"] is True and t3["cancel_reason"] == "T2 가 이미 덮는다"

    # 진행기가 두 번 봤다 — 호출마다 다시 판정해 사람 대기를 새로 적었다. 여전히 연결 없는 질문이 전부 막으므로
    # 대기는 그대로이고 구현 실행을 만들지 않았다.
    conv = h.conversation(case_id)
    seen = [(e["step"], e["action"]) for e in conv["progress"]["events"][events_before:]]
    assert seen == [("deferred_questions", "waiting_human")] * 2
    assert _wait_codes(conv) == ["deferred_questions"], conv["progress"]
    assert _impl_runs(h, case_id) == []


def test_a_closed_or_cancelled_case_refuses_graph_edits_and_keeps_its_revision(processing_harness):
    """AC-6 — 취소(종료)된 업무의 그래프는 추가·취소·질문 연결 모두 거부되고 리비전이 늘지 않는다.

    추가·취소는 원래도 새 리비전 쪽에서 거부됐다. 질문 연결은 그 거부 **전에** 연결 표를 지우고 다시 썼다 — 409 를
    돌려주면서 기록이 바뀌었다(UI-05a 가 고침). 그래서 표를 직접 본다."""
    h = processing_harness
    case_id, question = _blocked_by_an_unlinked_question(h)
    response = h.client.post(
        f"/api/cases/{case_id}/cancel", json={"actor": "owner", "reason": "방향이 바뀌어 이 업무는 버린다"}
    )
    assert response.status_code == 200, response.text
    revision = h.work_graph(case_id)["graph"]["revision"]

    def block_refs() -> list[str]:
        rows = _repo(h).conn.execute(
            "SELECT raw_ref FROM question_block_ref WHERE question_id = ? ORDER BY raw_ref", (question["id"],)
        ).fetchall()
        return [r["raw_ref"] for r in rows]

    refs_before = block_refs()

    refused = [
        h.client.post(
            f"/api/cases/{case_id}/work-graph/tasks",
            json={"task": {"key": "T9", "kind": "implementation", "summary": "늦은 작업"}, "reason": "늦게 생각남", "actor": "owner"},
        ),
        h.client.post(
            f"/api/cases/{case_id}/work-graph/tasks/T1/cancel", json={"reason": "필요 없음", "actor": "owner"}
        ),
        h.client.put(
            f"/api/cases/{case_id}/questions/{question['id']}/blocks",
            json={"task_keys": ["T2"], "reason": "늦은 연결", "actor": "owner"},
        ),
    ]
    for response in refused:
        assert response.status_code == 409, response.text
        assert "case_already_closed" in response.text
    graph = h.work_graph(case_id)
    assert graph["graph"]["revision"] == revision
    assert graph["question_blocks"] == {}
    assert all(t["task_key"] != "T9" for t in graph["tasks"])
    assert block_refs() == refs_before
