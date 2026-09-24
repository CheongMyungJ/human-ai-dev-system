"""여섯 Profile 의 완료 의미 — 결과 기록 규칙·목적 커버리지·실험 정리(P4-03).

**여기에는 DB 도 HTTP 도 없다.** `domain/progression.py`·`domain/quality.py` 와 같은
자리이며 같은 이유로 그렇게 둔다 — 결과 기록·완료 후보·화면·시험이 **같은 함수를
봐야** 한다.

이 파일이 답하는 질문은 셋이다.

    1. 이 기준 결과를 받아도 되는가       충족 방식·결론·근거 실행이 그 기준의 목적
                                         의무에 맞는가
    2. 이 Case 의 목적을 전부 다뤘는가     요구된 목적 의무마다 기준이 있는가
    3. 실험이 임시 변경을 남겼는가         실행 전후 관측으로 도출한다

**v1 Case 는 여기의 새 규칙을 받지 않는다.** 계약(`CompletionContract`)이 없으면
1·2 는 아무 것도 거부하지 않는다 — 기존 Case 에 새 완료 규칙을 소급하지 않는다(D-62).

제어부는 본문을 읽지 않는다. 여기서 보는 것은 의무·방식·결론·실행 목적·트리 지문
같은 **구조화된 값뿐**이다. "원인을 정말 찾았는가"는 사람·AI 검토의 몫이며, 이
파일은 "판단 불가를 확정으로 적었는가"처럼 값끼리 모순되는 것만 막는다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from domain.models import (
    Conclusion,
    ConclusionRule,
    CriterionObligation,
    CriterionVerdict,
    EvidenceKind,
    ExperimentCleanup,
    ObligationSource,
    Permission,
    RunPurpose,
    RunStatus,
    Satisfaction,
)
from domain import profiles
from domain.profiles import CompletionContract

_O = CriterionObligation
_S = Satisfaction

# =============================================== 1. 의무별 허용 충족 방식

#: `met` 으로 적을 수 있는 충족 방식 — **의무마다 다르다.**
#:
#: `NOT_REPRODUCED` 는 어느 의무에도 없다. `INVESTIGATED` 는 결론을 내는 의무에만,
#: `PRESERVED` 는 보존에만 있다. 개선·목표 상태에 `ALREADY_SATISFIED` 가 있는 이유는
#: "실제 변경 없이 이미 목표 상태임을 증거로 확인한 경우도 정상 완료할 수 있다"
#: (case-profiles 4절)가 목적을 가리지 않기 때문이다.
MET_SATISFACTION: dict[CriterionObligation, frozenset[Satisfaction]] = {
    _O.BEHAVIOR: frozenset({_S.CHANGED_AND_VERIFIED, _S.ALREADY_SATISFIED}),
    _O.RESTORATION: frozenset({_S.CHANGED_AND_VERIFIED, _S.ALREADY_SATISFIED}),
    _O.CAUSE: frozenset({_S.INVESTIGATED}),
    _O.ANSWER: frozenset({_S.INVESTIGATED}),
    _O.IMPROVEMENT: frozenset({_S.CHANGED_AND_VERIFIED, _S.ALREADY_SATISFIED}),
    _O.PRESERVATION: frozenset({_S.PRESERVED}),
    _O.TARGET_STATE: frozenset({_S.CHANGED_AND_VERIFIED, _S.ALREADY_SATISFIED}),
}

#: 결론(확정/판단 불가)을 내는 의무.
CONCLUSION_OBLIGATIONS: frozenset[CriterionObligation] = frozenset({_O.CAUSE, _O.ANSWER})

#: **제품 상태**에 대한 의무. 실험의 임시 변경이 섞이면 안 되는 쪽이다.
PRODUCT_OBLIGATIONS: frozenset[CriterionObligation] = frozenset(
    set(CriterionObligation) - CONCLUSION_OBLIGATIONS
)

#: v1 기준(의무 없음)이 받을 수 있는 충족 방식 — P3-R4 의 세 값 그대로다.
LEGACY_SATISFACTION: frozenset[Satisfaction] = frozenset(
    {_S.CHANGED_AND_VERIFIED, _S.ALREADY_SATISFIED, _S.NOT_REPRODUCED}
)

#: 조사 결론(`investigated`)의 근거가 될 수 있는 실행 목적.
#:
#: 의도 초안·설계·계획을 **쓴** 실행은 조사 근거가 아니다 — 그 실행의 산출물은
#: 결론이 아니라 계획이다. 검토 실행도 아니다 — 검토는 남의 결과를 본다.
INVESTIGATION_EVIDENCE_PURPOSES: frozenset[RunPurpose] = frozenset(
    {RunPurpose.LIMITED_ANALYSIS, RunPurpose.LOCAL_EXPERIMENT, RunPurpose.VERIFICATION_RUN}
)

#: 관측으로 확인해야 하는 충족 방식 → 그 관측을 하는 실행 목적.
#:
#: "이미 목표 상태다"와 "보존됐다"는 **바꾸지 않은 것을 확인하는** 주장이다. 그
#: 근거가 구현 실행이면 "바꿨다"는 기록 위의 관측이 되고, 실험이면 임시 변경 위의
#: 관측이 된다. 둘 다 제품 상태의 관측이 아니다.
OBSERVATION_EVIDENCE_PURPOSES: dict[Satisfaction, frozenset[RunPurpose]] = {
    _S.ALREADY_SATISFIED: frozenset({RunPurpose.VERIFICATION_RUN}),
    _S.PRESERVED: frozenset({RunPurpose.VERIFICATION_RUN}),
}


def derive_obligation(
    contract: CompletionContract | None,
    relates_to: str | None,
    reported: str | None,
    version: str | None = None,
) -> tuple[CriterionObligation | None, ObligationSource | None]:
    """기준 하나의 목적 의무와 그 출처.

    계약이 없으면(v1) **정하지 않는다** — 보고값이 있어도 받지 않는다. v1 Case 에
    의무를 붙이면 그 기준에 새 규칙이 적용된다.

    보고값이 있으면 그것이다(모르는 이름은 `ValueError`). 없으면 연결 항목에 정의의
    대응표를 적용한다. 그것은 본문 해석이 아니라 공개된 정의의 적용이며, 출처를
    `derived_from_field` 로 구별해 남긴다.

    **유지 항목의 기준은 그 항목을 가진 Profile 의 의무다**(UI-04c, D-86). 개정으로
    계약이 바뀌어도 `cause_questions` 에 걸린 기준은 RCA 계약의 `cause` 로 도출된다 —
    현재 계약의 주 의무로 도출하면 원인 기준이 조용히 수정 기준이 되고, 지문이 바뀌어
    판정도 잇지 못한다. `version` 이 없으면(옛 호출자) 현재 계약만 본다. 공통 항목·자기
    Profile 의 항목은 그대로 현재 계약이다.
    """
    if contract is None:
        return None, None
    if reported:
        return CriterionObligation(reported), ObligationSource.REPORTED
    owner = profiles.field_owner(relates_to)
    if owner is not None and version is not None:
        owner_contract = profiles.completion_contract(owner.value, version)
        if owner_contract is not None and owner_contract != contract:
            return (
                owner_contract.obligation_for_field(relates_to),
                ObligationSource.DERIVED_FROM_FIELD,
            )
    return contract.obligation_for_field(relates_to), ObligationSource.DERIVED_FROM_FIELD


def effective_conclusion_rule(rule: str | None) -> ConclusionRule:
    """기록된 결론 요구를 **적용할** 값으로 바꾼다.

    `None` 은 확정 필수다. 판단 불가 허용은 명시로만 생긴다 — 모르는 것을 느슨한
    쪽으로 읽으면 원인을 확정하지 못한 분석이 조용히 완료된다(case-profiles 4절).
    """
    if rule is None:
        return ConclusionRule.DEFINITIVE_REQUIRED
    return ConclusionRule(rule)


# ================================================ 2. 결과 기록 규칙


@dataclass(frozen=True)
class ResultViolation:
    code: str
    detail: str

    def __str__(self) -> str:
        return f"{self.code}: {self.detail}"


def check_result(
    *,
    contract_applies: bool,
    obligation: str | None,
    conclusion_rule: str | None,
    verdict: CriterionVerdict,
    satisfaction: Satisfaction | None,
    conclusion: Conclusion | None,
    evidence_kind: EvidenceKind,
    evidence_run: dict[str, Any] | None,
) -> list[ResultViolation]:
    """이 결과를 기준에 기록해도 되는가 — **P4-03 이 더한 규칙만** 본다.

    근거 없는 판정·불명 실행의 `met`·미재현 `met` 같은 기존 규칙은
    `Repository.record_criterion_result` 에 그대로 있고, 이 함수는 그 뒤에 불린다.

    **계약이 없는 기준은 v1 규칙이다.** 새 방식(`investigated`·`preserved`)과 결론은
    받지 않는다 — 그 값들은 의무가 있어야 뜻이 있다. 그 외에는 아무 것도 더
    거부하지 않는다.
    """
    violations: list[ResultViolation] = []

    if not contract_applies or obligation is None:
        if satisfaction is not None and satisfaction not in LEGACY_SATISFACTION:
            violations.append(
                ResultViolation(
                    "satisfaction_needs_obligation",
                    f"satisfaction='{satisfaction.value}' 는 목적 의무가 있는 기준(Profile"
                    " 정의 v2)에만 쓴다. 이 기준은 v1 규칙을 따른다",
                )
            )
        if conclusion is not None:
            violations.append(
                ResultViolation(
                    "conclusion_not_applicable",
                    "결론은 원인·조사 의무의 기준에만 붙는다. 이 기준에는 의무가 없다",
                )
            )
        return violations

    ob = CriterionObligation(obligation)

    if conclusion is not None and ob not in CONCLUSION_OBLIGATIONS:
        violations.append(
            ResultViolation(
                "conclusion_not_applicable",
                f"결론은 원인·조사 의무의 기준에만 붙는다. 이 기준의 의무는 {ob.value} 다",
            )
        )

    if verdict is not CriterionVerdict.MET:
        # 보존을 확인했다면서 미충족이라고 적지 않는다. 기록이 판정과 어긋나면
        # 나중에 어느 쪽이 사실인지 물을 수 없다(`changed_and_verified` 와 같은 규칙).
        if satisfaction is Satisfaction.PRESERVED:
            violations.append(
                ResultViolation(
                    "satisfaction_does_not_fit_verdict",
                    "satisfaction='preserved' 는 met 이 아닌 판정과 맞지 않는다",
                )
            )
        if satisfaction is not None and satisfaction not in (
            MET_SATISFACTION[ob] | {Satisfaction.NOT_REPRODUCED}
        ):
            violations.append(
                ResultViolation(
                    "satisfaction_not_allowed_for_obligation",
                    f"{ob.value} 의무에는 satisfaction='{satisfaction.value}' 를 쓰지 않는다",
                )
            )
        return violations

    # --- 여기부터 `met` -----------------------------------------------------
    if satisfaction is None:
        # **생략 우회를 막는 자리다.** P3-R4 는 `not_reproduced` 로 적은 `met` 만
        # 거부했고 아무것도 적지 않은 `met` 은 받았다 — 미재현을 해결로 만드는 데
        # 필요한 것은 방식을 비워 두는 것 하나였다.
        violations.append(
            ResultViolation(
                "satisfaction_required",
                f"{ob.value} 의무의 기준을 met 으로 적으려면 어떻게 충족했는가"
                f"({', '.join(sorted(s.value for s in MET_SATISFACTION[ob]))})를 함께 적는다",
            )
        )
    elif satisfaction not in MET_SATISFACTION[ob]:
        violations.append(
            ResultViolation(
                "satisfaction_not_allowed_for_obligation",
                f"{ob.value} 의무는 satisfaction='{satisfaction.value}' 로 충족되지 않는다."
                f" 허용: {', '.join(sorted(s.value for s in MET_SATISFACTION[ob]))}",
            )
        )

    if ob in CONCLUSION_OBLIGATIONS:
        if conclusion is None:
            violations.append(
                ResultViolation(
                    "conclusion_required",
                    "원인·조사 의무를 met 으로 적으려면 결론이 확정인지 판단 불가인지 적는다",
                )
            )
        elif (
            conclusion is Conclusion.INCONCLUSIVE
            and effective_conclusion_rule(conclusion_rule)
            is ConclusionRule.DEFINITIVE_REQUIRED
        ):
            violations.append(
                ResultViolation(
                    "inconclusive_not_allowed",
                    "이 기준은 확정 결론을 요구한다(결론 요구가 기록되지 않았으면 확정 필수로"
                    " 취급한다). 판단 불가는 not_met 이며, 닫으려면 사람의 예외 수용이다",
                )
            )

    if evidence_kind is EvidenceKind.RUN_OUTPUT and evidence_run is not None:
        purpose = _purpose(evidence_run)
        is_experiment = bool(evidence_run.get("is_experiment"))
        if is_experiment and satisfaction is not Satisfaction.INVESTIGATED:
            # **증거와 임시 변경을 구분한다**(D-66). 실험의 작업공간은 관측을 위해
            # 고친 상태이며 제품 상태가 아니다.
            violations.append(
                ResultViolation(
                    "experiment_evidence_not_product",
                    "로컬 실험의 실행은 조사 결론의 근거로만 쓴다. 제품 의무"
                    f"({ob.value})의 근거가 되지 않는다",
                )
            )
        if satisfaction is Satisfaction.INVESTIGATED and (
            purpose not in INVESTIGATION_EVIDENCE_PURPOSES
        ):
            violations.append(
                ResultViolation(
                    "evidence_run_not_investigation",
                    "조사 결론의 근거는 분석·실험·검증 실행이다. 이 실행의 목적은"
                    f" {purpose.value if purpose else '미기록'} 이다",
                )
            )
        needed = OBSERVATION_EVIDENCE_PURPOSES.get(satisfaction) if satisfaction else None
        if needed is not None and purpose not in needed and not is_experiment:
            violations.append(
                ResultViolation(
                    "observation_needs_verification_run",
                    f"satisfaction='{satisfaction.value}' 는 검증 실행이 관측해야 한다."
                    f" 이 실행의 목적은 {purpose.value if purpose else '미기록'} 이다",
                )
            )
    return violations


def _purpose(run: dict[str, Any]) -> RunPurpose | None:
    raw = run.get("purpose")
    if not raw:
        return None
    try:
        return RunPurpose(raw)
    except ValueError:
        return None


# ================================================ 3. 목적 커버리지


@dataclass(frozen=True)
class RequiredObjective:
    obligation: CriterionObligation
    #: 왜 요구되는가: `profile` · `profile_conditional` · `declared`
    required_by: tuple[str, ...]


def required_objectives(
    contract: CompletionContract | None,
    declared: Iterable[str] | None,
    filled_fields: Iterable[str],
) -> list[RequiredObjective]:
    """완료하려면 기준이 있어야 하는 목적 의무.

    `Profile 필수 ∪ 조건부(항목이 채워졌을 때) ∪ 의도가 선언한 목적` 이다.

    **선언된 목적은 Profile 이 아니라 의도에 있다.** 그래서 대표 Profile 이 다른 명시
    목적을 지우지 않고(case-profiles 5절), 나중에 분류가 바뀌어도 요청한 목적은 의도에
    그대로 남는다.
    """
    if contract is None:
        return []
    filled = set(filled_fields)
    reasons: dict[CriterionObligation, list[str]] = {}
    for req in contract.requirements:
        if req.when_field_filled is None:
            reasons.setdefault(req.obligation, []).append("profile")
        elif req.when_field_filled.value in filled:
            reasons.setdefault(req.obligation, []).append("profile_conditional")
    for raw in declared or []:
        reasons.setdefault(CriterionObligation(raw), []).append("declared")
    order = list(CriterionObligation)
    return [
        RequiredObjective(obligation=o, required_by=tuple(reasons[o]))
        for o in sorted(reasons, key=order.index)
    ]


def objective_coverage(
    required: Iterable[RequiredObjective],
    criteria: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """요구 의무마다 어떤 기준이 있고 몇 건이 충족됐는가.

    상태는 셋이다 — `missing`(기준 없음), `met`(전부 충족), `open`(남은 기준 있음).
    **요구되지 않은 의무의 기준도 보인다**(`required = False`). 선언하지 않은 목적의
    기준이 있어도 그 기준은 여전히 충족돼야 하며(미해결 기준 규칙), 그것을 숨기면
    화면이 사람에게 목적의 일부만 보인다.
    """
    by_ob: dict[str, list[dict[str, Any]]] = {}
    for crit in criteria:
        ob = crit.get("obligation")
        if ob:
            by_ob.setdefault(ob, []).append(crit)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for req in required:
        items = by_ob.get(req.obligation.value, [])
        rows.append(_coverage_row(req.obligation.value, True, req.required_by, items))
        seen.add(req.obligation.value)
    for ob in CriterionObligation:
        if ob.value in by_ob and ob.value not in seen:
            rows.append(_coverage_row(ob.value, False, (), by_ob[ob.value]))
    return rows


def _coverage_row(
    obligation: str, required: bool, required_by: tuple[str, ...], items: list[dict[str, Any]]
) -> dict[str, Any]:
    met = sum(1 for c in items if c.get("verdict") == CriterionVerdict.MET.value)
    if not items:
        status = "missing"
    elif met == len(items):
        status = "met"
    else:
        status = "open"
    return {
        "obligation": obligation,
        "required": required,
        "required_by": list(required_by),
        "criteria": sorted(c["criterion_key"] for c in items),
        "total": len(items),
        "met": met,
        "status": status,
    }


# ================================================ 4. 실험의 정리 상태


def experiment_cleanup(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """실험 실행마다 **임시 변경을 남겼는가**를 관측에서 도출한다(D-66).

    입력은 Case 의 실행 행 전부(시작 순)다. 각 행에는 `run_id`·`status`·`permission`·
    `is_experiment`·`repository_id`·`workspace_effect`(dict 또는 None)가 있어야 한다.

    **저장하지 않고 도출한다.** 뒤 실행이 정리를 관측하면 판정이 바뀌어야 하는데,
    저장하면 그때마다 누가 값을 고치는가가 새 문제가 된다(R3 의 `stop` 과 같은 판단).

    정리 판단의 기준은 **실험 전 트리 지문**이다. 실험 뒤 어떤 실행이든 그 지문에서
    시작했거나 그 지문으로 끝났으면 실험의 임시 변경은 그 시점에 걷혔다. 그런 관측이
    없으면 남았다고 본다 — 관측하지 못한 것을 정리됐다고 읽지 않는다.
    """
    ordered = list(runs)
    result: list[dict[str, Any]] = []
    for index, run in enumerate(ordered):
        if not run.get("is_experiment"):
            continue
        effect = run.get("workspace_effect")
        row: dict[str, Any] = {
            "run_id": run["run_id"],
            "repository_id": run.get("repository_id"),
            "restored_by": None,
            "outside_workspace_changed": (
                effect.get("outside_workspace_changed") if effect else None
            ),
        }
        if run.get("status") != RunStatus.FINISHED.value:
            row["cleanup"] = ExperimentCleanup.NOT_FINISHED.value
        elif run.get("permission") == Permission.READ_ONLY.value:
            row["cleanup"] = ExperimentCleanup.NO_WRITE_PERMISSION.value
        elif not effect or not effect.get("tree_digest_before"):
            row["cleanup"] = ExperimentCleanup.UNOBSERVED.value
        elif effect.get("tree_digest_after") == effect.get("tree_digest_before") and (
            effect.get("head_after") == effect.get("head_before")
        ):
            row["cleanup"] = ExperimentCleanup.RESTORED_IN_RUN.value
        else:
            origin = effect["tree_digest_before"]
            restored_by = None
            for later in ordered[index + 1 :]:
                if later.get("repository_id") != run.get("repository_id"):
                    continue
                later_effect = later.get("workspace_effect") or {}
                if origin in (
                    later_effect.get("tree_digest_before"),
                    later_effect.get("tree_digest_after"),
                ):
                    restored_by = later["run_id"]
                    break
            if restored_by is not None:
                row["cleanup"] = ExperimentCleanup.RESTORED_LATER.value
                row["restored_by"] = restored_by
            else:
                row["cleanup"] = ExperimentCleanup.LEFT_CHANGES.value
        result.append(row)
    return result


#: 잔여로 보는 정리 상태. **모르는 것(`unobserved`)도 잔여다.**
RESIDUE_STATES: frozenset[str] = frozenset(
    {ExperimentCleanup.LEFT_CHANGES.value, ExperimentCleanup.UNOBSERVED.value}
)


# ================================================ 5. 한 Case 의 완료 의미


def evaluate(
    *,
    profile: str | None,
    version: str | None,
    contract: CompletionContract | None,
    declared: Iterable[str] | None,
    filled_fields: Iterable[str],
    criteria: Iterable[dict[str, Any]],
    runs: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """조회·후보·완료 검사가 함께 보는 **완료 의미의 현재 상태.**

    계약이 없으면(v1·Profile 없음) `contract = None` 이고 아무 것도 막지 않는다.
    실험 정리 상태는 계약과 무관하게 보인다 — 표시는 소급이 아니다.
    """
    criteria = list(criteria)
    experiments = experiment_cleanup(runs)
    residue = [e["run_id"] for e in experiments if e["cleanup"] in RESIDUE_STATES]
    if contract is None:
        return {
            "contract": None,
            "profile": profile,
            "profile_version": version,
            "detail": "이 Case 의 Profile 정의에는 완료 계약이 없다(v1 또는 미기록)."
            " 완료 판정은 기준 전부 충족 하나다",
            "declared_objectives": list(declared) if declared is not None else None,
            "objectives": [],
            "missing": [],
            "experiments": experiments,
            "residue": residue,
            "residue_blocks_auto_completion": False,
        }
    required = required_objectives(contract, declared, filled_fields)
    coverage = objective_coverage(required, criteria)
    missing = [row["obligation"] for row in coverage if row["required"] and not row["total"]]
    product = any(r.obligation in PRODUCT_OBLIGATIONS for r in required)
    return {
        "contract": "profile_completion_contract",
        "profile": profile,
        "profile_version": version,
        "detail": None,
        "declared_objectives": list(declared) if declared is not None else None,
        "objectives": coverage,
        "missing": missing,
        "experiments": experiments,
        "residue": residue,
        # **제품 목적이 있을 때만** 잔여가 자동 완료를 막는다. 조사만 하는 Case 의
        # 결과는 보고서이며 작업공간이 결과물이 아니다.
        "residue_blocks_auto_completion": bool(residue) and product,
    }


def snapshot_block(meaning: dict[str, Any]) -> dict[str, Any] | None:
    """완료 후보 스냅샷에 넣는 부분. **계약이 없으면 `None`** 이다.

    v1 Case 의 후보에 이 블록을 넣으면 해시가 바뀌어 controlled 의 결과 확인이 소급으로
    낡는다. 계약이 있는 Case 만 넣는다.

    Profile 이름은 넣지 않는다. 후보가 말하는 것은 "무엇을 입증했는가"이고, 그것이
    같으면 분류 표기만 다른 두 후보는 같은 후보다.
    """
    if meaning.get("contract") is None:
        return None
    return {
        "objectives": [
            {
                "obligation": row["obligation"],
                "required": row["required"],
                "criteria": row["criteria"],
                "met": row["met"],
                "status": row["status"],
            }
            for row in meaning["objectives"]
        ],
        "missing": list(meaning["missing"]),
        "residue": list(meaning["residue"]),
        "residue_blocks_auto_completion": bool(meaning["residue_blocks_auto_completion"]),
    }
