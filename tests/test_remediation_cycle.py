"""P4-10 (이슈 #9) — 검증이 근거와 함께 기준 미충족을 보고하면 진행기가 수정 구현 → 재검증을 한도 안에서 돌린다
(plans/P4-PLAN-10.md AC-7~9).

    근거 있는 미충족이면 사이클         작업 그래프 새 리비전(출처 `progressor_remediation`, 사유)에 FIX<n>·REVERIFY<n>
    수정 실행은 검증 보고를 받는다       핵심 참조 `verification_report` + 지시문 "검증이 보고한 미충족"
    한도 안에서만                        `remediation_limit`(기본 2) 뒤·0 이면 `criteria_unresolved` 카드에 사용/한도·이력
    근거 없으면 열지 않는다              `unverified`·명령 없는 `not_met` 은 이유와 함께 사람 카드

**실제 CLI 를 부르지 않는다.** `conftest` 의 가짜 실행기로 진행기 경유 흐름을 돈다.
"""

from __future__ import annotations

import json
from typing import Any

from tests.conftest import FAKE_VERIFICATION_RESPONSE
from tests.test_work_progressor import VERIFICATION_ONE_FAILS, _agree, _drive, _runs, _start, _wait_codes

#: 수정 실행이 실제로 쓰는 다른 내용(첫 구현과 달라야 "바뀐 것이 있다").
FIXED_READER = (
    "def read(path):\n"
    "    lines = open(path, encoding='utf-8').read().splitlines()\n"
    "    return [l for l in lines if l.startswith('ERROR')]\n"
)

#: 미충족을 적었지만 **왜인지 말하지 않은** 보고 — 근거가 없다. (명령이 하나도 없는 검증은 Runner 가 이미 실패로
#: 적는다 — P3-03 — 그래서 끝까지 돈 검증에서 빠질 수 있는 근거는 요약이다.)
VERIFICATION_NOT_MET_NO_SUMMARY = """확인했습니다.

```json
{
  "commands": [
    {"command": "python -m pytest tests/test_reader.py -k filter", "summary": "필터 시험", "exit_code": 0},
    {"command": "python -m pytest tests/test_reader.py -k path", "summary": "경로 시험", "exit_code": 1}
  ],
  "result_summary": "실패가 있었다",
  "criteria": [
    {"key": "C-01", "verdict": "met", "summary": "시험 통과"},
    {"key": "C-02", "verdict": "not_met"}
  ]
}
```
"""

#: 확인하지 못함(환경 부족) — 구현 결함이 아니다.
VERIFICATION_UNVERIFIED = """확인했습니다.

```json
{
  "commands": [
    {"command": "python -m pytest tests/test_reader.py", "summary": "reader 시험", "exit_code": 0}
  ],
  "result_summary": "C-02 는 이 PC 에 표본 경로가 없어 확인하지 못했다",
  "criteria": [
    {"key": "C-01", "verdict": "met", "summary": "시험 통과"},
    {"key": "C-02", "verdict": "unverified", "summary": "표본 경로 없음"}
  ]
}
```
"""


def _set_limits(h, case_id: str, **values: Any) -> None:
    response = h.client.put(
        f"/api/cases/{case_id}/progress/limits", json={**values, "reason_summary": "시험"}
    )
    assert response.status_code == 200, response.text


def _run_until_stop(h, case_id: str, adjust, polls: int = 60) -> dict[str, Any]:
    """Runner 를 돌리며 매번 가짜 실행기의 응답을 조정한다(첫 구현·첫 검증 뒤에 바뀐다)."""
    adjust()
    for _ in range(polls):
        h.agent.poll_once()
        adjust()
    return _drive(h, case_id, polls=20)


def _revisions(h, case_id: str) -> list[dict[str, Any]]:
    return h.client.get(f"/api/cases/{case_id}/work-graph-revisions").json()  # 최신 먼저


def _prompt_for(h, run_id: str) -> str:
    return next(c["prompt"] for c in h.agent.cli_executor.calls if c["run_id"] == run_id)


def _crits(h, case_id: str) -> dict[str, dict[str, Any]]:
    return {c["criterion_key"]: c for c in h.criteria(case_id)}


