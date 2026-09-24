"""UI-05a (이슈 #7, D-94) — 명시로 켠 품질 게이트를 진행기가 스스로 검토·수정한다(plans/UI-PLAN-05a.md AC-9~13).

    켠 게이트가 막으면 검토한다     사람 없이 별도 세션 검토 실행 → 그 발견이 검증 1회의 판정(독립 검사)
    실패면 고치고 다시 본다         지적을 실은 수정 실행 → 새 버전을 다시 검토. 수정은 게이트 한도를 쓴다
    한도 뒤에만 사람                 `quality_gate` 대기(게이트·판정·지적·사용/한도) → 한도 올림·끄기 뒤 이어 간다
    검토 자체가 실패하면             `blocked`(통과 아님) → 재시도 한도 안에서 다시 검토 → 넘으면 사람
    결합 기록 경로                   QG-02 가 결합 기록 작성을 막지 않고, 구현 전에 결합 기록을 검토한다

**실제 CLI 를 부르지 않는다.** `conftest` 의 가짜 실행기로 진행기 경유 흐름을 돈다. 실제 codex 가 발견을 JSON 으로
내는지는 라이브에서 본다.
"""

from __future__ import annotations

import json
from typing import Any

from tests.test_work_progressor import _agree, _drive, _runs, _start, _wait_codes

FAILING_REVIEW = json.dumps(
    {
        "findings": [
            {
                "finding_key": "c01-empty-file",
                "criterion": "C-01",
                "severity": "required",
                "certainty": "confirmed",
                "target": "reader.py",
                "summary": "빈 파일에서 예외가 난다 — ERROR 줄만 남기는 동작이 빈 입력을 다루지 않는다",
            }
        ]
    },
    ensure_ascii=False,
)
CLEAN_REVIEW = '{"findings": []}'
#: 수정 실행이 실제로 쓰는 다른 내용(첫 구현과 달라야 "바뀐 것이 있다").
REPAIRED_READER = (
    "def read(path):\n"
    "    lines = open(path).read().splitlines()\n"
    "    return [l for l in lines if l.startswith('ERROR')]\n"
)


