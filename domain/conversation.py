"""대화·요청의 순수 규칙(UI-01).

**판정이 한 곳에 있어야 한다.** 전송 가능 여부는 화면(비활성 표시)과 서버(거부)가 같은
답을 내야 하고, 요청 종료는 API 와 재시작 뒤의 복구가 같은 답을 내야 한다. 두 벌로
쓰면 "화면은 열렸는데 서버는 막는" 상태가 조용히 생긴다. 그래서 DB 를 모르는 함수로
둔다 — `domain/completion_meaning.py` 와 같은 방식이다.

**잠금의 단위는 요청이다**(D-70). Run 하나가 끝났다고 풀지 않고, Case 가 끝날 때까지
잠그지도 않는다. 요청이 끝나는 시점은 요청을 처리하는 쪽이 **명시적으로** 적는다 —
연결된 실행이 전부 끝났다는 사실만으로는 다음 실행을 만들기 직전인지 알 수 없기
때문이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from domain.models import (
    LOCKING_REQUEST_STATES,
    CaseStage,
    ConversationRefusal,
    MessageReceipt,
    RequestOutcomeReason,
    RequestSettleOutcome,
    RequestState,
    RunOutcome,
    RunStatus,
    StageSource,
)


# ================================================================ 단계


def derive_stage(stored: str | None, has_work_start: bool) -> tuple[CaseStage, StageSource]:
    """저장된 단계 값에서 **유효 단계와 그 출처**를 도출한다.

    NULL 은 UI-01 이전에 만든 Case 다. 그때는 목적 없이 Case 를 만들 경로가 없었으므로
    업무 단계이며, 값을 채워 넣지 않고 출처로 그 사실을 드러낸다.
    """
    if stored is None:
        return CaseStage.WORK, StageSource.CREATED_BEFORE_STAGE
    stage = CaseStage(stored)
    if stage is CaseStage.DISCUSSION:
        return stage, StageSource.CREATED_AS_DISCUSSION
    if has_work_start:
        return stage, StageSource.WORK_STARTED
    return stage, StageSource.CREATED_AS_WORK


# ================================================================ 접수


def receipt_for_intake(intake_state: str | None) -> MessageReceipt:
    """intake 상태에서 메시지 접수 상태를 도출한다.

    **`stored` 만 접수 완료다.** 중계됐다는 사실은 접수가 아니며, Runner 가 해시가 맞지
    않아 저장하지 않은 원문은 `pending` 에 머문다 — 저장되지 않은 것을 접수로 적지
    않는다(NFR-01·D-83).
    """
    if intake_state == "stored":
        return MessageReceipt.STORED
    if intake_state == "lost_before_persist":
        return MessageReceipt.LOST_BEFORE_PERSIST
    return MessageReceipt.PENDING


# ================================================================ 전송 가능


@dataclass(frozen=True)
class SendState:
    """일반 전송을 지금 받을 수 있는가. 화면과 서버가 같은 값을 본다."""

    allowed: bool
    refusal: ConversationRefusal | None
    detail: str
    active_request_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "refusal": self.refusal.value if self.refusal else None,
            "detail": self.detail,
            "active_request_id": self.active_request_id,
        }


def general_send_state(case_closed: bool, active_request: dict[str, Any] | None) -> SendState:
    """일반·정정 메시지를 지금 받을 수 있는가(D-70·FR-11).

    **대기열이 없다.** 막힌 전송은 거부이며 나중에 자동으로 보내지지 않는다. 사용자의
    초안은 사용자에게 남는다(D-83 은 UI-03 이 연결한다).
    """
    if case_closed:
        return SendState(
            False,
            ConversationRefusal.CASE_ALREADY_CLOSED,
            "종료된 업무다. 실제 수정은 연결된 새 업무로 한다",
            None,
        )
    if active_request is None:
        return SendState(True, None, "보낼 수 있다", None)
    state = RequestState(active_request["state"])
    if state is RequestState.UNKNOWN:
        return SendState(
            False,
            ConversationRefusal.REQUEST_STATE_UNKNOWN,
            "현재 요청의 실행 상태를 확인하지 못했다. 확인 전에는 새 요청을 받지 않는다",
            active_request["id"],
        )
    return SendState(
        False,
        ConversationRefusal.REQUEST_IN_PROGRESS,
        "현재 요청을 처리하고 있다. 초안은 편집할 수 있고 질문 카드에는 답할 수 있다",
        active_request["id"],
    )


def is_locking(state: str) -> bool:
    return RequestState(state) in LOCKING_REQUEST_STATES


# ================================================================ 요청 종료


@dataclass(frozen=True)
class SettleDecision:
    """요청 종료 기록의 판정. `refusal` 이 있으면 아무 것도 바꾸지 않는다."""

    refusal: ConversationRefusal | None
    detail: str
    state: RequestState | None = None
    reason: RequestOutcomeReason | None = None


def decide_settle(
    requested: RequestSettleOutcome,
    opening_receipt: MessageReceipt,
    runs: Iterable[dict[str, Any]],
) -> SettleDecision:
    """처리 중인 요청을 어떤 상태로 끝낼 수 있는가.

    순서가 판정의 일부다.

    1. **끝나지 않은 실행이 있으면 거부한다.** 요청을 끝내면 잠금이 풀리므로, 실행이
       아직 돌고 있는데 새 일반 전송을 받게 된다 — Run 사이에 잠금을 푸는 것과 같다.
    2. **결과를 모르는 실행이 있으면 `unknown` 이다.** 요청한 결과가 `failed` 여도
       그렇다. 모르는 실행을 실패로 적으면 잠금이 풀리고, 그 실행이 아직 무엇을
       쓰고 있을지 모르는 채로 새 요청이 열린다(D-76).
    3. **`completed` 는 여는 메시지가 저장됐을 때만이다.** 받지 않은 말을 처리했다고
       적지 않는다. `failed` 는 막지 않는다 — 처리하지 못했다는 사실은 적을 수 있다.
    """
    runs = list(runs)
    unfinished = [r for r in runs if r.get("status") != RunStatus.FINISHED.value]
    if unfinished:
        return SettleDecision(
            ConversationRefusal.REQUEST_RUNS_UNFINISHED,
            "이 요청에 연결된 실행이 아직 끝나지 않았다: "
            + ", ".join(r["run_id"] for r in unfinished),
        )
    if any(r.get("outcome") == RunOutcome.UNKNOWN.value for r in runs):
        return SettleDecision(
            None,
            "연결된 실행 중 결과를 모르는 것이 있다. 확인 전에는 잠금을 풀지 않는다",
            RequestState.UNKNOWN,
            RequestOutcomeReason.RUN_OUTCOME_UNKNOWN,
        )
    if requested is RequestSettleOutcome.COMPLETED and opening_receipt is not MessageReceipt.STORED:
        return SettleDecision(
            ConversationRefusal.REQUEST_ORIGINAL_NOT_STORED,
            f"요청을 연 메시지가 {opening_receipt.value} 상태다. 받지 않은 말을 처리했다고"
            " 적지 않는다",
        )
    return SettleDecision(
        None,
        "종료를 기록한다",
        RequestState(requested.value),
        RequestOutcomeReason.SETTLED,
    )


def lost_original_fails_request(
    request_state: str, opening_receipt: MessageReceipt, linked_run_count: int
) -> bool:
    """여는 메시지가 유실됐을 때 **시스템이** 요청을 실패로 닫는가.

    연결된 실행이 하나도 없을 때만이다. 실행이 있으면 그 실행이 다른 지시로 무엇을
    했을 수 있으므로 처리하는 쪽의 종료 기록을 기다린다 — 모르는 것을 닫지 않는다.
    """
    return (
        request_state == RequestState.PROCESSING.value
        and opening_receipt is MessageReceipt.LOST_BEFORE_PERSIST
        and linked_run_count == 0
    )
