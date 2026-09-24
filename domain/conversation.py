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

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from domain.models import (
    LOCKING_REQUEST_STATES,
    CaseProfile,
    CaseStage,
    ConversationRefusal,
    CriterionObligation,
    InterpretationKind,
    InterpretationRefusal,
    InterpretationStatus,
    MessageReceipt,
    RequestOutcomeReason,
    RequestSettleOutcome,
    RequestState,
    RunOutcome,
    RunStatus,
    StageSource,
)
from domain.run_control import execution_unconfirmed


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
    """일반 전송을 지금 받을 수 있는가. 화면과 서버가 같은 값을 본다.

    `refusal` 은 대표 사유이고 `refusals` 는 **지금 걸리는 사유 전부**다(UI-02). 요청 처리
    중이면서 PC 도 미연결이면 둘 다 풀려야 보낼 수 있다.
    """

    allowed: bool
    refusal: ConversationRefusal | None
    detail: str
    active_request_id: str | None
    refusals: tuple[ConversationRefusal, ...] = ()
    #: P4-05. 열려 있어도 **무엇으로** 열렸는지(종료 뒤 설명 전용). 없으면 일반 전송이다.
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "refusal": self.refusal.value if self.refusal else None,
            "refusals": [r.value for r in (self.refusals or ((self.refusal,) if self.refusal else ()))],
            "detail": self.detail,
            "active_request_id": self.active_request_id,
            "note": self.note,
        }


#: P4-05. 종료 Case 의 일반 전송이 열린 이유. 화면이 이 값을 보고 "설명만"을 말한다.
EXPLANATION_ONLY_NOTE = "explanation_only"


