"""FR-29 기능 구현의 진입 조건 검사.

**여기가 "실행을 배정해도 되는가"를 정하는 유일한 곳이다.** 화면의 버튼을 없애는
것으로는 부족하다 — 직접 API 호출도 같은 검사를 받아야 하므로 Run 생성 경로에서
이 함수를 부른다.

P2-02의 동의 거절(`AgreementRefusal`)과 **다른 검사다.** 저쪽은 "사람의 동의를
기록할 수 있는가"이고 이쪽은 "실행을 열어도 되는가"다. 두 목록을 한 함수로 합치면
동의가 곧 실행 권한이 된다.

세 가지 우회를 구조적으로 막는다(FR-29 수용 기준).

    하위 작업  Run 마다 검사한다. `task_id` 가 다르다고 면제되지 않는다
    재시작     판단 근거를 전부 DB에서 다시 읽는다. 메모리에 통과 상태를 두지 않는다
    유형 변경  조건표는 Case 의 `kind` 가 아니라 **의도 버전의 존재**로 고른다

그리고 **없는 선행 조건을 통과로 처리하지 않는다.**

P2-03·P2-04에서는 설계·계획 검토의 구현이 없었으므로 `feature_implementation` 을
`prerequisite_not_implemented` 로 한 줄 거부했다. **P3-01에서 그 선행 조건을 실제로
만들었으므로 이제 실제 검사를 한다** — 수준 판단, 설계·계획 산출물의 존재와 최신
의도 기준 여부, 수준이 요구하는 항목, 단계별 사람 검토, 이월 질문의 해결.
조건을 모두 갖추면 **허용한다.**

다만 `workspace_write` 는 여전히 열지 않는다(P3-03). 배정 조건을 갖춘 것과 코드를
바꿀 권한은 다른 문제이고, 작업공간·브랜치 준비 없이 쓰기를 열면 사용자의 미커밋
변경을 보호할 수단이 없다. **검토를 마쳤다는 사실이 쓰기 권한을 만들지 않는다.**

**P3-02에서 차단의 단위가 Case 에서 Task 로 좁아졌다.** 이월 질문 하나가 업무 전체를
멈추는 대신 그 결정에 의존하는 Task 만 멈춘다. 좁히기가 우회가 되지 않게 하는 규칙은
`_check_work_graph` 에 있다 — 그래프가 없거나, Task 가 없거나, 질문이 어떤 Task 를
막는지 모르면 **전부 막는다.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from domain.progression import (
    NEEDS_CONTROLLED_START,
    experiment_allowed,
    purpose_outside_objective,
    required_stages,
)
from domain.models import (
    AdmissionOutcome,
    AdmissionProfile,
    AdmissionRefusal,
    Availability,
    CaseKind,
    CaseStage,
    MessageReceipt,
    GateVerdict,
    IntentAgreementState,
    Permission,
    PreparationStage,
    RequestState,
    ReviewMode,
    RunPurpose,
    RunRole,
    StageReviewState,
    WorkspaceState,
)

#: 목적마다 배정할 수 있는 권한(P3-03).
#:
#: **전역 목록 하나가 아니라 목적별 표인 이유**는, 하나를 넓히면 의도 초안 작성과
#: 의미 검토에도 쓰기가 열리기 때문이다. 초안을 쓰는 실행이 코드를 바꿀 이유는
#: 없고, 그 조합을 막는 자리는 여기다.
#:
#: 쓰기가 열린 목적이라고 **바로 쓸 수 있는 것은 아니다.** `_check_workspace` 가
#: 준비된 Case 작업공간과 쓰기 경합을 따로 본다 — 권한과 작업공간은 함께 열리며
#: 그것이 P3-02까지 쓰기를 미룬 이유 그대로다(FR-08·FR-26).
#:
#: `explicit_escalated` 는 **어느 목적에도 없다.** 어댑터에 매핑이 없고(P1-02),
#: 무엇을 어디까지 올리는지 사람이 확인하는 경로도 아직 없다.
ALLOWED_PERMISSIONS: dict[RunPurpose, frozenset[Permission]] = {
    RunPurpose.INTENT_AUTHORING: frozenset({Permission.READ_ONLY}),
    RunPurpose.INTENT_GATE_REVIEW: frozenset({Permission.READ_ONLY}),
    RunPurpose.QUALITY_GATE_REVIEW: frozenset({Permission.READ_ONLY}),
    RunPurpose.LIMITED_ANALYSIS: frozenset({Permission.READ_ONLY}),
    RunPurpose.DESIGN_AUTHORING: frozenset({Permission.READ_ONLY}),
    RunPurpose.PLAN_AUTHORING: frozenset({Permission.READ_ONLY}),
    RunPurpose.FEATURE_IMPLEMENTATION: frozenset(
        {Permission.READ_ONLY, Permission.WORKSPACE_WRITE}
    ),
    RunPurpose.VERIFICATION_RUN: frozenset(
        {Permission.READ_ONLY, Permission.WORKSPACE_WRITE}
    ),
    # P3-R4. 허용된 로컬 실험은 **쓰기를 받는다**(D-66 "복구 가능한 로컬 재현·임시
    # 계측·테스트"). 무엇이 달라지는지는 권한이 아니라 선행 조건이다 — 설계·계획·
    # 작업 그래프를 요구하지 않고, 작업공간·대상 저장소·예산·직렬화는 그대로 요구한다.
    RunPurpose.LOCAL_EXPERIMENT: frozenset(
        {Permission.READ_ONLY, Permission.WORKSPACE_WRITE}
    ),
    # UI-01. 논의 응답은 **읽기 전용뿐이다.** 준비 단계에서 열리는 유일한 목적이므로
    # 여기에 쓰기가 들어가면 목표·Profile 없이 코드를 바꾸는 문이 된다.
    RunPurpose.DISCUSSION_REPLY: frozenset({Permission.READ_ONLY}),
}

#: 작업공간을 바꿀 수 있는 권한. 이 권한의 실행은 준비된 작업공간을 요구하고
#: 같은 Case 안에서 직렬화한다.
WRITE_PERMISSIONS: frozenset[Permission] = frozenset(
    {Permission.WORKSPACE_WRITE, Permission.EXPLICIT_ESCALATED}
)

#: 목적별로 기대하는 역할. 의미 검토는 작성과 분리해야 한다(FR-29 검토 방식).
EXPECTED_ROLE: dict[RunPurpose, RunRole] = {
    RunPurpose.INTENT_AUTHORING: RunRole.AUTHOR,
    RunPurpose.INTENT_GATE_REVIEW: RunRole.REVIEWER,
    RunPurpose.QUALITY_GATE_REVIEW: RunRole.REVIEWER,
    RunPurpose.LIMITED_ANALYSIS: RunRole.AUTHOR,
    RunPurpose.DESIGN_AUTHORING: RunRole.AUTHOR,
    RunPurpose.PLAN_AUTHORING: RunRole.AUTHOR,
    RunPurpose.FEATURE_IMPLEMENTATION: RunRole.AUTHOR,
    RunPurpose.VERIFICATION_RUN: RunRole.AUTHOR,
    RunPurpose.LOCAL_EXPERIMENT: RunRole.AUTHOR,
    RunPurpose.DISCUSSION_REPLY: RunRole.AUTHOR,
}

#: 동의된 의도를 선행 조건으로 받는 목적들. 기능 개발 조건표를 적용한다.
NEEDS_AGREED_INTENT: frozenset[RunPurpose] = frozenset(
    {
        RunPurpose.LIMITED_ANALYSIS,
        RunPurpose.DESIGN_AUTHORING,
        RunPurpose.PLAN_AUTHORING,
        RunPurpose.FEATURE_IMPLEMENTATION,
        RunPurpose.VERIFICATION_RUN,
        # P3-R4. 실험도 그 Case 의 합의된 목적 안에서 도는 실행이다. 조건표가
        # `non_feature_minimal` 인 Case 에서는 이 집합에 있어도 의도 동의를
        # 요구받지 않는다 — 조사·연구 Case 가 그쪽이다.
        RunPurpose.LOCAL_EXPERIMENT,
    }
)

#: AI가 실제로 글을 써야 성립하는 목적. 골격 실행기로 배정하면 실행은 정상 종료하는데
#: 산출물이 없어 아무 일도 일어나지 않은 것처럼 보인다.
NEEDS_CODING_CLI: frozenset[RunPurpose] = frozenset(
    {
        RunPurpose.INTENT_AUTHORING,
        RunPurpose.INTENT_GATE_REVIEW,
        RunPurpose.QUALITY_GATE_REVIEW,
        RunPurpose.DESIGN_AUTHORING,
        RunPurpose.PLAN_AUTHORING,
        # P3-03. 구현·검증도 마찬가지다. 골격 실행기는 코드를 고치지도 명령을
        # 실행하지도 않으면서 **정상 종료한다** — 그 실행이 완료로 기록되면
        # 아무 것도 하지 않은 실행 하나로 후속 Task 가 전부 열린다.
        RunPurpose.FEATURE_IMPLEMENTATION,
        RunPurpose.VERIFICATION_RUN,
        # P3-R4. 실험도 마찬가지다. 골격 실행기는 계측 코드를 쓰지도 명령을 돌리지도
        # 않으면서 정상 종료하고, 그 실행이 "실험했다"로 기록된다.
        RunPurpose.LOCAL_EXPERIMENT,
        # UI-01. 논의 응답도 마찬가지다. 골격 실행기는 답을 쓰지 않으면서 정상 종료하고,
        # 그 출력이 AI 의 말로 대화에 붙는다.
        RunPurpose.DISCUSSION_REPLY,
    }
)


@dataclass
class AdmissionRequest:
    """검사 입력. 제어부가 가진 상태만으로 판단한다. 본문은 들어오지 않는다."""

    case_id: str
    case_kind: CaseKind
    #: 이미 종료된 Case 인가. 종료 뒤에는 새 실행을 받지 않는다(D-33).
    case_closed: bool
    run_id: str
    task_id: str
    purpose: RunPurpose
    role: RunRole
    permission: Permission
    tool_id: str
    session: str
    instruction_availability: str
    intent_state: dict[str, Any]
    gate_state: dict[str, Any]
    target_intent_version_id: str | None
    tool_installed: bool
    permission_mapped: bool
    #: `Repository.preparation_state()` 의 결과. 수준·설계·계획·검토 상태가 들어 있다.
    #: 기본값이 빈 dict 인 것은 P2 시절 호출(시험)이 이 인자를 모르기 때문이며,
    #: 빈 상태는 **아무 것도 준비되지 않음**으로 읽힌다 — 통과로 읽지 않는다.
    preparation_state: dict[str, Any] = field(default_factory=dict)
    #: 이 도구가 실제 코딩 CLI인가. P2-01의 골격 실행기는 실행은 되지만 글을 쓰지 않는다.
    tool_is_coding_cli: bool = False
    author_session_refs: list[str] = field(default_factory=list)
    requested_session_ref: str | None = None
    #: `Repository.workspace_state()` 의 결과(P3-03). 빈 dict 는 **작업공간 없음**이며
    #: 준비됨으로 읽지 않는다 — 없음을 통과로 읽으면 CLI 가 사용자의 원래 저장소를
    #: 직접 고치게 된다(FR-08·FR-26).
    workspace_state: dict[str, Any] = field(default_factory=dict)
    #: 이 Case 에서 아직 끝나지 않은 **다른** 쓰기 실행. 같은 Case 의 쓰기는
    #: 직렬화한다(FR-26 "동일 Runner 쓰기 실행은 기본 1개", D-39).
    case_write_runs: list[dict[str, Any]] = field(default_factory=list)
    #: 이 실행을 배정하면 넘는 hard 예산 한도들(P3-R3). 빈 목록은 **한도가 없거나
    #: 한도 안**이라는 뜻이고, 둘을 여기서 구분하지 않는 이유는 판정이 같기 때문이다.
    #:
    #: 실제 예약은 Run 생성 트랜잭션 안에서 **다시** 검사한다. 여기 있는 것은 "왜
    #: 실행이 열리지 않았는지"를 사람이 볼 수 있게 하는 층이고(FR-14), 저쪽은 마지막
    #: 한 칸의 경쟁을 막는 층이다. 두 층이 필요한 이유는 `Repository.create_run()`
    #: 주석에 있다.
    budget_breaches: list[dict[str, Any]] = field(default_factory=list)
    #: `Repository.checkpoint_state()` 의 결과(P3-R4). 빈 dict 는 **확인 지점을
    #: 모른다**이며 controlled 가 아님으로 읽지 않는다 — 없음을 통과로 읽지 않는
    #: 규칙이 여기에도 적용된다. 그래서 기본값에 `required: False` 를 두지 않고
    #: `_check_autonomy` 가 키의 부재를 확인 안 됨으로 해석한다.
    checkpoint_state: dict[str, Any] = field(default_factory=dict)
    #: 이 Case 의 Profile(P3-R4·D-66). `None` 은 R1 이전 Case 이며 **유도하지 않는다**.
    case_profile: str | None = None
    #: 사용자의 명시 결정으로 목적이 넓어졌는가. AI 판단이나 Profile 변경이 아니다.
    objective_widened: bool = False
    #: `Repository.material_delta_state()` 의 결과(P3-R4). 확인되지 않은 누적 변경이
    #: 어떤 Task 를 막는지가 들어 있다. 연결을 모르면 **전부 막는다**.
    material_delta_state: dict[str, Any] = field(default_factory=dict)
    #: `Repository.fast_lane_state()` 의 결과(P3-R4). 결합 기록 하나로 충분한지를
    #: 정한다. 빈 dict 는 `eligible = False` 로 읽힌다 — 판정이 없으면 일반 경로다.
    fast_lane: dict[str, Any] = field(default_factory=dict)
    #: `Repository.task_repository_state()` 의 결과(P3-04). 이 Task 가 어느 저장소를
    #: 바꾸기로 했는지와 고를 수 있는 저장소의 수가 들어 있다. 빈 dict 는 **그래프가
    #: 없거나 이 Task 가 그래프에 없다**이며, 그 상태는 `_check_work_graph` 가 이미
    #: 본다 — 여기서 없음을 통과로 읽는 것이 아니라 같은 사실을 두 번 거부하지
    #: 않는 것이다.
    task_repository: dict[str, Any] = field(default_factory=dict)
    #: 이 실행이 **밝힌** 대상 저장소(P3-04). 작업공간 상태에서 끌어내지 않는 이유는,
    #: 준비되지 않은 저장소를 대상으로 적은 요청이 작업공간이 없다는 이유로 대조를
    #: 건너뛰게 되기 때문이다 — 그 경우에도 "이 Task 의 저장소가 아니다"는 사실이다.
    run_repository_id: str | None = None
    #: P4-01. 현재 목적이 의존하는 **명시 ON** 일반 게이트 중 통과하지 않은 것.
    #: Profile 추천의 기존 QG-02/03 조건은 준비 판정이 이미 강제하므로 중복하지 않고,
    #: 사용자가 별도 게이트를 명시한 경우에만 이 추가 조건이 생긴다.
    quality_gate_blockers: list[dict[str, Any]] = field(default_factory=list)
    #: P4-02. 요청이 기대한 게이트 정책과 **지금의** 정책이 다른 목록. 비어 있으면
    #: 기대를 적지 않았거나 그대로다. 예약(`pending`)은 여기에 오지 않는다.
    quality_gate_policy_drift: list[dict[str, Any]] = field(default_factory=list)
    #: UI-01. 이 Case 의 **유효** 단계. 기본값이 업무 단계인 이유는 P2 시절 호출(시험)이
    #: 이 인자를 모르기 때문이며, 그 호출들은 전부 업무 단계 Case 다.
    case_stage: str = CaseStage.WORK.value
    #: UI-01. 이 실행이 **밝힌** 사용자 요청. 없으면 요청과 무관한 실행이다.
    request_id: str | None = None
    #: `Repository.request_admission_state()` 의 결과. 빈 dict 는 **그 요청을 모른다**
    #: 이며 처리 중으로 읽지 않는다.
    request_state: dict[str, Any] = field(default_factory=dict)
    #: 이 실행의 지시 원문 `(artifact_id, revision)`. 논의 응답은 그 요청을 연 메시지를
    #: 지시로 받아야 한다 — 응답이 실제로 받은 말에 대한 것이어야 하기 때문이다.
    instruction_artifact: tuple[str, int] | None = None
    #: P4-04. 이 실행의 입력 패키지 계획(`domain.context.ContextPlan.summary()`).
    #: 빈 dict 는 계획을 세우지 않은 호출(P2 시절 시험)이며 한도 초과로 읽지 않는다 —
    #: 그 호출들은 고정 참조가 없거나 작다.
    context_plan: dict[str, Any] = field(default_factory=dict)
    #: P4-04. 인라인으로 넣을 **핵심** 참조 중 지금 `available` 이 아닌 것.
    context_unavailable: list[dict[str, Any]] = field(default_factory=list)
    #: P4-06. 이 실행에 적용되는 필수 지식 사이의 **열린 충돌**(id·두 항목 키).
    knowledge_conflicts: list[dict[str, Any]] = field(default_factory=list)
    #: P4-05. **종료 뒤 설명 전용 진입**(D-87). 요청에 묶인 읽기 전용 논의 응답만 참이며, 그때만
    #: 종료 Case 의 거부를 묻지 않는다. 다른 모든 목적은 종료 Case 에서 그대로 거부된다.
    explanation_entry: bool = False


@dataclass
class AdmissionResult:
    outcome: AdmissionOutcome
    profile: AdmissionProfile
    refusals: list[AdmissionRefusal]
    reasons: dict[str, str]
    intent_version_id: str | None
    intent_agreement_state: str | None
    gate_verdict: str | None

    @property
    def admitted(self) -> bool:
        return self.outcome is AdmissionOutcome.ADMITTED

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome.value,
            "profile": self.profile.value,
            "refusals": [r.value for r in self.refusals],
            "reasons": self.reasons,
            "intent_version_id": self.intent_version_id,
            "intent_agreement_state": self.intent_agreement_state,
            "gate_verdict": self.gate_verdict,
        }


def choose_profile(request: AdmissionRequest) -> AdmissionProfile:
    """어떤 조건표를 적용할지 정한다.

    **Case 의 `kind` 만 보지 않는다.** 의도 버전이 하나라도 있으면 그 Case는 이미
    기능 개발 흐름을 탄 것이므로 유형 표기와 무관하게 기능 조건표를 적용한다.
    유형을 바꿔 조건을 벗어나는 경로를 만들지 않기 위해서다(FR-29).
    """
    if request.purpose in (RunPurpose.INTENT_AUTHORING, RunPurpose.INTENT_GATE_REVIEW):
        return AdmissionProfile.INTENT_PRODUCTION
    if request.purpose is RunPurpose.DISCUSSION_REPLY:
        # UI-01. 의도·동의가 아니라 요청·원문 저장이 조건인 조건표다.
        return AdmissionProfile.CONVERSATION
    has_intent = request.intent_state.get("latest_intent_version") is not None
    if has_intent or request.case_kind is CaseKind.FEATURE:
        return AdmissionProfile.FEATURE_INTENT
    return AdmissionProfile.NON_FEATURE_MINIMAL


#: 단계별 거부 사유. 사람이 무엇을 갖춰야 하는지 한 번에 알도록 종류를 나눠 둔다.
_STAGE_REFUSALS: dict[PreparationStage, dict[str, AdmissionRefusal]] = {
    PreparationStage.DESIGN: {
        "missing": AdmissionRefusal.DESIGN_MISSING,
        "stale": AdmissionRefusal.DESIGN_STALE,
        "incomplete": AdmissionRefusal.DESIGN_INCOMPLETE_FOR_LEVEL,
        "review": AdmissionRefusal.DESIGN_REVIEW_MISSING,
    },
    PreparationStage.PLAN: {
        "missing": AdmissionRefusal.PLAN_MISSING,
        "stale": AdmissionRefusal.PLAN_STALE,
        "incomplete": AdmissionRefusal.PLAN_INCOMPLETE_FOR_LEVEL,
        "review": AdmissionRefusal.PLAN_REVIEW_MISSING,
    },
    # P3-R4. 결합 기록의 사유를 설계·계획과 **나눠 둔다.** 같은 코드를 쓰면 화면이
    # "설계가 없다"고 말하는데 사람이 만들어야 하는 것은 결합 기록인 상태가 된다.
    PreparationStage.COMBINED: {
        "missing": AdmissionRefusal.COMBINED_RECORD_MISSING,
        "stale": AdmissionRefusal.COMBINED_RECORD_STALE,
        "incomplete": AdmissionRefusal.COMBINED_RECORD_INCOMPLETE_FOR_LEVEL,
        "review": AdmissionRefusal.COMBINED_RECORD_REVIEW_MISSING,
    },
}

_STAGE_LABEL = {
    PreparationStage.DESIGN: "설계",
    PreparationStage.PLAN: "개발계획",
    PreparationStage.COMBINED: "결합 기록",
}


def _check_stage_ready(request: AdmissionRequest, stage: PreparationStage, refuse: Any) -> None:
    """한 단계의 준비 상태를 검사한다.

    네 가지를 **따로** 본다(FR-05 "산출물 존재, 품질 판정, 사람 검토는 구분한다").

        있는가          산출물이 등록됐는가
        최신인가        대체된 의도 버전 위에 세운 것이 아닌가, 원문을 읽을 수 있는가
        충분한가        현재 수준이 요구하는 항목이 미정으로 비어 있지 않은가
        검토됐는가      사람 검토 또는 자동 진행 기록이 있는가

    자동 진행 모드에서도 **기록은 필요하다.** 모드를 자동으로 바꾼 것만으로 검토가
    끝나지는 않는다 — 산출물과 필수 항목을 갖춘 시점에 조건 충족이 기록된다.
    """
    codes = _STAGE_REFUSALS[stage]
    label = _STAGE_LABEL[stage]
    state = (request.preparation_state or {}).get(stage.value) or {}
    artifact = state.get("artifact")

    if artifact is None:
        refuse(codes["missing"], f"{label} 산출물이 없다")
        return

    if state.get("stale"):
        refuse(
            codes["stale"],
            f"{label}이 대체된 의도 버전 위에 세워져 있다. 최신 의도 기준으로 다시 만든다",
        )
    elif artifact.get("availability") != Availability.AVAILABLE.value:
        # 원문을 읽을 수 없으면 사람이 검토할 수도, 실행자가 따를 수도 없다.
        refuse(
            codes["stale"],
            f"{label} 원문이 {artifact.get('availability')} 상태라 지금 읽을 수 없다",
        )

    missing_sections = state.get("missing_required_sections") or []
    if missing_sections:
        refuse(
            codes["incomplete"],
            f"현재 수준이 요구하는 {label} 항목이 미정이다: " + ", ".join(missing_sections),
        )

    review = state.get("review")
    if review is None:
        mode = ReviewMode(state.get("mode") or ReviewMode.HUMAN_REVIEW.value)
        if mode is ReviewMode.HUMAN_REVIEW:
            refuse(codes["review"], f"{label}에 대한 사람 검토가 없다")
        else:
            # 자동 진행을 골랐어도 **조건 충족 기록**이 필요하다. 설정만으로
            # 검토가 끝났다고 적으면 그것이 곧 사람 승인 기록의 대체가 된다.
            refuse(
                codes["review"],
                f"{label}은 자동 진행 설정이지만 조건 충족이 아직 기록되지 않았다",
            )
    elif review.get("state") not in (
        StageReviewState.HUMAN_REVIEWED.value,
        StageReviewState.AUTO_CONDITIONS_MET.value,
    ):
        refuse(codes["review"], f"{label} 검토 상태가 {review.get('state')} 다")


#: 수준·설계·계획의 선행 조건을 받는 목적.
#:
#: **검증 실행도 여기 있다.** 무엇을 확인할지는 계획이 정하므로, 계획 없이 도는
#: 빌드·테스트는 "무엇을 검증했는가"를 답할 수 없다(FR-09).
#:
#: **로컬 실험은 여기 없다**(P3-R4·D-66). "임시 코드가 있다는 이유만으로 기능 개발
#: 전체 절차를 요구하지 않는다" — 대신 작업공간·대상 저장소·예산·쓰기 직렬화는
#: 전부 지난다. 무엇을 면제하고 무엇을 면제하지 않는지가 이 차이에 있다.
NEEDS_PREPARATION: frozenset[RunPurpose] = frozenset(
    {RunPurpose.FEATURE_IMPLEMENTATION, RunPurpose.VERIFICATION_RUN}
)


def _check_preparation(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """구현·검증의 준비 조건. **Fast Lane 이면 결합 기록 하나로 충분하다**(P3-R4).

    요구는 "이 중 **하나**를 갖추라"는 대안 집합이다. 일반 경로는 설계+계획 두 건,
    Fast Lane 에서는 결합 기록 한 건이 그 자리를 대신한다
    (`domain.progression.required_stages`).

    **Fast Lane 이어도 설계·계획 경로가 사라지지 않는다.** 이미 두 산출물이 있으면
    그대로 통과한다 — 결합 기록은 대체하는 선택지이지 강제가 아니다.

    거부 사유를 고를 때 **가장 가까운 대안의 것을 쓴다.** 두 대안의 사유를 모두
    쏟아 내면 사람이 "설계도 계획도 결합 기록도 없다"는 세 줄을 받고 무엇을 만들어야
    하는지 알 수 없게 된다. 결합 기록이 있으면 그쪽을, 없으면 설계·계획 쪽을 말한다.
    """
    prep = request.preparation_state or {}
    fast_lane = bool((request.fast_lane or {}).get("eligible"))
    alternatives = required_stages(fast_lane)

    def satisfied(stages: frozenset[PreparationStage]) -> bool:
        probe: list[AdmissionRefusal] = []
        for stage in stages:
            _check_stage_ready(request, stage, lambda r, m: probe.append(r))
        return not probe

    for stages in alternatives:
        if satisfied(stages):
            return

    combined = (prep.get(PreparationStage.COMBINED.value) or {}).get("artifact")
    if combined is not None and not fast_lane:
        # 결합 기록은 있는데 Fast Lane 조건이 깨졌다. **사람 확인 요구가 아니다** —
        # 필요한 준비를 추가한 일반 자동 진행으로 전환하는 것이다
        # (autonomy-budget-policy 4절 마지막 문단).
        blockers = ", ".join(
            b["detail"] for b in (request.fast_lane or {}).get("blockers") or []
        )
        refuse(
            AdmissionRefusal.FAST_LANE_LEFT_NEEDS_PREPARATION,
            f"결합 기록이 있으나 Fast Lane 조건이 깨졌다: {blockers}."
            " 설계·개발계획을 갖춘 일반 진행으로 전환한다 — 이것은 사람 확인 요구가"
            " 아니라 준비 추가다",
        )
        _check_stage_ready(request, PreparationStage.DESIGN, refuse)
        _check_stage_ready(request, PreparationStage.PLAN, refuse)
        return

    if fast_lane and combined is not None:
        # 결합 기록이 있고 Fast Lane 인데 통과하지 못했다 = 그 기록 자체의 문제다.
        _check_stage_ready(request, PreparationStage.COMBINED, refuse)
        return

    _check_stage_ready(request, PreparationStage.DESIGN, refuse)
    _check_stage_ready(request, PreparationStage.PLAN, refuse)


def _check_workspace_target(request: AdmissionRequest, refuse: Any) -> None:
    """이 실행이 **어느 저장소의 작업공간에서 도는가**(P3-R2·D-39).

    **쓰기에만 적용하지 않는다.** 읽기 전용 검토·조사도 "이 Case 가 실제로 만들고
    있는 코드"를 봐야 하고(배정이 worktree 를 주는 이유가 그것이다), 대상을 모르는
    채로 내보내면 배정이 조용히 사용자의 원래 저장소로 떨어진다 — 검토가 이 Case 의
    작업이 아니라 사용자의 다른 작업을 읽게 된다.

    **작업공간이 하나뿐이면 모호하지 않으므로 아무 것도 하지 않는다.** 이 검사가
    무는 것은 저장소가 둘 이상인 Case 뿐이고, 그런 Case 는 R2 이전에 없었다.
    """
    workspace = request.workspace_state or {}
    if workspace.get("present") and not workspace.get("target_recorded", True):
        refuse(
            AdmissionRefusal.WORKSPACE_TARGET_NOT_RECORDED,
            f"이 업무에 작업공간이 {workspace.get('repository_count')}개 있는데 이"
            " 실행의 대상 저장소가 기록되지 않았다. 어느 저장소를 보거나 고칠지"
            " 모르는 채로 실행을 배정하지 않는다",
        )


#: Task 가 자기 저장소를 밝혀야 하는 목적(P3-04).
#:
#: **조사·검토·초안은 여기 없다.** 그것들은 코드를 바꾸지 않으며, 그래프가 생기기
#: 전에도 돌아야 한다. 무는 것은 실제로 저장소를 고치거나 그 저장소 위에서 검증을
#: 돌리는 목적뿐이다.
NEEDS_TASK_REPOSITORY: frozenset[RunPurpose] = frozenset(
    {
        RunPurpose.FEATURE_IMPLEMENTATION,
        RunPurpose.VERIFICATION_RUN,
    }
)


def _check_task_repository(request: AdmissionRequest, refuse: Any) -> None:
    """이 실행의 대상 저장소가 **그 Task 가 바꾸기로 한 저장소인가**(P3-04).

    R2 의 `_check_workspace_target` 은 "대상이 기록됐는가"를 묻고 여기서는 "그
    대상이 맞는가"를 묻는다. 둘은 저장소가 하나뿐이면 같은 질문이지만, 두 저장소를
    함께 바꾸는 업무에서는 다르다 — 대상을 기록했다는 이유만으로 통과하면 "UI
    작업을 한다면서 API 저장소를 고치는 실행"이 열리고, 실행 전후 대조가 엉뚱한
    Task 에 붙는다. 그 대조가 우리가 가진 유일한 증거다.

    **소급하지 않는 자리가 둘이다.** 저장소가 하나뿐인 Case 는 아무 것도 달라지지
    않고(고를 것이 없다), v12 이전 Task 는 `repository_id` 가 미기록이라 미기록
    경로를 탄다. 미기록을 막는 것은 **저장소가 둘 이상인 Case** 뿐이며, 그런 Case 는
    R2 이후에만 있고 그 안에서 저장소를 말하지 않는 계획은 덜 된 계획이다.
    """
    if request.purpose not in NEEDS_TASK_REPOSITORY:
        return
    task = request.task_repository or {}
    if not task.get("present"):
        # 이 Task 가 현재 그래프에 없다. `_check_work_graph` 가 이미 거부했다.
        return

    recorded = task.get("repository_id")
    target = request.run_repository_id or (
        (request.workspace_state or {}).get("repository_id")
    )

    if recorded:
        if target and target != recorded:
            refuse(
                AdmissionRefusal.RUN_TASK_REPOSITORY_MISMATCH,
                f"{request.task_id!r} 는 {task.get('repository_name')!r} 저장소의 작업인데"
                f" 이 실행의 대상 저장소는 {target!r} 다."
                " 다른 저장소의 변경을 이 작업의 결과로 적지 않는다",
            )
        return

    # 미기록이다. 고를 것이 둘 이상일 때만 문다.
    if (task.get("choice_count") or 0) < 2:
        return
    # 계획이 적었는데 해석되지 않은 것과 아무 것도 적지 않은 것은 **사람이 해야 할
    # 일이 다르다.** 앞은 이름을 고치거나 그 저장소를 선택에 넣는 것이고 뒤는
    # 계획이 저장소를 말하는 것이다.
    unresolved = task.get("repository_ref")
    if unresolved:
        refuse(
            AdmissionRefusal.TASK_REPOSITORY_NOT_RECORDED,
            f"{request.task_id!r} 의 계획이 {unresolved!r} 저장소를 가리키는데 이 업무가"
            " 고른 저장소 중에 그런 이름이 없다. 계획이 가리키는 저장소를 고치거나"
            " 그 저장소를 이 업무의 선택에 넣는다",
        )
    else:
        refuse(
            AdmissionRefusal.TASK_REPOSITORY_NOT_RECORDED,
            f"이 업무는 저장소를 {task.get('choice_count')}개 바꿀 수 있는데"
            f" {request.task_id!r} 가 어느 저장소의 작업인지 계획에 없다."
            " 어느 저장소를 고칠지 모르는 채로 그 작업의 결과를 적지 않는다",
        )


def _check_workspace(request: AdmissionRequest, refuse: Any) -> None:
    """쓰기를 열기 전의 작업공간 조건(P3-03).

    **왜 권한만으로 열지 않는가.** Case 전용 branch/worktree 와 기준 커밋이 없으면
    CLI 는 사용자의 원래 저장소를 직접 고치게 되고, 그 순간 미커밋 변경을 보호할
    수단이 없다(FR-08·FR-26). 그래서 권한과 작업공간은 **함께** 열린다.

    그리고 같은 Case 의 쓰기는 **직렬화한다.** 두 실행이 같은 worktree 에 동시에
    쓰면 어느 쪽이 무엇을 바꿨는지 실행 전후 대조로 나눌 수 없고, 그 대조가 우리가
    가진 유일한 증거다(execution-workspace-review 2절).

    **이것은 OS 격리가 아니다.** worktree 는 파일 배치의 분리이며 다른 경로·공유
    자격증명 접근을 막지 못한다(D-44). 여기서 하는 일은 배정을 막는 것뿐이다.
    """
    workspace = request.workspace_state or {}
    if not workspace.get("present"):
        refuse(
            AdmissionRefusal.WORKSPACE_NOT_READY,
            "이 업무의 전용 작업공간이 없다. 브랜치·worktree 와 기준 커밋을 먼저"
            " 준비한다 — 준비 없이 쓰기를 열면 사용자의 미커밋 변경을 보호할 수 없다",
        )
    elif not workspace.get("target_recorded", True):
        # 아래 `_check_workspace_target` 이 이미 같은 사유로 거부했다. 여기서 준비
        # 상태를 더 따지지 않는 이유는, 어느 작업공간을 보는지 모르는 채로 "준비되지
        # 않았다"를 말하면 사람이 엉뚱한 저장소를 고치러 가기 때문이다.
        pass
    elif workspace.get("state") == WorkspaceState.FAILED.value:
        refuse(
            AdmissionRefusal.WORKSPACE_FAILED,
            "작업공간 준비가 실패한 상태다: "
            + (workspace.get("failure_reason") or "사유가 기록되지 않음"),
        )
    elif not workspace.get("ready"):
        refuse(
            AdmissionRefusal.WORKSPACE_NOT_READY,
            f"작업공간이 {workspace.get('state')} 상태다. 요청은 준비됨이 아니다",
        )

    others = [r for r in (request.case_write_runs or []) if r.get("run_id") != request.run_id]
    if others:
        refuse(
            AdmissionRefusal.CASE_WRITE_IN_PROGRESS,
            "이 업무에 아직 끝나지 않은 쓰기 실행이 있다: "
            + ", ".join(f"{r['run_id']}({r['status']})" for r in others),
        )


#: 작업 그래프 검사를 받는 목적(P3-02).
#:
#: **조사도 실행이다.** "하위 작업 `task_id` 가 다르다고 면제되지 않는다"는 FR-29의
#: 규칙은 목적이 달라도 같게 적용돼야 한다. 다만 검사는 **그래프가 있는 Case 에서만**
#: 돈다 — 그래프는 계획에서 태어나므로 계획 이전의 조사까지 막으면 순환이 된다.
NEEDS_WORK_GRAPH: frozenset[RunPurpose] = frozenset(
    {
        RunPurpose.FEATURE_IMPLEMENTATION,
        RunPurpose.VERIFICATION_RUN,
        RunPurpose.LIMITED_ANALYSIS,
    }
)

#: **로컬 실험은 작업 그래프를 요구하지 않는다**(P3-R4·D-66).
#:
#: 위 집합에 `LOCAL_EXPERIMENT` 를 넣지 않은 것은 실수가 아니다. 실험은 계획이 정의한
#: Task 가 아니라 조사 목적 안의 활동이며, 그래프를 요구하면 "임시 코드가 있다는
#: 이유만으로 기능 개발 전체 절차를 요구하지 않는다"가 깨진다. 대신 **목적 검사**가
#: 그 실행이 조사 Profile 안인지를 본다(`_check_objective`).


def _check_work_graph(request: AdmissionRequest, refuse: Any) -> None:
    """작업 그래프 조건을 검사한다(P3-02).

    **좁히는 것이 느슨해지는 것이 되어서는 안 된다.** P3-01에서 이월 질문 하나는
    Case 전체를 막았고, 여기서 "그 결정에 의존하는 Task 만"으로 좁힌다. 좁히기가
    우회가 되지 않도록 아래 세 경우는 **전부 막는다.**

        그래프가 없다                    계획이 Task 를 정의하지 않았다
        Task 가 0건이다                  같은 사실의 다른 모습
        열린 질문에 연결된 Task 가 없다  `blocks` 가 비었거나 해석되지 않았다

    셋째가 핵심이다. 연결이 없다는 것은 "아무 것도 막지 않는다"가 아니라 **무엇을
    막는지 모른다**는 뜻이고, 모르는 것을 안전한 쪽으로 읽으면 질문 하나를 연결하지
    않는 것만으로 모든 차단이 사라진다.

    그래프가 아예 없는 Case 에서는 P3-01의 Case 수준 차단을 그대로 쓴다. 준비
    조건(`design_*`/`plan_*`)이 그 상태를 이미 정확히 설명하므로, 그래프가 생기기
    전의 `limited_analysis` 까지 막지는 않는다.
    """
    prep = request.preparation_state or {}
    deferred = prep.get("deferred_open_questions") or []
    graph_state = prep.get("work_graph") or {}

    if not graph_state.get("present"):
        # --- P3-01 그대로: Case 수준 차단 ---------------------------------
        # 그래프가 없는데 기능 구현을 요청하면 계획이 작업을 정의하지 않은 것이다.
        if request.purpose is RunPurpose.FEATURE_IMPLEMENTATION:
            refuse(
                AdmissionRefusal.WORK_GRAPH_MISSING,
                "개발계획이 Task 를 정의하지 않아 작업 그래프가 없다."
                " 무엇을 어떤 순서로 만들지가 정해지지 않았다",
            )
            if deferred:
                refuse(
                    AdmissionRefusal.DEFERRED_QUESTIONS_UNRESOLVED,
                    "설계·계획으로 이월한 질문이 남아 있다: "
                    + ", ".join(q["question_key"] for q in deferred),
                )
        return

    if graph_state.get("stale"):
        # 새 의도 버전이 생겼다. 그 위에 세운 그래프를 재사용하지 않는다(FR-23).
        refuse(
            AdmissionRefusal.WORK_GRAPH_STALE,
            "작업 그래프가 대체된 의도 버전 위에 세워져 있다."
            " 최신 의도 기준으로 계획을 다시 만든다",
        )
        return

    if not graph_state.get("tasks"):
        refuse(
            AdmissionRefusal.WORK_GRAPH_MISSING,
            "작업 그래프에 Task 가 없다",
        )
        return

    readiness = (graph_state.get("readiness") or {}).get(request.task_id)
    if readiness is None:
        refuse(
            AdmissionRefusal.TASK_NOT_IN_WORK_GRAPH,
            f"{request.task_id!r} 는 현재 작업 그래프의 Task 가 아니다."
            " 그래프의 Task 키로 요청한다",
        )
        return

    # 차단 사유는 `controller/work_graph.py` 가 계산한다. 화면·진입 검사·시험이
    # 같은 함수를 보게 하기 위해서다 — 두 벌로 쓰면 한쪽만 고치는 실수가 생긴다.
    for block in readiness.get("blocked_by") or []:
        refuse(AdmissionRefusal(block["reason"]), block["detail"])


def _check_autonomy(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """controlled 의 시작 확인이 있는가(P3-R4·D-65).

    **초안 작성·의미 검토·조사는 막지 않는다.** 시작 확인의 대상이 "목표·범위·기준·
    허용 행동"인데 사람이 그것을 확인하려면 초안이 먼저 있어야 하고, 조사까지 막으면
    확인에 필요한 사실을 모을 수 없다. 어느 목적이 막히는지는
    `domain.progression.NEEDS_CONTROLLED_START` 가 갖는다 — 진입 검사·화면·시험이
    같은 집합을 본다.

    **확인 지점 상태를 모르면 막는다.** `checkpoint_state` 가 비어 있다는 것은
    "controlled 가 아니다"가 아니라 판단 근거가 없다는 뜻이다. 다만 그 경우 이
    함수를 부르는 쪽이 이미 상태를 읽어 넣으므로, 빈 dict 는 P2 시절 호출(시험)에서만
    나타나고 그때는 `required` 키가 없어 아무 것도 막지 않는다.
    """
    state = request.checkpoint_state or {}
    if not state.get("required"):
        return
    if request.purpose not in NEEDS_CONTROLLED_START:
        return
    if state.get("start_confirmed"):
        return
    treated = state.get("is_treatment")
    detail = (
        "이 업무는 controlled 이며 시작 목표·범위·기준·허용 행동의 확인이 아직 없다."
        f" {request.purpose.value} 는 그 확인 뒤에 배정한다"
    )
    if treated:
        detail += (
            ". 이 Case 는 Autonomy 가 기록되지 않아 controlled 로 취급되고 있다"
            " — Autonomy 를 기록하면 그 설정을 따른다"
        )
    refuse(AdmissionRefusal.CONTROLLED_START_NOT_CONFIRMED, detail)


def _check_objective(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """이 목적이 Case 의 합의된 목적 안인가(P3-R4·D-66·FR-20).

    "원인 분석만 요청한 Case 는 허용된 조사·임시 실험을 수행할 수 있지만 **제품
    수정으로 목적을 확대하지 않는다**"의 구현이다. 실험은 열려 있고 기능 구현이
    닫혀 있는 것이 그 문장의 내용이며, 넓히는 방법은 사용자의 명시 결정 하나다.

    **로컬 실험은 Profile 이 기록된 Case 에서만 연다.** R1 이전 Case 의 목적을
    `kind` 에서 유도해 채우지 않는다는 규칙(D-62)이 여기에도 적용된다 — 유도한
    목적으로 쓰기를 여는 것은 그 규칙을 가장 비싼 방식으로 어기는 일이다.
    """
    if purpose_outside_objective(
        request.purpose, request.case_profile, request.objective_widened
    ):
        refuse(
            AdmissionRefusal.PURPOSE_OUTSIDE_CASE_OBJECTIVE,
            f"이 업무의 Profile 은 {request.case_profile} 이며 조사·분석이 목적이다."
            f" {request.purpose.value} 는 제품 수정이므로 목적 확대에 해당한다 —"
            " 사용자의 명시 결정으로 목적을 넓힌 뒤에 배정한다. 허용된 로컬 실험은"
            " 그대로 수행할 수 있다",
        )
    if request.purpose is RunPurpose.LOCAL_EXPERIMENT and not experiment_allowed(
        request.case_profile
    ):
        refuse(
            AdmissionRefusal.PROFILE_NOT_RECORDED,
            "이 업무에 Profile 이 기록되지 않아 어떤 목적의 실험인지 알 수 없다."
            " 유형에서 유도해 쓰기를 열지 않는다",
        )


def _check_material_delta(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """확인되지 않은 누적 변경이 이 Task 를 막는가(P3-R4·D-60).

    차단 범위는 **그 변경이 가리키는 기준에 붙은 Task** 다. 의도 항목·저장소 허용의
    변경은 특정 Task 에 대응시킬 수 없으므로 **전부 막는다** — 그것들은 Case 의 범위
    자체를 바꾼다.

    연결을 모르는 변경도 전부 막는다. "아무 것도 막지 않는다"가 아니라 **무엇을
    막는지 모른다**는 뜻이고, 모르는 것을 안전한 쪽으로 읽으면 연결하지 않는 것만으로
    차단이 사라진다(`controller/work_graph.py` 의 같은 규칙).
    """
    if request.purpose is RunPurpose.DISCUSSION_REPLY:
        # UI-01. **논의 응답은 막지 않는다.** 읽기 전용이라 어떤 기준·항목도 바꾸지
        # 않고, 확인되지 않은 변경에 대해 **이야기하는 것**조차 막으면 사람이 그 변경을
        # 논의할 수단이 없어진다. 변경에 의존하는 작업은 여전히 막힌다.
        return
    state = request.material_delta_state or {}
    pending = state.get("pending") or []
    if not pending:
        return
    blocks_all = state.get("blocks_all_tasks")
    blocked = set(state.get("blocked_task_keys") or [])
    if not blocks_all and request.task_id not in blocked:
        return
    keys = ", ".join(d["target_key"] for d in pending)
    detail = (
        f"마지막 유효 위임 기준과 대조해 확인하지 않은 변경이 {len(pending)}건 쌓여"
        f" 있다: {keys}. 그 변경에 의존하는 작업은 확인 뒤에 배정한다"
    )
    if blocks_all:
        detail += ". 어떤 작업을 막는지 연결되지 않은 변경이 있어 전부 막는다"
    refuse(AdmissionRefusal.MATERIAL_DELTA_UNCONFIRMED, detail)


def _check_conversation(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """준비 단계와 사용자 요청의 조건(UI-01·D-69·D-70).

    1. **준비 단계에서는 논의 응답만 연다.** 목표·Profile 이 없는 Case 에서 의도 초안·
       검토·준비·구현·검증·실험을 열면 목적 없는 업무가 생긴다. 업무화가 먼저다.
    2. **논의 응답은 요청에 묶인다.** 어떤 메시지에 대한 응답인지 없으면 대화의 어느
       자리에도 붙을 수 없다.
    3. **요청에 묶인 실행은 그 요청이 처리 중일 때만 연다.** 끝난 요청에 실행을 붙이면
       잠금이 풀린 채 실행이 돈다. 요청을 모르면 처리 중으로 읽지 않는다. 처리 중이어도
       **중단이 요청됐으면 열지 않는다**(UI-02·D-76).
    4. **그 요청을 연 메시지가 PC 에 저장돼야 한다.** 받지 않은 말을 처리하지 않는다.
    5. **논의 응답의 지시는 그 메시지 원문이다.** 다른 지시를 주면 응답이 받은 말이
       아닌 것에 대한 것이 된다.
    """
    if (
        request.case_stage == CaseStage.DISCUSSION.value
        and request.purpose is not RunPurpose.DISCUSSION_REPLY
    ):
        refuse(
            AdmissionRefusal.CASE_IN_DISCUSSION_STAGE,
            "이 대화는 아직 준비 단계다(목표·Profile 미정). 논의 응답 말고는 배정하지"
            f" 않는다 — {request.purpose.value} 는 업무화 뒤에 배정한다",
        )
    if request.purpose is RunPurpose.DISCUSSION_REPLY and request.request_id is None:
        refuse(
            AdmissionRefusal.REQUEST_REQUIRED,
            "논의 응답은 어떤 요청에 대한 응답인지가 있어야 한다(request_id)",
        )
    if request.request_id is None:
        return
    state = request.request_state or {}
    if not state.get("in_case") or state.get("state") != RequestState.PROCESSING.value:
        refuse(
            AdmissionRefusal.REQUEST_NOT_PROCESSING,
            f"요청 {request.request_id} 은 처리 중이 아니다"
            f"({state.get('state') or '이 업무의 요청이 아님'}). 끝난 요청에 실행을"
            " 붙이지 않는다",
        )
        return
    if state.get("stop_requested_at"):
        # UI-02. 중단 요청은 **후속 실행 시작을 막는다**(D-76). 처리 중이라는 사실만 보면
        # 중단 요청 뒤에 새 실행이 시작된다.
        refuse(
            AdmissionRefusal.REQUEST_STOP_REQUESTED,
            f"요청 {request.request_id} 에 중단이 요청됐다({state['stop_requested_at']})."
            " 관련 실행의 실제 종료를 확인하는 동안 새 실행을 시작하지 않는다",
        )
        return
    if state.get("opening_receipt") != MessageReceipt.STORED.value:
        refuse(
            AdmissionRefusal.REQUEST_ORIGINAL_NOT_STORED,
            f"요청을 연 메시지가 {state.get('opening_receipt')} 상태다. PC 가 저장하기"
            " 전에는 처리하지 않는다",
        )
    if request.purpose is RunPurpose.DISCUSSION_REPLY:
        opening = (state.get("opening_artifact_id"), state.get("opening_artifact_rev"))
        if request.instruction_artifact is None or tuple(request.instruction_artifact) != opening:
            refuse(
                AdmissionRefusal.REQUEST_INSTRUCTION_MISMATCH,
                "논의 응답의 지시는 그 요청을 연 메시지 원문이어야 한다",
            )


def budget_refusal_reason(breaches: list[dict[str, Any]]) -> str:
    """예산 거부의 사람용 설명. **무엇이 얼마나 찼는지와 그 보장 범위**를 담는다.

    `guarantee` 를 문구에 넣는 이유는 `no_absolute_cap` 한도가 왜 초과된 값을
    보여 주는지를 같은 자리에서 설명하기 위해서다 — 진행 중 실행을 초 단위로 끊을
    수 없어 노출이 한도를 넘어설 수 있다(D-61).
    """
    detail = "; ".join(
        f"{b['metric']} {b['exposure']}/{b['limit_value']} {b['unit']} ({b['guarantee']})"
        for b in breaches
    )
    return (
        f"설정된 hard 한도에 도달했다: {detail}."
        " 그 한도를 소비하는 새 실행을 배정하지 않는다. 현재 결과·남은 작업은"
        " 그대로 보존되며, 한도를 바꾸거나 해제하면 다시 배정된다"
    )


def _check_budget(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """설정된 hard 예산이 이 실행을 허용하는가(P3-R3).

    **완료도 취소도 아니다.** 그 한도를 소비하는 새 실행을 배정하지 않을 뿐이며
    현재 결과·미검증·남은 작업은 그대로 보존된다(autonomy-budget-policy 8절).

    `continue` 류의 예외 인자를 받지 않는 것이 이 함수의 계약이다. 한도를 그대로 둔
    채 이어 가는 경로가 있으면 hard 는 경고선과 같아진다(D-61).
    """
    if request.budget_breaches:
        refuse(
            AdmissionRefusal.BUDGET_HARD_LIMIT_REACHED,
            budget_refusal_reason(request.budget_breaches),
        )


def _check_context(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """핵심 입력을 갖추고 한 실행에 담을 수 있는가(P4-04).

    **핵심을 빼고 실행하지 않는다**(review-context-contract 4절 1항). 한도 때문에
    자르지 않고, 원문이 아직 없거나 사라졌다고 건너뛰지 않는다. 두 경우 모두 그 실행만
    보류된다 — 다른 Case·다른 목적은 막지 않는다.

    보조 입력(AI 의 이전 제안)은 여기서 막지 않는다. 한도를 넘으면 계획이 이미 드러내어
    생략했고, 원문을 못 읽으면 Runner 가 영수증에 적고 실행은 `partial` 이 된다.
    """
    plan = request.context_plan
    if plan.get("over_limit"):
        refuse(
            AdmissionRefusal.CONTEXT_OVER_INLINE_LIMIT,
            f"지시와 핵심 입력만으로 {plan['core_bytes']} 바이트라 한 실행의 인라인 한도"
            f" {plan['limit']} 바이트를 넘는다(보조 입력을 빼도 넘는다)."
            " 핵심 입력을 잘라 실행하지 않는다 — 요청·대화를 나누거나 한도를 조정해야 한다",
        )
    if request.context_unavailable:
        detail = ", ".join(
            f"{u['role']} {u['artifact_id']}@{u['revision']}={u['availability']}"
            for u in request.context_unavailable
        )
        refuse(
            AdmissionRefusal.REQUIRED_CONTEXT_UNAVAILABLE,
            f"핵심 입력의 원문을 지금 읽을 수 없다: {detail}."
            " 그 입력을 빼고 실행하지 않는다 — 저장 대기면 저장된 뒤, 유실이면 다시 보내거나"
            " 그 입력을 정리한 뒤 실행한다",
        )


def _check_knowledge(request: AdmissionRequest, refuse: Callable[..., None]) -> None:
    """적용되는 필수 지식이 서로 충돌하는가(P4-06).

    근거만으로 풀지 못한 충돌은 사람에게 묻고 **그 지식에 의존하는 작업만** 보류한다 — 두 항목이
    모두 이 실행에 적용될 때만 막고 무관한 업무는 막지 않는다(project-knowledge 2절). 최신 날짜나
    좁은 경로로 한쪽을 조용히 고르지 않는다.
    """
    if request.knowledge_conflicts:
        detail = ", ".join(
            f"{c['knowledge_a']}↔{c['knowledge_b']}" for c in request.knowledge_conflicts
        )
        refuse(
            AdmissionRefusal.KNOWLEDGE_CONFLICT_UNRESOLVED,
            f"이 실행에 적용되는 필수 지식이 서로 충돌한다: {detail}. 사람이 해소(한쪽 무효·개정·"
            "해소 기록)한 뒤 진행한다",
        )


def evaluate(request: AdmissionRequest) -> AdmissionResult:
    """진입 조건을 검사한다. 거부 사유는 **모두** 모은다.

    첫 번째 사유에서 멈추지 않는 이유는 사람이 무엇을 갖춰야 하는지 한 번에 알아야
    하기 때문이다(FR-14: 전체 대화를 다시 읽지 않고 현재 상태를 알 수 있어야 한다).
    """
    refusals: list[AdmissionRefusal] = []
    reasons: dict[str, str] = {}
    profile = choose_profile(request)

    def refuse(reason: AdmissionRefusal, message: str) -> None:
        if reason not in refusals:
            refusals.append(reason)
            reasons[reason.value] = message

    # --- 모든 목적에 공통인 조건 --------------------------------------------

    # 종료된 Case 는 조건을 갖춰도 열리지 않는다. 완료 후 수정은 기존 Case 재개가
    # 아니라 연결된 새 Case 다(D-33). **검사 기록으로 남기려고** 여기서 본다 —
    # 앞단에서 예외로 던지면 "왜 실행이 열리지 않았는가"가 진입 검사 표에 없다.
    if request.case_closed and not (
        request.explanation_entry
        and request.purpose is RunPurpose.DISCUSSION_REPLY
        and request.permission is Permission.READ_ONLY
        and request.request_id is not None
    ):
        # P4-05. 종료 Case 에서 열리는 것은 **설명 전용 논의 응답**뿐이다(D-87). 읽기 전용이고
        # 요청에 묶여 같은 Case 의 예산에 누적된다. 그 밖의 목적·권한은 그대로 거부다.
        refuse(
            AdmissionRefusal.CASE_ALREADY_CLOSED,
            "이미 종료된 업무다. 수정은 연결된 새 Case 로 한다",
        )

    expected_role = EXPECTED_ROLE[request.purpose]
    if request.role is not expected_role:
        refuse(
            AdmissionRefusal.ROLE_MISMATCH,
            f"{request.purpose.value} 는 role={expected_role.value} 로 실행한다",
        )

    allowed = ALLOWED_PERMISSIONS.get(request.purpose, frozenset({Permission.READ_ONLY}))
    if request.permission not in allowed:
        refuse(
            AdmissionRefusal.PERMISSION_NOT_ALLOWED_IN_STAGE,
            f"{request.purpose.value} 에 {request.permission.value} 는 배정하지 않는다."
            f" 허용: {', '.join(sorted(p.value for p in allowed))}",
        )
    elif request.permission in WRITE_PERMISSIONS:
        # 권한이 열린 목적이어도 **작업공간과 경합 조건을 따로 본다.**
        _check_workspace(request, refuse)

    # **준비 단계와 사용자 요청**(UI-01). 종료 다음에 본다 — 둘 다 "이 대화가 지금
    # 이 실행을 받을 자리인가"이고, 사람이 할 일(업무화·요청 종료 대기)이 앞의 것들보다
    # 먼저 알려져야 한다.
    _check_conversation(request, refuse)

    # 대상 저장소는 **권한과 무관하게** 본다(P3-R2). 읽기 전용 검토도 어느 코드를
    # 보는지 정해져 있어야 한다.
    _check_workspace_target(request, refuse)
    # 그리고 그 대상이 **이 Task 의 저장소인지**를 따로 본다(P3-04). 위 검사는
    # "기록됐는가"이고 이것은 "맞는가"다.
    _check_task_repository(request, refuse)

    if not request.tool_installed:
        refuse(
            AdmissionRefusal.TOOL_NOT_AVAILABLE,
            f"{request.tool_id} 를 사용 가능하다고 보고한 Runner가 없다",
        )
    elif not request.permission_mapped:
        # 매핑을 못 하면 더 넓은 권한으로 조용히 대체하지 않고 거부한다(P1 계약 6절).
        refuse(
            AdmissionRefusal.PERMISSION_NOT_MAPPED,
            f"{request.tool_id} 에 {request.permission.value} 매핑이 확인되지 않았다",
        )

    if request.instruction_availability != "available":
        refuse(
            AdmissionRefusal.INSTRUCTION_NOT_AVAILABLE,
            f"지시 원문이 {request.instruction_availability} 상태라 실행자가 읽을 수 없다",
        )
    # 지시 원문 다음에 **나머지 핵심 입력**을 본다(P4-04). 같은 질문의 연장이다 —
    # 실행자가 읽어야 할 것을 읽을 수 있는가.
    _check_context(request, refuse)
    _check_knowledge(request, refuse)

    latest = request.intent_state.get("latest_intent_version")
    agreement_state = request.intent_state.get("agreement_state")
    gate_verdict = request.gate_state.get("verdict")

    # --- 목적별 조건 ---------------------------------------------------------

    # 초안 작성과 의미 검토는 **AI가 글을 써야** 성립한다. 골격 실행기로 배정하면
    # 실행은 정상 종료하는데 산출물이 없어 아무 일도 일어나지 않은 것처럼 보인다.
    # 그 조합을 화면이 아니라 여기서 막는다.
    if request.purpose in NEEDS_CODING_CLI:
        if request.tool_installed and not request.tool_is_coding_cli:
            refuse(
                AdmissionRefusal.TOOL_IS_NOT_A_CODING_CLI,
                f"{request.tool_id} 는 코딩 CLI가 아니다."
                f" {request.purpose.value} 는 실제 AI 실행이 필요하다",
            )

    if request.purpose is RunPurpose.INTENT_GATE_REVIEW:
        target = request.target_intent_version_id or (latest or {}).get("id")
        if target is None:
            refuse(
                AdmissionRefusal.INTENT_VERSION_MISSING,
                "검토할 의도 버전이 없다",
            )
        elif target != (latest or {}).get("id"):
            # **대체된 버전을 검토하지 않는다.** 검토가 끝나도 최신 버전의 게이트는
            # 그대로 `not_run` 이라 아무 것도 진척되지 않고, 화면에는 옛 버전의
            # 판정이 새 결과처럼 보인다. 실제 CLI를 부르기 전에 여기서 막는다.
            refuse(
                AdmissionRefusal.INTENT_VERSION_NOT_LATEST,
                "검토 대상이 최신 의도 버전이 아니다."
                " 최신 버전의 의도 원문을 지시로 지정한다",
            )
        elif (latest or {}).get("availability") != "available":
            refuse(
                AdmissionRefusal.INTENT_ORIGINAL_NOT_AVAILABLE,
                "검토할 의도 원문을 지금 읽을 수 없다",
            )
        # 의미 검토는 **작성과 별도 세션**이어야 한다. 세션을 이어받는 요청은 거부한다.
        if request.session != "new":
            refuse(
                AdmissionRefusal.REVIEW_SESSION_NOT_SEPARATE,
                "의미 검토는 새 세션에서 수행한다. 작성 세션을 이어받지 않는다",
            )
        elif (
            request.requested_session_ref is not None
            and request.requested_session_ref in request.author_session_refs
        ):
            refuse(
                AdmissionRefusal.REVIEW_SESSION_NOT_SEPARATE,
                "요청한 세션이 이 초안을 작성한 세션과 같다",
            )

    if request.purpose in NEEDS_AGREED_INTENT:
        if profile is AdmissionProfile.FEATURE_INTENT:
            if agreement_state != IntentAgreementState.AGREED_CURRENT.value:
                refuse(
                    AdmissionRefusal.INTENT_NOT_AGREED,
                    f"최신 의도에 대한 동의가 없다(현재 {agreement_state})",
                )
            open_questions = request.intent_state.get("open_intent_questions") or []
            if open_questions:
                refuse(
                    AdmissionRefusal.OPEN_INTENT_QUESTIONS,
                    "의도 단계에서 결정할 질문이 남아 있다: "
                    + ", ".join(q["question_key"] for q in open_questions),
                )
            if latest is not None and latest.get("availability") != "available":
                refuse(
                    AdmissionRefusal.INTENT_ORIGINAL_NOT_AVAILABLE,
                    "동의 대상 의도 원문을 지금 읽을 수 없다",
                )
            if gate_verdict != GateVerdict.PASS.value:
                refuse(
                    AdmissionRefusal.INTENT_GATE_NOT_PASSED,
                    f"QG-01 이 {gate_verdict} 상태다. 필수 게이트는 끌 수 없다",
                )

    # 계획 작성은 **검토된 설계 위에서만** 한다. 의존 관계가
    # `의도 → 설계 → 개발계획` 이므로(intent-artifacts 2절) 설계가 없거나 아직
    # 검토되지 않았으면 무엇을 구현할 계획인지 말할 수 없다.
    if request.purpose is RunPurpose.PLAN_AUTHORING:
        # **Fast Lane 에서는 설계를 선행 조건으로 받지 않는다**(P3-R4·D-60).
        #
        # 그 실행이 쓰는 것은 계획이 아니라 **결합 기록**이며, 결합 기록은 설계 위에
        # 세우는 것이 아니라 설계의 자리를 함께 대신한다. 설계를 요구하면 "별도
        # 설계·계획 파일 없이 진행한다"가 성립할 수 없다.
        #
        # **설계가 이미 있으면 Fast Lane 이어도 그대로 요구한다.** 있는 설계를
        # 건너뛰고 결합 기록을 쓰면 그 설계가 버려진다 — 같은 판단이
        # `Repository._authoring_stage` 에 있고 두 곳이 같은 값을 본다.
        prep = request.preparation_state or {}
        has_design = (prep.get(PreparationStage.DESIGN.value) or {}).get("artifact")
        fast_lane = bool((request.fast_lane or {}).get("eligible"))
        if has_design is not None or not fast_lane:
            _check_stage_ready(request, PreparationStage.DESIGN, refuse)

    if request.purpose in NEEDS_PREPARATION:
        # **여기가 P3-01이 여는 문이다.** P2까지는 선행 조건의 구현이 없어 한 줄로
        # 거부했다. 이제 실제로 검사하고, 갖춰졌으면 허용한다.
        #
        # 아래 검사는 조건표(`profile`)와 무관하게 **항상** 돈다. 의도 버전이 없는
        # Case 는 `non_feature_minimal` 조건표를 받아 의도 동의를 요구받지 않지만,
        # 준비 산출물은 의도 버전 위에만 만들 수 있고(repository) 의도 버전이 하나라도
        # 생기면 조건표가 기능 쪽으로 바뀐다. 그래서 "유형을 비기능으로 두고 설계·계획만
        # 만들어 통과한다"는 우회는 구조적으로 닫혀 있다(FR-29 유형 변경 우회 금지).
        prep = request.preparation_state or {}
        if not prep.get("level"):
            refuse(
                AdmissionRefusal.SIZING_NOT_DECIDED,
                "작업 수준이 결정되지 않았다. 축별 판단이 있는 의도 초안이 필요하다",
            )
        # **P3-R4에서 산출물의 개수가 조건에 따라 달라진다.** Fast Lane 이면 결합
        # 기록 하나로 충분하고, 아니면 설계+계획 두 건이다. 어느 쪽이든 **없어지는
        # 것은 없다** — 필수 항목이 미정이면 그대로 거부된다.
        _check_preparation(request, refuse)

        # **계획이 옛 설계의 것인지는 여기서 보지 않는다.** 설계를 새로 만들면
        # 그 위에 세웠던 계획이 곧바로 대체되므로(repository.create_preparation_artifact)
        # 이 상태는 `plan_missing` 으로 드러난다. 여기에 같은 뜻의 두 번째 검사를 두면
        # 닿을 수 없는 분기가 되고, 닿을 수 없는 검사는 시험할 수도 없다.
        # 대체된 계획은 단계별 목록에 `superseded` 로 남아 무엇이 있었는지 조회된다.

    if request.purpose in NEEDS_WORK_GRAPH:
        _check_work_graph(request, refuse)

    # --- P3-R4: Autonomy·목적·누적 변경 ------------------------------------
    #
    # 예산보다 **앞에** 둔다. 앞의 조건들과 같은 종류이기 때문이다 — "이 실행을 열 수
    # 있는가"를 묻는다. 예산만 마지막에 남는다(그것은 "살 수 있는가"다).
    _check_autonomy(request, refuse)
    _check_objective(request, refuse)
    _check_material_delta(request, refuse)

    if request.quality_gate_blockers:
        refuse(
            AdmissionRefusal.QUALITY_GATE_NOT_PASSED,
            "명시한 품질 게이트가 현재 입력에서 통과하지 않았다: "
            + ", ".join(
                f"{item['gate']}({item['verdict']})"
                for item in request.quality_gate_blockers
            ),
        )

    # **저장과 배정 사이의 변경을 본다**(P4-02). 위 검사가 "통과했는가"라면 이것은
    # "그 통과를 만든 정책이 아직 그대로인가"다. 옛 배정 요청만으로 시작하지 않는다.
    if request.quality_gate_policy_drift:
        refuse(
            AdmissionRefusal.QUALITY_GATE_POLICY_CHANGED,
            "요청이 기대한 게이트 정책이 그 사이 바뀌었다: "
            + ", ".join(
                f"{item['gate']}(기대 {item['expected_revision']} →"
                f" 현재 {item['current_revision']})"
                for item in request.quality_gate_policy_drift
            ),
        )

    # **예산은 마지막에 본다.** 앞의 조건들은 "이 실행을 열 수 있는가"이고 이것은
    # "열어도 되는데 살 수 있는가"이다. 순서를 바꾸면 조건을 갖추지 못한 요청이 예산
    # 사유로만 거부돼 사람이 엉뚱한 것을 고치게 된다.
    _check_budget(request, refuse)

    outcome = AdmissionOutcome.REFUSED if refusals else AdmissionOutcome.ADMITTED
    return AdmissionResult(
        outcome=outcome,
        profile=profile,
        refusals=refusals,
        reasons=reasons,
        intent_version_id=(latest or {}).get("id"),
        intent_agreement_state=agreement_state,
        gate_verdict=gate_verdict,
    )
