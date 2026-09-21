"""자동 진행의 판정 — Autonomy·Fast Lane·정합성 방식·누적 변경(P3-R4).

**여기에는 DB도 HTTP도 없다.** `domain/sizing.py`·`controller/work_graph.py`·
`domain/budget.py` 와 같은 자리이며 같은 이유로 그렇게 둔다 — 진입 검사·완료 판정·
화면·시험이 **모두 같은 함수를 봐야** 하고, 두 벌로 쓰면 한쪽만 고치는 실수가 생긴다.
R2 가 실제로 그 실수를 했다(P3-R2 결과 9절 결함 1).

이 파일이 지키는 네 가지:

    1. 기록과 취급을 구분한다     `autonomy = NULL` 을 `controlled` 로 **취급**하되
                                   `controlled` 로 **적지 않는다**
    2. 방식과 결과를 구분한다     가벼운 확인을 독립 검토 완료로 표시하지 않는다
    3. 이탈은 확인이 아니다       Fast Lane 을 벗어나면 **준비를 추가**한다.
                                   그것만으로 사람을 부르지 않는다
    4. 모르면 막는다              연결을 모르는 변경은 전부 막는다. 모르는 것을
                                   안전한 쪽으로 읽지 않는다
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from domain.models import (
    Autonomy,
    CaseProfile,
    CompletionMode,
    ConformanceMethod,
    ContentOrigin,
    EffectiveAutonomySource,
    Materiality,
    PreparationStage,
    ReviewMode,
    RunPurpose,
    WorkLevel,
)

# ===================================================== 1. Autonomy 의 취급


@dataclass(frozen=True)
class EffectiveAutonomy:
    """**적용되는** Autonomy 와 그 출처.

    `recorded_value` 가 `None` 인데 `value` 가 `controlled` 인 조합이 정상이다 —
    R1 이전 Case 의 처리(사용자 결정 2026-09-22). 그 경우 `is_treatment` 가 참이며
    화면·조회가 "사람이 고른 설정"과 구별해 보인다.
    """

    value: Autonomy
    source: EffectiveAutonomySource
    recorded_value: Autonomy | None

    @property
    def is_treatment(self) -> bool:
        """기록되지 않은 값을 이행 정책으로 취급하고 있는가."""
        return self.source is not EffectiveAutonomySource.RECORDED

    @property
    def controlled(self) -> bool:
        return self.value is Autonomy.CONTROLLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "effective_autonomy": self.value.value,
            "effective_source": self.source.value,
            "is_treatment": self.is_treatment,
        }


#: 기록되지 않은 Autonomy 를 무엇으로 취급하는가.
#:
#: **사용자 결정(2026-09-22)이다.** 선택지는 세 가지였다 — v0.6 규칙 유지, 진행 차단,
#: controlled 취급. 사용자가 셋째를 골랐다. 기본값(`ask_on_decision`)으로 올리는 안은
#: 인계가 명시로 금지했으므로 후보가 아니었다(DEVELOPMENT.md 9절).
MIGRATED_UNKNOWN_TREATMENT = Autonomy.CONTROLLED


def effective_autonomy(recorded: str | Autonomy | None) -> EffectiveAutonomy:
    """저장된 값에서 **적용할** 값을 정한다.

    `None` 은 R1 이전 Case 다. `controlled` 로 취급하되 **저장된 값은 건드리지
    않는다** — 없는 사람의 선택을 기록하지 않기 위해서다.
    """
    if recorded is None:
        return EffectiveAutonomy(
            value=MIGRATED_UNKNOWN_TREATMENT,
            source=EffectiveAutonomySource.MIGRATED_UNKNOWN_TREATED_AS_CONTROLLED,
            recorded_value=None,
        )
    value = Autonomy(recorded)
    return EffectiveAutonomy(
        value=value,
        source=EffectiveAutonomySource.RECORDED,
        recorded_value=value,
    )


def derived_completion_mode(autonomy: EffectiveAutonomy) -> CompletionMode:
    """Autonomy 에서 완료 모드를 도출한다(D-31).

    기본 ask-on-decision 은 **조건을 충족하면 자동 완료**한다. controlled 는 결과
    후보를 사람이 확인한 뒤 종료한다. 이것은 `completion_policy` 행이 **없을 때의**
    값이며, 명시 설정은 그대로 이긴다(autonomy-budget-policy 5절 "사용자 명시 설정을
    조용히 덮어쓰지 않는다").
    """
    if autonomy.controlled:
        return CompletionMode.HUMAN_ACCEPTANCE
    return CompletionMode.AUTO_ON_CONDITIONS


def derived_review_mode(autonomy: EffectiveAutonomy) -> ReviewMode:
    """단계 검토의 기본값을 Autonomy 에서 도출한다(D-16·D-21·D-65).

    **controlled 도 자동 진행이다.** controlled 가 요구하는 것은 시작 범위와 결과
    후보의 확인이며 "설계·계획의 사람 검토는 별도 선택 사항"이다(D-65). 두 가지를
    묶으면 controlled 를 고른 사람이 요구하지 않은 검토까지 받게 된다.

    **취급 중인 Case 는 v0.6 기본값을 유지한다.** 11절의 결정은 진입·완료를 보수적으로
    하라는 것이지 옛 Case 의 단계 검토 설정을 새로 만들라는 것이 아니다. 그 Case 들은
    이미 사람 검토를 받고 있었고, 그 상태를 그대로 둔다.
    """
    if autonomy.is_treatment:
        return ReviewMode.HUMAN_REVIEW
    return ReviewMode.AUTO_PROCEED


# ============================================ 2. controlled 가 막는 목적

#: controlled 의 **시작 확인 전에는 배정하지 않는** 목적(D-65).
#:
#: **초안 작성·의미 검토·조사는 여기 없다.** 시작 확인의 대상이 "목표·범위·기준·허용
#: 행동"인데 사람이 그것을 확인하려면 **초안이 먼저 있어야 한다**(case-profiles 3절
#: "초안을 제시할 준비와 해당 작업을 실행할 준비를 구분한다"). 조사까지 막으면 확인에
#: 필요한 사실을 모을 수 없고 "질문과 무관한 조사까지 모두 멈추지 않는다"에도 어긋난다
#: (autonomy-budget-policy 9절 2).
#:
#: `LIMITED_ANALYSIS` 는 읽기 전용이고 R2 가 이미 대상 저장소를 고정한다. 실제로
#: 무엇을 바꾸는 목적만 이 집합에 있다.
NEEDS_CONTROLLED_START: frozenset[RunPurpose] = frozenset(
    {
        RunPurpose.DESIGN_AUTHORING,
        RunPurpose.PLAN_AUTHORING,
        RunPurpose.FEATURE_IMPLEMENTATION,
        RunPurpose.VERIFICATION_RUN,
        RunPurpose.LOCAL_EXPERIMENT,
    }
)


# =================================== 3. Profile 이 정하는 목적의 경계 (D-66)

#: 그 Profile 의 Case 에서 **제품 수정으로 목적을 확대하지 않는** 것들.
#:
#: "원인 분석만 요청한 Case 는 허용된 조사·임시 실험을 수행할 수 있지만 제품 수정으로
#: 목적을 확대하지 않는다"(FR-20 수용 기준, D-66). 로컬 실험은 열려 있고 기능 구현이
#: 닫혀 있는 것이 그 문장의 구현이다.
#:
#: 넓히는 방법은 **사용자의 명시 결정** 하나다(`delegation_basis` 의 `user_decision`).
#: Profile 재분류로 넓히지 않는다 — "분류 변경만으로 재승인·예산 초기화·기준 삭제를
#: 하지 않는다"(D-62).
INVESTIGATION_ONLY_PROFILES: frozenset[CaseProfile] = frozenset(
    {CaseProfile.ROOT_CAUSE_ANALYSIS, CaseProfile.RESEARCH}
)

#: 조사 목적 Profile 에서 닫히는 목적.
PRODUCT_CHANGE_PURPOSES: frozenset[RunPurpose] = frozenset(
    {RunPurpose.FEATURE_IMPLEMENTATION}
)


def purpose_outside_objective(
    purpose: RunPurpose,
    profile: str | None,
    objective_widened: bool,
) -> bool:
    """이 목적이 Case 의 합의된 목적 밖인가.

    `objective_widened` 는 **사용자의 명시 결정**이 있었는가다. AI 의 판단이나
    Profile 변경이 아니다.
    """
    if profile is None or objective_widened:
        return False
    try:
        case_profile = CaseProfile(profile)
    except ValueError:
        return False
    if case_profile not in INVESTIGATION_ONLY_PROFILES:
        return False
    return purpose in PRODUCT_CHANGE_PURPOSES


def experiment_allowed(profile: str | None) -> bool:
    """로컬 실험을 배정할 수 있는가.

    **Profile 이 기록되지 않았으면 열지 않는다.** R1 이전 Case 의 목적을 `kind` 에서
    유도해 채우지 않는다는 규칙(D-62)이 여기에도 적용된다 — 유도한 목적으로 쓰기를
    여는 것은 그 규칙을 가장 비싼 방식으로 어기는 일이다.
    """
    if profile is None:
        return False
    try:
        CaseProfile(profile)
    except ValueError:
        return False
    return True


# ====================================================== 4. Fast Lane 판정


#: Fast Lane 이 아닌 이유의 코드. 화면·거부 사유가 같은 값을 쓴다.
class FastLaneBlocker(str):
    LEVEL_NOT_SIMPLE = "level_not_simple"
    EVIDENCE_GAP = "evidence_gap"
    OPEN_INTENT_QUESTIONS = "open_intent_questions"
    DEFERRED_QUESTIONS = "deferred_questions"
    MATERIAL_DELTA_PENDING = "material_delta_pending"


_BLOCKER_DETAIL = {
    FastLaneBlocker.LEVEL_NOT_SIMPLE: "효과 수준이 간소가 아니다",
    FastLaneBlocker.EVIDENCE_GAP: "수준 판단에 근거가 부족한 축이 있다",
    FastLaneBlocker.OPEN_INTENT_QUESTIONS: "의도 단계에서 결정할 질문이 남아 있다",
    FastLaneBlocker.DEFERRED_QUESTIONS: "설계·계획으로 이월한 질문이 남아 있다",
    FastLaneBlocker.MATERIAL_DELTA_PENDING: "확인하지 않은 누적 변경이 있다",
}


@dataclass(frozen=True)
class FastLaneOutcome:
    """Fast Lane 조건의 판정과 **그렇지 않은 이유.**

    이유를 함께 돌려주는 이유는 이탈이 사람 확인 요구가 아니기 때문이다 — 무엇을
    더 준비해야 하는지 말할 수 있어야 한다(autonomy-budget-policy 4절 마지막).
    """

    eligible: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "blockers": [
                {"reason": b, "detail": _BLOCKER_DETAIL[b]} for b in self.blockers
            ],
        }


def assess_fast_lane(
    *,
    level: str | None,
    evidence_gap: bool,
    open_intent_questions: int,
    deferred_questions: int,
    pending_material_deltas: int,
) -> FastLaneOutcome:
    """Fast Lane 조건을 판정한다. **저장하지 않고 도출한다.**

    저장하면 "누가 그 값을 적었는가"가 새 문제가 되고, 조건이 바뀌었는데 값이 남아
    있는 상태를 다시 관리해야 한다(R3 의 `stop` 과 같은 판단).

    `level` 이 `None` 이면 수준 판단 자체가 없다. **간소로 읽지 않는다** — 판단이
    없는 것과 낮은 것은 다르며, 없는 것을 낮게 읽으면 아무 판단 없이 Fast Lane 이
    된다(`domain/sizing.py` 의 같은 규칙).
    """
    blockers: list[str] = []
    if level != WorkLevel.SIMPLE.value:
        blockers.append(FastLaneBlocker.LEVEL_NOT_SIMPLE)
    if evidence_gap:
        blockers.append(FastLaneBlocker.EVIDENCE_GAP)
    if open_intent_questions:
        blockers.append(FastLaneBlocker.OPEN_INTENT_QUESTIONS)
    if deferred_questions:
        blockers.append(FastLaneBlocker.DEFERRED_QUESTIONS)
    if pending_material_deltas:
        blockers.append(FastLaneBlocker.MATERIAL_DELTA_PENDING)
    return FastLaneOutcome(eligible=not blockers, blockers=tuple(blockers))


def required_stages(fast_lane: bool) -> tuple[frozenset[PreparationStage], ...]:
    """구현·검증이 요구하는 준비 산출물의 **대안 집합.**

    돌려주는 것은 "이 중 **하나**를 갖추면 된다"는 목록이다. 일반 경로는 설계+계획
    두 건이고, Fast Lane 에서는 결합 기록 한 건이 그 자리를 대신한다.

    **Fast Lane 이어도 설계·계획 경로가 사라지지 않는다.** 이미 두 산출물이 있으면
    그대로 통과한다 — 결합 기록은 대체하는 선택지이지 강제가 아니다.
    """
    pair = frozenset({PreparationStage.DESIGN, PreparationStage.PLAN})
    if fast_lane:
        return (pair, frozenset({PreparationStage.COMBINED}))
    return (pair,)


# ================================= 5. 요청 정합성 확인 — 가벼운 확인과 독립 검토


#: 독립 검토가 **필수**인 이유의 코드.
class IndependentReason(str):
    LEVEL_ABOVE_SIMPLE = "level_above_simple"
    EVIDENCE_GAP = "evidence_gap"
    MATERIAL_DELTA_PENDING = "material_delta_pending"
    CASE_POLICY = "case_policy_requires_independent_review"


_REASON_DETAIL = {
    IndependentReason.LEVEL_ABOVE_SIMPLE: "효과 수준이 간소를 넘어선다",
    IndependentReason.EVIDENCE_GAP: "수준 판단에 근거가 부족한 축이 있다",
    IndependentReason.MATERIAL_DELTA_PENDING: "확인하지 않은 누적 변경이 있다",
    IndependentReason.CASE_POLICY: "이 Case 의 설정이 독립 의미 검토를 요구한다",
}

#: 가벼운 확인이 **보지 않은 것.** 조회·화면에 값으로 남는다.
#:
#: 이 문장이 없으면 가벼운 확인과 독립 검토가 같은 `pass` 로 보인다. "실제 검사
#: 방식·근거·남은 불확실성을 남긴다"(autonomy-budget-policy 4절)의 구현이다.
LIGHT_UNVERIFIED_SCOPE = (
    "원문의 의미 대응을 AI 가 검토하지 않았다. 구조·참조·버전·필수 항목의 결정적"
    " 검사만 수행했다"
)


@dataclass(frozen=True)
class ConformanceRequirement:
    """이 Case 의 요청 정합성 확인을 **어떤 방식으로** 해야 하는가.

    QG-01 자체는 끌 수 없다(intent-artifacts 9행). 달라지는 것은 방식뿐이다.
    """

    required: ConformanceMethod
    reasons: tuple[str, ...]

    @property
    def light_allowed(self) -> bool:
        return self.required is ConformanceMethod.LIGHT

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_method": self.required.value,
            "independent_review_required": not self.light_allowed,
            "reasons": [
                {"reason": r, "detail": _REASON_DETAIL[r]} for r in self.reasons
            ],
        }


def required_conformance_method(
    *,
    level: str | None,
    evidence_gap: bool,
    pending_material_deltas: int,
    case_requires_independent: bool = False,
) -> ConformanceRequirement:
    """가벼운 확인으로 충분한가, 독립 의미 검토가 필요한가(D-25·D-60).

    **Case 설정은 올릴 수만 있고 내릴 수 없다.** `case_requires_independent` 는
    독립 검토를 요구하는 방향으로만 작용한다 — 규칙이 독립 검토를 요구하는데 설정으로
    가벼운 확인으로 바꾸는 인자는 **없다.** "필수 요청 정합성 확인은 일반 preset 이나
    AI 추천으로 완화할 수 없다"(autonomy-budget-policy 5절).

    `level` 이 `None`(수준 미판단)이면 독립 검토가 필요하다. 모르는 것을 저위험으로
    읽지 않는다.
    """
    reasons: list[str] = []
    if level != WorkLevel.SIMPLE.value:
        reasons.append(IndependentReason.LEVEL_ABOVE_SIMPLE)
    if evidence_gap:
        reasons.append(IndependentReason.EVIDENCE_GAP)
    if pending_material_deltas:
        reasons.append(IndependentReason.MATERIAL_DELTA_PENDING)
    if case_requires_independent:
        reasons.append(IndependentReason.CASE_POLICY)
    required = (
        ConformanceMethod.INDEPENDENT if reasons else ConformanceMethod.LIGHT
    )
    return ConformanceRequirement(required=required, reasons=tuple(reasons))


def conformance_satisfies(
    requirement: ConformanceMethod, performed: ConformanceMethod | None
) -> bool:
    """수행한 방식이 요구를 충족하는가.

    독립 검토는 가벼운 확인의 요구도 충족한다(더 많이 본 것이다). 반대는 아니다 —
    **그 비대칭이 이 함수의 전부다.**
    """
    if performed is None:
        return False
    if requirement is ConformanceMethod.LIGHT:
        return True
    return performed is ConformanceMethod.INDEPENDENT


# ========================================== 6. 누적 material delta 의 분류


@dataclass(frozen=True)
class DeltaClassification:
    materiality: Materiality
    detail: str


def classify_change(
    *,
    origin: str | None,
    target_agreed: bool,
    user_directed: bool,
) -> DeltaClassification:
    """바뀐 항목 하나를 분류한다(D-60, autonomy-budget-policy 3절).

    입력은 **구조화된 사실뿐이다.** 제어부는 본문을 읽지 않으므로 "문구만 정리"인지
    "의미가 바뀌었는지"를 스스로 판단할 수 없다. 그래서 규칙은 셋이다.

        사용자 지시에서 왔다        위임 기준을 갱신한다. 막지 않는다
        동의된 항목이 AI 출처로 바뀌었다   material. 의존 작업을 막는다
        아직 동의되지 않았다        초안 작업이다. 막지 않는다

    둘째가 과다 차단인 것은 알고 있다. 방향이 안전한 쪽이고, 사용자 지시 경로가
    정상 흐름을 연다. **AI 가 "의미가 같다"고 주장해도 여기서는 바뀌지 않는다** —
    그 주장은 `ai_assessment` 로 따로 기록되고 사람의 확인으로만 해소된다.
    """
    if user_directed:
        return DeltaClassification(
            materiality=Materiality.USER_DIRECTED,
            detail="사용자의 답변·수정 요청에서 온 변경이다. 위임 기준을 갱신한다",
        )
    if not target_agreed:
        return DeltaClassification(
            materiality=Materiality.DRAFT_WORK,
            detail="아직 동의되지 않은 항목의 변경이다. 초안 작업으로 진행한다",
        )
    if origin in (ContentOrigin.USER_REQUIREMENT.value, ContentOrigin.PROJECT_RULE.value):
        # 동의된 항목이지만 출처가 사용자 요구·프로젝트 규칙이다. 사용자 지시 기록이
        # 붙어 있지 않으면 **확인 대상으로 둔다** — 출처 표기만으로 위임을 넓히지
        # 않는다. AI 가 출처를 `user_requirement` 로 적는 것을 막을 수단이 없기 때문이다.
        return DeltaClassification(
            materiality=Materiality.MATERIAL,
            detail="동의된 항목이 바뀌었다. 사용자 지시 기록이 연결되지 않았다",
        )
    return DeltaClassification(
        materiality=Materiality.MATERIAL,
        detail="동의된 항목이 AI 출처로 바뀌었다. 마지막 유효 위임과 대조해 확인한다",
    )


def blocked_task_keys(
    pending: Iterable[dict[str, Any]],
    criterion_tasks: dict[str, list[str]],
) -> tuple[frozenset[str], bool]:
    """미확인 변경이 막는 Task 와 "전부 막는가" 를 돌려준다.

    **연결을 모르면 전부 막는다.** 어떤 변경이 어느 Task 에 닿는지 모른다는 것은
    "아무 것도 막지 않는다"가 아니라 **무엇을 막는지 모른다**는 뜻이고, 모르는 것을
    안전한 쪽으로 읽으면 연결하지 않는 것만으로 차단이 사라진다
    (`controller/work_graph.py` 의 같은 규칙).

    의도 항목·저장소 허용의 변경은 특정 Task 에 대응시킬 수 없다 — 그것들은 Case 의
    범위 자체를 바꾸므로 **전부 막는다.**
    """
    keys: set[str] = set()
    block_all = False
    for row in pending:
        target_id = row.get("target_id")
        change_class = row.get("change_class")
        if change_class != "success_criterion" or not target_id:
            block_all = True
            continue
        tasks = criterion_tasks.get(target_id)
        if not tasks:
            block_all = True
            continue
        keys.update(tasks)
    return frozenset(keys), block_all


# ============================================ 7. 무변경 충족과 미재현 (3.9절)

#: `met` 으로 저장할 수 있는 충족 방식.
#:
#: `NOT_REPRODUCED` 가 **여기 없다.** "재현 실패나 단일 테스트 통과를 기존 문제
#: 해결의 증거로 확대하지 않는다"(case-profiles 4절)를 화면이 아니라 쓰기 경로에서
#: 지킨다 — 문구로만 구별하면 API 직접 호출로 우회된다.
SATISFACTION_ALLOWING_MET: frozenset[str] = frozenset(
    {"changed_and_verified", "already_satisfied"}
)

#: 실제 검증 실행의 증거를 요구하는 충족 방식.
#:
#: 코드를 바꾸지 않고 "이미 목표 상태다"라고 말하려면 **그것을 관측한 실행**이 있어야
#: 한다. 사람 판단만으로 적으면 미재현과 구별되지 않는다.
SATISFACTION_NEEDING_RUN_EVIDENCE: frozenset[str] = frozenset({"already_satisfied"})