def general_send_state(
    case_closed: bool,
    active_request: dict[str, Any] | None,
    runner_disconnected: bool = False,
    explanation_allowed: bool = False,
) -> SendState:
    """일반·정정 메시지를 지금 받을 수 있는가(D-70·D-75·FR-11).

    **대기열이 없다.** 막힌 전송은 거부이며 나중에 자동으로 보내지지 않는다. 사용자의
    초안은 사용자에게 남는다(D-83 은 UI-03 이 연결한다).

    `runner_disconnected` 는 원문을 저장할 PC 가 미연결이라는 판단이다(UI-02). 요청 잠금과
    함께 걸리면 둘 다 사유로 남는다.

    `explanation_allowed` 는 P4-05 의 **종료 뒤 설명 전용 진입**(D-87)이다. 종료 Case 의 일반
    메시지는 기존 결과·근거의 설명 응답만 받고, 수정 요청은 연결된 새 대화로 옮겨진다. 그 사실을
    `note` 로 함께 준다 — 열린 것이 "업무 재개"로 보이지 않게.
    """
    if case_closed and not explanation_allowed:
        return SendState(
            False,
            ConversationRefusal.CASE_ALREADY_CLOSED,
            "종료된 업무다. 실제 수정은 연결된 새 업무로 한다",
            None,
        )
    reasons: list[tuple[ConversationRefusal, str]] = []
    active_id = active_request["id"] if active_request is not None else None
    if active_request is not None:
        state = RequestState(active_request["state"])
        if state is RequestState.UNKNOWN:
            reasons.append(
                (
                    ConversationRefusal.REQUEST_STATE_UNKNOWN,
                    "현재 요청의 실행 상태를 확인하지 못했다. 확인 전에는 새 요청을 받지 않는다",
                )
            )
        elif active_request.get("stop_requested_at"):
            reasons.append(
                (
                    ConversationRefusal.REQUEST_STOP_REQUESTED,
                    "중단을 요청했다. 관련 실행이 실제로 끝난 것을 확인하면 다시 보낼 수 있다",
                )
            )
        else:
            reasons.append(
                (
                    ConversationRefusal.REQUEST_IN_PROGRESS,
                    "현재 요청을 처리하고 있다. 초안은 편집할 수 있고 질문 카드에는 답할 수 있다",
                )
            )
    if runner_disconnected:
        reasons.append(
            (
                ConversationRefusal.RUNNER_DISCONNECTED,
                "원문을 저장할 PC 가 연결돼 있지 않다. 입력은 그대로 두고 연결되면 직접 보낸다",
            )
        )
    if not reasons:
        if case_closed:
            return SendState(
                True,
                None,
                "종료된 업무다. 기존 결과·근거의 설명만 답하고, 실제 수정 요청은 연결된 새"
                " 대화로 옮긴다",
                None,
                note=EXPLANATION_ONLY_NOTE,
            )
        return SendState(True, None, "보낼 수 있다", None)
    return SendState(
        False,
        reasons[0][0],
        " · ".join(detail for _code, detail in reasons),
        active_id,
        tuple(code for code, _detail in reasons),
        note=EXPLANATION_ONLY_NOTE if case_closed else None,
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
    stop_requested: bool = False,
) -> SettleDecision:
    """처리 중인 요청을 어떤 상태로 끝낼 수 있는가.

    순서가 판정의 일부다.

    1. **중단이 요청됐으면 거부한다**(UI-02). 끝내는 것은 실제 종료를 확인한 제어부다 —
       실행이 남아 있든 아니든 처리하는 쪽이 할 일이 없다는 답이 먼저다.
    2. **끝나지 않은 실행이 있으면 거부한다.** 요청을 끝내면 잠금이 풀리므로, 실행이
       아직 돌고 있는데 새 일반 전송을 받게 된다 — Run 사이에 잠금을 푸는 것과 같다.
    3. **실제로 끝났는지 모르는 실행이 있으면 `unknown` 이다.** 요청한 결과가 `failed`
       여도 그렇다. 모르는 실행을 실패로 적으면 잠금이 풀리고, 그 실행이 아직 무엇을
       쓰고 있을지 모르는 채로 새 요청이 열린다(D-76). 결과 `unknown`·`cancelled` 이면서
       잔류 활동을 확인하지 못한 실행이다(`domain.run_control.execution_unconfirmed`).
    4. **결과를 모르지만 끝난 것은 확인한 실행이 있으면 `interrupted` 다**(UI-02). 완료로도
       실패로도 적지 않는다 — 결과를 모른다는 사실이 남는다.
    5. **`completed` 는 여는 메시지가 저장됐을 때만이다.** 받지 않은 말을 처리했다고
       적지 않는다. `failed` 는 막지 않는다 — 처리하지 못했다는 사실은 적을 수 있다.
    """
    runs = list(runs)
    if stop_requested:
        return SettleDecision(
            ConversationRefusal.REQUEST_STOP_REQUESTED,
            "중단이 요청된 요청이다. 관련 실행의 실제 종료를 확인한 제어부가 끝낸다",
        )
    unfinished = [r for r in runs if r.get("status") != RunStatus.FINISHED.value]
    if unfinished:
        return SettleDecision(
            ConversationRefusal.REQUEST_RUNS_UNFINISHED,
            "이 요청에 연결된 실행이 아직 끝나지 않았다: "
            + ", ".join(r["run_id"] for r in unfinished),
        )
    unconfirmed = [r for r in runs if execution_unconfirmed(r)]
    if unconfirmed:
        outcome_unknown = any(r.get("outcome") == RunOutcome.UNKNOWN.value for r in unconfirmed)
        return SettleDecision(
            None,
            "연결된 실행 중 실제로 끝났는지 모르는 것이 있다. 확인 전에는 잠금을 풀지 않는다",
            RequestState.UNKNOWN,
            RequestOutcomeReason.RUN_OUTCOME_UNKNOWN
            if outcome_unknown
            else RequestOutcomeReason.RUN_RESIDUAL_UNCONFIRMED,
        )
    if any(r.get("outcome") == RunOutcome.UNKNOWN.value for r in runs):
        return SettleDecision(
            None,
            "결과를 모르는 실행이 있지만 그 실행이 끝난 것은 확인했다. 완료·실패로 적지 않는다",
            RequestState.INTERRUPTED,
            RequestOutcomeReason.EXECUTION_ENDED_RESULT_UNKNOWN,
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


# ================================================================ UI-03 요청 처리기
#
# 요청을 처리하는 쪽이 사람·하네스에서 제어부의 처리기로 옮겨 왔다. 처리기는 **읽기 전용
# 논의 응답 하나**를 만들고 그 결과로 요청을 끝낸다. 판정은 여기 둔다 — 처리기의 실시간
# 경로와 기동 복구가 같은 답을 내야 한다.


def processor_settle_outcome(
    reply_outcome: str | None, reply_message_attached: bool
) -> RequestSettleOutcome:
    """처리기가 끝내는 요청에 **무엇을 요청하는가.**

    응답 실행이 완료됐고 그 응답이 AI 메시지로 대화에 붙었을 때만 `completed` 다. 붙지
    않았으면 사람은 답을 받지 못했다 — 처리했다고 적지 않는다. 결과를 모르는 실행은 이
    요청을 받은 `decide_settle` 이 `unknown`·`interrupted` 로 바꾼다(UI-02 그대로).
    """
    if reply_outcome == RunOutcome.COMPLETED.value and reply_message_attached:
        return RequestSettleOutcome.COMPLETED
    return RequestSettleOutcome.FAILED


#: 논의 응답 끝에 AI 가 두는 기계용 블록의 이름(```hads-interpretation ... ```).
INTERPRETATION_FENCE = "hads-interpretation"

_INTERPRETATION_BLOCK = re.compile(
    r"```[ \t]*" + re.escape(INTERPRETATION_FENCE) + r"[ \t]*\r?\n(.*?)```",
    re.DOTALL,
)


@dataclass(frozen=True)
class Interpretation:
    """AI 가 사용자의 마지막 메시지를 어떻게 읽었는가(D-69). **본문을 담지 않는다.**"""

    status: InterpretationStatus
    kind: InterpretationKind | None = None
    profile: CaseProfile | None = None
    detail: str = ""
    #: UI-04c(D-86). `profile_change` 가 더하는 목적 의무(열거값). 없으면 빈 튜플이다.
    objectives: tuple[str, ...] = ()
    #: P4-09(g), D-93. 응답이 함께 낸 대화 제목(공백 정리 뒤 40자 초과는 잘린 짧은 값). 본문이 아니다. 없으면 None.
    title: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"status": self.status.value}
        if self.kind is not None:
            out["kind"] = self.kind.value
        if self.profile is not None:
            out["profile"] = self.profile.value
        if self.objectives:
            out["objectives"] = list(self.objectives)
        if self.title:
            out["title"] = self.title
        if self.detail:
            out["detail"] = self.detail[:200]
        return out


