"""여섯 Case Profile 의 정의 — 목적별 의도 항목·증거 기대·완료 의미.

**Profile 은 고정 pipeline 이 아니라 의미 계약이다**(D-62, case-profiles.md 1절).
여기 있는 것은 "이 목적의 업무를 말할 때 무엇이 빠지면 말이 안 되는가"이며 "모든
Case 가 작성해야 하는 문서 세트"가 아니다.

두 가지를 구별한다.

    의미 항목   의도 초안이 구별해 표현해야 하는 정보. 시스템이 **존재를 강제한다**
    증거 기대   그 목적의 결과를 무엇으로 보이는가. 내용 판단은 사람·AI 검토의 몫

시스템이 강제하는 것은 항목이 **행으로 존재하고 상태·출처가 구별되는가**까지다
(`ConfirmationState`·`ContentOrigin`). 내용이 충분한지는 QG-01 의 AI 의미 검토와
사람의 판단이 본다 — 제어부는 본문을 읽지 않기 때문이다(data-boundary-review 1절).

**공개한 버전은 고치지 않는다.** 정의를 바꿔야 하면 새 버전을 더한다. Case 는 자기
`profile_version` 을 기록하고 이 표를 그 버전으로 조회하므로, 새 정의가 기존 Case 에
조용히 소급되지 않는다(D-62 "새로운 Profile 정의를 기존 Case 에 조용히 소급 적용하지
않는다"). `tests/test_policy.py` 가 기록된 모든 버전이 조회되는지 확인한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from domain.models import CaseKind, CaseProfile, IntentField

#: 지금 새 Case 에 붙는 정의판. 문자열인 이유는 조회 키이고 비교하지 않기 때문이다.
CURRENT_PROFILE_VERSION = "1"


class ProfileField(str, Enum):
    """Profile 별 의미 항목의 이름.

    공통 여섯 항목(`IntentField`)과 **같은 표에 들어간다**(`intent_field`). 별도 표를
    만들면 한 초안의 항목이 두 곳에 나뉘어 "사실·제안·미정"의 구별 방식이 항목 종류마다
    달라진다. 이름이 겹치지 않게 목적별 접두사를 쓰지 않는 대신 값을 전부 다르게 둔다.
    """

    # feature
    NEED = "need"
    USAGE_CONTEXT = "usage_context"
    DESIRED_BEHAVIOR = "desired_behavior"
    ACCEPTANCE_CASES = "acceptance_cases"
    # defect-fix
    OBSERVED_BEHAVIOR = "observed_behavior"
    EXPECTED_BEHAVIOR = "expected_behavior"
    EXPECTATION_BASIS = "expectation_basis"
    OCCURRENCE_CONDITIONS = "occurrence_conditions"
    RESTORE_SCOPE = "restore_scope"
    # root-cause-analysis
    PHENOMENON = "phenomenon"
    OBSERVATIONS = "observations"
    CAUSE_QUESTIONS = "cause_questions"
    CONCLUSION_REQUIREMENT = "conclusion_requirement"
    ANALYSIS_END_CONDITION = "analysis_end_condition"
    # research
    RESEARCH_QUESTIONS = "research_questions"
    DECISION_PURPOSE = "decision_purpose"
    EVALUATION_CRITERIA = "evaluation_criteria"
    REQUIRED_EVIDENCE = "required_evidence"
    RESEARCH_END_CONDITION = "research_end_condition"
    # refactoring
    IMPROVEMENT_TARGET = "improvement_target"
    IMPROVEMENT_REASON = "improvement_reason"
    TARGET_BOUNDARY = "target_boundary"
    PRESERVED_CONTRACTS = "preserved_contracts"
    IMPROVEMENT_CRITERIA = "improvement_criteria"
    # maintenance
    MAINTENANCE_TARGET = "maintenance_target"
    CURRENT_STATE = "current_state"
    TARGET_STATE = "target_state"
    WORK_REASON = "work_reason"
    PRESERVED_CONDITIONS = "preserved_conditions"


#: 사람이 읽는 항목 이름. 화면·지시문이 같은 문구를 쓰게 하려고 한 곳에 둔다.
FIELD_LABEL: dict[str, str] = {
    ProfileField.NEED.value: "해결할 필요·문제",
    ProfileField.USAGE_CONTEXT.value: "대상 사용자 또는 사용 상황",
    ProfileField.DESIRED_BEHAVIOR.value: "원하는 동작·결과",
    ProfileField.ACCEPTANCE_CASES.value: "주요 수용 사례",
    ProfileField.OBSERVED_BEHAVIOR.value: "관찰된 동작",
    ProfileField.EXPECTED_BEHAVIOR.value: "기대 동작",
    ProfileField.EXPECTATION_BASIS.value: "기대 동작의 근거",
    ProfileField.OCCURRENCE_CONDITIONS.value: "발생 조건·영향",
    ProfileField.RESTORE_SCOPE.value: "복원할 범위",
    ProfileField.PHENOMENON.value: "설명할 현상",
    ProfileField.OBSERVATIONS.value: "관찰 근거",
    ProfileField.CAUSE_QUESTIONS.value: "답할 원인 질문",
    ProfileField.CONCLUSION_REQUIREMENT.value: "결론의 요구 범위·증거 수준",
    ProfileField.ANALYSIS_END_CONDITION.value: "분석 종료조건",
    ProfileField.RESEARCH_QUESTIONS.value: "조사 질문",
    ProfileField.DECISION_PURPOSE.value: "판단 목적",
    ProfileField.EVALUATION_CRITERIA.value: "비교·평가 기준",
    ProfileField.REQUIRED_EVIDENCE.value: "필요한 근거",
    ProfileField.RESEARCH_END_CONDITION.value: "조사 종료조건",
    ProfileField.IMPROVEMENT_TARGET.value: "개선할 구조·품질",
    ProfileField.IMPROVEMENT_REASON.value: "개선하는 이유",
    ProfileField.TARGET_BOUNDARY.value: "대상 경계",
    ProfileField.PRESERVED_CONTRACTS.value: "보존할 외부 동작·인터페이스·데이터 계약",
    ProfileField.IMPROVEMENT_CRITERIA.value: "개선 판단 기준",
    ProfileField.MAINTENANCE_TARGET.value: "유지 대상",
    ProfileField.CURRENT_STATE.value: "현재 상태",
    ProfileField.TARGET_STATE.value: "목표 상태",
    ProfileField.WORK_REASON.value: "작업 이유",
    ProfileField.PRESERVED_CONDITIONS.value: "보존할 호환성·운영 조건",
}

FIELD_LABEL.update(
    {
        IntentField.GOAL.value: "목표",
        IntentField.EXPECTED_OUTCOME.value: "기대 결과",
        IntentField.SCOPE.value: "적용 범위",
        IntentField.EXCLUSIONS.value: "제외 범위",
        IntentField.CONSTRAINTS.value: "제약",
        IntentField.OPEN_QUESTIONS.value: "미정 사항",
    }
)


@dataclass(frozen=True)
class ProfileDefinition:
    """한 Profile 의 한 버전.

    `semantic_fields` 는 **순서가 있는** 항목 목록이다. 화면·지시문·문서가 같은 순서로
    보여야 사람이 버전 사이 차이를 눈으로 볼 수 있다.
    """

    profile: CaseProfile
    version: str
    purpose: str
    semantic_fields: tuple[ProfileField, ...]
    #: 최소 증거 기대(case-profiles.md 4절). **검사 도구 목록이 아니다.**
    minimum_evidence: str
    #: 조건부 추가 증거. 실제 성공 기준·영향 범위로 고른다
    conditional_evidence: str
    #: 정상 완료가 무엇을 뜻하는가. 예산 소진·미재현은 여기에 해당하지 않는다
    completion_meaning: str
    #: 초안에서 고정하지 않는 실행 상세. 사람에게 빈칸을 채우게 하지 않기 위한 경계
    not_fixed_in_draft: str

    @property
    def required_fields(self) -> tuple[str, ...]:
        """구조 보고에 반드시 있어야 하는 항목 이름 — 공통 여섯 + 의미 항목."""
        common = tuple(f.value for f in IntentField)
        return common + tuple(f.value for f in self.semantic_fields)

    def to_dict(self) -> dict[str, object]:
        return {
            "profile": self.profile.value,
            "version": self.version,
            "purpose": self.purpose,
            "common_fields": [f.value for f in IntentField],
            "semantic_fields": [
                {"field": f.value, "label": FIELD_LABEL[f.value]} for f in self.semantic_fields
            ],
            "required_fields": list(self.required_fields),
            "minimum_evidence": self.minimum_evidence,
            "conditional_evidence": self.conditional_evidence,
            "completion_meaning": self.completion_meaning,
            "not_fixed_in_draft": self.not_fixed_in_draft,
        }


_V1: tuple[ProfileDefinition, ...] = (
    ProfileDefinition(
        profile=CaseProfile.FEATURE,
        version="1",
        purpose="새 기능·동작을 만든다",
        semantic_fields=(
            ProfileField.NEED,
            ProfileField.USAGE_CONTEXT,
            ProfileField.DESIRED_BEHAVIOR,
            ProfileField.ACCEPTANCE_CASES,
        ),
        minimum_evidence="합의한 사용자 동작·결과와 실제 확인의 연결",
        conditional_evidence="영향받는 회귀·권한·성능·다중 Repo 통합",
        completion_meaning="합의한 기능·수용 기준을 충족한다",
        not_fixed_in_draft="구현 구조·세부 알고리즘. UI 가 없는 기능에 화면 설계를 요구하지 않는다",
    ),
    ProfileDefinition(
        profile=CaseProfile.DEFECT_FIX,
        version="1",
        purpose="기대 동작을 복원한다",
        semantic_fields=(
            ProfileField.OBSERVED_BEHAVIOR,
            ProfileField.EXPECTED_BEHAVIOR,
            ProfileField.EXPECTATION_BASIS,
            ProfileField.OCCURRENCE_CONDITIONS,
            ProfileField.RESTORE_SCOPE,
        ),
        minimum_evidence="증상·정상 동작의 근거와 수정 후 비교",
        conditional_evidence="관련 회귀·반례. 재현이 어려우면 대체 검증 근거와 한계",
        completion_meaning="기존 기대 동작 복원과 필요한 검증을 충족한다."
        " 미재현만으로 해결을 선언하지 않는다",
        not_fixed_in_draft="아직 확인하지 않은 원인을 확정하거나 수정 방법을 먼저 고정하지 않는다",
    ),
    ProfileDefinition(
        profile=CaseProfile.ROOT_CAUSE_ANALYSIS,
        version="1",
        purpose="현상의 원인을 설명한다",
        semantic_fields=(
            ProfileField.PHENOMENON,
            ProfileField.OBSERVATIONS,
            ProfileField.CAUSE_QUESTIONS,
            ProfileField.CONCLUSION_REQUIREMENT,
            ProfileField.ANALYSIS_END_CONDITION,
        ),
        minimum_evidence="관찰·가설·결론의 구분과 지지·기각 근거, 남은 대안",
        conditional_evidence="인과 주장에 필요한 재현·대조·개입 증거",
        completion_meaning="요청한 원인 분석의 종료조건을 충족한다."
        " 원인 확정이 필수면 미확정은 성공이 아니다",
        not_fixed_in_draft="작업 가설·계측·실험 방법은 별도 조사 산출물로 발전시킨다",
    ),
    ProfileDefinition(
        profile=CaseProfile.RESEARCH,
        version="1",
        purpose="판단에 필요한 사실을 조사한다",
        semantic_fields=(
            ProfileField.RESEARCH_QUESTIONS,
            ProfileField.DECISION_PURPOSE,
            ProfileField.EVALUATION_CRITERIA,
            ProfileField.REQUIRED_EVIDENCE,
            ProfileField.RESEARCH_END_CONDITION,
        ),
        minimum_evidence="질문별 출처·비교·관찰과 결론·한계",
        conditional_evidence="성능·실현가능성 주장에 필요한 실험 조건·결과",
        completion_meaning="합의한 조사·판단 조건을 충족한다."
        " 그 조건이 허용하면 판단 불가도 정상 결과다",
        not_fixed_in_draft="후보가 미정인 탐색을 허용한다. 전체 후보·세부 실험을 시작 전에 확정하지 않는다",
    ),
    ProfileDefinition(
        profile=CaseProfile.REFACTORING,
        version="1",
        purpose="외부 동작을 보존하면서 구조를 개선한다",
        semantic_fields=(
            ProfileField.IMPROVEMENT_TARGET,
            ProfileField.IMPROVEMENT_REASON,
            ProfileField.TARGET_BOUNDARY,
            ProfileField.PRESERVED_CONTRACTS,
            ProfileField.IMPROVEMENT_CRITERIA,
        ),
        minimum_evidence="구조 개선 목표와 보존 조건 각각에 대한 근거",
        conditional_evidence="영향받는 인터페이스·데이터·성능·통합 증거",
        completion_meaning="개선과 보존 조건을 함께 충족한다."
        " 테스트 통과만으로 모든 보존을 증명하지 않는다",
        not_fixed_in_draft="구체적인 해결 구조는 필요한 설계에서 결정한다",
    ),
    ProfileDefinition(
        profile=CaseProfile.MAINTENANCE,
        version="1",
        purpose="특정 대상을 목표 상태로 유지한다",
        semantic_fields=(
            ProfileField.MAINTENANCE_TARGET,
            ProfileField.CURRENT_STATE,
            ProfileField.TARGET_STATE,
            ProfileField.WORK_REASON,
            ProfileField.PRESERVED_CONDITIONS,
        ),
        minimum_evidence="유지 대상의 목표 상태와 필요한 확인",
        conditional_evidence="대상에 따른 링크·예제, 의존성 해결·빌드·실행, 호환성 검증",
        completion_meaning="특정한 유지 목표와 보존 조건을 충족한다",
        not_fixed_in_draft="의존성·문서·빌드 설정 등 대상과 무관한 항목을 일괄 요구하지 않는다",
    ),
)

#: `(profile, version) → 정의`. 새 버전은 더하고 기존 항목은 고치지 않는다.
DEFINITIONS: dict[tuple[str, str], ProfileDefinition] = {
    (d.profile.value, d.version): d for d in _V1
}

#: Profile 에서 유도하는 기존 `kind` 축의 값. 새 Case 의 `case.kind` 를 정한다.
#:
#: **유도이지 동일시가 아니다.** 반대 방향(`kind → profile`)은
#: `PROFILE_FOR_KIND` 이며 그 결과는 출처가 `derived_from_kind` 로 남는다.
KIND_FOR_PROFILE: dict[CaseProfile, CaseKind] = {
    CaseProfile.FEATURE: CaseKind.FEATURE,
    CaseProfile.DEFECT_FIX: CaseKind.BUG,
    CaseProfile.ROOT_CAUSE_ANALYSIS: CaseKind.ANALYSIS,
    CaseProfile.RESEARCH: CaseKind.RESEARCH,
    CaseProfile.REFACTORING: CaseKind.REFACTORING,
    CaseProfile.MAINTENANCE: CaseKind.MAINTENANCE,
}

#: 기존 `kind` 축에서 Profile 을 유도한다. **요청에 Profile 이 없을 때만** 쓴다.
#:
#: `analysis → root_cause_analysis` 는 v0.6의 `analysis` 가 원인 분석을 뜻했기
#: 때문이다. 유도된 값은 사람의 선택이 아니므로 출처를 구별해 기록한다(FR-04).
PROFILE_FOR_KIND: dict[CaseKind, CaseProfile] = {
    CaseKind.FEATURE: CaseProfile.FEATURE,
    CaseKind.BUG: CaseProfile.DEFECT_FIX,
    CaseKind.ANALYSIS: CaseProfile.ROOT_CAUSE_ANALYSIS,
    CaseKind.RESEARCH: CaseProfile.RESEARCH,
    CaseKind.REFACTORING: CaseProfile.REFACTORING,
    CaseKind.MAINTENANCE: CaseProfile.MAINTENANCE,
}


def resolve(profile: str, version: str) -> ProfileDefinition:
    """기록된 `(profile, version)` 의 정의를 돌려준다.

    **없는 버전을 현재 버전으로 대체하지 않는다.** 대체하면 기존 Case 가 새 정의로
    판정되고, 그것이 D-62 가 금지하는 조용한 소급 적용이다.
    """
    key = (CaseProfile(profile).value, str(version))
    definition = DEFINITIONS.get(key)
    if definition is None:
        raise KeyError(f"unknown profile definition: {key}")
    return definition


def current(profile: CaseProfile | str) -> ProfileDefinition:
    """새 Case 에 붙는 현재 정의."""
    return resolve(CaseProfile(profile).value, CURRENT_PROFILE_VERSION)


def required_fields(profile: str | None, version: str | None) -> frozenset[str]:
    """그 Case 의 구조 보고가 가져야 하는 항목 이름.

    **Profile 이 기록되지 않은 Case 는 공통 여섯 항목이다.** R1 이전에 만들어진
    Case 에 지금의 의미 항목을 요구하면, 그 Case 의 기존 의도 버전이 갑자기 불완전한
    문서가 된다 — 새 규칙의 소급 적용이다(DEVELOPMENT.md 3절).
    """
    if profile is None or version is None:
        return frozenset(f.value for f in IntentField)
    return frozenset(resolve(profile, version).required_fields)


def field_order(profile: str | None, version: str | None) -> tuple[str, ...]:
    """표시·검사 순서. 공통 여섯 항목이 먼저 오고 의미 항목이 뒤에 온다."""
    common = tuple(f.value for f in IntentField)
    if profile is None or version is None:
        return common
    return resolve(profile, version).required_fields


def catalog() -> list[dict[str, object]]:
    """현재 버전의 여섯 정의. 화면·API 가 같은 내용을 보게 한다."""
    return [current(p).to_dict() for p in CaseProfile]
