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