#: P4-09(g), D-93. 자동 제목의 상한(문자). 더 길면 자른다 — 형식 오류로 만들지 않는다(제목은 표시값이다).
TITLE_MAX_CHARS = 40


def normalize_title(value: Any) -> str | None:
    """해석 블록의 `title` 을 짧은 표시값으로 만든다. 비어 있거나 문자열이 아니면 None."""
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    if not text:
        return None
    return text[:TITLE_MAX_CHARS]


def parse_interpretation(value: Any) -> Interpretation:
    """해석 값 하나를 검사한다. Runner 가 블록에서 읽은 것과 제어부가 받은 보고에 같이 쓴다.

    `work_request` 는 **여섯 Profile 중 하나**를 가져야 한다. Profile 없는 업무 요청은 무엇을
    열지 모르므로 형식 오류다 — 모르는 것을 논의로 바꿔 읽지 않고 `invalid` 로 남긴다.
    """
    if not isinstance(value, dict):
        return Interpretation(InterpretationStatus.INVALID, detail="not an object")
    try:
        kind = InterpretationKind(value.get("kind"))
    except ValueError:
        return Interpretation(InterpretationStatus.INVALID, detail="unknown kind")
    title = normalize_title(value.get("title"))
    if kind is InterpretationKind.DISCUSSION:
        return Interpretation(InterpretationStatus.REPORTED, kind, title=title)
    try:
        profile = CaseProfile(value.get("profile"))
    except ValueError:
        return Interpretation(
            InterpretationStatus.INVALID,
            kind,
            detail=f"{kind.value} needs one of the six profiles",
        )
    # UI-04c(D-86). 목적 변경은 더하는 목적 의무를 함께 적을 수 있다. **모르는 의무 이름은 형식
    # 오류다** — 조용히 버리면 그 목적이 사라진 채 개정된다.
    objectives: list[str] = []
    raw = value.get("objectives")
    if raw is not None:
        if not isinstance(raw, list):
            return Interpretation(InterpretationStatus.INVALID, kind, detail="objectives is not a list")
        for item in raw:
            try:
                name = CriterionObligation(str(item)).value
            except ValueError:
                return Interpretation(
                    InterpretationStatus.INVALID, kind, detail=f"unknown objective: {item!s}"[:200]
                )
            if name not in objectives:
                objectives.append(name)
    return Interpretation(
        InterpretationStatus.REPORTED, kind, profile, objectives=tuple(objectives), title=title
    )


