"""입력·실행 제어의 순수 규칙(UI-02).

`domain/conversation.py` 와 같은 이유로 DB 를 모르는 함수로 둔다 — 화면이 보는 판정과
서버가 적용하는 판정, 재시작 뒤 대조가 내리는 판정이 **같은 함수**에서 나와야 한다.

세 가지를 정한다.

    실행이 **실제로** 끝났는가     결과(`outcome`)와 다른 축이다. 결과를 몰라도 끝난 것은
                                  확인할 수 있고, 결과를 알아도 트리가 끝났는지는 모를 수 있다
    PC 가 연결돼 있는가            heartbeat 에서 도출한다(D-75). 저장하지 않는다
    요청을 제어부가 끝낼 수 있는가  중단 요청 뒤, 또는 `unknown` 이 확인으로 풀릴 때(D-76)
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from domain.models import (
    CONFIRMING_RESIDUAL_BASES,
    RequestOutcomeReason,
    RequestState,
    ResidualBasis,
    RunExecutionState,
    RunnerConnection,
    RunOutcome,
    RunStatus,
)

#: PC 미연결로 보는 heartbeat 공백의 기본값(초). 상세 설계 제안값이며 사용자 결정이 아니다.
DEFAULT_RUNNER_STALE_SECONDS = 15.0

#: 결과가 이것이면 **실행이 정상적으로 끝나지 않았다.** 잔류를 확인해야 끝난 것으로 본다.
INTERRUPTED_OUTCOMES = frozenset({RunOutcome.UNKNOWN.value, RunOutcome.CANCELLED.value})


def _parse(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


# ============================================================ 잔류·실행 상태


def residual_claim_valid(residual: str, basis: str | None) -> bool:
    """`none` 은 확인 근거가 있을 때만 받는다. 근거 없는 `none` 은 확인이 아니다."""
    if residual != "none":
        return residual == "unknown"
    if basis is None:
        # 근거를 보내지 않는 Runner(UI-02 이전)의 `none`. 기존 계약 그대로 받는다 —
        # 골격 실행기는 자식 프로세스를 만들지 않아 `none` 이 정확했다.
        return True
    try:
        return ResidualBasis(basis) in CONFIRMING_RESIDUAL_BASES
    except ValueError:
        return False


def effective_residual(run: dict[str, Any]) -> str:
    """유효 잔류 = 가장 최근 관측, 없으면 결과 보고 값. **원래 보고를 고쳐 쓰지 않는다.**"""
    observed = run.get("residual_observed")
    if observed in ("none", "unknown"):
        return observed
    return run.get("residual_activity") or "unknown"


def execution_confirmed_ended(run: dict[str, Any]) -> bool:
    """이 실행이 **실제로 끝났음**을 확인했는가."""
    if run.get("status") != RunStatus.FINISHED.value:
        return False
    if run.get("not_started_reason"):
        return True
    return effective_residual(run) == "none"


def execution_unconfirmed(run: dict[str, Any]) -> bool:
    """요청을 잠그는 실행 — 정상적으로 끝나지 않았고(`unknown`·`cancelled`) 트리가 끝났는지 모른다.

    **정상 종료(`completed`·`failed`) 실행의 잔류 `unknown` 은 여기 들지 않는다**(UI-01 규칙
    유지). 지금까지의 모든 실제 CLI 실행이 그 값이고, 소급해 잠그지 않는다.
    """
    if run.get("status") != RunStatus.FINISHED.value:
        return False
    if run.get("not_started_reason"):
        return False
    return run.get("outcome") in INTERRUPTED_OUTCOMES and effective_residual(run) != "none"


def run_execution_state(
    run: dict[str, Any],
    *,
    runner_connected: bool | None,
    now: datetime | None = None,
    stale_seconds: float = DEFAULT_RUNNER_STALE_SECONDS,
) -> RunExecutionState:
    """실행의 지금 상태. **결과가 아니라 실행이 살아 있는가·끝났는가**다."""
    status = run.get("status")
    if status == RunStatus.PENDING.value:
        return RunExecutionState.PENDING
    if status != RunStatus.FINISHED.value:
        seen = _parse(run.get("liveness_at"))
        now = now or datetime.now(timezone.utc)
        fresh = seen is not None and now - seen <= timedelta(seconds=stale_seconds)
        return (
            RunExecutionState.EXECUTING
            if runner_connected and fresh
            else RunExecutionState.UNCONFIRMED
        )
    return (
        RunExecutionState.ENDED
        if execution_confirmed_ended(run)
        else RunExecutionState.ENDED_UNCONFIRMED
    )


# =================================================================== PC 연결


def runner_connection(
    runner: dict[str, Any] | None,
    *,
    now: datetime | None = None,
    stale_seconds: float = DEFAULT_RUNNER_STALE_SECONDS,
    basis: str = "",
) -> dict[str, Any]:
    """PC 연결 상태. `basis` 는 **왜 이 Runner 로 판단했는가**다(화면에 그대로 보인다)."""
    if runner is None:
        return {
            "state": RunnerConnection.NOT_DETERMINED.value,
            "runner_id": None,
            "last_seen_at": None,
            "stale_after_seconds": stale_seconds,
            "basis": basis or "no_runner",
        }
    seen = _parse(runner.get("last_heartbeat_at"))
    now = now or datetime.now(timezone.utc)
    if seen is None:
        state = RunnerConnection.NEVER_SEEN
    elif now - seen <= timedelta(seconds=stale_seconds):
        state = RunnerConnection.CONNECTED
    else:
        state = RunnerConnection.DISCONNECTED
    return {
        "state": state.value,
        "runner_id": runner.get("id"),
        "last_seen_at": runner.get("last_heartbeat_at"),
        "stale_after_seconds": stale_seconds,
        "basis": basis,
    }


def connection_refuses(connection: dict[str, Any] | None) -> bool:
    """이 연결 상태에서 사용자 입력을 거부하는가. 정할 수 없는 상태는 거부 근거가 아니다."""
    if connection is None:
        return False
    return connection["state"] in (
        RunnerConnection.DISCONNECTED.value,
        RunnerConnection.NEVER_SEEN.value,
    )


# ======================================================= 제어부가 끝내는 요청


def system_settlement(
    runs: Iterable[dict[str, Any]],
    *,
    state: str,
    stop_requested: bool,
) -> tuple[RequestState, RequestOutcomeReason] | None:
    """제어부가 **스스로** 요청을 끝내거나 옮길 수 있는가. `None` 이면 지금은 아니다.

    제어부가 끝내는 경우는 둘뿐이다(D-76).

    1. **중단이 요청된 처리 중 요청.** 연결 실행이 전부 끝나면 확인된 것은 `interrupted`,
       확인되지 않은 것이 있으면 `unknown`(잠금).
    2. **`unknown` 요청.** 확인되지 않던 실행이 전부 확인되면 `interrupted`.

    처리 중이고 중단 요청이 없으면 끝내는 것은 처리하는 쪽이다(UI-01) — `None`.
    """
    runs = list(runs)
    if any(r.get("status") != RunStatus.FINISHED.value for r in runs):
        return None
    current = RequestState(state)
    if current is RequestState.PROCESSING and not stop_requested:
        return None
    if current not in (RequestState.PROCESSING, RequestState.UNKNOWN):
        return None
    unconfirmed = [r for r in runs if execution_unconfirmed(r)]
    if unconfirmed:
        if current is RequestState.UNKNOWN:
            return None  # 그대로 잠긴다
        reason = (
            RequestOutcomeReason.RUN_OUTCOME_UNKNOWN
            if any(r.get("outcome") == RunOutcome.UNKNOWN.value for r in unconfirmed)
            else RequestOutcomeReason.RUN_RESIDUAL_UNCONFIRMED
        )
        return RequestState.UNKNOWN, reason
    if stop_requested:
        return RequestState.INTERRUPTED, RequestOutcomeReason.STOPPED_BY_REQUEST
    return RequestState.INTERRUPTED, RequestOutcomeReason.EXECUTION_ENDED_RESULT_UNKNOWN


def interruption_summary(runs: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """중단·불명 요청의 **사실 요약**(D-76). 문장이 아니라 수와 식별자다.

    완료한 부분·남은 변경·결과를 모르는 것·시작하지 않은 것을 나눈다. 작업공간 변화는
    실행 전후 대조가 있는 실행만 센다 — 관측하지 않은 실행을 "변경 없음"으로 세지 않는다.
    """
    runs = list(runs)
    by_outcome: dict[str, int] = {}
    changed: list[str] = []
    unobserved: list[str] = []
    not_started: list[str] = []
    result_unknown: list[str] = []
    unconfirmed: list[str] = []
    cumulative_files: int | None = None
    for run in runs:
        rid = run.get("run_id")
        if run.get("not_started_reason"):
            not_started.append(rid)
            continue
        outcome = run.get("outcome") or "unfinished"
        by_outcome[outcome] = by_outcome.get(outcome, 0) + 1
        if outcome == RunOutcome.UNKNOWN.value:
            result_unknown.append(rid)
        if execution_unconfirmed(run) or run.get("status") != RunStatus.FINISHED.value:
            unconfirmed.append(rid)
        effect = run.get("workspace_effect")
        if isinstance(effect, dict):
            if effect.get("changed"):
                changed.append(rid)
            files = effect.get("files_changed")
            if isinstance(files, int):
                # 누적 수다. 가장 최근 관측이 지금 작업공간의 모습이다.
                cumulative_files = files
        elif run.get("permission") in ("workspace_write", "explicit_escalated"):
            unobserved.append(rid)
    return {
        "runs": len(runs),
        "by_outcome": by_outcome,
        "not_started": not_started,
        "result_unknown": result_unknown,
        "execution_unconfirmed": unconfirmed,
        "workspace_changed_by": changed,
        "workspace_unobserved": unobserved,
        "workspace_files_changed_cumulative": cumulative_files,
        "detail": (
            "중단은 취소 성공이나 롤백이 아니다. 이미 만든 변경·출력·사용량은 남아 있다"
        ),
    }
