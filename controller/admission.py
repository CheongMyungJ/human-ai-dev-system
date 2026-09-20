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

그리고 **없는 선행 조건을 통과로 처리하지 않는다.** 설계·계획 검토는 아직 구현이
없으므로 그것을 요구하는 목적(`feature_implementation`)은 임시 통과가 아니라
`prerequisite_not_implemented` 로 거부된다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from domain.models import (
    AdmissionOutcome,
    AdmissionProfile,
    AdmissionRefusal,
    CaseKind,
    GateVerdict,
    IntentAgreementState,
    Permission,
    RunPurpose,
    RunRole,
)

#: 이번 단계에서 배정할 수 있는 권한.
#:
#: 쓰기 권한은 **제품이 지원하지 않는 것이 아니라 이 단계에서 열지 않은 것이다.**
#: 선행 조건(설계·계획 검토)이 없는 상태로 코드를 바꾸는 실행을 배정하지 않는다
#: (DEVELOPMENT.md P2 제외 범위).
STAGE_ALLOWED_PERMISSIONS: frozenset[Permission] = frozenset({Permission.READ_ONLY})

#: 목적별로 기대하는 역할. 의미 검토는 작성과 분리해야 한다(FR-29 검토 방식).
EXPECTED_ROLE: dict[RunPurpose, RunRole] = {
    RunPurpose.INTENT_AUTHORING: RunRole.AUTHOR,
    RunPurpose.INTENT_GATE_REVIEW: RunRole.REVIEWER,
    RunPurpose.LIMITED_ANALYSIS: RunRole.AUTHOR,
    RunPurpose.FEATURE_IMPLEMENTATION: RunRole.AUTHOR,
}


@dataclass
class AdmissionRequest:
    """검사 입력. 제어부가 가진 상태만으로 판단한다. 본문은 들어오지 않는다."""

    case_id: str
    case_kind: CaseKind
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
    author_session_refs: list[str] = field(default_factory=list)
    requested_session_ref: str | None = None


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
    has_intent = request.intent_state.get("latest_intent_version") is not None
    if has_intent or request.case_kind is CaseKind.FEATURE:
        return AdmissionProfile.FEATURE_INTENT
    return AdmissionProfile.NON_FEATURE_MINIMAL


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

    expected_role = EXPECTED_ROLE[request.purpose]
    if request.role is not expected_role:
        refuse(
            AdmissionRefusal.ROLE_MISMATCH,
            f"{request.purpose.value} 는 role={expected_role.value} 로 실행한다",
        )

    if request.permission not in STAGE_ALLOWED_PERMISSIONS:
        refuse(
            AdmissionRefusal.PERMISSION_NOT_ALLOWED_IN_STAGE,
            f"{request.permission.value} 는 이 단계에서 배정하지 않는다."
            " 코드를 바꾸는 실행은 설계·계획 선행 조건이 준비된 뒤에 연결한다",
        )

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

    latest = request.intent_state.get("latest_intent_version")
    agreement_state = request.intent_state.get("agreement_state")
    gate_verdict = request.gate_state.get("verdict")

    # --- 목적별 조건 ---------------------------------------------------------

    if request.purpose is RunPurpose.INTENT_GATE_REVIEW:
        target = request.target_intent_version_id or (latest or {}).get("id")
        if target is None:
            refuse(
                AdmissionRefusal.INTENT_VERSION_MISSING,
                "검토할 의도 버전이 없다",
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

    if request.purpose in (RunPurpose.LIMITED_ANALYSIS, RunPurpose.FEATURE_IMPLEMENTATION):
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

    if request.purpose is RunPurpose.FEATURE_IMPLEMENTATION:
        # 설계·계획 검토와 그 사람 검토는 아직 구현이 없다. 없는 조건을 통과로
        # 처리하는 대신 그 사실을 거부 사유로 드러낸다(P2 제외 범위).
        refuse(
            AdmissionRefusal.PREREQUISITE_NOT_IMPLEMENTED,
            "설계·계획 검토와 쓰기 권한 경로가 아직 없다."
            " 기능 코드 변경 실행은 P3에서 선행 조건과 함께 연결한다",
        )

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
