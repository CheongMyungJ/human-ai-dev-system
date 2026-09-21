"""P2-01 최소 영속 모델의 상태값과 자료 구조.

상태값 집합은 설계 문서의 구분을 그대로 옮긴 것이다. 편의를 위해 값을 합치지 않는다.
특히 다음 세 가지는 서로 다른 기록이며 하나가 다른 하나를 만들지 않는다.

  - Decision(사람의 결정: 의도 동의 / 검토 / 최종 인수 / 예외 수용 / 외부 반영 승인)
  - Run 의 outcome(실행 결과)
  - ArtifactRef 의 availability(원문을 실제로 읽을 수 있는지)

design-draft.md "실행 모델과 상태", FR-23, NFR-03, p1-environment-contract.md 6~7절을 따른다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CaseStatus(str, Enum):
    """Case 진행 상태. design-draft.md "실행 모델과 상태"의 구분."""

    RECEIVED = "received"
    IN_PROGRESS = "in_progress"
    WAITING_HUMAN = "waiting_human"
    WAITING_ENVIRONMENT = "waiting_environment"
    PAUSED = "paused"
    WAITING_FINAL_ACCEPTANCE = "waiting_final_acceptance"
    CLOSED = "closed"
    CANCELLED = "cancelled"


class CaseKind(str, Enum):
    """업무 유형. 기능 개발만 의도 동의·설계·계획 선행 조건을 받는다(FR-03, FR-29).

    P2-01은 유형을 기록만 하고 진입 조건 검사는 P2-03에서 붙인다.
    """

    FEATURE = "feature"
    BUG = "bug"
    ANALYSIS = "analysis"
    RESEARCH = "research"


class IntentStatus(str, Enum):
    """의도 버전의 상태. `agreed` 는 사람의 명시적 동의가 있을 때만 쓴다(FR-03)."""

    DRAFT = "draft"
    AGREED = "agreed"
    SUPERSEDED = "superseded"


class DecisionKind(str, Enum):
    """사람의 결정 종류. FR-23은 이들을 서로 구별해 기록하라고 요구한다.

    하나를 다른 하나로 확대하지 않는다. 예: 의도 동의는 push 승인이 아니다.
    """

    INTENT_AGREEMENT = "intent_agreement"
    DESIGN_REVIEW = "design_review"
    PLAN_REVIEW = "plan_review"
    FINAL_ACCEPTANCE = "final_acceptance"
    EXCEPTION_CLOSURE = "exception_closure"
    PUSH_APPROVAL = "push_approval"
    PUBLICATION_GRANT = "publication_grant"


class RunStatus(str, Enum):
    """제어부가 보는 Run의 진행 상태."""

    PENDING = "pending"
    ASSIGNED = "assigned"
    RUNNING = "running"
    FINISHED = "finished"


class RunOutcome(str, Enum):
    """실행 결과. p1-environment-contract.md 7.2 절의 계약을 그대로 쓴다.

    `UNKNOWN` 은 정식 값이다. 실패로도 성공으로도 바꾸지 않는다.
    종료 코드만으로 `COMPLETED` 를 쓰지 않는다(FR-28).
    """

    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class EventType(str, Enum):
    """정규화 이벤트 종류. p1-environment-contract.md 7.1 절.

    CLI가 제공하지 않는 종류는 비워 두고 추정으로 채우지 않는다.
    """

    RUN_STARTED = "run_started"
    SESSION_IDENTIFIED = "session_identified"
    ASSISTANT_MESSAGE = "assistant_message"
    TOOL_CALL_STARTED = "tool_call_started"
    TOOL_CALL_FINISHED = "tool_call_finished"
    PERMISSION_REQUESTED = "permission_requested"
    PERMISSION_DECIDED = "permission_decided"
    USAGE_REPORTED = "usage_reported"
    ERROR = "error"
    RUN_FINISHED = "run_finished"


class Permission(str, Enum):
    """추상 권한. CLI별 매핑은 어댑터가 하며 매핑 불가는 실행 거부다(P1 계약 6절)."""

    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    EXPLICIT_ESCALATED = "explicit_escalated"


class RunRole(str, Enum):
    """실행 역할. 의미 검토는 작성과 별도 세션이어야 한다(FR-29)."""

    AUTHOR = "author"
    REVIEWER = "reviewer"


class CapabilityState(str, Enum):
    """CLI 능력의 확인 상태. p1-environment-contract.md 8절.

    "도움말에 옵션이 있음"을 "지원함"으로 승격시키지 않기 위해 네 값을 유지한다.
    """

    DOC_ONLY = "doc_only"
    VERIFIED = "verified"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class Availability(str, Enum):
    """원문을 지금 읽을 수 있는지. 없음을 빈 문서나 삭제로 표시하지 않는다(D-51).

    `PENDING`  아직 Runner가 영속 저장했다고 보고하지 않음 → 저장 완료가 아니다
    `AVAILABLE` 소유 Runner가 영속 저장을 확인함
    `RUNNER_OFFLINE` 참조는 있으나 소유 Runner에 지금 닿지 않음
    `LOST_BEFORE_PERSIST` 제어부가 중계 중이던 원문이 영속 저장 전에 사라짐
    """

    PENDING = "pending"
    AVAILABLE = "available"
    RUNNER_OFFLINE = "runner_offline"
    LOST_BEFORE_PERSIST = "lost_before_persist"


class ArtifactKind(str, Enum):
    """원문 종류. 서버는 이 분류와 참조만 갖고 본문은 갖지 않는다.

    `DESIGN`·`DEV_PLAN` 은 P3-01에서 더했다. 두 종류를 하나로 합치지 않는 이유는
    "설계와 개발계획을 각각 조회할 수 있어야 한다"(intent-artifacts 2절)가
    저장 분류에서부터 지켜져야 하기 때문이다.
    """

    INTENT = "intent"
    FEEDBACK = "feedback"
    INSTRUCTION = "instruction"
    RUN_OUTPUT = "run_output"
    DESIGN = "design"
    DEV_PLAN = "dev_plan"


@dataclass(frozen=True)
class ArtifactRef:
    """원문 참조. data-boundary-review.md 1절이 정한 다섯 항목.

    실제 경로는 담지 않는다. Runner가 허용 저장소 안에서 해석한다.
    """

    artifact_id: str
    revision: int
    content_hash: str
    owner_runner_id: str
    availability: Availability

    def to_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "revision": self.revision,
            "content_hash": self.content_hash,
            "owner_runner_id": self.owner_runner_id,
            "availability": self.availability.value,
        }


@dataclass(frozen=True)
class RunRequest:
    """제어부가 Runner에 보내는 실행 요청. p1-environment-contract.md 6절의 의미 단위.

    CLI 인자 형태에 종속되지 않는다(NFR-07). `secrets` 항목은 없다 —
    시스템은 CLI 자격증명을 읽지도 주입하지도 않는다.
    """

    run_id: str
    case_id: str
    task_id: str
    role: RunRole
    assignment_generation: int
    tool_id: str
    mode: str
    permission: Permission
    instruction_ref: ArtifactRef
    context_refs: list[ArtifactRef] = field(default_factory=list)
    model: str | None = None
    workspace: dict[str, Any] | None = None
    writable_paths: list[str] = field(default_factory=list)
    output_schema: str | None = None
    session: str = "new"
    limits: dict[str, Any] | None = None


@dataclass(frozen=True)
class RunResult:
    """실행 결과. p1-environment-contract.md 7.2절.

    `usage` 가 없으면 `not_reported` 로 남긴다. 0으로 표시하지 않는다.
    `residual_activity` 를 확인할 수 없으면 `unknown` 이다.
    """

    run_id: str
    outcome: RunOutcome
    exit_code: int | None = None
    final_output_ref: ArtifactRef | None = None
    session_ref: str | None = None
    usage: dict[str, Any] | str = "not_reported"
    workspace_effect: dict[str, Any] | None = None
    residual_activity: str = "unknown"
    observed_tool_version: str | None = None


# --------------------------------------------------------------------- P2-02


class IntentField(str, Enum):
    """의도 초안의 필수 여섯 항목(intent-artifacts.md 1절).

    이 집합은 줄이지 않는다. 정보가 없는 항목도 행으로 남기고 `UNDECIDED` 로 표시한다.
    """

    GOAL = "goal"
    EXPECTED_OUTCOME = "expected_outcome"
    SCOPE = "scope"
    EXCLUSIONS = "exclusions"
    CONSTRAINTS = "constraints"
    OPEN_QUESTIONS = "open_questions"


class ConfirmationState(str, Enum):
    """항목의 확인 상태(intent-artifacts.md 3절 "확인 상태").

    `USER_CONFIRMED` 는 실제 확인 근거가 있는 항목에만 쓴다.
    """

    UNDECIDED = "undecided"
    PROPOSED = "proposed"
    USER_CONFIRMED = "user_confirmed"
    NEEDS_RECHECK = "needs_recheck"
    SUPERSEDED = "superseded"


class ContentOrigin(str, Enum):
    """내용의 성격(FR-04, intent-artifacts.md 3절).

    AI 추정을 확정 요구로 표시하지 않기 위해 값을 합치지 않는다.
    `NONE` 은 "아직 아무 내용이 없다"이며 출처가 불명이라는 뜻이 아니다.
    """

    NONE = "none"
    USER_REQUIREMENT = "user_requirement"
    PROJECT_RULE = "project_rule"
    OBSERVATION = "observation"
    AI_PROPOSAL = "ai_proposal"
    AI_ASSUMPTION = "ai_assumption"


class FieldChange(str, Enum):
    """이전 의도 버전과 비교한 항목 단위 변화."""

    INITIAL = "initial"
    UNCHANGED = "unchanged"
    CHANGED = "changed"


class DecideAt(str, Enum):
    """질문을 어느 단계에서 결정하는지(intent-artifacts.md 2절, FR-03 질문 처리).

    `INTENT` 질문은 의도 단계에서 사람이 결정해야 한다.
    `DESIGN`/`PLAN` 은 그 단계와 의존 작업을 표시해 이월한 질문이다.
    """

    INTENT = "intent"
    DESIGN = "design"
    PLAN = "plan"


class QuestionState(str, Enum):
    OPEN = "open"
    ANSWERED = "answered"
    WITHDRAWN = "withdrawn"


class FeedbackState(str, Enum):
    """피드백의 처리 상태.

    `NOT_REFLECTED` 는 이유를 함께 남긴다. 반영하지 않은 것을 조용히 닫지 않는다.
    """

    RECEIVED = "received"
    REFLECTED = "reflected"
    NOT_REFLECTED = "not_reflected"


class ReadRequestState(str, Enum):
    """원문 열람 요청의 상태(data-boundary-review.md 3절).

    `PENDING`   소유 Runner가 아직 가져가지 않음 → 화면은 "PC 연결 필요"로 표시한다
    `RELAYED`   Runner가 올린 본문이 제어부 **메모리에만** 있다
    `DELIVERED` 브라우저가 한 번 받아 갔고 버퍼에서 버렸다
    `EXPIRED`   중계 중이던 본문이 사라졌다(대표 사례: 제어부 재시작)
    """

    PENDING = "pending"
    RELAYED = "relayed"
    DELIVERED = "delivered"
    EXPIRED = "expired"


class IntentAgreementState(str, Enum):
    """Case 수준에서 본 의도 동의 상태(FR-03, FR-23).

    `STALE_AGREEMENT` 가 핵심이다. 과거 버전에 대한 동의는 기록으로 남지만
    최신 버전에 적용되지 않는다. 이 상태를 `AGREED_CURRENT` 로 승격시키지 않는다.
    """

    NO_INTENT = "no_intent"
    NEVER_AGREED = "never_agreed"
    STALE_AGREEMENT = "stale_agreement"
    AGREED_CURRENT = "agreed_current"


class AgreementRefusal(str, Enum):
    """동의를 기록할 수 없는 이유.

    **이것은 FR-29 진입 조건 검사가 아니다.** 실행 배정을 여는 조건이 아니라
    "사람의 동의를 기록할 수 있는가"의 조건이며, P2-03에서 붙일 진입 검사와 구별한다.
    """

    NOT_EXPLICIT = "not_explicit"
    NOT_LATEST_VERSION = "not_latest_version"
    ORIGINAL_NOT_AVAILABLE = "original_not_available"
    ORIGINAL_NOT_READ = "original_not_read"
    CONTENT_CHANGED = "content_changed"
    OPEN_INTENT_QUESTIONS = "open_intent_questions"


# --------------------------------------------------------------------- P2-03


class RunPurpose(str, Enum):
    """실행의 목적. **진입 조건은 목적마다 다르다**(FR-29).

    목적을 도입한 이유는 순환을 피하기 위해서다. 의도 초안을 **쓰는** 실행에
    "최신 의도에 동의했는가"를 요구하면 어떤 Case도 시작할 수 없다. 반대로 모든
    실행에서 조건을 빼면 진입 검사가 무의미해진다. 그래서 목적별 조건표를 둔다
    (plans/P2-PLAN-03.md "목적별 진입 조건표").

    `FEATURE_IMPLEMENTATION` 은 정의만 있고 이번 단계에서는 **항상 거부된다.**
    선행 조건인 설계·계획 검토가 아직 없기 때문이며, 없는 조건을 통과로
    처리하지 않는다는 P2 제외 범위를 코드로 드러내기 위한 값이다.
    """

    INTENT_AUTHORING = "intent_authoring"
    INTENT_GATE_REVIEW = "intent_gate_review"
    LIMITED_ANALYSIS = "limited_analysis"
    #: P3-01. 설계와 계획은 **서로 다른 목적**이다. 하나로 합치면 두 산출물의
    #: 검토가 한 실행에 묶여 "각각 독립적인 검토 옵션"을 지킬 수 없다.
    DESIGN_AUTHORING = "design_authoring"
    PLAN_AUTHORING = "plan_authoring"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    #: P3-03. 빌드·테스트를 작업공간에서 실행하고 명령·종료 코드를 증거로 남긴다.
    #: 구현과 **별도 목적**인 이유는 완료 판정이 다르기 때문이다 — 구현은 작업공간
    #: 변화가 있어야 완료이고, 검증은 실제로 실행된 명령이 있어야 완료다.
    VERIFICATION_RUN = "verification_run"


class AdmissionOutcome(str, Enum):
    ADMITTED = "admitted"
    REFUSED = "refused"


class AdmissionProfile(str, Enum):
    """어떤 조건표를 적용했는지.

    `FEATURE_INTENT` 는 의도 동의·게이트를 요구하는 기능 개발 조건표다.
    Case의 `kind` 가 아니라 **의도 버전의 존재**로 정한다 — 유형만 바꿔서
    조건을 벗어나지 못하게 하기 위해서다(FR-29 "유형 변경으로 우회하지 않는다").
    """

    FEATURE_INTENT = "feature_intent"
    NON_FEATURE_MINIMAL = "non_feature_minimal"
    INTENT_PRODUCTION = "intent_production"


class AdmissionRefusal(str, Enum):
    """진입을 거부한 이유.

    **P2-02의 `AgreementRefusal` 과 다른 검사다.** 저쪽은 "사람의 동의를 기록할 수
    있는가", 이쪽은 "실행을 배정해도 되는가"이다. 두 목록을 합치지 않는다.
    """

    INTENT_NOT_AGREED = "intent_not_agreed"
    OPEN_INTENT_QUESTIONS = "open_intent_questions"
    INTENT_GATE_NOT_PASSED = "intent_gate_not_passed"
    INTENT_ORIGINAL_NOT_AVAILABLE = "intent_original_not_available"
    INSTRUCTION_NOT_AVAILABLE = "instruction_not_available"
    PERMISSION_NOT_ALLOWED_IN_STAGE = "permission_not_allowed_in_stage"
    PERMISSION_NOT_MAPPED = "permission_not_mapped"
    ROLE_MISMATCH = "role_mismatch"
    #: **P3-01부터 발급하지 않는다.** 실제 선행 조건 검사가 아래 사유들로 대체했다.
    #: 값을 지우지 않는 이유는 P2-03·P2-04가 남긴 진입 검사 기록이 이 코드를 갖고
    #: 있어서다 — 값을 지우면 과거 기록을 읽을 수 없다.
    PREREQUISITE_NOT_IMPLEMENTED = "prerequisite_not_implemented"
    TOOL_NOT_AVAILABLE = "tool_not_available"
    TOOL_IS_NOT_A_CODING_CLI = "tool_is_not_a_coding_cli"
    REVIEW_SESSION_NOT_SEPARATE = "review_session_not_separate"
    INTENT_VERSION_MISSING = "intent_version_missing"
    INTENT_VERSION_NOT_LATEST = "intent_version_not_latest"
    CASE_ALREADY_CLOSED = "case_already_closed"

    # --- P3-01: 실제 선행 조건 -------------------------------------------
    #
    # 위의 `PREREQUISITE_NOT_IMPLEMENTED` 를 대신한다. 아래 사유들은 **없는 조건을
    # 통과로 처리하지 않는다**는 같은 원칙의 구체적 구현이며, 사람이 무엇을 갖춰야
    # 하는지 한 번에 알 수 있도록 종류별로 나눠 둔다(FR-29 수용 기준, FR-14).
    SIZING_NOT_DECIDED = "sizing_not_decided"
    DESIGN_MISSING = "design_missing"
    DESIGN_STALE = "design_stale"
    DESIGN_INCOMPLETE_FOR_LEVEL = "design_incomplete_for_level"
    DESIGN_REVIEW_MISSING = "design_review_missing"
    PLAN_MISSING = "plan_missing"
    PLAN_STALE = "plan_stale"
    PLAN_INCOMPLETE_FOR_LEVEL = "plan_incomplete_for_level"
    PLAN_REVIEW_MISSING = "plan_review_missing"
    #: **P3-02에서 범위가 좁아졌다.** Case 전체가 아니라 그 결정에 의존하는 Task 를
    #: 막는다. 새 코드를 만들지 않는 이유는 사람이 해야 할 일("그 질문에 답하라")이
    #: 같기 때문이다. 다만 **연결된 Task 가 하나도 없는 질문은 여전히 전부 막는다** —
    #: 좁히는 것이 느슨해지는 것이 되지 않게 하는 지점이다.
    DEFERRED_QUESTIONS_UNRESOLVED = "deferred_questions_unresolved"

    # --- P3-02: 작업 그래프 ------------------------------------------------
    #
    # 준비(설계·계획) 조건 **위에 얹히는** 조건이며 대체하지 않는다. 계획 검토가
    # 끝났다는 사실과 무엇을 어떤 순서로 만들지가 정해졌다는 사실은 다른 것이다.
    WORK_GRAPH_MISSING = "work_graph_missing"
    WORK_GRAPH_STALE = "work_graph_stale"
    TASK_NOT_IN_WORK_GRAPH = "task_not_in_work_graph"
    TASK_DEPENDENCIES_UNMET = "task_dependencies_unmet"

    # --- P3-03 작업공간·쓰기 경합 ---------------------------------------
    #
    # `permission_not_allowed_in_stage` 는 **없어지지 않는다.** 의도·설계·계획
    # 목적의 쓰기 요청과 `explicit_escalated` 는 계속 그 사유로 거부된다.
    # 아래 넷은 "쓰기를 열 수 있는 목적인데 작업공간·경합 조건이 아니다" 이다.
    WORKSPACE_NOT_READY = "workspace_not_ready"
    WORKSPACE_FAILED = "workspace_failed"
    CASE_WRITE_IN_PROGRESS = "case_write_in_progress"


class GateId(str, Enum):
    """이번 단계가 구현하는 게이트. QG-02~07은 아직 값으로 두지 않는다 —
    정의만 있고 동작이 없는 게이트를 상태표에 노출하지 않기 위해서다."""

    QG_01 = "QG-01"


class GateVerdict(str, Enum):
    """게이트 판정. quality-gates.md 3절의 목록을 그대로 쓴다.

    **`NOT_RUN` 을 `PASS` 로 승격시키지 않는 것이 핵심이다.** 규칙 검사만 하고
    AI 의미 검토를 실행하지 않은 상태는 통과가 아니다(quality-gates 4절 A·D 구분).
    `BLOCKED` 는 검사를 수행할 수 없었던 상태(예: CLI 미설치)이며 실패와 다르다.
    """

    PASS = "pass"
    FAIL = "fail"
    HOLD = "hold"
    NOT_RUN = "not_run"
    NEEDS_RECHECK = "needs_recheck"
    BLOCKED = "blocked"
    NOT_APPLICABLE = "not_applicable"


class FindingSource(str, Enum):
    RULE = "rule"
    AI = "ai"


class FindingSeverity(str, Enum):
    """필수 기준 위반과 권고를 구분한다(quality-gates 3절).

    "AI의 막연한 의견이 새 필수 요구를 만들지는 않는다" — AI가 올린 발견은
    기본적으로 권고이며, 필수로 올리려면 연결된 기준이 있어야 한다.
    """

    REQUIRED = "required"
    ADVISORY = "advisory"


class FindingCertainty(str, Enum):
    """증거가 있는 위반과 의심을 구분한다. 의심을 확정 실패로 과장하지 않는다."""

    CONFIRMED = "confirmed"
    SUSPECTED = "suspected"


class AuthoringMode(str, Enum):
    """의도 초안을 **실제로 누가 썼는가.**

    P2-02는 사람만 가능했고 그 사실을 문서에 적었다. P2-03에서 AI 작성 경로가
    생겼으므로 두 값을 구분해 기록한다. 실제와 다른 값을 적지 않는다(FR-04).
    """

    HUMAN_TYPED = "human_typed"
    AI_DRAFTED = "ai_drafted"


# --------------------------------------------------------------------- P2-04


class CriterionState(str, Enum):
    """성공 기준의 확인 상태(intent-artifacts.md 1절).

    "초안 단계의 기준은 제안이며, 사용자가 확인한 기준과 구별한다."
    `USER_CONFIRMED` 는 사람이 그 의도 버전의 원문을 읽고 명시 동의했을 때만 붙는다.
    """

    PROPOSED = "proposed"
    USER_CONFIRMED = "user_confirmed"
    SUPERSEDED = "superseded"


class CriterionVerdict(str, Enum):
    """기준별 결과.

    **`UNVERIFIED` 가 기본값이다.** 실행이 끝났다는 사실이 판정을 만들지 않는다.

    **`unknown` 이 이 목록에 없는 것이 중요하다.** 실행의 불명은 `RunOutcome.UNKNOWN`
    이며 거기 머문다. 불명인 실행을 근거로 한 `MET` 은 기록 자체가 거부된다.
    불명을 기준 판정으로 옮기면 불명이 조용히 판정이 되어 버린다
    (FR-28, completion-lifecycle.md 5절).

    `BLOCKED` 는 확인할 수 없었던 상태이며 `NOT_MET` 과 다르다.
    """

    UNVERIFIED = "unverified"
    MET = "met"
    NOT_MET = "not_met"
    BLOCKED = "blocked"
    NEEDS_RECHECK = "needs_recheck"


class EvidenceKind(str, Enum):
    """판정의 근거 종류. 근거 없는 판정은 기록하지 않는다."""

    NONE = "none"
    RUN_OUTPUT = "run_output"
    HUMAN_JUDGEMENT = "human_judgement"


class CompletionMode(str, Enum):
    """완료 정책(D-31). 기본은 사람 최종 확인이다."""

    HUMAN_ACCEPTANCE = "human_acceptance"
    AUTO_ON_CONDITIONS = "auto_on_conditions"


class AcceptanceMode(str, Enum):
    """인수를 만든 주체. **자동 완료를 사람 확인으로 적지 않는다**(FR-17)."""

    HUMAN = "human"
    AUTO_POLICY = "auto_policy"


class ClosureKind(str, Enum):
    """종료의 종류.

    `CANCELLED` 는 성공도 예외 인수도 아니다(completion-lifecycle.md 2절).
    `CLOSED_WITH_EXCEPTIONS` 는 원래 판정을 보존한 채 사람이 수용한 종료다.
    """

    COMPLETED = "completed"
    CLOSED_WITH_EXCEPTIONS = "closed_with_exceptions"
    CANCELLED = "cancelled"


class CandidateState(str, Enum):
    OPEN = "open"
    SUPERSEDED = "superseded"


class AcceptanceRefusal(str, Enum):
    """최종 인수·예외 수용을 기록할 수 없는 이유.

    **세 번째 독립 목록이다.** P2-02의 `AgreementRefusal` 은 "사람의 동의를 기록할
    수 있는가", P2-03의 `AdmissionRefusal` 은 "실행을 배정해도 되는가", 이쪽은
    "이 후보를 종료로 확정해도 되는가"를 본다. 세 목록을 합치지 않는다(FR-23).
    """

    NOT_EXPLICIT = "not_explicit"
    CANDIDATE_SUPERSEDED = "candidate_superseded"
    UNRESOLVED_CRITERIA = "unresolved_criteria"
    NO_SUCCESS_CRITERIA = "no_success_criteria"
    OPEN_INTENT_QUESTIONS = "open_intent_questions"
    UNRESOLVED_FEEDBACK = "unresolved_feedback"
    UNSETTLED_RUNS_PRESENT = "unsettled_runs_present"
    INTENT_NOT_AGREED = "intent_not_agreed"
    CASE_ALREADY_CLOSED = "case_already_closed"
    AUTO_POLICY_CANNOT_ACCEPT_EXCEPTION = "auto_policy_cannot_accept_exception"
    EXCEPTION_TARGET_NOT_FAILING = "exception_target_not_failing"


class CaseRelationKind(str, Enum):
    """Case 사이의 연결. 완료 후 수정은 재개가 아니라 연결된 새 Case 다(D-33)."""

    FOLLOW_UP_CHANGE = "follow_up_change"


# --------------------------------------------------------------------- P3-01


class WorkLevel(str, Enum):
    """작업 수준(D-13, sizing-and-review-ux.md 2절).

    **크기가 아니라 필요한 준비·검증의 깊이**를 표현한다. 변경 줄 수·파일 수로
    정하지 않는다. 순서가 있는 값이며 `ORDER` 로 비교한다 — "AI가 진행을 위해
    수행 수준을 묵시적으로 낮추는 것"을 막으려면 높낮이를 비교할 수 있어야 한다.
    """

    SIMPLE = "simple"
    STANDARD = "standard"
    DEEP = "deep"


#: 수준의 높낮이. `max()` 로 비교하기 위한 순서이며 점수가 아니다.
WORK_LEVEL_ORDER: dict[WorkLevel, int] = {
    WorkLevel.SIMPLE: 0,
    WorkLevel.STANDARD: 1,
    WorkLevel.DEEP: 2,
}


class SizingAxis(str, Enum):
    """수준 판단의 일곱 축(sizing-and-review-ux.md 1절 표).

    축을 줄이지 않는다. 축마다 `판단 / 아직 확인할 것 / 준비·검증에 주는 영향`을
    따로 남기며 **숫자 점수로 합산하지 않는다** — 낮은 항목의 평균으로 권한·
    마이그레이션 같은 중요한 영향을 상쇄하지 않기 위해서다.
    """

    INTENT_CLARITY = "intent_clarity"
    CHANGE_SCOPE = "change_scope"
    COMPATIBILITY_AND_DATA = "compatibility_and_data"
    PERMISSION_AND_SECURITY = "permission_and_security"
    REVERSIBILITY = "reversibility"
    UNCERTAINTY = "uncertainty"
    VERIFICATION_DIFFICULTY = "verification_difficulty"


class AxisWeight(str, Enum):
    """그 축이 준비·검증 깊이에 주는 영향.

    `INSUFFICIENT_EVIDENCE` 를 따로 두는 것이 핵심이다. 근거가 부족한 축을 `LOW` 로
    적으면 모르는 것이 "영향 없음"이 된다. 부족은 부족으로 드러내고 조사 작업을
    제시한다(sizing-and-review-ux 2절 "불확실할 때는 근거가 부족함을 표시").
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SizingSource(str, Enum):
    """수준 판단을 만든 주체. **세 경우를 합치지 않는다**(FR-04).

    `AI_RECOMMENDATION` AI가 쓴 의도 초안 안의 판단
    `HUMAN_ASSESSMENT`  사람이 직접 쓴 의도 초안 안의 판단. 조정이 아니다 —
                        조정할 이전 판단이 없는데 "조정"으로 적으면 기록이 거짓이 된다
    `HUMAN_ADJUSTMENT`  사람이 기존 판단을 상향·하향한 것. 이유와 남는 위험이 필수다
    """

    AI_RECOMMENDATION = "ai_recommendation"
    HUMAN_ASSESSMENT = "human_assessment"
    HUMAN_ADJUSTMENT = "human_adjustment"


