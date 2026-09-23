"""업무 단계 자동 진행의 판정 — 다음 걸음·사람 대기·기준 보고 검사(P4-05).

**여기에는 DB 도 HTTP 도 없다.** `domain/progression.py`·`domain/conversation.py` 와 같은 자리이며
같은 이유로 그렇게 둔다 — 진행기·화면·복구·시험이 **같은 함수를 봐야** 하고, 두 벌로 쓰면 한쪽만
고치는 실수가 생긴다.

이 파일이 답하는 질문은 셋이다.

    1. 지금 무엇을 하는가          다음 실행 하나, 작업공간 요청, 기록 하나, 또는 멈춤(사람·환경)
    2. 왜 멈추는가                 사람이 해야 할 일과 환경이 막은 것을 **다른 코드**로 나눈다
    3. 이 기준 보고를 적는가       검증·분석 실행이 보고한 기준별 판정을 구조 검사로 거른다

이 파일이 지키는 것:

    진입 검사를 우회하지 않는다     여기서 정한 실행도 `admit_and_create_run` 을 지난다. 거부되면
                                    그 사유로 멈춘다
    사람의 결정을 만들지 않는다     동의·확인·인수·예외는 사람 경로에서만 기록된다. 여기서는
                                    "그것이 필요하다"를 값으로 낼 뿐이다
    통과할 때까지 돌리지 않는다     재작성·재시도에는 상한이 있고 넘으면 사람에게 넘긴다
    모르면 멈춘다                   상태를 읽지 못한 것을 "할 일 없음"으로 읽지 않는다
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.models import (
    AdmissionRefusal,
    CaseProfile,
    CaseStage,
    CompletionMode,
    Conclusion,
    ConclusionRule,
    CriterionObligation,
    CriterionVerdict,
    GateVerdict,
    IntentAgreementState,
    Permission,
    PreparationStage,
    ReviewMode,
    RunOutcome,
    RunPurpose,
    RunRole,
    RunStatus,
    Satisfaction,
    StageReviewState,
    TaskKind,
    TaskState,
    WorkspaceState,
)
from domain.progression import INVESTIGATION_ONLY_PROFILES, required_stages

#: 진행기가 만든 기록의 주체. 사람의 기록과 구별한다.
WORK_PROGRESSOR_ACTOR = "work-progressor"

#: 기준 판정을 제품이 적을 때의 주체(`criterion_result.recorded_by`).
CRITERIA_RECORDER = "policy:work_progressor"

#: 같은 대상을 다시 쓰는 상한(D-29 기본값과 같은 수). 넘으면 사람에게 넘긴다.
REPAIR_LIMIT = 2

#: 실패한 Task 실행을 다시 시도하는 상한(D-79 "제한 자동 복구"). 두 번째 실패는 사람 대기다.
TASK_ATTEMPT_LIMIT = 2


# ================================================================ 진행 상태 값


class ProgressState(str):
    RUNNING = "running"
    WAITING_HUMAN = "waiting_human"
    BLOCKED = "blocked"
    PAUSED = "paused"
    DONE = "done"


#: **사람이 해야 할 일**의 코드. 화면이 카드를 고르는 키다.
class WaitReason(str):
    INTENT_QUESTIONS = "intent_questions"
    INTENT_AGREEMENT = "intent_agreement"
    MATERIAL_DELTA = "material_delta"
    GATE_REPAIR_EXHAUSTED = "gate_repair_exhausted"
    SIZING_NOT_DECIDED = "sizing_not_decided"
    CONTROLLED_START = "controlled_start"
    STAGE_REVIEW = "stage_review"
    PREPARATION_REPAIR_EXHAUSTED = "preparation_repair_exhausted"
    DEFERRED_QUESTIONS = "deferred_questions"
    WORK_GRAPH_MISSING = "work_graph_missing"
    TASKS_BLOCKED = "tasks_blocked"
    REPOSITORY_SELECTION = "repository_selection"
    TASK_FAILED = "task_failed"
    UNRESOLVED_FEEDBACK = "unresolved_feedback"
    CONTROLLED_RESULT = "controlled_result"
    CRITERIA_UNRESOLVED = "criteria_unresolved"
    OBJECTIVE_WITHOUT_CRITERIA = "objective_without_criteria"
    QUALITY_GATE = "quality_gate"
    ADMISSION_REFUSED = "admission_refused"


#: **환경이 막은 것**의 코드. 사람의 결정이 아니라 조치·재시도가 필요하다(D-79 조치 카드).
class BlockReason(str):
    TOOL_UNAVAILABLE = "tool_unavailable"
    WORKSPACE_FAILED = "workspace_failed"
    BUDGET_HARD_LIMIT = "budget_hard_limit"
    CONTEXT_UNAVAILABLE = "context_unavailable"
    ADMISSION_REFUSED = "admission_refused"
    RUN_NOT_CREATED = "run_not_created"


WAIT_DETAIL: dict[str, str] = {
    WaitReason.INTENT_QUESTIONS: "의도 초안이 물은 것에 답해야 다음으로 간다",
    WaitReason.INTENT_AGREEMENT: "최신 의도 원문을 읽고 동의해야 실행을 위임한 것이 된다",
    WaitReason.MATERIAL_DELTA: "동의된 의도가 AI 출처로 바뀐 항목을 사람이 확인해야 한다",
    WaitReason.GATE_REPAIR_EXHAUSTED: "QG-01 지적을 재작성으로 해소하지 못했다. 요청을 고치거나 답한다",
    WaitReason.SIZING_NOT_DECIDED: "작업 수준이 결정되지 않았다(관리 화면에서 조정)",
    WaitReason.CONTROLLED_START: "controlled 업무다. 시작 범위(목표·범위·기준·허용 행동)를 확인한다",
    WaitReason.STAGE_REVIEW: "이 단계는 사람 검토 설정이다. 산출물을 읽고 검토를 기록한다",
    WaitReason.PREPARATION_REPAIR_EXHAUSTED: "준비 산출물의 필수 항목을 재작성으로 채우지 못했다",
    WaitReason.DEFERRED_QUESTIONS: "설계·계획으로 이월한 질문에 답해야 막힌 작업이 열린다",
    WaitReason.WORK_GRAPH_MISSING: "개발계획이 작업을 정의하지 않아 작업 그래프가 없다",
    WaitReason.TASKS_BLOCKED: "배정 가능한 작업이 없다(막는 사유 참조)",
    WaitReason.REPOSITORY_SELECTION: "코드를 바꿀 저장소를 골라 쓰기를 허용해야 한다(관리 화면)",
    WaitReason.TASK_FAILED: "작업 실행이 거듭 실패했다. 사유를 보고 다시 시도하거나 요청을 고친다",
    WaitReason.UNRESOLVED_FEEDBACK: "미해결 피드백이 남아 있다. 반영됨·미반영을 판단한다",
    WaitReason.CONTROLLED_RESULT: "controlled 업무다. 결과 후보를 확인하면 시스템이 종료를 확정한다",
    WaitReason.CRITERIA_UNRESOLVED: "미충족·미검증 기준이 남았다. 예외를 수용해 종료하거나 수정을 요청한다",
    WaitReason.OBJECTIVE_WITHOUT_CRITERIA: "요구된 목적 의무에 기준이 없다. 의도·기준을 바꿔야 한다",
    WaitReason.QUALITY_GATE: "명시한 품질 게이트가 통과하지 않았다(관리 화면에서 진행)",
    WaitReason.ADMISSION_REFUSED: "진입 검사가 사람의 조치를 요구했다",
}

BLOCK_DETAIL: dict[str, str] = {
    BlockReason.TOOL_UNAVAILABLE: "이 PC 에서 프로젝트 기본 도구가 코딩 CLI 로 확인되지 않았다",
    BlockReason.WORKSPACE_FAILED: "작업공간 준비가 실패했다",
    BlockReason.BUDGET_HARD_LIMIT: "설정된 hard 예산 한도에 도달했다. 한도를 바꾸면 다시 진행한다",
    BlockReason.CONTEXT_UNAVAILABLE: "핵심 입력의 원문을 지금 읽을 수 없거나 한도를 넘는다",
    BlockReason.ADMISSION_REFUSED: "진입 검사가 환경 사유로 거부했다",
    BlockReason.RUN_NOT_CREATED: "실행을 만들지 못했다",
}


#: 진입 거부 사유 중 **사람이 해야 할 일**인 것. 나머지는 환경·일시 사유로 본다.
HUMAN_ADMISSION_REFUSALS: frozenset[str] = frozenset(
    {
        AdmissionRefusal.INTENT_NOT_AGREED.value,
        AdmissionRefusal.OPEN_INTENT_QUESTIONS.value,
        AdmissionRefusal.INTENT_GATE_NOT_PASSED.value,
        AdmissionRefusal.DEFERRED_QUESTIONS_UNRESOLVED.value,
        AdmissionRefusal.DESIGN_REVIEW_MISSING.value,
        AdmissionRefusal.PLAN_REVIEW_MISSING.value,
        AdmissionRefusal.COMBINED_RECORD_REVIEW_MISSING.value,
        AdmissionRefusal.CONTROLLED_START_NOT_CONFIRMED.value,
        AdmissionRefusal.MATERIAL_DELTA_UNCONFIRMED.value,
        AdmissionRefusal.QUALITY_GATE_NOT_PASSED.value,
        AdmissionRefusal.PURPOSE_OUTSIDE_CASE_OBJECTIVE.value,
        AdmissionRefusal.TASK_REPOSITORY_NOT_RECORDED.value,
        AdmissionRefusal.WORKSPACE_TARGET_NOT_RECORDED.value,
        AdmissionRefusal.SIZING_NOT_DECIDED.value,
        AdmissionRefusal.RUN_TASK_REPOSITORY_MISMATCH.value,
        AdmissionRefusal.PROFILE_NOT_RECORDED.value,
        AdmissionRefusal.INTENT_VERSION_NOT_LATEST.value,
        AdmissionRefusal.INTENT_VERSION_MISSING.value,
    }
)

#: 잠깐 뒤 다시 보면 달라질 수 있는 거부. 멈추지 않고 다음 사건을 기다린다.
TRANSIENT_ADMISSION_REFUSALS: frozenset[str] = frozenset(
    {
        AdmissionRefusal.CASE_WRITE_IN_PROGRESS.value,
        AdmissionRefusal.REQUEST_NOT_PROCESSING.value,
        AdmissionRefusal.REQUEST_STOP_REQUESTED.value,
        AdmissionRefusal.REQUEST_ORIGINAL_NOT_STORED.value,
        AdmissionRefusal.WORKSPACE_NOT_READY.value,
    }
)


def classify_refusals(codes: list[str]) -> tuple[str, list[str]]:
    """진입 거부 사유를 **사람·일시·환경**으로 나눈다. (분류, 그 분류의 사유 목록)

    사람 사유가 하나라도 있으면 사람 대기다 — 환경 사유는 사람이 그것을 고치는 동안 함께
    풀리는 경우가 많고, 반대는 아니다. 종료된 Case 는 `done` 이다.
    """
    if AdmissionRefusal.CASE_ALREADY_CLOSED.value in codes:
        return "done", [AdmissionRefusal.CASE_ALREADY_CLOSED.value]
    human = [c for c in codes if c in HUMAN_ADMISSION_REFUSALS]
    if human:
        return "human", human
    transient = [c for c in codes if c in TRANSIENT_ADMISSION_REFUSALS]
    if transient and len(transient) == len(codes):
        return "transient", transient
    return "environment", [c for c in codes if c not in TRANSIENT_ADMISSION_REFUSALS]


def block_reason_for(codes: list[str]) -> str:
    if AdmissionRefusal.BUDGET_HARD_LIMIT_REACHED.value in codes:
        return BlockReason.BUDGET_HARD_LIMIT
    if AdmissionRefusal.WORKSPACE_FAILED.value in codes:
        return BlockReason.WORKSPACE_FAILED
    if any(
        c in codes
        for c in (
            AdmissionRefusal.TOOL_NOT_AVAILABLE.value,
            AdmissionRefusal.TOOL_IS_NOT_A_CODING_CLI.value,
            AdmissionRefusal.PERMISSION_NOT_MAPPED.value,
        )
    ):
        return BlockReason.TOOL_UNAVAILABLE
    if any(
        c in codes
        for c in (
            AdmissionRefusal.REQUIRED_CONTEXT_UNAVAILABLE.value,
            AdmissionRefusal.CONTEXT_OVER_INLINE_LIMIT.value,
            AdmissionRefusal.INSTRUCTION_NOT_AVAILABLE.value,
            AdmissionRefusal.INTENT_ORIGINAL_NOT_AVAILABLE.value,
        )
    ):
        return BlockReason.CONTEXT_UNAVAILABLE
    return BlockReason.ADMISSION_REFUSED


def wait_reason_for(codes: list[str]) -> str:
    """사람 사유의 진입 거부를 **카드 코드**로 옮긴다."""
    table = {
        AdmissionRefusal.INTENT_NOT_AGREED.value: WaitReason.INTENT_AGREEMENT,
        AdmissionRefusal.OPEN_INTENT_QUESTIONS.value: WaitReason.INTENT_QUESTIONS,
        AdmissionRefusal.INTENT_GATE_NOT_PASSED.value: WaitReason.GATE_REPAIR_EXHAUSTED,
        AdmissionRefusal.DEFERRED_QUESTIONS_UNRESOLVED.value: WaitReason.DEFERRED_QUESTIONS,
        AdmissionRefusal.DESIGN_REVIEW_MISSING.value: WaitReason.STAGE_REVIEW,
        AdmissionRefusal.PLAN_REVIEW_MISSING.value: WaitReason.STAGE_REVIEW,
        AdmissionRefusal.COMBINED_RECORD_REVIEW_MISSING.value: WaitReason.STAGE_REVIEW,
        AdmissionRefusal.CONTROLLED_START_NOT_CONFIRMED.value: WaitReason.CONTROLLED_START,
        AdmissionRefusal.MATERIAL_DELTA_UNCONFIRMED.value: WaitReason.MATERIAL_DELTA,
        AdmissionRefusal.QUALITY_GATE_NOT_PASSED.value: WaitReason.QUALITY_GATE,
        AdmissionRefusal.SIZING_NOT_DECIDED.value: WaitReason.SIZING_NOT_DECIDED,
        AdmissionRefusal.TASK_REPOSITORY_NOT_RECORDED.value: WaitReason.REPOSITORY_SELECTION,
        AdmissionRefusal.WORKSPACE_TARGET_NOT_RECORDED.value: WaitReason.REPOSITORY_SELECTION,
    }
    for code in codes:
        if code in table:
            return table[code]
    return WaitReason.ADMISSION_REFUSED


# ================================================================ Task → 목적

#: Task 의 종류가 실행의 목적과 권한을 정한다(P3-04 하네스와 같은 표).
#:
#: **진행기가 고르는 것이 아니라 계획이 고른 것이다.** 조사 Task 에 쓰기를 주거나 검증 Task 를
#: 구현 목적으로 돌리면, 무엇이 확인 작업이고 무엇이 제품 변경인지가 기록에서 사라진다.
PURPOSE_BY_TASK_KIND: dict[str, tuple[RunPurpose, Permission]] = {
    TaskKind.INVESTIGATION.value: (RunPurpose.LIMITED_ANALYSIS, Permission.READ_ONLY),
    TaskKind.IMPLEMENTATION.value: (RunPurpose.FEATURE_IMPLEMENTATION, Permission.WORKSPACE_WRITE),
    TaskKind.INTEGRATION.value: (RunPurpose.VERIFICATION_RUN, Permission.WORKSPACE_WRITE),
    TaskKind.VERIFICATION.value: (RunPurpose.VERIFICATION_RUN, Permission.WORKSPACE_WRITE),
    TaskKind.EXPERIMENT.value: (RunPurpose.LOCAL_EXPERIMENT, Permission.WORKSPACE_WRITE),
}


# ================================================================ 걸음


@dataclass(frozen=True)
class Step:
    """다음 걸음 하나.

    `kind`:
        run          실행 하나를 만든다
        workspace    작업공간을 요청한다
        light_check  가벼운 정합성 확인을 기록한다(실행 없음)
        candidate    종료 후보를 만든다(그 뒤 사람 대기)
        wait         사람이 해야 할 일이 있다
        blocked      환경이 막았다
        busy         끝나지 않은 실행·요청이 있다. 그 사건이 오면 다시 본다
        done         종료됐다
        idle         할 일이 없다(준비 단계·멈춤)
    """

    kind: str
    code: str
    detail: str = ""
    purpose: RunPurpose | None = None
    role: RunRole = RunRole.AUTHOR
    permission: Permission = Permission.READ_ONLY
    task_id: str = "conversation"
    repository_id: str | None = None
    #: 실행의 지시 원문: `work_request`(업무 요청 메시지) 또는 `latest_intent`(의도 원문).
    instruction: str = "work_request"
    #: 재작성·재시도 상한을 세는 키. 없으면 세지 않는다.
    attempt_key: str | None = None
    reasons: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "code": self.code,
            "detail": self.detail,
            "purpose": self.purpose.value if self.purpose else None,
            "task_id": self.task_id,
            "repository_id": self.repository_id,
            "reasons": list(self.reasons),
        }


def _wait(code: str, detail: str | None = None, **subject: Any) -> Step:
    return Step(
        "wait",
        code,
        detail or WAIT_DETAIL.get(code, code),
        reasons=({"code": code, "detail": detail or WAIT_DETAIL.get(code, code), **subject},),
    )


def _blocked(code: str, detail: str | None = None, **subject: Any) -> Step:
    return Step(
        "blocked",
        code,
        detail or BLOCK_DETAIL.get(code, code),
        reasons=({"code": code, "detail": detail or BLOCK_DETAIL.get(code, code), **subject},),
    )


@dataclass
class FlowState:
    """진행기가 DB 에서 읽어 넘기는 사실. **본문은 없다.**"""

    case_id: str
    closed: bool
    stage: str
    profile: str | None
    paused: bool
    #: 진행기가 만든 실행 중 끝나지 않은 것(요청·Case 전체).
    unfinished_runs: list[dict[str, Any]]
    intent: dict[str, Any]  # Repository.intent_state()
    #: 최신 의도 버전의 구조가 보고됐는가(항목 행이 있는가).
    intent_structure_reported: bool
    #: 최신 버전이 만들어진 뒤에 답한 의도 단계 질문이 있는가(답 반영 재작성이 필요).
    answers_after_version: bool
    gate: dict[str, Any]  # Repository.gate_state()
    conformance_required: str  # light | independent
    pending_deltas: int
    checkpoint: dict[str, Any]  # Repository.checkpoint_state()
    preparation: dict[str, Any]  # Repository.preparation_state()
    completion_mode: str
    criteria: list[dict[str, Any]]  # current_criteria()
    unresolved: list[dict[str, Any]]  # _candidate_snapshot()["unresolved"]
    unsettled_runs: list[dict[str, Any]]
    candidate: dict[str, Any] | None
    #: 코드 쓰기가 가능한 저장소(이 Case 가 고른 것 또는 암묵 단일 저장소). id·name.
    code_repositories: list[dict[str, Any]]
    #: 저장소별 작업공간 상태(`workspace_state`). 키는 저장소 id.
    workspaces: dict[str, dict[str, Any]]
    #: 진행기가 만든 실행의 시도 수(키 → 수).
    attempts: dict[str, int] = field(default_factory=dict)
    #: 조사 Profile 의 분석 실행이 끝났고 그 기준 보고를 적용했는가.
    analysis_done: bool = False
    #: 완료된 독립 검토 실행이 있는데 그 판정이 아직 게이트에 붙지 않았다(검토 보고는 결과 보고
    #: **뒤에** 온다). 그 사이에 두 번째 검토를 만들지 않는다.
    review_pending: bool = False
    #: 이 Case 의 실행 중 마지막으로 끝난 것(요약: run_id·purpose·task_id·outcome). 실패 재시도 판단.
    finished_runs: list[dict[str, Any]] = field(default_factory=list)


def _latest(state: FlowState) -> dict[str, Any] | None:
    return state.intent.get("latest_intent_version")


def _investigation(state: FlowState) -> bool:
    try:
        return CaseProfile(state.profile or "") in INVESTIGATION_ONLY_PROFILES
    except ValueError:
        return False


def next_step(state: FlowState) -> Step:
    """다음 걸음을 정한다. **순서가 판정이다** — 앞의 조건이 뒤의 조건보다 먼저 사람에게 알려진다."""
    if state.closed:
        return Step("done", "closed", "종료된 업무다")
    if state.stage != CaseStage.WORK.value:
        return Step("idle", "discussion", "준비 단계다. 업무화 뒤에 진행한다")
    if state.paused:
        return Step("idle", "paused", "사람이 멈췄다. 계속 진행을 누르면 이어 간다")
    if state.unfinished_runs:
        return Step(
            "busy",
            "runs_unfinished",
            "끝나지 않은 실행이 있다: " + ", ".join(r["run_id"] for r in state.unfinished_runs),
        )

    intent_step = _intent_phase(state)
    if intent_step is not None:
        return intent_step

    if state.checkpoint.get("required") and not state.checkpoint.get("start_confirmed"):
        latest = _latest(state) or {}
        return _wait(
            WaitReason.CONTROLLED_START,
            subject_type="intent_version",
            subject_id=latest.get("id"),
            subject_hash=latest.get("content_hash"),
        )

    if _investigation(state):
        return _analysis_phase(state)

    prep_step = _preparation_phase(state)
    if prep_step is not None:
        return prep_step

    graph_step = _graph_phase(state)
    if graph_step is not None:
        return graph_step

    return _completion_phase(state)


# ------------------------------------------------------------- 의도 단계


def _intent_phase(state: FlowState) -> Step | None:
    latest = _latest(state)
    if latest is None:
        return Step(
            "run",
            "intent_authoring",
            "업무 요청·대화를 읽고 의도 초안을 쓴다",
            purpose=RunPurpose.INTENT_AUTHORING,
            attempt_key="intent_authoring",
        )
    if not state.intent_structure_reported:
        return Step("busy", "intent_structure_pending", "의도 초안의 구조 보고를 기다린다")
    questions = state.intent.get("open_intent_questions") or []
    if questions:
        return _wait(
            WaitReason.INTENT_QUESTIONS,
            question_keys=[q["question_key"] for q in questions],
            intent_version_id=latest["id"],
        )
    if state.answers_after_version:
        return Step(
            "run",
            "intent_rewrite_answers",
            "답한 질문을 초안에 반영해 다시 쓴다",
            purpose=RunPurpose.INTENT_AUTHORING,
            attempt_key="intent_rewrite",
        )

    gate_step = _gate_phase(state, latest)
    if gate_step is not None:
        return gate_step

    if state.pending_deltas:
        return _wait(WaitReason.MATERIAL_DELTA, pending=state.pending_deltas)
    if state.intent.get("agreement_state") != IntentAgreementState.AGREED_CURRENT.value:
        return _wait(
            WaitReason.INTENT_AGREEMENT,
            intent_version_id=latest["id"],
            revision=latest.get("revision"),
            content_hash=latest.get("content_hash"),
        )
    unresolved_feedback = state.intent.get("unresolved_feedback") or []
    if unresolved_feedback:
        return _wait(
            WaitReason.UNRESOLVED_FEEDBACK, feedback_ids=[f["id"] for f in unresolved_feedback]
        )
    if not state.preparation.get("level"):
        return _wait(WaitReason.SIZING_NOT_DECIDED)
    return None


def _gate_phase(state: FlowState, latest: dict[str, Any]) -> Step | None:
    gate = state.gate
    if gate.get("verdict") == GateVerdict.PASS.value:
        return None
    repairs = state.attempts.get("intent_repair", 0)
    rule = gate.get("rule_verdict")
    ai = gate.get("ai_verdict")
    if rule is not None and rule != GateVerdict.PASS.value:
        # 규칙 검사가 막았다(필수 항목·참조·버전). 지적을 실어 다시 쓴다.
        if repairs >= REPAIR_LIMIT:
            return _wait(WaitReason.GATE_REPAIR_EXHAUSTED, verdict=gate.get("verdict"), repairs=repairs)
        return Step(
            "run",
            "intent_repair",
            "QG-01 규칙 검사의 지적을 고쳐 다시 쓴다",
            purpose=RunPurpose.INTENT_AUTHORING,
            attempt_key="intent_repair",
        )
    if ai in (None, GateVerdict.NOT_RUN.value):
        if state.review_pending:
            return Step("busy", "gate_review_pending", "독립 검토의 보고를 기다린다")
        if state.conformance_required == "light":
            return Step("light_check", "light_conformance", "가벼운 정합성 확인을 기록한다")
        return Step(
            "run",
            "intent_gate_review",
            "독립 의미 검토(별도 세션)를 돌린다",
            purpose=RunPurpose.INTENT_GATE_REVIEW,
            role=RunRole.REVIEWER,
            instruction="latest_intent",
            attempt_key="intent_gate_review",
        )
    if ai in (GateVerdict.FAIL.value, GateVerdict.HOLD.value):
        if repairs >= REPAIR_LIMIT:
            return _wait(WaitReason.GATE_REPAIR_EXHAUSTED, verdict=gate.get("verdict"), repairs=repairs)
        return Step(
            "run",
            "intent_repair",
            "독립 검토의 지적을 고쳐 다시 쓴다",
            purpose=RunPurpose.INTENT_AUTHORING,
            attempt_key="intent_repair",
        )
    # 통과가 아닌데 위 어느 경우도 아니다(예: 가벼운 확인이 요구를 충족하지 못함). 모르면 멈춘다.
    return _wait(WaitReason.GATE_REPAIR_EXHAUSTED, verdict=gate.get("verdict"), repairs=repairs)


# ------------------------------------------------------------- 조사 Profile


def _analysis_phase(state: FlowState) -> Step:
    """조사 Profile(RCA·research)은 준비 산출물 없이 분석 실행이 기준별 결론을 낸다(P4-03)."""
    if state.attempts.get("analysis", 0) == 0:
        return Step(
            "run",
            "analysis",
            "동의된 의도에 따라 읽기 전용 분석을 수행하고 기준별 결론을 보고한다",
            purpose=RunPurpose.LIMITED_ANALYSIS,
            task_id="analysis",
            attempt_key="analysis",
        )
    failed = [
        r
        for r in state.finished_runs
        if r.get("purpose") == RunPurpose.LIMITED_ANALYSIS.value
        and r.get("outcome") != RunOutcome.COMPLETED.value
    ]
    completed = any(
        r.get("purpose") == RunPurpose.LIMITED_ANALYSIS.value
        and r.get("outcome") == RunOutcome.COMPLETED.value
        for r in state.finished_runs
    )
    if not completed:
        if state.attempts.get("analysis", 0) < TASK_ATTEMPT_LIMIT:
            return Step(
                "run",
                "analysis_retry",
                "분석 실행이 실패해 한 번 다시 시도한다",
                purpose=RunPurpose.LIMITED_ANALYSIS,
                task_id="analysis",
                attempt_key="analysis",
            )
        return _wait(
            WaitReason.TASK_FAILED,
            task_key="analysis",
            failures=[r["run_id"] for r in failed],
        )
    return _completion_phase(state)


# ------------------------------------------------------------- 준비 단계


def _stage_step(state: FlowState, stage: PreparationStage, purpose: RunPurpose) -> Step | None:
    """한 준비 단계의 다음 걸음. 갖춰졌으면 `None`."""
    info = state.preparation.get(stage.value) or {}
    artifact = info.get("artifact")
    label = {"design": "설계", "plan": "개발계획", "combined": "결합 기록"}[stage.value]
    key = f"prep:{stage.value}"
    if artifact is None or info.get("stale"):
        return Step(
            "run",
            f"{stage.value}_authoring",
            f"{label}을(를) 쓴다",
            purpose=purpose,
            attempt_key=key,
        )
    review_state = info.get("state")
    if review_state in (
        StageReviewState.HUMAN_REVIEWED.value,
        StageReviewState.AUTO_CONDITIONS_MET.value,
    ):
        return None
    if info.get("mode") == ReviewMode.HUMAN_REVIEW.value:
        return _wait(
            WaitReason.STAGE_REVIEW,
            stage=stage.value,
            preparation_id=artifact.get("id"),
            content_hash=artifact.get("content_hash"),
        )
    # 자동 진행 설정인데 조건 기록이 없다 = 필수 항목이 미정이거나 원문을 읽을 수 없다.
    missing = info.get("missing_required_sections") or []
    if state.attempts.get(key, 0) >= REPAIR_LIMIT:
        return _wait(
            WaitReason.PREPARATION_REPAIR_EXHAUSTED, stage=stage.value, missing_sections=missing
        )
    return Step(
        "run",
        f"{stage.value}_rewrite",
        f"{label}의 필수 항목({', '.join(missing) or '조건'})을 채워 다시 쓴다",
        purpose=purpose,
        attempt_key=key,
    )


def _preparation_phase(state: FlowState) -> Step | None:
    prep = state.preparation
    fast_lane = bool((prep.get("fast_lane") or {}).get("eligible"))
    design = (prep.get("design") or {}).get("artifact")
    plan = (prep.get("plan") or {}).get("artifact")
    combined = (prep.get("combined") or {}).get("artifact")
    # 결합 기록 하나로 갈 수 있는가 — Fast Lane 이고 설계·계획 경로를 아직 타지 않았을 때.
    alternatives = required_stages(fast_lane)
    use_combined = (
        len(alternatives) > 1 and design is None and plan is None
    ) or (combined is not None and design is None and plan is None and fast_lane)
    if use_combined:
        return _stage_step(state, PreparationStage.COMBINED, RunPurpose.PLAN_AUTHORING)
    step = _stage_step(state, PreparationStage.DESIGN, RunPurpose.DESIGN_AUTHORING)
    if step is not None:
        return step
    return _stage_step(state, PreparationStage.PLAN, RunPurpose.PLAN_AUTHORING)


# ------------------------------------------------------------- 작업 그래프


def _graph_phase(state: FlowState) -> Step | None:
    graph = (state.preparation.get("work_graph") or {})
    if not graph.get("present"):
        return _wait(WaitReason.WORK_GRAPH_MISSING)
    if graph.get("stale"):
        # 새 의도 버전 위에 계획을 다시 세워야 한다 — 준비 단계가 `stale` 로 잡는다. 여기 오면
        # 준비는 최신인데 그래프만 낡은 것이므로 계획 재작성이 필요하다.
        return Step(
            "run",
            "plan_rewrite_stale_graph",
            "작업 그래프가 대체된 의도 위에 있다. 개발계획을 다시 쓴다",
            purpose=RunPurpose.PLAN_AUTHORING,
            attempt_key="prep:plan",
        )
    tasks = [t for t in graph.get("tasks") or [] if not t.get("cancelled")]
    if not tasks:
        return _wait(WaitReason.WORK_GRAPH_MISSING, detail="작업 그래프에 진행할 Task 가 없다")
    pending = [t for t in tasks if t.get("state") != TaskState.DONE.value]
    if not pending:
        return None
    readiness = graph.get("readiness") or {}
    runnable = [t for t in pending if (readiness.get(t["task_key"]) or {}).get("runnable")]
    if not runnable:
        deferred = graph.get("deferred_open_questions") or []
        if deferred:
            return _wait(
                WaitReason.DEFERRED_QUESTIONS,
                question_keys=[q["question_key"] for q in deferred],
                blocked_tasks=[t["task_key"] for t in pending],
            )
        return _wait(
            WaitReason.TASKS_BLOCKED,
            blocked={
                t["task_key"]: [
                    b["reason"] for b in (readiness.get(t["task_key"]) or {}).get("blocked_by") or []
                ]
                for t in pending
            },
        )
    task = runnable[0]
    key = task["task_key"]
    kind = task.get("kind")
    if kind not in PURPOSE_BY_TASK_KIND:
        return _wait(WaitReason.TASKS_BLOCKED, detail=f"{key} 의 종류 {kind!r} 를 실행할 수 없다")
    purpose, permission = PURPOSE_BY_TASK_KIND[kind]
    attempt_key = f"task:{key}"
    failures = [
        r
        for r in state.finished_runs
        if r.get("task_id") == key and r.get("outcome") != RunOutcome.COMPLETED.value
    ]
    if state.attempts.get(attempt_key, 0) >= TASK_ATTEMPT_LIMIT:
        return _wait(
            WaitReason.TASK_FAILED,
            task_key=key,
            failures=[r["run_id"] for r in failures],
        )
    repository_id: str | None = task.get("repository_id")
    if permission is Permission.WORKSPACE_WRITE:
        if repository_id is None:
            if len(state.code_repositories) == 1:
                repository_id = state.code_repositories[0]["id"]
            elif not state.code_repositories:
                return _wait(WaitReason.REPOSITORY_SELECTION, task_key=key)
            else:
                return _wait(
                    WaitReason.REPOSITORY_SELECTION,
                    detail=f"{key} 의 저장소가 계획에 없고 고를 수 있는 저장소가 여럿이다",
                    task_key=key,
                )
        space = state.workspaces.get(repository_id) or {}
        if not space.get("present"):
            return Step(
                "workspace",
                f"workspace:{repository_id}",
                "전용 작업공간을 요청한다",
                repository_id=repository_id,
                task_id=key,
            )
        if space.get("state") == WorkspaceState.FAILED.value:
            return _blocked(
                BlockReason.WORKSPACE_FAILED,
                detail=space.get("failure_reason") or BLOCK_DETAIL[BlockReason.WORKSPACE_FAILED],
                repository_id=repository_id,
            )
        if not space.get("ready"):
            return Step("busy", "workspace_pending", "작업공간 준비를 기다린다")
    return Step(
        "run",
        f"task:{key}",
        f"{key} ({kind}) 를 실행한다" + (" — 다시 시도" if failures else ""),
        purpose=purpose,
        permission=permission,
        task_id=key,
        repository_id=repository_id,
        attempt_key=attempt_key,
    )


# ------------------------------------------------------------- 완료


def _completion_phase(state: FlowState) -> Step:
    if state.unsettled_runs:
        return Step(
            "busy",
            "runs_unsettled",
            "결과를 확정할 수 없는 실행이 남아 있다: "
            + ", ".join(r["run_id"] for r in state.unsettled_runs),
        )
    unresolved = state.unresolved
    objectives = [u for u in unresolved if u.get("kind") == "objective_without_criteria"]
    if objectives:
        return _wait(
            WaitReason.OBJECTIVE_WITHOUT_CRITERIA, obligations=[u["id"] for u in objectives]
        )
    questions = [u for u in unresolved if u.get("kind") == "open_intent_question"]
    if questions:
        return _wait(WaitReason.INTENT_QUESTIONS)
    feedback = [u for u in unresolved if u.get("kind") == "unresolved_feedback"]
    if feedback:
        return _wait(WaitReason.UNRESOLVED_FEEDBACK, feedback_ids=[u["id"] for u in feedback])
    criteria = [u for u in unresolved if u.get("kind") == "criterion"]
    if not state.criteria:
        return _wait(
            WaitReason.CRITERIA_UNRESOLVED,
            detail="성공 기준이 없어 완료를 판정할 수 없다. 의도에 기준이 필요하다",
        )
    controlled = state.checkpoint.get("required") and not state.checkpoint.get("result_confirmed")
    if criteria:
        if state.candidate is None:
            return Step("candidate", "candidate", "종료 후보를 만든다")
        return _wait(
            WaitReason.CRITERIA_UNRESOLVED,
            candidate_id=state.candidate.get("id"),
            criteria=[{"id": u["id"], "key": u.get("key"), "verdict": u.get("verdict")} for u in criteria],
        )
    if state.completion_mode != CompletionMode.AUTO_ON_CONDITIONS.value or controlled:
        if state.candidate is None:
            return Step("candidate", "candidate", "종료 후보를 만든다")
        return _wait(
            WaitReason.CONTROLLED_RESULT,
            candidate_id=state.candidate.get("id"),
            snapshot_hash=state.candidate.get("snapshot_hash"),
        )
    # 조건이 전부 갖춰졌는데 닫히지 않았다 — 자동 완료는 기준 판정·실행 종료 때 스스로 시도한다.
    # 여기 오는 것은 그 시도가 거부된 경우(예: 미확인 변경)이고, 후보를 만들어 사유를 드러낸다.
    if state.candidate is None:
        return Step("candidate", "candidate", "자동 완료 조건을 확인한다")
    return _wait(
        WaitReason.CONTROLLED_RESULT,
        detail="자동 완료가 확정되지 않았다. 후보의 거부 사유를 본다",
        candidate_id=state.candidate.get("id"),
    )


# ================================================================ 기준 보고


#: 검증·분석 실행이 보고하는 판정 값.
REPORTABLE_VERDICTS: frozenset[str] = frozenset(
    {CriterionVerdict.MET.value, CriterionVerdict.NOT_MET.value, CriterionVerdict.UNVERIFIED.value}
)


def parse_criteria_report(value: Any) -> list[dict[str, Any]]:
    """Runner 가 보낸 기준 보고를 읽는다. **모르는 값은 버린다** — 지어내지 않는다.

    한 항목은 `{key, verdict, conclusion?, summary?}` 이며 요약은 200자에서 자른다.
    """
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    for raw in value:
        if not isinstance(raw, dict):
            continue
        key = str(raw.get("key") or "").strip()
        verdict = str(raw.get("verdict") or "").strip()
        if not key or verdict not in REPORTABLE_VERDICTS:
            continue
        item: dict[str, Any] = {"key": key[:64], "verdict": verdict}
        conclusion = raw.get("conclusion")
        if conclusion in (Conclusion.DETERMINED.value, Conclusion.INCONCLUSIVE.value):
            item["conclusion"] = conclusion
        summary = " ".join(str(raw.get("summary") or "").split())
        if summary:
            item["summary"] = summary[:200]
        out.append(item)
    return out


@dataclass(frozen=True)
class CriterionDecision:
    """보고 한 건을 어떻게 적는가. `record=False` 면 적지 않고 `reason` 을 남긴다."""

    key: str
    criterion_id: str | None
    record: bool
    verdict: str | None = None
    satisfaction: str | None = None
    conclusion: str | None = None
    summary: str = ""
    reason: str | None = None


def decide_criteria(
    *,
    report: list[dict[str, Any]],
    run: dict[str, Any],
    commands: list[dict[str, Any]],
    criteria: list[dict[str, Any]],
    linked_ids: set[str] | None,
    product_change_observed: bool,
    contract_applies: bool,
) -> list[CriterionDecision]:
    """기준 보고를 **구조 검사**로 거른다(P4-05 plan 3.4).

    `linked_ids` 가 `None` 이면 연결 검사를 하지 않는다(조사 Profile 의 분석 실행 — 그래프가
    없다). 검증 실행은 종료 코드 0 인 명령이 하나라도 있어야 `met` 을 적는다(P3-04 하네스 규칙).
    미충족·미검증 보고는 그대로 적는다 — 실패를 없던 일로 만들지 않는다.
    """
    by_key = {c["criterion_key"]: c for c in criteria}
    purpose = run.get("purpose")
    completed = run.get("outcome") == RunOutcome.COMPLETED.value
    succeeded = any(c.get("exit_code") == 0 for c in commands)
    decisions: list[CriterionDecision] = []
    for item in report:
        key = item["key"]
        criterion = by_key.get(key)
        if criterion is None:
            decisions.append(CriterionDecision(key, None, False, reason="unknown_criterion"))
            continue
        cid = criterion["id"]
        if linked_ids is not None and cid not in linked_ids:
            decisions.append(CriterionDecision(key, cid, False, reason="unlinked"))
            continue
        if criterion.get("verdict") == CriterionVerdict.MET.value and (
            criterion.get("evidence_run_id") not in (None, run.get("run_id"))
        ):
            # 이미 다른 실행의 근거로 충족된 기준은 덮어쓰지 않는다. 판정을 낮추는 보고는 받는다.
            if item["verdict"] == CriterionVerdict.MET.value:
                decisions.append(CriterionDecision(key, cid, False, reason="already_met"))
                continue
        verdict = item["verdict"]
        summary = item.get("summary") or f"{purpose} 실행 {run.get('run_id')} 의 보고"
        conclusion: str | None = item.get("conclusion")
        satisfaction: str | None = None
        obligation = criterion.get("obligation") if contract_applies else None
        if verdict == CriterionVerdict.MET.value:
            if not completed:
                decisions.append(CriterionDecision(key, cid, False, reason="run_not_completed"))
                continue
            if purpose == RunPurpose.VERIFICATION_RUN.value and not succeeded:
                decisions.append(
                    CriterionDecision(key, cid, False, reason="no_successful_command")
                )
                continue
            if obligation in (CriterionObligation.CAUSE.value, CriterionObligation.ANSWER.value):
                satisfaction = Satisfaction.INVESTIGATED.value
                if conclusion is None:
                    conclusion = Conclusion.DETERMINED.value
                if conclusion == Conclusion.INCONCLUSIVE.value and (
                    criterion.get("conclusion_rule") or ConclusionRule.DEFINITIVE_REQUIRED.value
                ) == ConclusionRule.DEFINITIVE_REQUIRED.value:
                    # 확정 필수 기준의 판단 불가는 충족이 아니다(P4-03). 미충족으로 적는다.
                    verdict = CriterionVerdict.NOT_MET.value
                    summary = (summary + " · 판단 불가(확정 필수)")[:200]
            elif obligation == CriterionObligation.PRESERVATION.value:
                satisfaction = Satisfaction.PRESERVED.value
            elif obligation is not None or not contract_applies:
                satisfaction = (
                    Satisfaction.CHANGED_AND_VERIFIED.value
                    if product_change_observed
                    else Satisfaction.ALREADY_SATISFIED.value
                )
        else:
            if obligation not in (
                CriterionObligation.CAUSE.value,
                CriterionObligation.ANSWER.value,
            ):
                conclusion = None
        decisions.append(
            CriterionDecision(
                key,
                cid,
                True,
                verdict=verdict,
                satisfaction=satisfaction,
                conclusion=conclusion,
                summary=summary[:200],
            )
        )
    return decisions


# ================================================================ 요청 종료 값


def settle_note(step: Step) -> str:
    """요청을 끝낼 때 `note_summary` 에 남기는 사유 코드."""
    if step.kind == "wait":
        return f"waiting: {step.code}"[:200]
    if step.kind == "blocked":
        return f"blocked: {step.code}"[:200]
    if step.kind == "done":
        return "done"
    return f"{step.kind}: {step.code}"[:200]


def finished_summary(run: dict[str, Any]) -> dict[str, Any]:
    """진행 판정이 보는 끝난 실행의 요약. 본문 없음."""
    return {
        "run_id": run["run_id"],
        "purpose": run.get("purpose"),
        "task_id": run.get("task_id"),
        "outcome": run.get("outcome"),
        "status": run.get("status"),
    }


def is_unfinished(run: dict[str, Any]) -> bool:
    return run.get("status") != RunStatus.FINISHED.value
