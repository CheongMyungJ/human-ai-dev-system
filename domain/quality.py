"""P4-01 품질 게이트 선택과 repair의 결정적 규칙.

이 모듈은 본문을 읽지 않는다. Profile·WorkDepth·Task 종류·저장소 수·명시 설정처럼
제어부가 실제로 아는 구조화된 사실에서 **적용안**을 계산한다. 의미 판정이 필요하면
`independent`를 요구할 뿐 여기서 통과를 만들지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from domain.models import CaseProfile, GateId, TaskKind, WorkLevel


DEFAULT_REPAIR_LIMIT = 2


class GateSetting(str, Enum):
    REQUIRED = "required"
    ON = "on"
    OFF = "off"
    NOT_APPLICABLE = "not_applicable"


class InspectionMethod(str, Enum):
    RULE = "rule"
    LIGHT = "light"
    INDEPENDENT = "independent"


class GatePolicySource(str, Enum):
    SYSTEM_REQUIRED = "system_required"
    PROFILE_DEFAULT = "profile_default"
    AUTOMATIC_CONDITION = "automatic_condition"
    CASE_EXPLICIT = "case_explicit"
    TASK_EXPLICIT = "task_explicit"


class GateRunStatus(str, Enum):
    NOT_RUN = "not_run"
    RUNNING = "running"
    COMPLETED = "completed"
    BLOCKED = "blocked"


class GateValidity(str, Enum):
    CURRENT = "current"
    NEEDS_RECHECK = "needs_recheck"
    HISTORICAL = "historical"


@dataclass(frozen=True)
class EffectiveGatePolicy:
    gate: GateId
    setting: GateSetting
    inspection: InspectionMethod
    source: GatePolicySource
    reason: str
    repair_limit: int = DEFAULT_REPAIR_LIMIT

    @property
    def applied(self) -> bool:
        return self.setting in (GateSetting.REQUIRED, GateSetting.ON)


GATE_LABELS: dict[GateId, str] = {
    GateId.QG_01: "요청·의도 정합성",
    GateId.QG_02: "설계 적합성",
    GateId.QG_03: "개발계획 실행 가능성",
    GateId.QG_04: "구현 묶음 품질",
    GateId.QG_05: "통합·행동 검증",
    GateId.QG_06: "업무 종료 근거",
    GateId.QG_07: "연구·원인 판단 근거",
}


def _profile(value: str | None) -> CaseProfile | None:
    try:
        return CaseProfile(value) if value else None
    except ValueError:
        return None


def _level(value: str | None) -> WorkLevel | None:
    try:
        return WorkLevel(value) if value else None
    except ValueError:
        return None


def recommended_policy(
    gate: GateId,
    *,
    profile: str | None,
    level: str | None,
    task_kind: str | None = None,
    repository_count: int = 1,
    risk_requires_independent: bool = False,
    qg01_independent: bool = False,
) -> EffectiveGatePolicy:
    """현재 구조 사실에서 초기 적용안을 계산한다.

    명시 override는 저장 계층이 이 값 위에 얹는다. 이 함수가 사람 선택을 만들어
    기록하지 않는 이유다.
    """

    p = _profile(profile)
    depth = _level(level)
    try:
        kind = TaskKind(task_kind) if task_kind else None
    except ValueError:
        kind = None

    if gate is GateId.QG_01:
        return EffectiveGatePolicy(
            gate,
            GateSetting.REQUIRED,
            InspectionMethod.INDEPENDENT if qg01_independent else InspectionMethod.LIGHT,
            GatePolicySource.SYSTEM_REQUIRED,
            "기능 개발 요청 정합성은 필수이며 위험·불확실성에 따라 검사 강도만 달라진다",
        )

    independent = risk_requires_independent or depth is WorkLevel.DEEP
    semantic = InspectionMethod.INDEPENDENT if independent else InspectionMethod.RULE

    if gate is GateId.QG_02:
        applied = depth in (WorkLevel.STANDARD, WorkLevel.DEEP)
        return EffectiveGatePolicy(
            gate,
            GateSetting.ON if applied else GateSetting.NOT_APPLICABLE,
            semantic,
            GatePolicySource.AUTOMATIC_CONDITION,
            "standard/deep은 채택할 설계 기록이 필요하다"
            if applied
            else "simple 경로에는 별도 설계 채택 경계가 없다",
        )

    if gate is GateId.QG_03:
        applied = kind is not None or p in {
            CaseProfile.FEATURE,
            CaseProfile.DEFECT_FIX,
            CaseProfile.REFACTORING,
            CaseProfile.MAINTENANCE,
        }
        return EffectiveGatePolicy(
            gate,
            GateSetting.ON if applied else GateSetting.NOT_APPLICABLE,
            semantic,
            GatePolicySource.PROFILE_DEFAULT,
            "실행 Task와 검증 연결을 채택한다"
            if applied
            else "결론 채택형 업무라 실행 계획 게이트를 자동 적용하지 않는다",
        )

    if gate is GateId.QG_04:
        applied = kind in {
            TaskKind.IMPLEMENTATION,
            TaskKind.EXPERIMENT,
        } or (kind is None and p in {
            CaseProfile.FEATURE,
            CaseProfile.DEFECT_FIX,
            CaseProfile.REFACTORING,
            CaseProfile.MAINTENANCE,
        })
        return EffectiveGatePolicy(
            gate,
            GateSetting.ON if applied else GateSetting.NOT_APPLICABLE,
            semantic,
            GatePolicySource.PROFILE_DEFAULT,
            "코드·변경 묶음의 품질을 채택한다"
            if applied
            else "이 대상에는 구현 묶음이 없다",
        )

    if gate is GateId.QG_05:
        applied = (
            kind is TaskKind.INTEGRATION
            or repository_count > 1
            or depth is WorkLevel.DEEP
        )
        return EffectiveGatePolicy(
            gate,
            GateSetting.ON if applied else GateSetting.NOT_APPLICABLE,
            InspectionMethod.INDEPENDENT if independent else InspectionMethod.RULE,
            GatePolicySource.AUTOMATIC_CONDITION,
            "통합 Task·복수 저장소·deep 중 하나가 실제 통합 검증을 요구한다"
            if applied
            else "별도 통합 채택 경계가 관찰되지 않았다",
        )

    if gate is GateId.QG_06:
        return EffectiveGatePolicy(
            gate,
            GateSetting.ON,
            InspectionMethod.RULE,
            GatePolicySource.SYSTEM_REQUIRED,
            "모든 Case는 종료 전에 현재 기준·증거·실행 상태를 대조한다",
        )

    if gate is GateId.QG_07:
        applied = kind is TaskKind.INVESTIGATION or p in {
            CaseProfile.ROOT_CAUSE_ANALYSIS,
            CaseProfile.RESEARCH,
        }
        return EffectiveGatePolicy(
            gate,
            GateSetting.ON if applied else GateSetting.NOT_APPLICABLE,
            semantic,
            GatePolicySource.PROFILE_DEFAULT,
            "연구·원인 결론의 주장 범위와 근거를 채택한다"
            if applied
            else "연구·원인 결론 채택 업무가 아니다",
        )

    raise ValueError(f"unsupported gate: {gate.value}")


def inspection_satisfies(required: InspectionMethod, used: InspectionMethod) -> bool:
    order = {
        InspectionMethod.RULE: 0,
        InspectionMethod.LIGHT: 1,
        InspectionMethod.INDEPENDENT: 2,
    }
    return order[used] >= order[required]