class SizingState(str, Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"


class PreparationStage(str, Enum):
    """준비 산출물의 단계. **두 단계는 각각 조회·검토된다**(intent-artifacts 2절)."""

    DESIGN = "design"
    PLAN = "plan"


class ReviewMode(str, Enum):
    """단계별 검토 방식. **프로젝트 기본값은 두 단계 모두 사람 검토다**(D-14).

    설정 행이 없는 상태는 `HUMAN_REVIEW` 다. 없음을 자동 진행으로 읽으면 기본값이
    조용히 뒤집힌다.
    """

    HUMAN_REVIEW = "human_review"
    AUTO_PROCEED = "auto_proceed"


class StageReviewState(str, Enum):
    """단계 검토의 현재 상태.

    **`AUTO_CONDITIONS_MET` 을 `HUMAN_REVIEWED` 로 적지 않는다.** 자동 진행의 결과는
    "자동 조건 충족"이며 사람 승인 기록이 아니다(sizing-and-review-ux 2·5절).
    """

    NOT_READY = "not_ready"
    AWAITING_HUMAN_REVIEW = "awaiting_human_review"
    #: 자동 진행 설정인데 조건 충족이 아직 기록되지 않은 상태. `NOT_READY` 와 합치지
    #: 않는 이유는 산출물이 **있는데도** "산출물 준비 전"으로 보이면 사람이 무엇을
    #: 해야 하는지 알 수 없기 때문이다.
    AWAITING_AUTO_CONDITIONS = "awaiting_auto_conditions"
    HUMAN_REVIEWED = "human_reviewed"
    AUTO_CONDITIONS_MET = "auto_conditions_met"
    NEEDS_RECHECK = "needs_recheck"


class PreparationState(str, Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"


class ContextRefRole(str, Enum):
    """작성 실행에 고정한 참조의 역할(review-context-contract 2절).

    **이것이 P2-04가 남긴 위험 1의 해소다.** 재작성 실행에 이전 버전을 고정해 주지
    않으면 AI가 산출물을 처음부터 다시 써서 퇴화한다. 실제로 그렇게 됐다.
    """

    PREVIOUS_INTENT = "previous_intent"
    AGREED_INTENT = "agreed_intent"
    PREVIOUS_DESIGN = "previous_design"
    CURRENT_DESIGN = "current_design"
    PREVIOUS_PLAN = "previous_plan"
    FEEDBACK = "feedback"


# --------------------------------------------------------------------- P3-02


class TaskKind(str, Enum):
    """Task 의 종류(FR-07 "필요한 조사·설계·구현·실험·검증 단위").

    구현과 검증을 값으로 나누는 것이 핵심이다. 합치면 "이 기준을 확인하는 작업이
    계획에 있는가"를 물을 수 없고, 구현만 있는 계획이 완결된 것처럼 보인다.
    """

    INVESTIGATION = "investigation"
    IMPLEMENTATION = "implementation"
    VERIFICATION = "verification"
    EXPERIMENT = "experiment"
    INTEGRATION = "integration"


class TaskRelation(str, Enum):
    """Task 와 성공 기준의 연결 방식(FR-06·FR-07).

    `IMPLEMENTS` 이 Task 가 그 기준을 충족시키는 것을 만든다
    `VERIFIES`   이 Task 가 그 기준의 충족을 확인한다

    두 값을 합치면 "만들기는 하는데 확인하지 않는 기준"이 보이지 않는다.
    """

    IMPLEMENTS = "implements"
    VERIFIES = "verifies"


class TaskState(str, Enum):
    """Task 의 현재 상태. **`DONE` 은 컬럼이 아니라 실행에서 도출한다.**

    사람이 "끝났다"고 적는 경로를 만들지 않는다 — 그것은 실행 증거 없이 의존을
    푸는 문이 된다(FR-09 "미실행을 실행·통과로 표시하지 않는다"). 완료는 그
    `task_key` 의 실행 중 `outcome=completed` 가 있는가로 본다.

    `CANCELLED` 만 표에 저장되는 값이며 사람의 재계획으로 정해진다.
    """

    PLANNED = "planned"
    IN_PROGRESS = "in_progress"
    DONE = "done"
    CANCELLED = "cancelled"


class WorkGraphSource(str, Enum):
    """이 그래프 리비전을 누가 만들었는가.

    `PLAN_ARTIFACT`    검토를 마친 개발계획의 구조 보고에서 태어났다
    `HUMAN_REPLANNING` 사람이 Task 를 추가·취소하거나 질문 연결을 고쳤다

    두 경우를 합치지 않는 이유는 P3-01이 `stage_review` 에서 사람 검토와 자동
    진행을 합치지 않은 것과 같다. 무엇이 사람의 결정인지가 기록으로 남아야 한다.
    """

    PLAN_ARTIFACT = "plan_artifact"
    HUMAN_REPLANNING = "human_replanning"


class WorkGraphState(str, Enum):
    CURRENT = "current"
    SUPERSEDED = "superseded"


# --------------------------------------------------------------------- P3-03


class WorkspaceState(str, Enum):
    """Case 작업공간의 준비 상태.

    `REQUESTED` 제어부가 필요하다고 기록했다. **아직 아무 것도 만들어지지 않았다**
    `READY`     Runner 가 브랜치·worktree 를 실제로 만들었고 기준 커밋이 확정됐다
    `FAILED`    만들 수 없었다. 사유가 남는다

    **`REQUESTED` 를 준비됨으로 읽지 않는다.** 요청만으로 쓰기를 열면 작업공간이
    없는 상태에서 CLI 가 사용자의 원래 저장소를 직접 고치게 된다(FR-08·FR-26).
    """

    REQUESTED = "requested"
    READY = "ready"
    FAILED = "failed"


class ClaimDeferral(str, Enum):
    """배정을 **거부가 아니라 미룬** 이유(FR-26 "동일 Runner 쓰기 실행은 기본 1개").

    진입 조건 거부와 구별한다. 거부는 "조건을 갖추기 전에는 실행할 수 없다"이고
    이것은 "지금은 이 Runner 가 맡지 않는다"이다 — 실행은 `pending` 으로 남아
    앞의 쓰기가 끝나면 그대로 배정된다. 둘을 합치면 사람이 조건을 고치려 들게
    되는데 고칠 조건이 없다.
    """

    RUNNER_WRITE_SLOT_BUSY = "runner_write_slot_busy"


class WorkspaceOwnership(str, Enum):
    """이미 있는 브랜치·경로가 **누구 것인가.**

    이름이 같다고 우리 것으로 간주하지 않는다. 기록된 worktree 경로와 대조해
    확인된 것만 재사용하고, 확인할 수 없으면 덮어쓰지 않고 거부한다
    (execution-workspace-review 2절 "기존 내용을 덮어쓰지 않고 소유 관계를 대조한다").
    """

    #: 이 Case 의 기록과 일치한다. 재사용한다
    SYSTEM_OWNED = "system_owned"
    #: 있는데 이 Case 의 것이 아니다. 거부한다
    FOREIGN = "foreign"
    #: 없다. 새로 만든다
    ABSENT = "absent"
