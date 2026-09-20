"""P3-01 작업 수준 판단 — AC-2·AC-3·AC-4.

여기서 확인하는 것은 셋이다.

  축별 판단이 **의도 버전에 묶여** 기록되고 점수로 합산되지 않는다
  AI가 수준을 **조용히 낮추지 못한다**
  사람은 조정할 수 있지만 **이유와 남는 위험**이 남고, 다른 조건을 해제하지 않는다

수준 판단은 의도 문서 안에 있으므로(v3) 이 시험은 초안 제출 경로를 통해 확인한다.
축별 근거를 따로 넣는 API 는 없다 — 있으면 데이터 경계가 뚫린다.
"""

from __future__ import annotations

import copy

from controller.sizing import assess, derive_level
from domain.models import AxisWeight, SizingAxis, WorkLevel
from tests.conftest import DEFAULT_SIZING

FIELDS = {
    "goal": {"text": "로그에서 오류 줄만 뽑는다", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 줄만 출력된다", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용 조회", "origin": "ai_proposal"},
    "exclusions": {"text": "회전 정책은 다루지 않는다", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬 파일만", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 미정", "origin": "ai_assumption"},
}


def _sizing(level: str, **weights: str) -> dict:
    """기본 판단에서 일부 축의 영향만 바꾼다."""
    out = copy.deepcopy(DEFAULT_SIZING)
    out["recommended_level"] = level
    for axis, weight in weights.items():
        for row in out["axes"]:
            if row["axis"] == axis:
                row["weight"] = weight
    return out


def _case_with_sizing(harness, sizing):
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS, sizing=sizing)
    return case


# --------------------------------------------------------------- 도출 규칙


def test_one_high_axis_is_not_averaged_away():
    """AC-2: **낮은 축들의 평균으로 중요한 영향을 상쇄하지 않는다.**

    권한 한 줄 변경이 심층 후보가 되는 것이 이 규칙이다
    (sizing-and-review-ux 1절, 3절의 예시).
    """
    weights = {axis: AxisWeight.LOW for axis in SizingAxis}
    weights[SizingAxis.PERMISSION_AND_SECURITY] = AxisWeight.HIGH
    assert derive_level(weights) is WorkLevel.DEEP

    # 여섯 축이 낮아도 결과가 달라지지 않는다. 여기가 평균이 아니라는 증거다.
    assert len([w for w in weights.values() if w is AxisWeight.LOW]) == 6


def test_insufficient_evidence_is_not_read_as_low():
    """AC-2: 모르는 축을 "영향 없음"으로 읽지 않는다."""
    weights = {axis: AxisWeight.LOW for axis in SizingAxis}
    weights[SizingAxis.UNCERTAINTY] = AxisWeight.INSUFFICIENT_EVIDENCE
    assert derive_level(weights) is WorkLevel.STANDARD

    outcome = assess(
        [{"axis": a.value, "weight": w.value} for a, w in weights.items()],
        WorkLevel.SIMPLE,
    )
    assert outcome.evidence_gap is True
    assert SizingAxis.UNCERTAINTY in outcome.evidence_gap_axes


def test_missing_axes_do_not_derive_the_shallowest_level():
    """AC-2: 축이 다 오지 않았으면 남은 축만으로 간소를 도출하지 않는다.

    보지 않은 축은 곧 확인하지 않은 영향이다.
    """
    outcome = assess(
        [{"axis": SizingAxis.CHANGE_SCOPE.value, "weight": AxisWeight.LOW.value}],
        WorkLevel.SIMPLE,
    )
    assert outcome.derived_level is WorkLevel.STANDARD
    assert outcome.effective_level is WorkLevel.STANDARD
    assert len(outcome.missing_axes) == 6


# ------------------------------------------------- 기록과 조용한 하향 차단


def test_the_axes_are_recorded_against_the_intent_version(harness):
    """AC-2: 축별 판단이 의도 버전에 묶여 기록된다. 일곱 축이 모두 남는다."""
    case = _case_with_sizing(harness, DEFAULT_SIZING)
    intent = harness.latest_intent(case["id"])
    prep = harness.preparation(case["id"])

    sizing = prep["sizing"]
    assert sizing is not None
    assert sizing["intent_version_id"] == intent["id"]
    assert {a["axis"] for a in sizing["axes"]} == {a.value for a in SizingAxis}
    # 판단 한 줄이 축마다 있다. 영향만 있는 축은 만들지 않는다.
    assert all(a["judgement_summary"] for a in sizing["axes"])
    # 사람이 쓴 초안이므로 AI 제안으로 적지 않는다(FR-04).
    assert sizing["source"] == "human_assessment"


def test_a_low_recommendation_does_not_lower_the_level(harness):
    """AC-3: **도출값보다 낮은 제안은 쓰이지 않는다.** 두 값이 모두 남는다.

    sizing-and-review-ux 3절: "AI가 진행을 위해 사용자 검토 옵션을 끄거나 수행 수준을
    묵시적으로 낮추는 것은 확정된 검토 정책상 허용하지 않는다."
    """
    case = _case_with_sizing(
        harness, _sizing("simple", permission_and_security="high")
    )
    sizing = harness.preparation(case["id"])["sizing"]

    assert sizing["recommended_level"] == "simple"
    assert sizing["derived_level"] == "deep"
    # 적용되는 것은 도출값이다.
    assert sizing["level"] == "deep"


