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

    **P3-R1에서 이 축은 `CaseProfile` 에 자리를 넘겼다.** 값을 지우지 않는 이유는
    P2-01부터의 기존 Case 기록이 이 컬럼을 갖고 있어서다. 새 Case 의 `kind` 는
    Profile 에서 유도하며(`domain.profiles.KIND_FOR_PROFILE`) `refactoring`·
    `maintenance` 는 그때 필요해진 값이다 — 여섯 Profile 중 둘은 v0.6 유형에 대응하는
    값이 없었고, 없는 대응을 억지로 만들면(`refactoring` 을 `feature` 로 적는 식)
    기록이 거짓이 된다.
    """

    FEATURE = "feature"
    BUG = "bug"
    ANALYSIS = "analysis"
    RESEARCH = "research"
    REFACTORING = "refactoring"
    MAINTENANCE = "maintenance"


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
    #: P3-R4. 사람이 누적 변경 한 건을 확인했다(D-60).
    #:
    #: **의도 동의와 다른 기록이다.** 동의는 그 버전 전체에 대한 것이고 이쪽은
    #: 변경 한 건에 대한 것이다. 합치면 한 번의 확인이 누적 전체의 승인이 되어
    #: 누적을 세는 의미가 사라진다.
    MATERIAL_DELTA_CONFIRMATION = "material_delta_confirmation"


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
    #: P3-R4. 허용된 로컬 재현·계측·테스트(D-66·FR-20).
    #:
    #: **쓰기를 받지만 기능 개발 pipeline 을 받지 않는다.** "임시 코드가 있다는
    #: 이유만으로 기능 개발 전체 절차를 요구하지 않는다"가 D-66 이고, 그래서 설계·
    #: 계획·작업 그래프를 요구하지 않는다. 대신 작업공간·대상 저장소·예산·쓰기
    #: 직렬화는 **전부 지난다** — 사용자의 미커밋 변경을 보호하는 것은 실험이라고
    #: 면제되지 않는다(FR-08·FR-26).
    #:
    #: 이 목적의 실행 효과는 `run.is_experiment` 로 표시되어 결과 후보에서 제품
    #: 변경과 구별된다. "증거와 임시 변경을 구분한다"(D-66).
    LOCAL_EXPERIMENT = "local_experiment"


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

    # --- P3-R2 Case × Repository -----------------------------------------
    #
    # 작업공간이 저장소마다 생기면 "이 실행이 어느 작업공간에서 도는가"가 새 질문이
    # 된다. 하나뿐일 때는 모호하지 않아 그대로 해석하고, 둘 이상인데 실행에 대상이
    # 기록되지 않았으면 **지어내지 않고 거부한다** — 어느 저장소를 고칠지 모르는
    # 채로 쓰기를 여는 것이 가장 비싼 실수다(D-39).
    WORKSPACE_TARGET_NOT_RECORDED = "workspace_target_not_recorded"

    # --- P3-R3 예산 -------------------------------------------------------
    #
    # **완료도 취소도 아니다.** 설정된 hard 한도를 소비하는 새 실행을 배정하지
    # 않는다는 뜻이며, 현재 결과·미검증·남은 작업은 그대로 보존된다
    # (autonomy-budget-policy 8절). 한도를 바꾸면 그 순간 다시 배정된다 —
    # `continue` 류의 예외 경로는 만들지 않는다(D-61).
    BUDGET_HARD_LIMIT_REACHED = "budget_hard_limit_reached"

    # --- P3-R4 Autonomy·목적·누적 변경 ------------------------------------
    #
    # R1 이 기록만 하던 축이 여기서 실제 배정을 정한다. 넷의 뜻이 서로 다르므로
    # 한 사유로 합치지 않는다 — 사람이 해야 할 일이 각각 다르다.
    #
    #   시작 확인이 없다        사람이 목표·범위·기준·허용 행동을 확인해야 한다
    #   목적 밖이다             사람이 명시 결정으로 목적을 넓혀야 한다
    #   미확인 변경이 있다      사람이 그 변경을 확인해야 한다
    #   Fast Lane 을 벗어났다   **사람이 아니라 준비가 더 필요하다**
    #
    # 넷째가 특히 중요하다. Fast Lane 이탈은 사람 확인 요구가 아니라 "필요한 준비를
    # 추가한 일반 자동 진행으로 전환"이다(autonomy-budget-policy 4절 마지막).
    CONTROLLED_START_NOT_CONFIRMED = "controlled_start_not_confirmed"
    PURPOSE_OUTSIDE_CASE_OBJECTIVE = "purpose_outside_case_objective"
    MATERIAL_DELTA_UNCONFIRMED = "material_delta_unconfirmed"
    FAST_LANE_LEFT_NEEDS_PREPARATION = "fast_lane_left_needs_preparation"
    #: 결합 준비 기록(Fast Lane)의 상태. 설계·계획의 사유와 나누는 이유는 사람이
    #: 만들어야 하는 것이 **다른 산출물**이기 때문이다.
    COMBINED_RECORD_MISSING = "combined_record_missing"
    COMBINED_RECORD_STALE = "combined_record_stale"
    COMBINED_RECORD_INCOMPLETE_FOR_LEVEL = "combined_record_incomplete_for_level"
    COMBINED_RECORD_REVIEW_MISSING = "combined_record_review_missing"
    #: Profile 이 기록되지 않은 Case 의 로컬 실험. **유도해서 열지 않는다**(D-62).
    PROFILE_NOT_RECORDED = "profile_not_recorded"


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

    # --- P3-R4 controlled 확인 순서 ---------------------------------------
    #
    # D-65 의 순서(`초기 확인 → 작업·로컬 검증 → 변경 결과 확인 → 게시 → 완료`)에서
    # **종료 직전의 두 선행 조건**이다. 셋으로 나누는 이유는 사람이 해야 할 일이
    # 다르기 때문이다 — 확인을 하거나, 바뀐 후보를 다시 보거나, 시작을 확인한다.
    #
    # `STALE` 은 "같은 내용의 재전송"과 구별된다. 후보 해시가 같으면 이전 확인이
    # 그대로 유효하며 재확인을 요구하지 않는다(D-65 마지막 문장).
    CONTROLLED_RESULT_NOT_CONFIRMED = "controlled_result_not_confirmed"
    CONTROLLED_CONFIRMATION_STALE = "controlled_confirmation_stale"
    CONTROLLED_START_NOT_CONFIRMED = "controlled_start_not_confirmed"
    #: 미확인 누적 변경이 남은 채로 종료하지 않는다(D-60).
    MATERIAL_DELTA_UNCONFIRMED = "material_delta_unconfirmed"


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
    """준비 산출물의 단계. **각 단계는 따로 조회·검토된다**(intent-artifacts 2절)."""

    DESIGN = "design"
    PLAN = "plan"
    #: P3-R4. Fast Lane 의 결합 기록 — "별도 설계·계획 파일이나 실행 없이 요청·핵심
    #: 변경 이유·작업·검증의 최소 논리 기록"(intent-artifacts 48행, D-60).
    #:
    #: **설계·계획을 없애는 값이 아니라 대체하는 선택지다.** Fast Lane 조건이
    #: 깨지면 이 기록만으로는 통과하지 않는다. 그리고 필수 항목이 미정이면 거부된다 —
    #: 기록을 줄이는 것이지 내용을 비우는 것이 아니다.
    COMBINED = "combined"


#: 준비 산출물이 대체할 수 있는 관계. 결합 기록은 설계·계획 **둘 다**를 대신한다.
COMBINED_COVERS: frozenset[PreparationStage] = frozenset(
    {PreparationStage.DESIGN, PreparationStage.PLAN}
)


class ReviewMode(str, Enum):
    """단계별 검토 방식.

    **v0.6 의 기본값은 사람 검토였고 P3-R4 에서 Autonomy 에서 도출한다**(D-16·D-21·
    D-65 "설계·계획의 사람 검토는 별도 선택 사항"). 도출은 `domain.progression`
    한 곳에 있고, Case 명시 설정은 그대로 이긴다.

    **기존 Case 에는 소급하지 않는다.** Autonomy 가 기록되지 않은 Case 는 v0.6
    기본값(`HUMAN_REVIEW`)을 유지한다 — 사람이 검토하기로 하고 진행하던 업무가
    조용히 통과하는 일을 만들지 않는다.
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