def test_a_not_met_with_evidence_opens_a_fix_and_reverify_cycle_that_closes_the_work(processing_harness):
    """AC-7 — 검증이 명령·요약과 함께 C-02 `not_met` 을 보고하면 사람 없이 새 리비전(출처 `progressor_remediation`,
    행위자 진행기, 사유)에 FIX1(구현, C-02 를 implements, 출처 관측)·REVERIFY1(검증, T2 가 보던 기준 전부, FIX1 에 의존)이
    더해진다. FIX1 실행은 T2 의 출력을 `verification_report` 로 받고 지시문에 미충족 블록이 있다. 재검증이 충족이면
    자동 완료한다. 이전 리비전과 T2 의 판정 이력은 남는다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _drive(h, case_id)
    _agree(h, case_id)
    executor = h.agent.cli_executor
    executor.verification_response = VERIFICATION_ONE_FAILS
    first_write = dict(executor.write_files)

    def adjust() -> None:
        runs = _runs(h, case_id)
        impl = [r for r in runs if r["purpose"] == "feature_implementation" and r["status"] == "finished"]
        verify = [r for r in runs if r["purpose"] == "verification_run" and r["status"] == "finished"]
        # 가짜 실행기는 쓰기 권한 실행마다 같은 파일을 쓴다(검증 포함) — 첫 검증 뒤에 바꿔야 수정 실행이 "바뀐 것" 이 된다.
        executor.write_files = first_write if not verify else {"reader.py": FIXED_READER}
        executor.verification_response = VERIFICATION_ONE_FAILS if not verify else FAKE_VERIFICATION_RESPONSE

    conv = _run_until_stop(h, case_id, adjust)
    assert conv["progress"]["state"] == "done", conv["progress"]
    case = h.client.get(f"/api/cases/{case_id}").json()
    assert case["result"]["closure"]["closure_kind"] == "completed"

    runs = _runs(h, case_id)
    work = [(r["purpose"], r["task_id"]) for r in runs if r["purpose"] in ("feature_implementation", "verification_run")]
    assert work == [
        ("feature_implementation", "T1"),
        ("verification_run", "T2"),
        ("feature_implementation", "FIX1"),
        ("verification_run", "REVERIFY1"),
    ]
    t2 = next(r for r in runs if r["task_id"] == "T2")
    fix = next(r for r in runs if r["task_id"] == "FIX1")
    reverify = next(r for r in runs if r["task_id"] == "REVERIFY1")

    revisions = _revisions(h, case_id)
    current = revisions[0]
    assert (current["source"], current["actor"], current["state"]) == ("progressor_remediation", "work-progressor", "current")
    assert "C-02" in current["reason_summary"] and "1/2" in current["reason_summary"] and t2["run_id"] in current["reason_summary"]
    assert revisions[1]["source"] == "plan_artifact" and revisions[1]["state"] == "superseded"
    tasks = {t["task_key"]: t for t in current["tasks"]}
    assert set(tasks) == {"T1", "T2", "FIX1", "REVERIFY1"}
    assert (tasks["FIX1"]["kind"], tasks["FIX1"]["origin"], tasks["FIX1"]["depends_on"]) == ("implementation", "observation", [])
    assert (tasks["REVERIFY1"]["kind"], tasks["REVERIFY1"]["depends_on"]) == ("verification", ["FIX1"])
    crit_ids = {c["criterion_key"]: c["id"] for c in h.criteria(case_id)}
    assert tasks["FIX1"]["criteria"] == [{"criterion_id": crit_ids["C-02"], "relation": "implements"}]
    assert sorted(l["criterion_id"] for l in tasks["REVERIFY1"]["criteria"]) == sorted(crit_ids.values())

    # 수정 실행의 입력 — 검증 보고(핵심)와 미충족 블록.
    refs = h.client.get(f"/api/runs/{fix['run_id']}/context-refs").json()
    report = [r for r in refs if r["role"] == "verification_report"]
    assert [(r["artifact_id"], r["tier"]) for r in report] == [(t2["output_artifact_id"], "core")]
    assert report[0]["receipt_status"] == "read"
    prompt = _prompt_for(h, fix["run_id"])
    assert "--- 검증이 보고한 미충족 ---" in prompt and "C-02: 로컬 경로 시험 실패" in prompt
    assert t2["run_id"] in prompt and "약하게" in prompt
    # T1 을 처음 돌릴 때는 미충족이 없었다 — 그 실행에는 검증 보고가 없다.
    t1 = next(r for r in runs if r["task_id"] == "T1")
    assert not [r for r in h.client.get(f"/api/runs/{t1['run_id']}/context-refs").json() if r["role"] == "verification_report"]

    crits = _crits(h, case_id)
    assert (crits["C-02"]["verdict"], crits["C-02"]["evidence_run_id"]) == ("met", reverify["run_id"])
    events = conv["progress"]["events"]
    opened = [e for e in events if e["action"] == "remediation_opened"]
    assert len(opened) == 1 and "FIX1" in opened[0]["detail"] and opened[0]["codes"] == ["C-02"]


def test_the_cycle_repeats_within_the_limit_then_waits_with_its_history_and_raising_it_goes_on(processing_harness):
    """AC-8 — 재검증도 미충족이면 다음 차수(FIX2·REVERIFY2), 한도(여기서는 1) 뒤 `criteria_unresolved` 대기에 사용/한도·
    이력·후보가 실린다. 한도를 올리면(설정 변경 → 진행기) 한 번 더 돌고, 이번에 충족되면 자동 완료한다. 사용 수는 새
    리비전으로 초기화되지 않는다."""
    h = processing_harness
    _project, case_id, _request_id = _start(h)
    _set_limits(h, case_id, remediation_limit=1)
    _drive(h, case_id)
    _agree(h, case_id)
    executor = h.agent.cli_executor
    executor.verification_response = VERIFICATION_ONE_FAILS
    contents = iter(f"def read(path):\n    return {n}\n" for n in range(1, 10))
    last_impls = {"n": 0}

    def adjust() -> None:
        impl = [r for r in _runs(h, case_id) if r["purpose"] == "feature_implementation"]
        if len(impl) != last_impls["n"]:
            last_impls["n"] = len(impl)
            executor.write_files = {"reader.py": next(contents)}

    conv = _run_until_stop(h, case_id, adjust)
    assert _wait_codes(conv) == ["criteria_unresolved"], conv["progress"]
    wait = conv["progress"]["wait"][0]
    remediation = wait["remediation"]
    assert (remediation["status"], remediation["used"], remediation["limit"]) == ("exhausted", 1, 1)
    assert remediation["limit_source"] == "case_setting" and remediation["candidates"] == ["C-02"]
    assert [(e["cycle"], e["tasks"]) for e in remediation["history"]] == [(1, ["FIX1", "REVERIFY1"])]
    assert [c["key"] for c in wait["criteria"]] == ["C-02"]

    # 한도를 올리면 한 번 더 — 이번에는 재검증이 충족을 보고한다.
    executor.verification_response = FAKE_VERIFICATION_RESPONSE
    _set_limits(h, case_id, remediation_limit=2)
    conv = _run_until_stop(h, case_id, adjust)
    assert conv["progress"]["state"] == "done", conv["progress"]
    tasks = [r["task_id"] for r in _runs(h, case_id) if r["purpose"] in ("feature_implementation", "verification_run")]
    assert tasks == ["T1", "T2", "FIX1", "REVERIFY1", "FIX2", "REVERIFY2"]
    sources = [r["source"] for r in reversed(_revisions(h, case_id))]
    assert sources == ["plan_artifact", "progressor_remediation", "progressor_remediation"]
    assert h.client.get(f"/api/cases/{case_id}").json()["result"]["closure"]["closure_kind"] == "completed"


def test_unverified_or_command_less_not_met_does_not_open_a_cycle(processing_harness):
    """AC-9 — `unverified`(확인 못 함 — 구현 결함이 아니다)와 요약 없는 `not_met`(근거 없음)은 사이클을 열지 않는다.
    사람 카드에 이유가 실리고 작업 그래프는 계획 그대로다."""
    for response, verdict, reason in (
        (VERIFICATION_UNVERIFIED, "unverified", "unverified"),
        (VERIFICATION_NOT_MET_NO_SUMMARY, "not_met", "no_summary"),
    ):
        h = processing_harness
        _project, case_id, _request_id = _start(h)
        _drive(h, case_id)
        _agree(h, case_id)
        h.agent.cli_executor.verification_response = response
        conv = _drive(h, case_id, polls=30)
        assert _wait_codes(conv) == ["criteria_unresolved"], conv["progress"]
        remediation = conv["progress"]["wait"][0]["remediation"]
        assert remediation["status"] == "not_applicable" and remediation["used"] == 0
        assert remediation["excluded"] == [{"key": "C-02", "verdict": verdict, "reason": reason}]
        assert [r["source"] for r in _revisions(h, case_id)] == ["plan_artifact"]
        assert _crits(h, case_id)["C-02"]["verdict"] == verdict


def test_a_limit_of_zero_turns_the_cycle_off(processing_harness):
    """AC-8 — 한도 0 은 사이클을 열지 않고 바로 사람 카드(`off`)다. 프로젝트 기본값으로도 같다."""
    h = processing_harness
    project, case_id, _request_id = _start(h)
    _set_limits(h, case_id, remediation_limit=0)
    _drive(h, case_id)
    _agree(h, case_id)
    h.agent.cli_executor.verification_response = VERIFICATION_ONE_FAILS
    conv = _drive(h, case_id, polls=30)
    assert _wait_codes(conv) == ["criteria_unresolved"]
    remediation = conv["progress"]["wait"][0]["remediation"]
    assert (remediation["status"], remediation["used"], remediation["limit"]) == ("off", 0, 0)
    assert [r["source"] for r in _revisions(h, case_id)] == ["plan_artifact"]
    # 조회의 키별 범위 — 제한 시간은 초 10~86400, 수정 사이클은 0~10.
    limits = h.client.get(f"/api/cases/{case_id}/progress").json()["limits"]
    assert limits["ranges"]["remediation_limit"] == {"min": 0, "max": 10}
    assert limits["ranges"]["run_timeout_seconds"] == {"min": 10, "max": 86400}
    assert json.dumps(limits["remediation_limit"]["setting"]["limit_value"]) == "0"