def interpretation_from_report(report: Any) -> Interpretation:
    """Runner 가 결과에 실어 보낸 해석을 읽는다(제어부).

    `reported` 는 값을 다시 검사한다 — Runner 의 판정을 그대로 믿으면 형식이 틀린 해석이
    업무화를 연다. `missing`·`invalid` 는 그대로 남긴다(모른다는 사실이 기록이다).
    """
    if not isinstance(report, dict):
        return Interpretation(InterpretationStatus.INVALID, detail="not an object")
    try:
        status = InterpretationStatus(report.get("status"))
    except ValueError:
        return Interpretation(InterpretationStatus.INVALID, detail="unknown status")
    if status is InterpretationStatus.MISSING:
        return Interpretation(InterpretationStatus.MISSING)
    if status is InterpretationStatus.INVALID:
        try:
            kind = InterpretationKind(report.get("kind")) if report.get("kind") else None
        except ValueError:
            kind = None
        return Interpretation(
            InterpretationStatus.INVALID, kind, detail=str(report.get("detail") or "")[:200]
        )
    return parse_interpretation(report)


def split_interpretation(final_message: str) -> tuple[str, Interpretation]:
    """응답 글에서 해석 블록을 **떼어 낸다.** (사람이 읽을 글, 해석)

    블록은 기계용이다 — 대화에 AI 의 말로 붙는 것은 나머지 글뿐이다. 블록이 없으면
    `missing`, 형식이 틀리거나 **둘 이상이면** `invalid` 다(어느 쪽이 AI 의 판단인지 모른다).
    어떤 경우에도 글은 남는다 — 해석이 실패했다고 응답을 지우지 않는다.
    """
    blocks = list(_INTERPRETATION_BLOCK.finditer(final_message))
    if not blocks:
        return final_message.strip(), Interpretation(InterpretationStatus.MISSING)
    text = _INTERPRETATION_BLOCK.sub("", final_message).strip()
    if len(blocks) > 1:
        return text, Interpretation(InterpretationStatus.INVALID, detail="more than one block")
    try:
        value = json.loads(blocks[0].group(1))
    except ValueError:
        return text, Interpretation(InterpretationStatus.INVALID, detail="block is not JSON")
    return text, parse_interpretation(value)


def interpretation_refusal(
    interpretation: Interpretation, reply_outcome: str | None
) -> InterpretationRefusal | None:
    """이 해석으로 **업무화를 시도하는가.** 시도하지 않는 이유를 돌려준다(없으면 시도한다).

    업무화 자체의 조건(준비 단계·처리 중 요청·저장된 메시지)은 `start_work` 가 본다 — 두
    곳에 쓰지 않는다. 여기서는 해석과 응답의 조건만 본다.
    """
    if interpretation.status is not InterpretationStatus.REPORTED:
        return InterpretationRefusal.NOT_REPORTED
    # UI-04c. `profile_change`(업무 단계의 목적·유형 변경, D-86)도 시도한다 — 그 조건(업무 단계·
    # 저장된 메시지·완료된 실행)은 `revise_profile` 이 본다.
    if interpretation.kind not in (
        InterpretationKind.WORK_REQUEST,
        InterpretationKind.PROFILE_CHANGE,
    ):
        return InterpretationRefusal.NOT_A_WORK_REQUEST
    if reply_outcome != RunOutcome.COMPLETED.value:
        return InterpretationRefusal.REPLY_NOT_COMPLETED
    return None