# --------------------------------------------------------------------- P3-R1
#
# v0.7 정책 모델. **여기서 만드는 것은 기록이고 강제가 아니다.**
#
# R1은 정책·Profile·저장소·예산의 영속 모델과 기존 데이터의 이행까지다. 그 위에
# 강제가 하나씩 붙었다 — Case×Repo 작업공간과 허용 내 자동 추가는 R2, 예산의
# 예약·정지는 R3. **Autonomy 에 따른 실행 경로는 아직 R4 의 몫이다.** 값이 생겼다는
# 이유로 그 기능을 지원한다고 표시하지 않는다
# (DEVELOPMENT.md 3절 "구현하지 않은 모드는 비활성/미지원으로 표시한다").

#: 이 코드가 적용하는 정책 규칙판. 기록마다 남겨 나중에 "어느 규칙으로 정해졌는가"를
#: 답할 수 있게 한다. **이행된 기록에는 당시 값(`0.6`)이 남는다** — 지금 값으로
#: 덮어쓰면 과거 Case 가 새 규칙으로 정해진 것처럼 보인다.
POLICY_VERSION = "0.7"

#: R1 이전 기록에 붙는 정책 버전. 비교가 아니라 출처 표시용이라 문자열로 둔다.
LEGACY_POLICY_VERSION = "0.6"


