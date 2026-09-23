"""요청 처리기 (UI-03, P4-05 에서 업무 단계 진행기와 이어짐).

UI-01 은 "요청을 처리하는 쪽"을 비워 두었다 — 메시지가 저장돼도 사람이 관리 화면에서 논의
응답 실행을 만들고 요청 종료를 적어야 했고, 라이브에서는 하네스가 그 자리를 채웠다. 이
모듈이 그 자리를 **제품 안에서** 채운다.

**하는 일은 좁다.** 저장된 사용자 요청마다 **읽기 전용 논의 응답 하나**를 만들고, 그 결과로
요청을 끝낸다. 준비 단계 대화의 응답은 AI 가 사용자의 마지막 메시지를 어떻게 읽었는지를
함께 보고하고, 그것이 명확한 업무 요청이면 같은 Case 에서 업무화한다(D-69).

**P4-05.** 업무화 뒤의 다음 작업은 **업무 단계 진행기**(`controller.work_progressor`)가 잇는다.
처리기는 응답이 끝난 자리에서 진행기에 넘기고, 진행기가 다음 실행을 만들면 요청을 끝내지 않는다
(실행 사이에 잠금을 풀지 않는다 — D-70). 진행기가 만들지 않으면(사람 대기·완료·막힘) 처리기가
종료를 적는다. 시스템이 연 진행 요청(여는 메시지 없음)에는 응답을 만들지 않는다.

종료 Case 의 메시지는 **설명 전용** 응답을 받는다(D-87). 그 응답의 해석이 업무 요청이면 연결된
새 대화를 만들어 그 메시지를 옮기고 거기서 처음부터 잇는다(D-33·D-78).

**하지 않는 일:**

    판정                      진입 검사·요청 종료 판정·업무화 조건은 기존 경로가 한다. 여기서는
                              순서만 정한다 — 두 곳에서 판정하면 한쪽만 고치는 실수가 생긴다
    중단된 요청               UI-02 대로 실제 종료를 확인한 제어부가 끝낸다. 건드리지 않는다

**이벤트로 돈다.** 여는 메시지의 저장 보고(API), 실행 결과 보고(API), 제어부 기동(복구)
세 곳에서 부른다. 별도 스레드를 두지 않는다 — 제어부는 연결 하나를 공유한다.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from controller.repository import ConflictError, ConversationRefused, NotFoundError, Repository
from domain import conversation as convmod
from domain.models import (
    OPENS_REQUEST,
    REQUEST_PROCESSOR_ACTOR,
    CaseStage,
    MessageKind,
    MessageReceipt,
    Permission,
    RequestSettleOutcome,
    RequestState,
    RunOutcome,
    RunPurpose,
    RunRole,
    RunStatus,
    WorkStartDecider,
)

if TYPE_CHECKING:  # pragma: no cover
    from controller.work_progressor import WorkProgressor

#: 처리기가 만드는 논의 응답 실행의 식별자. **요청마다 하나로 고정한다** — 같은 저장 보고의
#: 재전송이나 기동 복구가 두 번째 응답을 만들지 않는다(`admit_and_create_run` 의 멱등).
REPLY_RUN_PREFIX = "reply-"

#: 논의 응답 실행이 쓰는 작업 키. 업무 그래프의 Task 가 아니라 대화의 자리다.
REPLY_TASK_ID = "conversation"

#: 처리기가 만들 수 없을 때 요청에 남기는 사유 코드.
REPLY_TOOL_UNAVAILABLE = "reply_tool_unavailable"


def reply_run_id(request_id: str) -> str:
    return f"{REPLY_RUN_PREFIX}{request_id}"[:64]


class RequestProcessor:
    """저장된 사용자 요청 → 논의 응답 → (해석 적용) → (진행기) → 요청 종료."""

    def __init__(
        self, repo: Repository, *, enabled: bool, progressor: "WorkProgressor | None" = None
    ) -> None:
        self.repo = repo
        self.enabled = enabled
        self.progressor = progressor

    # ------------------------------------------------------------- 시작

    def on_intake_stored(self, intake: dict[str, Any]) -> dict[str, Any] | None:
        """원문 저장 보고 뒤. 그 원문이 **요청을 연 메시지**면 처리를 시작한다."""
        if not self.enabled or intake.get("state") != "stored":
            return None
        message = self.repo.message_for_intake(intake["id"])
        if message is None or message.get("request_id") is None:
            return None
        if MessageKind(message["message_kind"]) not in OPENS_REQUEST:
            return None  # 카드 답변은 요청을 열지 않는다 — 처리할 요청이 없다
        return self.start(message["request_id"])

    def start(self, request_id: str) -> dict[str, Any] | None:
        """요청에 논의 응답 실행을 만든다. 이미 실행이 있으면 아무 것도 하지 않는다.

        반환: 만든(또는 이미 있던) 실행, 만들 수 없어 요청을 끝냈으면 그 요청, 할 일이 없으면
        `None`.
        """
        request = self.repo.get_request(request_id)
        if request["state"] != RequestState.PROCESSING.value or request.get("stop_requested_at"):
            return None
        if not request.get("opened_by_message_id"):
            return None  # P4-05. 시스템이 연 진행 요청이다. 응답이 아니라 진행기의 실행이 붙는다
        opening = self.repo.get_message(request["opened_by_message_id"])
        if opening["receipt"] != MessageReceipt.STORED.value:
            return None  # 받지 않은 말은 처리하지 않는다. 유실은 기존 경로가 닫는다
        if self.repo.request_runs(request_id):
            # 이미 누군가 처리하고 있다(처리기의 재호출이거나 사람이 붙인 실행). 두 번째 응답을
            # 만들지 않는다. 끝나면 `finish` 가 본다.
            return None
        case = self.repo.get_case(request["case_id"])
        project = self.repo.get_project(case["project_id"])
        runner_id = self.repo.get_artifact_ref(opening["artifact_id"], opening["artifact_rev"])[
            "owner_runner_id"
        ]
        tool = (
            self.repo.reply_tool(runner_id, project["default_tool_id"]) if runner_id else None
        )
        if tool is None:
            # **만들 수 없으면 끝낸다.** 처리 중으로 두면 잠금이 영원히 남는다. 사유는 요청에
            # 남고 사람은 설정을 고친 뒤 다시 보낸다.
            return self._close_failed(
                request,
                f"{REPLY_TOOL_UNAVAILABLE}: {project['default_tool_id']}"
                f" on {runner_id or 'unknown runner'}",
            )
        try:
            run, _created, admission, _check = self.repo.admit_and_create_run(
                case_id=request["case_id"],
                run_id=reply_run_id(request_id),
                task_id=REPLY_TASK_ID,
                purpose=RunPurpose.DISCUSSION_REPLY,
                role=RunRole.AUTHOR,
                tool_id=tool["tool_id"],
                mode=tool["mode"],
                permission=Permission.READ_ONLY,
                instruction_artifact_id=opening["artifact_id"],
                instruction_artifact_rev=opening["artifact_rev"],
                request_id=request_id,
            )
        except (ConflictError, NotFoundError) as exc:
            return self._close_failed(request, f"reply_not_created: {exc}")
        if admission is not None and not admission.admitted:
            # 진입 거부는 진입 검사 기록에 남는다. 요청에는 사유 코드만 남긴다.
            codes = ", ".join(r.value for r in admission.refusals)
            return self._close_failed(request, f"reply_refused: {codes}")
        return run

    def _close_failed(self, request: dict[str, Any], note: str) -> dict[str, Any] | None:
        try:
            return self.repo.settle_request(
                request["case_id"],
                request["id"],
                RequestSettleOutcome.FAILED,
                REQUEST_PROCESSOR_ACTOR,
                note[:200],
            )
        except ConversationRefused:
            return None  # 그 사이 다른 기록이 먼저 끝냈거나 중단됐다

    # ------------------------------------------------------------- 끝

    def on_run_finished(self, run_id: str) -> dict[str, Any] | None:
        """실행 결과 보고 뒤. 그 실행의 요청을 끝낼 수 있으면 끝낸다."""
        if not self.enabled:
            return None
        run = self.repo.get_run(run_id)
        if not run.get("request_id"):
            return None
        return self.finish(run["request_id"])

    def finish(self, request_id: str) -> dict[str, Any] | None:
        """연결 실행이 전부 끝난 처리 중 요청을 끝낸다. **해석을 먼저 적용한다.**

        종료 판정(`unknown`·`interrupted` 포함)은 `settle_request` 가 한다. 여기서는 무엇을
        요청할지만 정한다 — 응답이 완료되고 대화에 붙었으면 `completed`, 아니면 `failed`.

        **P4-05.** 업무 단계면 진행기에 넘긴다. 진행기가 다음 실행을 만들면 요청은 처리 중으로
        남는다(잠금 유지). 진행 요청(여는 메시지 없음)은 진행기가 끝낸다.
        """
        request = self.repo.get_request(request_id)
        if request["state"] != RequestState.PROCESSING.value or request.get("stop_requested_at"):
            return None
        runs = self.repo.request_runs(request_id)
        if not runs or any(r["status"] != RunStatus.FINISHED.value for r in runs):
            return None  # 실행 사이에 잠금을 풀지 않는다 — 마지막 실행이 끝날 때 다시 본다
        if not request.get("opened_by_message_id"):
            # 진행 요청. 다음 걸음을 만들거나(요청 유지) 진행기가 사람 대기·완료·막힘으로 끝낸다.
            if self.progressor is not None:
                self.progressor.continue_request(request_id)
            return None
        replies = [r for r in runs if r.get("purpose") == RunPurpose.DISCUSSION_REPLY.value]
        work_started = False
        for reply in replies:
            # P4-06. 응답이 옮긴 프로젝트 규칙을 **먼저** 등록한다 — 같은 요청에서 업무화되면 그
            # 업무의 첫 실행부터 규칙이 주입된다. 등록은 응답이 완료됐을 때만이고 한 번뿐이다.
            self.repo.apply_knowledge_report(reply["run_id"])
            row = self.apply_interpretation(reply["run_id"])
            work_started = work_started or bool(row and row.get("applied"))
        if self.progressor is not None:
            case_id = request["case_id"]
            stage, _source = self.repo.case_stage(case_id)
            if stage is CaseStage.WORK and not self.repo.case_is_closed(case_id):
                progress = self.repo.progress_state(case_id)
                created = False
                if progress is None and work_started:
                    result = self.progressor.on_work_started(case_id, request_id)
                    created = bool(result and result.get("run_created"))
                elif progress is not None:
                    created = self.progressor.continue_request(request_id)
                if created:
                    return None  # 다음 실행이 이 요청에 붙었다. 잠금은 그대로다
        # 대화에 붙은 완료 응답이 하나라도 있으면 사람은 답을 받았다.
        outcomes = [
            convmod.processor_settle_outcome(
                r.get("outcome"), self.repo.assistant_message_for_run(r["run_id"]) is not None
            )
            for r in replies
        ]
        outcome = (
            RequestSettleOutcome.COMPLETED
            if RequestSettleOutcome.COMPLETED in outcomes
            else RequestSettleOutcome.FAILED
        )
        note = None if outcome is RequestSettleOutcome.COMPLETED else "reply_not_completed"
        try:
            return self.repo.settle_request(
                request["case_id"], request_id, outcome, REQUEST_PROCESSOR_ACTOR, note
            )
        except ConversationRefused:
            return None

    # ------------------------------------------------------------ 해석

    def apply_interpretation(self, run_id: str) -> dict[str, Any] | None:
        """보고된 해석을 **한 번** 평가한다. 명확한 업무 요청이면 같은 Case 에서 업무화한다.

        위임 근거는 여는 메시지 원문이다(`start_work` 가 그렇게 적는다). 업무화 조건(준비
        단계·처리 중 요청·저장된 메시지·해석 실행)은 `start_work` 가 본다.

        **P4-05.** 종료 Case 의 응답이 업무 요청이면 연결된 새 대화를 만들어 그 메시지를 옮긴다
        (D-33·D-78). 새 대화의 요청에는 처리기가 바로 응답을 만든다.
        """
        row = self.repo.get_interpretation(run_id)
        if row is None or row["evaluated_at"] is not None:
            return row
        run = self.repo.get_run(run_id)
        parsed = convmod.interpretation_from_report(
            {"status": row["report_status"], "kind": row["kind"], "profile": row["profile"]}
        )
        refusal = convmod.interpretation_refusal(parsed, run.get("outcome"))
        if refusal is not None:
            return self.repo.mark_interpretation_evaluated(
                run_id, applied=False, refusal=refusal.value
            )
        opening = self.repo.get_message(row["opening_message_id"])
        if self.repo.case_is_closed(row["case_id"]):
            return self._move_to_follow_up(row, run, opening)
        try:
            self.repo.start_work(
                row["case_id"],
                profile=parsed.profile,
                request_message_id=row["opening_message_id"],
                decided_by=WorkStartDecider.AI_INTERPRETATION,
                actor=f"ai:{run['tool_id']}",
                # **본문에서 만들지 않는다.** 이해한 목표는 PC 에 있는 응답 글에 있다.
                summary=f"AI 해석 · {parsed.profile.value} 업무 요청 · 메시지 #{opening['seq']}",
                interpretation_run_id=run_id,
            )
        except ConversationRefused as exc:
            code = exc.refusals[0].value if exc.refusals else "work_start_refused"
            return self.repo.mark_interpretation_evaluated(run_id, applied=False, refusal=code)
        return self.repo.mark_interpretation_evaluated(run_id, applied=True, refusal=None)

    def _move_to_follow_up(
        self, row: dict[str, Any], run: dict[str, Any], opening: dict[str, Any]
    ) -> dict[str, Any] | None:
        """종료 Case 의 수정 요청 → 연결된 새 대화(D-33·D-78). 해석 행에는 적용으로 남긴다."""
        try:
            view = self.repo.create_successor_conversation(
                row["case_id"],
                row["opening_message_id"],
                actor=f"ai:{run['tool_id']}",
                reason_summary=f"종료 뒤 수정 요청 · 메시지 #{opening['seq']} · AI 해석",
            )
        except (ConflictError, NotFoundError) as exc:
            return self.repo.mark_interpretation_evaluated(
                run_id=run["run_id"], applied=False, refusal=f"follow_up_refused: {exc}"[:64]
            )
        marked = self.repo.mark_interpretation_evaluated(run["run_id"], applied=True, refusal=None)
        # 새 대화의 요청은 이미 저장된 메시지로 열렸다 — 저장 보고가 다시 오지 않으므로 여기서 시작한다.
        try:
            self.start(view["request_id"])
        except (ConflictError, NotFoundError):
            pass
        return marked

    # ------------------------------------------------------------- 복구

    def recover(self) -> dict[str, int]:
        """제어부 기동 때. 처리 중인 요청에서 **빠진 단계**를 잇는다.

        실행이 없으면 응답 실행을 만들고, 연결 실행이 전부 끝났으면 끝낸다. 도는 중인 실행은
        그대로 둔다 — 그 결과가 오면 `on_run_finished` 가 본다. 진행 요청은 진행기의 복구가 본다.
        """
        counts = {"started": 0, "finished": 0}
        if not self.enabled:
            return counts
        for request in self.repo.processing_requests():
            if not request.get("opened_by_message_id"):
                continue
            runs = self.repo.request_runs(request["id"])
            if not runs:
                if self.start(request["id"]) is not None:
                    counts["started"] += 1
            elif all(r["status"] == RunStatus.FINISHED.value for r in runs):
                if self.finish(request["id"]) is not None:
                    counts["finished"] += 1
        return counts
