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
    """원문 종류. 서버는 이 분류와 참조만 갖고 본문은 갖지 않는다."""

    INTENT = "intent"
    FEEDBACK = "feedback"
    INSTRUCTION = "instruction"
    RUN_OUTPUT = "run_output"


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
    FEATURE_IMPLEMENTATION = "feature_implementation"


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
    PREREQUISITE_NOT_IMPLEMENTED = "prerequisite_not_implemented"
    TOOL_NOT_AVAILABLE = "tool_not_available"
    TOOL_IS_NOT_A_CODING_CLI = "tool_is_not_a_coding_cli"
    REVIEW_SESSION_NOT_SEPARATE = "review_session_not_separate"
    INTENT_VERSION_MISSING = "intent_version_missing"


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