class CaseProfile(str, Enum):
    """업무의 대표 목적(D-62, case-profiles.md 1절).

    **고정 pipeline 이 아니라 의미 계약이다.** 이름을 바꾸어 권한·검증·성공 기준을
    완화할 수 없고, 대표 Profile 이 Task 의 조사·구현·실험 활동을 대신하지도 않는다.

    `CaseKind` 와 합치지 않는다. `kind` 는 P2-01부터 있던 축이고 기존 Case 의 기록이
    그 값을 갖고 있다. Profile 은 v0.7의 여섯 목적이며 **R1 이전 Case 에는 없다.**
    """

    FEATURE = "feature"
    DEFECT_FIX = "defect_fix"
    ROOT_CAUSE_ANALYSIS = "root_cause_analysis"
    RESEARCH = "research"
    REFACTORING = "refactoring"
    MAINTENANCE = "maintenance"


class ProfileSource(str, Enum):
    """Profile 을 누가·어떻게 정했는가(FR-04).

    `EXPLICIT`          요청에 Profile 이 지정됐다
    `DERIVED_FROM_KIND` 지정이 없어 기존 `kind` 축에서 유도했다. 사람의 선택이 아니다
    `NOT_RECORDED`      R1 이전에 만들어진 Case. 유도해서 채우지 않는다
    """

    EXPLICIT = "explicit"
    DERIVED_FROM_KIND = "derived_from_kind"
    NOT_RECORDED = "not_recorded"


class Autonomy(str, Enum):
    """사람이 확인해야 하는 시점(D-59, autonomy-budget-policy.md 1절).

    **WorkDepth 와 다른 축이다.** `WorkLevel`(=WorkDepth)은 조사·설계·검증의 깊이이고
    이것은 확인 경계다. `deep + ask_on_decision` 이 성립한다.

    `fast` 는 여기에 없다. Fast Lane 은 자율성 등급이 아니라 조건에 맞을 때 절차를
    줄일 수 있는 실행 경로다(D-59).
    """

    ASK_ON_DECISION = "ask_on_decision"
    CONTROLLED = "controlled"


