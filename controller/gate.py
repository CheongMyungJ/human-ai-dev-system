"""QG-01 의도 초안 품질 게이트.

**게이트는 평가 보고서가 아니라 조건이다**(quality-gates.md "권고 요지"). 여기서
판정하는 것은 "이 초안이 **사람에게 검토를 요청할 준비**가 됐는가"이며, 사용자
의도에 부합한다는 최종 판정은 사람의 명시적 동의로 **따로** 충족한다.

두 종류의 검사를 분리한다(quality-gates.md 4절 A~D).

    규칙 검사  제어부가 보고된 항목 구조로 판정한다. 본문을 읽지 않는다
    AI 의미 검토  원문을 가진 Runner가 **작성과 별도 세션**에서 수행한다

**규칙만 통과한 상태는 게이트 통과가 아니다.** AI 검토를 실행하지 않았으면
`not_run` 이고, `not_run` 을 `pass` 로 승격시키지 않는다. 이 한 줄이 이 파일의
핵심이며 `combine_verdicts()` 가 그것을 강제한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.intent_doc import FIELD_ORDER
from domain.models import (
    Availability,
    ConfirmationState,
    ContentOrigin,
    DecideAt,
    FindingCertainty,
    FindingSeverity,
    FindingSource,
    GateVerdict,
    IntentField,
)

#: AI 의미 검토가 **필수 기준 위반**으로 올릴 수 있는 기준 목록.
#:
#: quality-gates.md 3절: "AI의 막연한 의견이 새 필수 요구를 만들지는 않는다."
#: 이 목록 밖의 발견은 기록하되 권고로 내린다. 목록의 네 항목은 QG-01 표의
#: "AI 검사 항목"을 그대로 옮긴 것이다.
AI_REQUIRED_CRITERIA: frozenset[str] = frozenset(
    {
        "request_missing_or_contradictory",  # 요청 누락·모순
        "assumption_presented_as_requirement",  # AI 가정의 확정 요구 둔갑
        "unverifiable_success_criteria",  # 확인 불가능한 성공 기준
        "important_open_question_unlisted",  # 중요한 미정 질문을 식별하지 못함
    }
)


@dataclass(frozen=True)
class Finding:
    """개별 발견 사항.

    점수로 합치지 않고 각각을 기준·필수/권고·차단 효과·확실성과 함께 남긴다
    (quality-gates.md 3절). `summary` 는 짧은 요약이며 원문을 대체하지 않는다.
    """

    source: FindingSource
    criterion: str
    severity: FindingSeverity
    blocking: bool
    certainty: FindingCertainty
    target: str
    summary: str
    evidence_artifact_id: str | None = None

    def to_row(self) -> dict[str, Any]:
        return {
            "source": self.source.value,
            "criterion": self.criterion,
            "severity": self.severity.value,
            "blocking": 1 if self.blocking else 0,
            "certainty": self.certainty.value,
            "target": self.target,
            "summary": self.summary[:200],
            "evidence_artifact_id": self.evidence_artifact_id,
        }


def _required(criterion: str, target: str, summary: str) -> Finding:
    return Finding(
        source=FindingSource.RULE,
        criterion=criterion,
        severity=FindingSeverity.REQUIRED,
        blocking=True,
        certainty=FindingCertainty.CONFIRMED,
        target=target,
        summary=summary,
    )


def _advisory(criterion: str, target: str, summary: str, certainty: FindingCertainty) -> Finding:
    return Finding(
        source=FindingSource.RULE,
        criterion=criterion,
        severity=FindingSeverity.ADVISORY,
        blocking=False,
        certainty=certainty,
        target=target,
        summary=summary,
    )


def rule_check(detail: dict[str, Any], is_latest: bool) -> tuple[GateVerdict, list[Finding]]:
    """규칙 검사. 본문을 읽지 않고 보고된 구조만 본다.

    `detail` 은 `Repository.get_intent_detail()` 의 결과다. 항목 구조가 아직
    보고되지 않았으면 **통과도 실패도 아니다** — 판단 보류(`hold`)로 남긴다.
    검사하지 못한 것을 통과로 적지 않기 위해서다.

    **P3-R1: 필수 항목 목록은 `detail["required_fields"]` 에서 온다.** Profile 이
    목적별 의미 항목을 더하기 때문이다(D-62). 목록이 없는 호출(옛 기록·직접 호출)은
    공통 여섯 항목으로 검사한다 — 없는 목록을 현재 Profile 의 것으로 채우면 그
    Case 의 과거 판정이 새 규칙으로 바뀐다.
    """
    required_fields: tuple[str, ...] = tuple(
        detail.get("required_fields") or [f.value for f in FIELD_ORDER]
    )
    findings: list[Finding] = []

    fields = {f["field"]: f for f in detail.get("fields", [])}
    if not fields:
        findings.append(
            _advisory(
                "structure_not_reported",
                "document",
                "소유 Runner가 아직 항목 구조를 보고하지 않아 규칙을 검사하지 못했다",
                FindingCertainty.CONFIRMED,
            )
        )
        return GateVerdict.HOLD, findings

    # 1. 필수 항목이 모두 있어야 한다. 정보가 없는 항목도 행으로 남아야 한다.
    for name in required_fields:
        if name not in fields:
            findings.append(
                _required(
                    "required_field_missing",
                    name,
                    f"필수 항목 {name} 이(가) 문서에 없다",
                )
            )

    for name in required_fields:
        row = fields.get(name)
        if row is None:
            continue
        state = row["state"]
        origin = row["origin"]

        # 2. 내용이 있는 항목은 출처가 있어야 한다(FR-04).
        if state != ConfirmationState.UNDECIDED.value and origin == ContentOrigin.NONE.value:
            findings.append(
                _required(
                    "origin_missing",
                    name,
                    f"{name} 에 내용이 있는데 출처가 none 으로 표시돼 있다",
                )
            )

        # 3. 미정 항목은 미정으로 표시돼 있어야 한다. 시스템이 채우지 않는다.
        if state == ConfirmationState.UNDECIDED.value and origin != ContentOrigin.NONE.value:
            findings.append(
                _required(
                    "undecided_mark_inconsistent",
                    name,
                    f"{name} 는 미정인데 출처가 {origin} 로 붙어 있다",
                )
            )

        # 4. AI 가정이 사용자 확정으로 둔갑하지 않았는지. 규칙으로는 **의심**까지만
        #    판단한다 — 사람이 실제로 확인했을 수도 있기 때문이다. 확정 판정은
        #    AI 의미 검토와 사람의 동의가 한다(quality-gates 3절).
        if (
            origin == ContentOrigin.AI_ASSUMPTION.value
            and state == ConfirmationState.USER_CONFIRMED.value
        ):
            findings.append(
                _advisory(
                    "assumption_marked_confirmed",
                    name,
                    f"{name} 는 AI 가정인데 사용자 확정 상태로 표시돼 있다",
                    FindingCertainty.SUSPECTED,
                )
            )

    # 5. 목표가 미정이면 검토를 요청할 준비가 된 것이 아니다(요청 누락).
    goal = fields.get(IntentField.GOAL.value)
    if goal is not None and goal["state"] == ConfirmationState.UNDECIDED.value:
        findings.append(
            _required("goal_undecided", IntentField.GOAL.value, "목표가 미정으로 비어 있다")
        )

    # 6. 최신 버전을 대상으로 한다(QG-01 표: "최신 검토본을 대상으로 수행").
    if not is_latest:
        findings.append(
            _required("not_latest_version", "document", "이 버전은 최신 의도 버전이 아니다")
        )

    # 7. 합의할 성공 기준이 하나도 없으면 결과를 무엇에 견줄지 없다.
    #    **권고로 둔다.** 기준의 내용이 충분한지는 본문을 읽어야 알 수 있고 그것은
    #    AI 의미 검토(`unverifiable_success_criteria`)의 몫이다. 규칙은 "0건"이라는
    #    구조적 사실만 드러낸다. 다만 이 상태로는 최종 인수가 거부된다 —
    #    기준 없이 결과를 인수할 수는 없기 때문이다(controller/repository.py
    #    check_acceptance 의 `no_success_criteria`).
    if not detail.get("criteria"):
        findings.append(
            _advisory(
                "no_success_criteria",
                "document",
                "합의할 성공 기준이 0건이다. 이대로는 결과를 견줄 기준이 없어 최종 인수가 거부된다",
                FindingCertainty.CONFIRMED,
            )
        )

    # 8. 원문을 읽을 수 없으면 사람에게 검토를 요청할 수 없다.
    if detail.get("availability") != Availability.AVAILABLE.value:
        findings.append(
            _required(
                "original_not_available",
                "document",
                f"원문 상태가 {detail.get('availability')} 라 사람이 읽을 수 없다",
            )
        )

    # 8. 미정 질문은 **있어도 된다.** QG-01의 통과 조건은 "질문을 숨기거나 임의로
    #    답하지 않는 것"이지 질문이 없는 것이 아니다. 그래서 권고로만 남긴다.
    open_intent_questions = [
        q
        for q in detail.get("questions", [])
        if q["state"] == "open" and q["decide_at"] == DecideAt.INTENT.value
    ]
    if open_intent_questions:
        findings.append(
            _advisory(
                "open_intent_questions_present",
                "questions",
                "의도 단계에서 결정할 질문이 "
                f"{len(open_intent_questions)}건 남아 있다 (게이트를 막지 않는다)",
                FindingCertainty.CONFIRMED,
            )
        )

    blocking = [f for f in findings if f.blocking]
    return (GateVerdict.FAIL if blocking else GateVerdict.PASS), findings


def normalize_ai_findings(raw: list[dict[str, Any]]) -> list[Finding]:
    """AI 검토가 올린 발견을 규칙에 맞게 정리한다.

    목록에 없는 기준은 **필수로 올릴 수 없다.** AI가 스스로 새 필수 요구를 만드는
    것을 막기 위해서다. 내려간 사실 자체도 기록에 남는다(`criterion` 은 그대로 둔다).
    """
    out: list[Finding] = []
    for item in raw:
        criterion = str(item.get("criterion") or "unspecified")
        certainty = FindingCertainty(item.get("certainty") or FindingCertainty.SUSPECTED.value)
        asked_required = (
            str(item.get("severity") or FindingSeverity.ADVISORY.value)
            == FindingSeverity.REQUIRED.value
        )
        severity = (
            FindingSeverity.REQUIRED
            if (asked_required and criterion in AI_REQUIRED_CRITERIA)
            else FindingSeverity.ADVISORY
        )
        # 확정 근거가 있는 필수 위반만 진행을 막는다. 의심은 판단 보류로 간다.
        blocking = severity is FindingSeverity.REQUIRED and certainty is FindingCertainty.CONFIRMED
        summary = " ".join(str(item.get("summary") or "").split())[:200]
        out.append(
            Finding(
                source=FindingSource.AI,
                criterion=criterion,
                severity=severity,
                blocking=blocking,
                certainty=certainty,
                target=str(item.get("target") or "document")[:120],
                summary=summary or "(요약 없음)",
                evidence_artifact_id=item.get("evidence_artifact_id"),
            )
        )
    return out


def ai_verdict_from(findings: list[Finding]) -> GateVerdict:
    """AI 검토 결과의 판정.

    확정된 필수 위반은 실패, 의심 단계의 필수 위반은 **판단 보류**다. 모호한 발견을
    통과로 감추지도, 확정 실패로 과장하지도 않는다(quality-gates 3절).
    """
    if any(f.blocking for f in findings):
        return GateVerdict.FAIL
    if any(
        f.severity is FindingSeverity.REQUIRED and f.certainty is FindingCertainty.SUSPECTED
        for f in findings
    ):
        return GateVerdict.HOLD
    return GateVerdict.PASS


def combine_verdicts(rule: GateVerdict, ai: GateVerdict) -> GateVerdict:
    """규칙 판정과 AI 판정을 합친다.

    **`not_run` 은 `pass` 가 되지 않는다.** 규칙 검사만으로 게이트를 통과시키면
    QG-01의 AI 검사 항목(요청 누락·모순, 가정의 둔갑, 확인 불가능한 성공 기준)이
    아무도 보지 않은 채 통과한다. 그래서 여기서 막는다.
    """
    if GateVerdict.FAIL in (rule, ai):
        return GateVerdict.FAIL
    if GateVerdict.HOLD in (rule, ai):
        return GateVerdict.HOLD
    if ai is GateVerdict.BLOCKED or rule is GateVerdict.BLOCKED:
        return GateVerdict.BLOCKED
    if ai is GateVerdict.NOT_RUN:
        return GateVerdict.NOT_RUN
    if rule is GateVerdict.PASS and ai is GateVerdict.PASS:
        return GateVerdict.PASS
    return GateVerdict.HOLD
