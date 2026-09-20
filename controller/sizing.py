"""작업 수준 판단 — 축에서 수준을 도출하고 AI의 조용한 하향을 막는다.

**여기서 하는 일은 점수 계산이 아니다.** 축마다 영향이 따로 남고, 합산도 평균도
하지 않는다. 낮은 축들의 평균으로 권한·마이그레이션 같은 중요한 영향을 상쇄하지
않기 위해서다(sizing-and-review-ux.md 1절).

도출 규칙은 같은 문서 2절의 초기 추천 규칙을 그대로 옮긴 것이다.

    높은 영향 축이 하나라도 있으면          심층
    중간 영향 축이 있거나 근거가 부족하면    표준
    전부 낮으면                            간소

근거 부족(`INSUFFICIENT_EVIDENCE`)을 낮음으로 취급하지 않는 것이 중요하다. 모르는
것을 "영향 없음"으로 적으면 조사할 이유가 사라진다. 대신 `evidence_gap` 으로
드러내고 조사가 필요한 축을 돌려준다.

**효과 수준은 AI 제안과 도출값 중 높은 쪽이다.** AI가 진행을 위해 수준을 묵시적으로
낮추는 것은 확정된 검토 정책상 허용되지 않는다(같은 문서 3절). 낮추는 것은 사람만
할 수 있고 그때 이유와 남는 위험이 기록된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from domain.models import WORK_LEVEL_ORDER, AxisWeight, SizingAxis, WorkLevel

#: 축 판단이 하나도 없으면 수준을 도출하지 않는다. "축이 없다"와 "전부 낮다"는
#: 다르며, 뒤쪽으로 읽으면 아무 판단 없이 간소가 되어 버린다.
REQUIRED_AXES: frozenset[SizingAxis] = frozenset(SizingAxis)


@dataclass(frozen=True)
class SizingOutcome:
    """축에서 도출한 결과."""

    derived_level: WorkLevel
    effective_level: WorkLevel
    #: 근거가 부족해 판단하지 못한 축. 비어 있지 않으면 화면에 조사 필요로 드러낸다.
    evidence_gap_axes: tuple[SizingAxis, ...]
    #: AI 제안이 도출값보다 낮아 쓰지 않은 경우. 기록에 남겨 조용한 하향을 드러낸다.
    recommendation_raised: bool
    missing_axes: tuple[SizingAxis, ...]

    @property
    def evidence_gap(self) -> bool:
        return bool(self.evidence_gap_axes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "derived_level": self.derived_level.value,
            "effective_level": self.effective_level.value,
            "evidence_gap": self.evidence_gap,
            "evidence_gap_axes": [a.value for a in self.evidence_gap_axes],
            "recommendation_raised": self.recommendation_raised,
            "missing_axes": [a.value for a in self.missing_axes],
        }


def derive_level(weights: dict[SizingAxis, AxisWeight]) -> WorkLevel:
    """축별 영향에서 수준을 도출한다. **평균을 내지 않는다.**

    하나의 높은 축이 나머지 여섯 개의 낮은 축에 희석되지 않는다. 권한 한 줄 변경이
    심층 후보가 되는 것이 바로 이 규칙 때문이다(sizing-and-review-ux 3절의 예시).
    """
    values = set(weights.values())
    if AxisWeight.HIGH in values:
        return WorkLevel.DEEP
    if AxisWeight.MEDIUM in values or AxisWeight.INSUFFICIENT_EVIDENCE in values:
        return WorkLevel.STANDARD
    return WorkLevel.SIMPLE


def higher(left: WorkLevel, right: WorkLevel) -> WorkLevel:
    return left if WORK_LEVEL_ORDER[left] >= WORK_LEVEL_ORDER[right] else right


def assess(
    axes: Iterable[dict[str, Any]], recommended_level: WorkLevel
) -> SizingOutcome:
    """축 판단과 AI 제안을 합쳐 효과 수준을 정한다.

    `axes` 는 `{"axis": ..., "weight": ...}` 목록이다. 판단이 빠진 축은 `missing_axes`
    로 돌려주며 **없는 판단을 낮음으로 채우지 않는다.**
    """
    weights: dict[SizingAxis, AxisWeight] = {}
    for row in axes:
        axis = SizingAxis(row["axis"])
        weights[axis] = AxisWeight(row["weight"])

    missing = tuple(sorted(REQUIRED_AXES - set(weights), key=lambda a: a.value))
    gap = tuple(
        sorted(
            (a for a, w in weights.items() if w is AxisWeight.INSUFFICIENT_EVIDENCE),
            key=lambda a: a.value,
        )
    )
    if missing:
        # 축이 다 오지 않았으면 그 자체가 근거 부족이다. 남은 축만으로 간소를
        # 도출하지 않는다 — 보지 않은 축이 곧 확인하지 않은 영향이다.
        derived = higher(derive_level(weights), WorkLevel.STANDARD)
    else:
        derived = derive_level(weights)

    effective = higher(recommended_level, derived)
    return SizingOutcome(
        derived_level=derived,
        effective_level=effective,
        evidence_gap_axes=gap or missing,
        recommendation_raised=effective is not recommended_level,
        missing_axes=missing,
    )