class AutonomySource(str, Enum):
    """적용된 Autonomy 값의 출처(autonomy-budget-policy.md 5절 우선순위).

    Task·Project 단위 조정은 아직 없어서 값도 두지 않는다. 조회 결과에 "Project
    기본값에서 왔다"가 나타나는 순간 사람이 없는 설정 화면을 찾게 된다.

    `MIGRATED_UNKNOWN` 이 핵심이다. R1 이전 Case 는 Autonomy 가 **기록되지 않았고**
    기본값으로 읽으면 v0.6에서 사람이 검토·인수하기로 한 업무가 조용히 자동 진행
    대상이 된다(DEVELOPMENT.md 3절 "새 정책을 기존 승인·동의·권한에 소급 적용하지
    않는다").
    """

    SYSTEM_DEFAULT = "system_default"
    CASE_EXPLICIT = "case_explicit"
    MIGRATED_UNKNOWN = "migrated_unknown"


class EffectiveAutonomySource(str, Enum):
    """**적용된** Autonomy 가 어디서 왔는가(P3-R4).

    `AutonomySource` 와 **다른 질문이다.** 저쪽은 "저장된 값의 출처"이고 이쪽은
    "R4 가 실제로 적용한 값의 출처"다. 둘이 갈리는 경우가 하나 있다 —
    `autonomy = NULL` 인 R1 이전 Case 다.

    사용자 결정(2026-09-22)에 따라 그 Case 는 **controlled 로 취급한다.** 그러나
    저장된 `autonomy` 는 여전히 `NULL`·`migrated_unknown` 이다. `controlled` 를
    적어 넣으면 **있지도 않은 사람의 선택을 기록하는 일**이 된다(D-14·FR-23). 그래서
    취급만 바꾸고 기록은 그대로 둔다.
    """

    RECORDED = "recorded"
    MIGRATED_UNKNOWN_TREATED_AS_CONTROLLED = "migrated_unknown_treated_as_controlled"


class ConformanceMethod(str, Enum):
    """요청 정합성을 **어떤 방식으로** 확인했는가(D-25, intent-artifacts 9행).

    `LIGHT`        제어부의 결정적 규칙 검사와 위험 조건 없음의 기록. 원문의 의미
                   대응은 **확인하지 않았다** — 그 사실이 `unverified_scope` 에 값으로
                   남는다
    `INDEPENDENT`  작성과 별도 세션의 AI 의미 검토(D-28)

    **둘을 같은 모양으로 적지 않는 것이 이 값의 존재 이유다.** 가벼운 확인을 독립
    검토 완료로 표시하면 "미실행을 통과로 표시하지 않는다"(D-25)가 깨진다.
    """

    LIGHT = "light"
    INDEPENDENT = "independent"


class DeltaChangeClass(str, Enum):
    """무엇이 바뀌었는가(D-60, autonomy-budget-policy.md 3절)."""

    INTENT_FIELD = "intent_field"
    SUCCESS_CRITERION = "success_criterion"
    REPOSITORY_ALLOWANCE = "repository_allowance"


class Materiality(str, Enum):
    """그 변경이 **사람의 확인을 요구하는가.**

    `MATERIAL`      동의된 내용이 AI 출처로 바뀌었거나 성공 기준이 삭제·완화됐다.
                    그 기준에 의존하는 작업을 막는다
    `USER_DIRECTED` 사용자의 답변·수정 요청에서 왔다. **위임 기준을 갱신**하고
                    막지 않는다(D-60 "실제 답한 항목과 명시한 범위의 위임 기준만 갱신")
    `DRAFT_WORK`    아직 동의되지 않은 항목의 변경. 초안 작업이며 막지 않는다

    **제어부는 본문을 읽지 않는다.** 그래서 "문구만 정리"와 "의미 변경"을 스스로
    구별할 수 없고, 동의된 항목의 AI 출처 변경을 **전부** `MATERIAL` 로 본다.
    과다 차단이지만 방향이 안전한 쪽이고, 사용자 지시 경로가 정상 흐름을 연다.
    AI 의 "의미가 같다"는 평가만으로는 풀리지 않는다(같은 절).
    """

    MATERIAL = "material"
    USER_DIRECTED = "user_directed"
    DRAFT_WORK = "draft_work"