def test_a_higher_recommendation_is_kept(harness):
    """AC-3: 제안이 도출값보다 높으면 제안을 쓴다. 상향은 막지 않는다."""
    case = _case_with_sizing(harness, _sizing("deep"))
    sizing = harness.preparation(case["id"])["sizing"]

    assert sizing["derived_level"] == "simple"
    assert sizing["level"] == "deep"


def test_a_new_intent_version_supersedes_the_assessment(harness):
    """AC-2: 의도가 바뀌면 그 위에서 쓴 판단도 대체된다.

    축별 근거는 그 의도 버전을 보고 쓴 것이다. 승계하면 바뀐 의도에 옛 근거가 붙는다.
    """
    case = _case_with_sizing(harness, DEFAULT_SIZING)
    first = harness.preparation(case["id"])["sizing"]

    harness.submit_intent_draft(case["id"], FIELDS, sizing=_sizing("standard"))
    second = harness.preparation(case["id"])["sizing"]

    assert second["id"] != first["id"]
    assert second["level"] == "standard"
    history = harness.preparation(case["id"])["sizing_history"]
    # 이전 판단은 지워지지 않고 대체됨으로 남는다.
    superseded = [h for h in history if h["id"] == first["id"]]
    assert superseded and superseded[0]["state"] == "superseded"


def test_a_draft_without_sizing_leaves_the_level_undecided(harness):
    """AC-2: 판단이 없으면 **미결정**이다. 가장 얕은 수준으로 읽지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS, with_sizing=False)

    prep = harness.preparation(case["id"])
    assert prep["sizing"] is None
    assert prep["level"] is None


# ------------------------------------------------------------- 사람의 조정


def test_an_adjustment_needs_a_reason_and_the_remaining_risk(harness):
    """AC-4: 이유·남는 위험 없는 조정은 거부한다."""
    case = _case_with_sizing(harness, DEFAULT_SIZING)

    assert harness.adjust_level(case["id"], "deep", reason="").status_code == 422
    assert (
        harness.adjust_level(case["id"], "deep", residual_risk="").status_code == 422
    )
    assert harness.adjust_level(case["id"], "deep").status_code == 201


def test_a_person_may_lower_below_the_derived_level(harness):
    """AC-4: 사람은 도출값 아래로도 내릴 수 있다. 그것이 조정권이다.

    대신 이전 수준·이유·남는 위험이 함께 남는다.
    """
    case = _case_with_sizing(harness, _sizing("deep", uncertainty="high"))
    assert harness.preparation(case["id"])["sizing"]["level"] == "deep"

    response = harness.adjust_level(
        case["id"],
        "standard",
        reason="불확실성은 조사로 해소됐다",
        residual_risk="복구 경로는 아직 확인하지 않았다",
    )
    assert response.status_code == 201
    sizing = harness.preparation(case["id"])["sizing"]
    assert sizing["level"] == "standard"
    assert sizing["adjusted_from"] == "deep"
    assert sizing["source"] == "human_adjustment"
    assert sizing["reason_summary"] == "불확실성은 조사로 해소됐다"
    assert sizing["residual_risk_summary"] == "복구 경로는 아직 확인하지 않았다"
    # 도출값은 그대로 남는다. 조정으로 근거를 지우지 않는다.
    assert sizing["derived_level"] == "deep"


def test_adjusting_the_level_does_not_release_other_conditions(harness):
    """AC-4: **상세도 조정이 의도 동의·검토 모드·성공 기준을 해제하지 않는다.**

    sizing-and-review-ux 1절의 요구를 그대로 확인한다. 낮춘 뒤에도 세 가지가
    그대로여야 한다.
    """
    case = _case_with_sizing(harness, _sizing("deep"))
    intent = harness.latest_intent(case["id"])
    harness.read_intent_original(intent)
    assert harness.agree(case["id"], intent).status_code == 201

    before_criteria = harness.criteria(case["id"])
    before_state = harness.intent_state(case["id"])["agreement_state"]
    before_design_mode = harness.preparation(case["id"])["design"]["mode"]

    assert harness.adjust_level(case["id"], "simple").status_code == 201

    assert harness.intent_state(case["id"])["agreement_state"] == before_state
    assert harness.criteria(case["id"]) == before_criteria
    assert harness.preparation(case["id"])["design"]["mode"] == before_design_mode
    # 새 의도 버전을 만들지 않는다. 수준은 의도의 내용이 아니다.
    assert harness.latest_intent(case["id"])["id"] == intent["id"]


def test_an_adjustment_without_a_prior_assessment_is_refused(harness):
    """AC-4: 축별 근거 없이 수준만 정하는 경로를 만들지 않는다."""
    project = harness.create_project()
    case = harness.create_case(project["id"])
    harness.submit_intent_draft(case["id"], FIELDS, with_sizing=False)

    response = harness.adjust_level(case["id"], "deep")
    assert response.status_code == 409
    assert "no sizing assessment" in response.text