def _set_gate(h, case_id: str, gate: str, *, setting: str = "on", repair_limit: int | None = None,
              task_key: str = "", reason: str = "이 업무는 이 게이트를 따로 검토한다") -> Any:
    response = h.client.put(
        f"/api/cases/{case_id}/quality-gates/{gate}/policy",
        json={"task_key": task_key, "setting": setting, "inspection": None, "repair_limit": repair_limit,
              "actor": "owner", "reason_summary": reason},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _gate(h, case_id: str, gate: str, task_key: str = "") -> dict[str, Any]:
    state = h.client.get(f"/api/cases/{case_id}/quality-gates", params={"task_key": task_key}).json()
    return next(g for g in state["gates"] if g["gate"] == gate)


def _purposes(h, case_id: str) -> list[str]:
    return [r["purpose"] for r in _runs(h, case_id)]


def _reviews(h, case_id: str) -> list[dict[str, Any]]:
    return [r for r in _runs(h, case_id) if r["purpose"] == "quality_gate_review"]


def _prompt_for(h, run_id: str) -> str:
    return next(c["prompt"] for c in h.agent.cli_executor.calls if c["run_id"] == run_id)


def _to_agreement(h, *, gates: list[tuple[str, dict[str, Any]]]) -> str:
    _project, case_id, _request_id = _start(h)
    for gate, options in gates:
        _set_gate(h, case_id, gate, **options)
    _drive(h, case_id)
    _agree(h, case_id)
    return case_id


def test_an_explicit_gate_is_reviewed_by_the_progressor_and_a_pass_lets_the_work_go_on(processing_harness):
    """AC-9 — QG-04 를 켜면 검증 실행 전에 진행기가 별도 세션 검토를 만들고, 발견 없음이 독립 검사의 통과로 기록된
    뒤 검증·자동 완료가 사람 없이 이어진다. 검토 지시문은 게이트·대상·기준 식별자를 받는다."""
    h = processing_harness
    case_id = _to_agreement(h, gates=[("QG-04", {})])
    h.agent.cli_executor.review_response = CLEAN_REVIEW
    conv = _drive(h, case_id, polls=40)
    assert conv["progress"]["state"] == "done", conv["progress"]
    purposes = _purposes(h, case_id)
    assert purposes[-3:] == ["feature_implementation", "quality_gate_review", "verification_run"]
    [review] = _reviews(h, case_id)
    assert review["task_id"] == "qg:QG-04:T2" and review["role"] == "reviewer" and review["permission"] == "read_only"
    gate = _gate(h, case_id, "QG-04", "T2")
    latest = gate["latest_run"]
    assert (latest["verdict"], latest["validity"], latest["inspection_used"]) == ("pass", "current", "independent")
    assert latest["reviewer_run_id"] == review["run_id"] and latest["subject_key"] == "impl:T2"
    assert f"run:{review['run_id']}" in latest["evidence_refs"]
    prompt = _prompt_for(h, review["run_id"])
    assert "게이트: QG-04 구현 묶음 품질" in prompt and "작업 디렉터리의 현재 코드" in prompt
    line = next(l for l in prompt.splitlines() if l.startswith("criterion 에 쓸 기준 식별자:"))
    assert sorted(line.split(":", 1)[1].replace(" ", "").split(",")) == ["C-01", "C-02"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"


def test_a_failing_review_is_repaired_within_the_limit_then_waits_and_raising_the_limit_goes_on(processing_harness):
    """AC-10·AC-11 — 실패면 지적을 실은 수정 실행(구현 다시)이 돌고 새 버전을 다시 검토한다. 수정 한도 1 을 쓰면
    `quality_gate` 사람 대기(판정·지적·1/1). 한도를 올리면(사유) 그 자리에서 한 번 더 고치고, 이번엔 통과해 끝난다."""
    h = processing_harness
    case_id = _to_agreement(h, gates=[("QG-04", {"repair_limit": 1})])
    executor = h.agent.cli_executor
    executor.review_response = FAILING_REVIEW
    # 첫 구현 뒤에 수정 실행이 실제로 파일을 바꾸게 한다(같은 내용이면 "고쳤다고 적었지만 바뀐 것이 없는" 실패다 —
    # 그때도 수정 차수는 쓰이고 대상이 그대로라 다시 검토하지 않는다).
    first = executor.write_files
    executor.write_files = {}

    def after_first_impl() -> None:
        impl = [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]
        executor.write_files = first if not impl else {"reader.py": REPAIRED_READER}

    after_first_impl()
    for _ in range(40):
        h.agent.poll_once()
        after_first_impl()
    conv = _drive(h, case_id, polls=40)
    assert _wait_codes(conv) == ["quality_gate"], conv["progress"]
    [wait] = conv["progress"]["wait"]
    assert (wait["gate"], wait["task_key"], wait["verdict"]) == ("QG-04", "T2", "fail")
    assert (wait["repairs_used"], wait["repair_limit"]) == (1, 1)
    assert wait["findings"][0]["criterion"] == "C-01" and "빈 파일" in wait["findings"][0]["summary"]
    # 검토 → 실패 → 수정(구현 다시, 지적이 지시문에) → 검토 → 실패 → 대기. 검증 실행은 없다.
    purposes = _purposes(h, case_id)
    assert purposes[-3:] == ["quality_gate_review", "feature_implementation", "quality_gate_review"]
    impl = [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]
    reviews = _reviews(h, case_id)
    assert len(impl) == 2 and len(reviews) == 2 and "verification_run" not in purposes
    repair_prompt = _prompt_for(h, impl[1]["run_id"])
    assert "품질 게이트(QG-04 구현 묶음 품질)의 지적" in repair_prompt
    assert "빈 파일에서 예외가 난다" in repair_prompt
    assert impl[1]["task_id"] == "T1"
    remediation = _gate(h, case_id, "QG-04", "T2")["remediation"]
    assert (remediation["used_attempts"], remediation["reserved_attempts"], remediation["subject_key"]) == (1, 0, "impl:T2")

    # 한도를 올린다 — 설정 변경 뒤 진행기가 그 자리에서 수정을 한 번 더 연다. 이번 검토는 통과한다.
    executor.review_response = CLEAN_REVIEW
    executor.write_files = {"reader.py": REPAIRED_READER + "\n# 빈 입력도 빈 목록\n"}
    _set_gate(h, case_id, "QG-04", repair_limit=2, reason="한 번 더 고쳐 본다")
    conv = _drive(h, case_id, polls=40)
    assert conv["progress"]["state"] == "done", conv["progress"]
    assert _purposes(h, case_id)[-3:] == ["feature_implementation", "quality_gate_review", "verification_run"]
    gate = _gate(h, case_id, "QG-04", "T2")
    assert gate["latest_run"]["verdict"] == "pass"
    assert gate["remediation"]["used_attempts"] == 2 and gate["remediation"]["state"] == "passed"


def test_a_review_that_cannot_run_is_blocked_retried_once_then_waits_and_turning_the_gate_off_goes_on(processing_harness):
    """AC-12·AC-11 — 검토가 발견을 내지 못하면(형식 오류로 실패) 판정은 `blocked`(통과 아님)이고 한 번 다시 검토한다.
    다시 실패하면 사람 대기. 사람이 게이트를 끄면(사유) 검증이 이어져 끝난다. 끈 뒤에는 검토를 만들지 않는다."""
    h = processing_harness
    case_id = _to_agreement(h, gates=[("QG-04", {})])
    h.agent.cli_executor.review_response = "검토했지만 JSON 을 내지 않았다"
    conv = _drive(h, case_id, polls=40)
    assert _wait_codes(conv) == ["quality_gate"], conv["progress"]
    assert conv["progress"]["wait"][0]["verdict"] == "blocked"
    reviews = _reviews(h, case_id)
    assert len(reviews) == 2 and all(r["outcome"] == "failed" for r in reviews)
    assert _gate(h, case_id, "QG-04", "T2")["latest_run"]["verdict"] == "blocked"

    _set_gate(h, case_id, "QG-04", setting="off", reason="이 업무는 구현 검토 없이 검증으로 확인한다")
    conv = _drive(h, case_id, polls=40)
    assert conv["progress"]["state"] == "done", conv["progress"]
    assert len(_reviews(h, case_id)) == 2
    assert _purposes(h, case_id)[-1] == "verification_run"


def test_recommended_or_turned_off_gates_make_no_review_runs(processing_harness):
    """AC-12 — 기본 적용(추천)만 있는 업무와 게이트를 명시로 끈 업무는 검토 실행을 만들지 않는다."""
    h = processing_harness
    case_id = _to_agreement(h, gates=[("QG-04", {"setting": "off"})])
    conv = _drive(h, case_id, polls=40)
    assert conv["progress"]["state"] == "done", conv["progress"]
    assert _reviews(h, case_id) == []


def test_on_the_combined_path_qg02_does_not_block_writing_the_record_and_reviews_it_before_implementation(processing_harness):
    """AC-13 — Fast Lane(결합 기록)에서 QG-02·QG-03 을 켜면 결합 기록 작성은 막히지 않고, 구현 전에 결합 기록을
    QG-02(대상 `design`)로, 그 작업을 QG-03(대상 `plan:T1`)으로 검토한 뒤 구현이 이어진다."""
    h = processing_harness
    case_id = _to_agreement(h, gates=[("QG-02", {}), ("QG-03", {})])
    h.agent.cli_executor.review_response = CLEAN_REVIEW
    conv = _drive(h, case_id, polls=40)
    assert conv["progress"]["state"] == "done", conv["progress"]
    purposes = _purposes(h, case_id)
    plan_at = purposes.index("plan_authoring")
    impl_at = purposes.index("feature_implementation")
    assert purposes[plan_at + 1 : impl_at] == ["quality_gate_review", "quality_gate_review"]
    reviews = _reviews(h, case_id)
    assert [r["task_id"] for r in reviews] == ["qg:QG-02:", "qg:QG-03:T1"]
    qg02 = _gate(h, case_id, "QG-02")["latest_run"]
    qg03 = _gate(h, case_id, "QG-03", "T1")["latest_run"]
    assert (qg02["subject_key"], qg02["verdict"]) == ("design", "pass")
    assert (qg03["subject_key"], qg03["verdict"]) == ("plan:T1", "pass")
    combined = h.preparation(case_id)["combined"]["artifact"]
    assert f"artifact:{combined['artifact_id']}:{combined['artifact_rev']}" in qg02["context_refs"]
    assert "결합 기록" in _prompt_for(h, reviews[0]["run_id"])