class DeltaState(str, Enum):
    """누적 변경 한 건의 상태.

    `PENDING` 이 쌓인다는 것이 "누적"의 구현이다. 하나씩 조용히 채택되면 작은 변경을
    연속 채택해 원래 요청과 다른 결과로 이동하게 된다(D-60).
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    ADOPTED = "adopted"
    SUPERSEDED = "superseded"


class Satisfaction(str, Enum):
    """기준이 **어떻게** 충족됐는가(case-profiles.md 4절).

    `CHANGED_AND_VERIFIED` 바꾸고 확인했다
    `ALREADY_SATISFIED`    바꾸지 않았고 이미 목표 상태임을 **검증 실행이 관측**했다.
                           코드 변경을 만들기 위해 불필요한 수정을 강제하지 않는다
    `NOT_REPRODUCED`       재현하지 못했다. **`MET` 이 될 수 없다** — "미재현만으로
                           버그 해결을 선언하지 않는다"

    셋째가 이 값의 존재 이유다. 화면 문구로만 구별하면 API 직접 호출로 우회되므로
    **쓰기 경로에서** 막는다.
    """

    CHANGED_AND_VERIFIED = "changed_and_verified"
    ALREADY_SATISFIED = "already_satisfied"
    NOT_REPRODUCED = "not_reproduced"


class PolicyState(str, Enum):
    """정책·예산 설정 행의 상태. 바뀐 값은 지우지 않고 대체로 남긴다."""

    CURRENT = "current"
    SUPERSEDED = "superseded"


class DelegationBasisKind(str, Enum):
    """자동 진행의 근거가 무엇인가(D-60, autonomy-budget-policy.md 2절).

    현재 위임 기준은 `최초 요청 + 사용자의 후속 명시 결정·변경 요청 + 유효한 정책` 이다.
    **AI 가 직전에 쓴 초안은 근거가 아니다** — 비교 자료일 뿐이며 그것을 근거로 적으면
    AI 가 자기 초안으로 위임 범위를 넓히게 된다. 그래서 값에 `ai_draft` 가 없다.
    """

    ORIGINAL_REQUEST = "original_request"
    USER_DECISION = "user_decision"
    PROJECT_POLICY = "project_policy"


class ControlledCheckpoint(str, Enum):
    """controlled 가 요구하는 확인 지점(D-65, completion-lifecycle.md 4절).

    순서는 `시작 범위 확인 → 작업·로컬 검증 → 결과 후보 확인 → 허용된 게시 → 필요한
    외부 CI → 완료` 다. 설계·계획의 사람 검토는 **이 목록에 없다** — 별도 선택
    사항이며 `stage_review_setting` 이 따로 관리한다.
    """

    START_SCOPE = "start_scope"
    RESULT_CANDIDATE = "result_candidate"


class CheckpointState(str, Enum):
    """확인 지점의 상태.

    `REQUIRED`   이 Case 에 필요하다. 아직 확인되지 않았다
    `CONFIRMED`  사람이 실제로 확인했다. 대상 해시·주체·시점이 함께 남는다
    `SUPERSEDED` 확인한 대상이 바뀌어 다시 확인해야 한다. **확인 기록은 지우지 않는다**

    `CONFIRMED` 는 그 대상에만 붙는다. 다음 후보에 자동으로 넘어가지 않는다(FR-23).
    """

    REQUIRED = "required"
    CONFIRMED = "confirmed"
    SUPERSEDED = "superseded"


class BudgetMetric(str, Enum):
    """한도를 걸 수 있는 지표(D-61, autonomy-budget-policy.md 7절 표).

    **CLI Run 과 CLI 내부 모델 호출은 같지 않다.** 여기서 세는 것은 시스템이 실제로
    시작한 실행이며, CLI 가 그 안에서 몇 번 모델을 부르는지는 관측 범위 밖이다.
    """

    RUN_COUNT = "run_count"
    REVIEW_RUN_COUNT = "review_run_count"
    INPUT_TOKENS = "input_tokens"
    OUTPUT_TOKENS = "output_tokens"
    CONTEXT_BYTES = "context_bytes"
    EXECUTION_SECONDS = "execution_seconds"
    ELAPSED_SECONDS = "elapsed_seconds"
    ESTIMATED_COST = "estimated_cost"


class BudgetThreshold(str, Enum):
    """경계의 종류(autonomy-budget-policy.md 8절).

    `WARN` 표시·허용된 절약. 경고만으로 사람 응답을 기다리지는 않는다
    `HARD` 그 한도를 소비하는 **새 실행을 배정하지 않는다.** 기존 결과는 보존한다
    """

    WARN = "warn"
    HARD = "hard"


class BudgetMeasurement(str, Enum):
    """그 지표를 어떻게 아는가(D-61).

    **`UNAVAILABLE` 을 0으로 기록하지 않는다.** 미제공을 0으로 적으면 한도가 영원히
    남아 있는 것처럼 보인다.
    """

    EXACT = "exact"
    ESTIMATED = "estimated"
    UNAVAILABLE = "unavailable"


class BudgetEnforcement(str, Enum):
    """그 설정을 실제로 강제할 수 있는가, 그리고 지금 강제하고 있는가.

    R1 에서 실제로 기록되는 값은 `RECORDED_NOT_ENFORCED` 뿐이었다. 예약·집계·정지를
    붙인 것이 R3 이다. `NOT_ENFORCEABLE` 은 측정 계약이 없어 **설정을 받지 않는** 경우를
    설명하는 값이며 그 설정은 저장되지 않는다(D-61 "보장할 수 없다면 해당 설정/실행을
    허용하지 않는다").

    **P3-R3 이 아래 셋을 더했다.** 강제하는 한도를 한 값으로 뭉뚱그리지 않는 것이
    이 단계의 요점이다.

    `ENFORCED_ABSOLUTE`         예약이 정확해 한도를 넘는 배정이 생기지 않는다
    `ENFORCED_NO_ABSOLUTE_CAP`  새 배정은 막지만 **진행 중 실행의 초과 노출이 있을
                                수 있다.** 시간 지표가 여기 속한다 — 돌고 있는 CLI 를
                                초 단위로 끊을 능력이 없다(P1-03)
    `DISPLAY_ONLY`              경고선. 표시이며 보장이 아니다

    `RECORDED_NOT_ENFORCED` 는 지우지 않는다. R1·R2 시절에 설정된 행이 그 값을 갖고
    있고, 값을 지우면 그 기록을 읽을 수 없다.
    """

    RECORDED_NOT_ENFORCED = "recorded_not_enforced"
    NOT_ENFORCEABLE = "not_enforceable"
    ENFORCED_ABSOLUTE = "enforced_absolute"
    ENFORCED_NO_ABSOLUTE_CAP = "enforced_no_absolute_cap"
    DISPLAY_ONLY = "display_only"


#: 지표별 측정 계약. **이것이 hard 한도를 받을 수 있는지 정한다.**
#:
#: 정확한 hard 한도를 요구했는데 보장할 수 없으면 설정을 거부한다(D-61). 지금
#: `EXACT` 인 것들은 시스템이 스스로 세거나 재는 값이다 — 실행을 시작한 횟수,
#: 시스템이 만들어 전달한 입력 패키지의 크기, 시작·종료 시각의 차이.
#:
#: 토큰·비용이 `ESTIMATED` 인 이유는 어댑터가 사용량을 주지 않을 때가 있고
#: (`run.usage_json` 의 기본값이 `"not_reported"` 다) 사후에만 주는 경우도 있어서다.
#: 그 지표에 정확한 hard 상한을 걸 수 있다고 표시하지 않는다.
BUDGET_MEASUREMENT: dict[BudgetMetric, BudgetMeasurement] = {
    BudgetMetric.RUN_COUNT: BudgetMeasurement.EXACT,
    BudgetMetric.REVIEW_RUN_COUNT: BudgetMeasurement.EXACT,
    BudgetMetric.CONTEXT_BYTES: BudgetMeasurement.EXACT,
    BudgetMetric.EXECUTION_SECONDS: BudgetMeasurement.EXACT,
    BudgetMetric.ELAPSED_SECONDS: BudgetMeasurement.EXACT,
    BudgetMetric.INPUT_TOKENS: BudgetMeasurement.ESTIMATED,
    BudgetMetric.OUTPUT_TOKENS: BudgetMeasurement.ESTIMATED,
    BudgetMetric.ESTIMATED_COST: BudgetMeasurement.ESTIMATED,
}

#: 지표의 단위. 표시·검증에 쓴다. 비용의 통화는 사용자가 정하므로 값만 받는다.
BUDGET_UNIT: dict[BudgetMetric, str] = {
    BudgetMetric.RUN_COUNT: "runs",
    BudgetMetric.REVIEW_RUN_COUNT: "runs",
    BudgetMetric.INPUT_TOKENS: "tokens",
    BudgetMetric.OUTPUT_TOKENS: "tokens",
    BudgetMetric.CONTEXT_BYTES: "bytes",
    BudgetMetric.EXECUTION_SECONDS: "seconds",
    BudgetMetric.ELAPSED_SECONDS: "seconds",
    BudgetMetric.ESTIMATED_COST: "currency_units",
}


class RepositorySelectionSource(str, Enum):
    """Case 가 그 저장소를 **어떻게** 선택했는가(D-63).

    `AUTO_IN_ALLOWANCE` 는 R2 가 만든다. 값을 미리 두는 이유는 마이그레이션·조회
    계약을 고정해 두기 위해서이며 **R1 은 이 값을 발급하지 않는다.**
    """

    EXPLICIT = "explicit"
    AUTO_IN_ALLOWANCE = "auto_in_allowance"
    EXCLUDED = "excluded"


class RepositorySource(str, Enum):
    """Project 등록 저장소 행의 출처.

    `MIGRATED_FROM_PROJECT` 는 R1 이전 Project 의 `repo_path` 를 옮긴 행이다. 사람이
    새로 등록한 것과 구별한다 — 등록 시점·주체가 다르기 때문이다.
    """

    REGISTERED = "registered"
    MIGRATED_FROM_PROJECT = "migrated_from_project"


class PolicyRefusal(str, Enum):
    """정책·Profile·저장소·예산 설정을 기록할 수 없는 이유.

    **네 번째 독립 목록이다.** `AgreementRefusal`(동의를 기록할 수 있는가),
    `AdmissionRefusal`(실행을 배정해도 되는가), `AcceptanceRefusal`(종료로 확정해도
    되는가)과 합치지 않는다. 이쪽은 "이 설정을 받아도 되는가"를 본다(FR-23).
    """

    CASE_ALREADY_CLOSED = "case_already_closed"
    #: 정확한 hard 한도를 요구했는데 그 지표를 정확히 측정·강제할 수 없다(D-61).
    HARD_LIMIT_NOT_ENFORCEABLE = "hard_limit_not_enforceable"
    LIMIT_NOT_POSITIVE = "limit_not_positive"
    #: 이 Case 의 Project 에 등록되지 않은 저장소다.
    REPOSITORY_NOT_IN_PROJECT = "repository_not_in_project"
    #: 기록 저장소를 코드 대상으로 선택하려 했다(D-17·D-34·FR-30).
    JOURNAL_REPOSITORY_NOT_A_CODE_TARGET = "journal_repository_not_a_code_target"
    #: 이 Case 는 Profile 이 기록되지 않았다(R1 이전). 조용히 채우지 않는다.
    PROFILE_NOT_RECORDED = "profile_not_recorded"
    #: 명시적으로 제외한 저장소다. **행이 없는 것과 다르다** — 없음은 아직 판단하지
    #: 않은 것이고, 제외는 R2 의 자동 추가가 건드리지 못하는 경계다(D-63).
    REPOSITORY_EXPLICITLY_EXCLUDED = "repository_explicitly_excluded"
    #: 선택은 돼 있지만 코드 쓰기가 허용되지 않은 저장소다. 선택이 쓰기 허용을
    #: 만들지 않는다(D-63 "등록 저장소, 쓰기/게시 허용 집합, Case 선택 집합을 구분").
    REPOSITORY_NOT_SELECTED_FOR_CODE = "repository_not_selected_for_code"
    #: 등록 저장소가 둘 이상인데 이 Case 가 무엇을 쓸지 기록하지 않았다. 하나를
    #: 골라 주지 않는다 — 고르는 것은 사람 또는 허용 내 자동 추가의 일이다.
    REPOSITORY_SELECTION_REQUIRED = "repository_selection_required"
    #: 허용 내 자동 추가가 **새 권한**을 요구했다. 자동 추가는 이미 가진 범위 안에서만
    #: 성립하며 쓰기 허용이 하나도 없는 Case 에 쓰기를 만들어 주지 않는다(D-38).
    AUTO_ADD_NEEDS_NEW_PERMISSION = "auto_add_needs_new_permission"
    #: 자동 추가로 게시 허용을 함께 주려 했다. **쓰기 허용 저장소 추가는 게시 허용
    #: 확대가 아니다**(D-64). 게시는 언제나 사람이 따로 허용한다.
    AUTO_ADD_CANNOT_GRANT_PUBLISH = "auto_add_cannot_grant_publish"
    #: controlled 가 아닌 Case 의 체크포인트를 확인하려 했다.
    CHECKPOINT_NOT_REQUIRED = "checkpoint_not_required"
    #: 확인 대상이 바뀌었다. 새 대상으로 다시 확인한다(FR-23).
    CHECKPOINT_SUBJECT_CHANGED = "checkpoint_subject_changed"
    NOT_EXPLICIT = "not_explicit"


# --------------------------------------------------------------------- P3-R2
#
# Case × Repository 작업공간과 코드 조합. **여기서부터 저장소 선택·쓰기 허용이
# 실제로 무엇을 막는다.** 게시 허용은 여전히 기록일 뿐이며 실제 push·PR 은 P5 다.


class WorkspaceAllowanceSource(str, Enum):
    """그 작업공간을 **무엇을 근거로** 만들었는가(P3-R2).

    `CASE_REPOSITORY`            Case 가 그 저장소를 선택하고 코드 쓰기를 허용했다
    `IMPLICIT_SINGLE_REPOSITORY` 선택 기록이 없는 Case 다. P3-03까지의 Case 는 선택
                                 없이 Project 의 단일 저장소에서 실제로 작업했고,
                                 거기에 "선택 기록이 없으니 쓰기 금지"를 적용하면 새
                                 정책을 기존 권한에 소급하는 것이 된다. 허용하되
                                 **허용의 출처를 기록에 남긴다** — 없던 선택을
                                 지어내지 않는다(DEVELOPMENT.md 3절)
    """

    CASE_REPOSITORY = "case_repository"
    IMPLICIT_SINGLE_REPOSITORY = "implicit_single_repository"


class CompositionEntrySource(str, Enum):
    """조합 항목을 무엇으로 채웠는가(execution-workspace-review 2.1절).

    `RUN_EFFECT`     실행이 실제로 관측했다. HEAD·미커밋 상태·트리 지문까지 고정된다
    `WORKSPACE_BASE` 관측이 없다. **기준 커밋만 있고 지금 상태는 모른다.** 기준
                     커밋만으로 실제 입력을 설명할 수 없다는 사실을 값으로 남긴다
    """

    RUN_EFFECT = "run_effect"
    WORKSPACE_BASE = "workspace_base"
