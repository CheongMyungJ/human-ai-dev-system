"""UI-04c — 실행시간 합계(D-88)의 계측 결함 수정(plans/UI-PLAN-04c.md AC-11).

지표는 새로 만들지 않았다 — `execution_seconds` 는 실행별 배정~종료의 합계이고 `elapsed_seconds` 는 Case 시계다.
이 파일이 지키는 것은 **재배정 뒤 옛 세대의 시간 행이 벽시계로 영원히 자라지 않는다**이다. 재배정 시점까지
관측한 값으로 `unresolved`(`reassigned`)가 되고, 풀지 않는다(과대 쪽 그대로, P3-R3 7절). v26 이전에 열린 채 남은
옛 세대 행은 노출에 시간을 더하지 않고 "모른다" 로 센다.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from domain.budget import RESERVATION_REASON
from domain.models import BudgetMetric
from tests.test_budget import _analysis_case, _budget, _set_assigned_at


def _ago(seconds: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _reservations(harness, case_id: str, run_id: str) -> dict[tuple[int, str], dict]:
    return {
        (r["generation"], r["metric"]): r
        for r in _budget(harness, case_id)["reservations"]
        if r["run_id"] == run_id
    }


def test_the_reason_texts_say_what_the_time_metrics_are():
    """AC-10 — 지표의 뜻은 서버가 말한다(화면이 지어내지 않는다). 실행시간 합계의 정의와 경과시간의 자리."""
    execution = RESERVATION_REASON[BudgetMetric.EXECUTION_SECONDS]
    assert "초 단위로" in execution and "배정~종료" in execution and "병렬" in execution and "D-88" in execution
    assert "별도 선택" in RESERVATION_REASON[BudgetMetric.ELAPSED_SECONDS]


def test_a_reassigned_generation_stops_growing_and_stays_unresolved(harness):
    """AC-11 — 재배정하면 옛 세대의 시간 행은 그때까지 관측한 값으로 `unresolved`/`reassigned` 가 되고 더 자라지
    않는다. 실행 수 행도 예약값 그대로 `unresolved` 다(공짜가 아니다). 새 세대는 정상 정산된다."""
    case, artifact = _analysis_case(harness)
    harness.create_run(case["id"], artifact, run_id="run-time-1")
    _set_assigned_at(harness, "run-time-1", _ago(30))  # 옛 세대가 30초 전에 배정됐다(관측 기록)
    usage = _budget(harness, case["id"])["usage"]["execution_seconds"]
    assert 29 <= usage["held"] <= 40 and usage["exposure"] == usage["held"]

    bumped = harness.client.post("/api/runs/run-time-1/reassign", json={})
    assert bumped.status_code in (200, 201), bumped.text
    rows = _reservations(harness, case["id"], "run-time-1")
    old_time = rows[(1, "execution_seconds")]
    assert (old_time["state"], old_time["settle_source"]) == ("unresolved", "reassigned")
    assert 29 <= old_time["actual_value"] <= 40
    old_count = rows[(1, "run_count")]
    assert (old_count["state"], old_count["settle_source"], old_count["actual_value"]) == ("unresolved", "reassigned", 1.0)
    assert rows[(2, "execution_seconds")]["state"] == "held" and rows[(2, "run_count")]["state"] == "held"

    usage = _budget(harness, case["id"])["usage"]
    assert usage["run_count"]["exposure"] == 2.0  # 재배정은 새 소비다(P3-R3 그대로)
    time_usage = usage["execution_seconds"]
    assert time_usage["held"] == 0.0  # 새 세대는 아직 배정 전 — 0 은 관측 사실이다
    assert 29 <= time_usage["unresolved"] <= 40 and time_usage["complete"] is False

    # 새 세대가 배정된 뒤 벽시계가 흘러도 옛 세대의 값은 그대로다 — 자라는 것은 새 세대의 관측뿐이다.
    _set_assigned_at(harness, "run-time-1", _ago(10))
    later = _budget(harness, case["id"])["usage"]["execution_seconds"]
    assert later["unresolved"] == time_usage["unresolved"]
    assert 9 <= later["held"] <= 20
    assert _reservations(harness, case["id"], "run-time-1")[(1, "execution_seconds")]["actual_value"] == old_time["actual_value"]

    # 새 세대의 정산 — 결과가 오면 새 세대 행만 확정되고 옛 세대 행은 `unresolved` 그대로다.
    harness.agent.poll_once()
    rows = _reservations(harness, case["id"], "run-time-1")
    assert rows[(2, "run_count")]["state"] == "settled"
    assert rows[(1, "execution_seconds")]["state"] == "unresolved"
    final = _budget(harness, case["id"])["usage"]["execution_seconds"]
    assert final["unresolved"] == time_usage["unresolved"] and final["runs_unknown"] >= 1


def test_a_stale_generation_left_open_by_an_old_database_does_not_add_wall_clock(harness):
    """AC-11 — v26 이전에 재배정된 실행의 옛 세대 `held` 행(재배정이 닫지 않던 시절)은 노출에 새 세대의 시각을 타고
    자라는 시간을 더하지 않는다. "모른다" 로 세고 예약값은 그대로 둔다."""
    case, artifact = _analysis_case(harness)
    harness.create_run(case["id"], artifact, run_id="run-stale-1")
    conn = sqlite3.connect(harness.controller_config.db_path)
    try:
        conn.execute("UPDATE run SET assignment_generation = 2, assigned_at = ? WHERE run_id = ?", (_ago(600), "run-stale-1"))
        # 옛 DB 의 모양: 세대 1 의 행이 `held` 로 남아 있고 세대 2 의 행은 없다.
        conn.commit()
    finally:
        conn.close()
    usage = _budget(harness, case["id"])["usage"]
    time_usage = usage["execution_seconds"]
    assert time_usage["held"] == 0.0 and time_usage["unresolved"] == 0.0  # 600 초를 더하지 않는다
    assert time_usage["runs_unknown"] == 1 and time_usage["complete"] is False
    count = usage["run_count"]
    assert count["unresolved"] == 1.0 and count["held"] == 0.0 and count["runs_unknown"] == 1
