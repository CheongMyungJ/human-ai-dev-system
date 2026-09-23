"""의도 초안의 정규 문서 형식 — 제어부와 Runner가 함께 쓰는 계약.

**누가 무엇을 하는지가 데이터 경계의 핵심이다.**

    제어부는 `compose()` 로 받은 항목을 문서 바이트로 만들어 **중계만** 한다.
    그 바이트는 메모리 버퍼를 지나 소유 Runner로 가고 제어부에는 남지 않는다.
    제어부는 `parse()`·`structure()` 를 **부르지 않는다.** 본문에서 상태를 끌어내는
    일은 원문을 소유한 Runner가 하고, 제어부에는 항목별 상태·출처·변화 여부와
    질문의 짧은 요약만 보고된다
    (data-boundary-review.md 1절 "상태 필드에 넣어 저장 제한을 우회하지 않는다").

형식을 이 한 곳에 두는 이유는 화면(TS)·제어부·Runner가 각자 다른 형식을 만들지
않게 하기 위해서다. 문서 형식은 UTF-8 JSON이며 사람이 읽는 표현은 화면이 만든다.
저장되는 원문은 항목 경계가 분명한 이 형식이다. 항목을 잃지 않기 위해서다.
"""

from __future__ import annotations

import json
from typing import Any

from domain import profiles
from domain.completion_meaning import CONCLUSION_OBLIGATIONS, derive_obligation
from domain.models import (
    AuthoringMode,
    AxisWeight,
    ConclusionRule,
    ConfirmationState,
    ContentOrigin,
    CriterionObligation,
    DecideAt,
    FieldChange,
    IntentField,
    SizingAxis,
    WorkLevel,
)

DOC_TYPE = "hads.intent-draft"
#: v2 에서 성공 기준(`criteria`)이 문서 안으로 들어왔다. 기준을 별도 문서로 두면
#: "성공 기준은 의도에서 분리되지 않도록 연결한다"(intent-artifacts 1절)를 지키기
#: 어렵다. v1 문서도 계속 읽을 수 있고, 그 문서의 기준은 **0건**이다 —
#: 없던 기준을 지금 와서 만들어 내지 않는다.
#:
#: v3 에서 작업 수준 판단(`sizing`)이 들어왔다. 같은 이유다 — 축별 근거를 별도
#: 본문 API 로 받으면 데이터 경계가 뚫리고, 의도 버전이 바뀌었을 때 옛 근거가 새
#: 의도에 그대로 붙는다. v1·v2 문서의 축은 **0건**이며 그 Case 는 수준 미결정이다.
#: 0건을 "간소"로 읽지 않는다.
#: v4 에서 Profile 이 들어왔다(P3-R1). 문서는 자기 Profile 과 **항목 순서**를 함께
#: 적는다 — 읽는 쪽이 현재 정의를 다시 조회하면, 정의가 새 버전으로 바뀐 뒤 옛 문서가
#: 갑자기 항목이 빠진 문서로 읽힌다(D-62 "새 정의를 기존 Case 에 소급 적용하지
#: 않는다"). v1~v3 문서의 항목은 공통 여섯 항목이며 Profile 은 **없음**이다.
#: v5 에서 **목적 의무**가 들어왔다(P4-03). 문서는 요청이 명시한 목적(`objectives`)과
#: 기준마다 무엇을 입증하는가(`obligation`), 원인·조사 기준의 결론 요구
#: (`conclusion_rule`)를 적는다. 셋 다 **완료 계약이 있는 Profile(정의판 v2)** 에서만
#: 쓴다. v1~v4 문서의 목적은 **없음**이고 기준의 의무도 없다 — 없던 것을 지금 와서
#: 만들어 내지 않는다.
DOC_VERSION = 5
SUPPORTED_DOC_VERSIONS = (1, 2, 3, 4, 5)

#: 필수 여섯 항목의 고정 순서. 줄이지 않는다.
FIELD_ORDER: tuple[IntentField, ...] = (
    IntentField.GOAL,
    IntentField.EXPECTED_OUTCOME,
    IntentField.SCOPE,
    IntentField.EXCLUSIONS,
    IntentField.CONSTRAINTS,
    IntentField.OPEN_QUESTIONS,
)

SUMMARY_LIMIT = 200


def _short(text: str) -> str:
    """목록 표시용 짧은 요약. 원문을 대체하지 않는다."""
    one_line = " ".join(str(text).split())
    if len(one_line) <= SUMMARY_LIMIT:
        return one_line
    return one_line[: SUMMARY_LIMIT - 1] + "…"


#: 작성 주체에 따른 설명. **문서에 적히는 것은 실제로 일어난 일이어야 한다.**
#:
#: P2-02까지는 사람만 초안을 쓸 수 있었고 문서에도 그렇게 적었다. P2-03에서 AI
#: 작성 경로가 생겼으므로 두 경우를 구분한다. 한쪽 문구를 그대로 두면 문서가
#: 거짓말을 한다.
AUTHORING_NOTE = {
    AuthoringMode.HUMAN_TYPED: (
        "사람이 화면에서 직접 입력한 초안이다. AI가 제시한 것이 아니다."
    ),
    AuthoringMode.AI_DRAFTED: (
        "AI 실행이 작성해 제시한 초안이다. 사람은 열람·질문·피드백·동의를 한다."
    ),
}


def compose(
    fields: dict[str, dict[str, Any]],
    questions: list[dict[str, Any]],
    case_id: str,
    authored_by: str,
    authoring_mode: AuthoringMode = AuthoringMode.HUMAN_TYPED,
    author_run_id: str | None = None,
    criteria: list[dict[str, Any]] | None = None,
    sizing: dict[str, Any] | None = None,
    profile: str | None = None,
    profile_version: str | None = None,
    objectives: list[str] | None = None,
) -> bytes:
    """필수 항목과 질문 목록을 정규 문서 바이트로 만든다.

    비어 있는 항목은 **삭제하지 않고** 본문 없이 `undecided` 로 남긴다
    (intent-artifacts.md 1절). 여기서 값을 추정해 채우지 않는다.

    `authored_by` 와 `authoring_mode` 는 이 초안을 **실제로 쓴 주체**다.
    FR-03의 핵심은 여섯 항목이 기록되는 것이 아니라 AI가 제시하고 사람이 검토하는
    역할 분리이므로, 둘 중 어느 쪽이 썼는지를 문서가 스스로 말해야 한다.

    `profile` 을 주면 공통 여섯 항목 **뒤에** 그 목적의 의미 항목이 붙는다(D-62).
    주지 않으면 여섯 항목만 쓴다 — Profile 이 기록되지 않은 Case(R1 이전)의 문서
    형식이며, 없는 Profile 을 기본값으로 채우지 않는다.

    **목적·의무·결론 요구는 완료 계약이 있는 Profile 에서만 받는다**(v5, P4-03).
    계약이 없는 Case 에 주면 거부한다 — 받아 두면 그 Case 의 기준에 뜻 없는 값이
    남고, 나중에 누군가 그것을 규칙으로 읽는다. `objectives` 는 **작성자가 선언한
    것만** 적는다. Profile 의 필수 의무를 여기에 복사하지 않는다 — 그것은 정의가
    말하고, 문서는 요청이 말한 것을 말한다.
    """
    field_order = profiles.field_order(profile, profile_version)
    contract = profiles.completion_contract(profile, profile_version)
    declared: list[str] | None = None
    if objectives is not None:
        if contract is None:
            raise ValueError(
                "objectives need a profile with a completion contract (definition v2)"
            )
        declared = []
        for raw in objectives:
            value = CriterionObligation(str(raw)).value
            if value not in declared:
                declared.append(value)
    body: dict[str, Any] = {
        "doc_type": DOC_TYPE,
        "doc_version": DOC_VERSION,
        "case_id": case_id,
        "authored_by": authored_by,
        "authoring_mode": AuthoringMode(authoring_mode).value,
        "author_run_id": author_run_id,
        "authoring_note": AUTHORING_NOTE[AuthoringMode(authoring_mode)],
        # Profile 과 항목 순서를 문서가 스스로 적는다(v4). 읽는 쪽은 이 목록으로
        # 항목을 돌며, 현재 정의를 다시 조회하지 않는다.
        "profile": profile,
        "profile_version": profile_version,
        "field_order": list(field_order),
        "fields": {},
        "questions": [],
        # 성공 기준은 **이 문서 안에** 있다. 기준마다 관련 의도 항목 → 확인 방법 →
        # 기대값을 이어서 적는다(intent-artifacts 1절). 제어부에는 짧은 요약만 간다.
        "criteria": [],
        # 요청이 명시한 목적 의무(v5). `None` 은 "선언하지 않음"이며 빈 목록과 다르다.
        "objectives": declared,
        # 작업 수준 판단도 이 문서 안에 있다(v3). 축별 **근거의 서술**은 여기 남고
        # 제어부에는 영향·짧은 판단 한 줄만 간다. `None` 은 "판단하지 않았다"이며
        # 빈 축 목록과 같은 뜻이다 — 어느 쪽도 "간소"가 아니다.
        "sizing": None,
    }

    for name in field_order:
        given = fields.get(name) or {}
        text = str(given.get("text") or "").strip()
        if text:
            state = ConfirmationState(given.get("state") or ConfirmationState.PROPOSED.value)
            origin = ContentOrigin(given.get("origin") or ContentOrigin.AI_PROPOSAL.value)
            if origin is ContentOrigin.NONE:
                # 내용이 있는데 출처가 없다고 적지 않는다.
                raise ValueError(f"field {name} has text but origin 'none'")
        else:
            # 내용이 없으면 상태·출처를 추정하지 않는다.
            state = ConfirmationState.UNDECIDED
            origin = ContentOrigin.NONE
        body["fields"][name] = {
            "text": text,
            "state": state.value,
            "origin": origin.value,
        }

    seen_keys: set[str] = set()
    for raw in questions:
        key = str(raw.get("key") or "").strip()
        text = str(raw.get("text") or "").strip()
        # 요약은 **작성자가 따로 쓴 문구**다. 본문에서 잘라 내지 않는다.
        # 이 저장소의 다른 요약과 같은 규칙이며(controller/api.py ArtifactIn),
        # 본문 일부가 요약을 타고 제어부에 남는 것을 막는다.
        summary = _short(str(raw.get("summary") or "").strip())
        if not key or not text:
            raise ValueError("question needs both a key and a text")
        if not summary:
            raise ValueError(f"question {key} needs its own summary, not an excerpt of the text")
        if key in seen_keys:
            raise ValueError(f"duplicate question key: {key}")
        seen_keys.add(key)
        body["questions"].append(
            {
                "key": key,
                "text": text,
                "summary": summary,
                # 결정 시점을 기록해 이월한 질문과 의도 단계 질문을 구별한다(FR-03).
                "decide_at": DecideAt(raw.get("decide_at") or DecideAt.INTENT.value).value,
                # 이 질문의 답을 기다리는 작업(FR-13). 아직 작업 그래프가 없으므로
                # 자유 문자열 목록으로 두고 P3-02에서 Task ID로 잇는다.
                "blocks": [str(b) for b in (raw.get("blocks") or [])],
            }
        )

    seen_criteria: set[str] = set()
    for raw in criteria or []:
        key = str(raw.get("key") or "").strip()
        text = str(raw.get("text") or "").strip()
        method = str(raw.get("method") or "").strip()
        summary = _short(str(raw.get("summary") or "").strip())
        method_summary = _short(str(raw.get("method_summary") or "").strip())
        if not key or not text:
            raise ValueError("success criterion needs both a key and a text")
        if not method:
            # 확인 방법이 없는 기준은 기준이 아니라 바람이다. QG-01의
            # `unverifiable_success_criteria` 가 잡는 바로 그 문제이며, 여기서
            # 빈 값을 통과시키면 게이트가 볼 것이 없어진다.
            raise ValueError(f"criterion {key} needs a verification method")
        if not summary or not method_summary:
            raise ValueError(
                f"criterion {key} needs its own summary and method_summary,"
                " not an excerpt of the text"
            )
        if key in seen_criteria:
            raise ValueError(f"duplicate criterion key: {key}")
        seen_criteria.add(key)
        relates_to = _field_name(
            raw.get("relates_to") or IntentField.EXPECTED_OUTCOME.value, field_order
        )
        entry: dict[str, Any] = {
            "key": key,
            "relates_to": relates_to,
            "text": text,
            "method": method,
            "summary": summary,
            "method_summary": method_summary,
        }
        entry.update(_criterion_obligation(key, raw, contract, relates_to))
        body["criteria"].append(entry)

    if sizing is not None:
        body["sizing"] = _compose_sizing(sizing)

    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")


def _criterion_obligation(
    key: str,
    raw: dict[str, Any],
    contract: profiles.CompletionContract | None,
    relates_to: str,
) -> dict[str, str]:
    """기준의 의무·결론 요구를 **작성자가 적은 그대로** 검증해 돌려준다(v5).

    적지 않은 의무는 문서에 넣지 않는다 — 도출은 제어부가 공개된 대응표로 하고
    출처를 `derived_from_field` 로 남긴다. 문서가 도출값을 적으면 "원문이 명시했다"와
    구별되지 않는다.

    결론 요구는 원인·조사 의무의 기준에만 붙는다. 다른 기준에 붙이면 거부한다.
    """
    obligation = raw.get("obligation")
    rule = raw.get("conclusion_rule")
    if contract is None:
        if obligation or rule:
            raise ValueError(
                f"criterion {key} carries an obligation but the profile has no"
                " completion contract (definition v2)"
            )
        return {}
    out: dict[str, str] = {}
    if obligation:
        out["obligation"] = CriterionObligation(str(obligation)).value
    effective, _ = derive_obligation(contract, relates_to, out.get("obligation"))
    if rule:
        if effective not in CONCLUSION_OBLIGATIONS:
            raise ValueError(
                f"criterion {key}: conclusion_rule belongs to cause/answer criteria,"
                f" not {effective.value if effective else 'none'}"
            )
        out["conclusion_rule"] = ConclusionRule(str(rule)).value
    return out


def _field_name(value: Any, field_order: tuple[str, ...]) -> str:
    """성공 기준이 가리키는 의도 항목 이름(P3-R1).

    이 문서의 항목 목록 안에 있어야 한다. 밖의 이름을 받아 두면 기준이 존재하지
    않는 항목에 걸려 "기준과 의도의 연결"이 끊긴다(intent-artifacts 1절).
    """
    name = str(value)
    if name not in field_order:
        raise ValueError(f"criterion relates_to is not a field of this document: {name}")
    return name


def _compose_sizing(sizing: dict[str, Any]) -> dict[str, Any]:
    """작업 수준 판단 블록.

    축마다 `근거 / 현재 판단 / 아직 확인할 것 / 영향`을 남긴다
    (sizing-and-review-ux 1절). **숫자 점수는 없다.** `evidence` 는 본문이라 이
    문서에 남고, 제어부로 가는 것은 `judgement`·`unconfirmed` 의 짧은 한 줄이다.

    영향만 적고 판단을 비운 축은 **거부한다.** 그것은 근거 없는 점수이며, 바로
    이 문서가 피하려는 형태다.
    """
    recommended = WorkLevel(sizing.get("recommended_level") or WorkLevel.STANDARD.value)
    axes: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in sizing.get("axes") or []:
        axis = SizingAxis(raw.get("axis"))
        if axis.value in seen:
            raise ValueError(f"duplicate sizing axis: {axis.value}")
        seen.add(axis.value)
        weight = AxisWeight(raw.get("weight"))
        judgement = _short(str(raw.get("judgement") or "").strip())
        if not judgement:
            raise ValueError(f"sizing axis {axis.value} needs a judgement, not just a weight")
        axes.append(
            {
                "axis": axis.value,
                "weight": weight.value,
                # 근거의 서술. **이 문서에만 남는다.**
                "evidence": str(raw.get("evidence") or "").strip(),
                "judgement": judgement,
                # 비어 있을 수 있다. 빈 값은 "적히지 않음"이며 "없음"이 아니다.
                "unconfirmed": _short(str(raw.get("unconfirmed") or "").strip()),
            }
        )
    return {"recommended_level": recommended.value, "axes": axes}


def parse(body: bytes) -> dict[str, Any]:
    doc = json.loads(body.decode("utf-8"))
    if doc.get("doc_type") != DOC_TYPE:
        raise ValueError(f"not an intent draft document: {doc.get('doc_type')!r}")
    version = doc.get("doc_version")
    if version not in SUPPORTED_DOC_VERSIONS:
        raise ValueError(f"unsupported intent draft version: {version!r}")
    # v1 문서에는 기준 항목이 없다. 빈 목록으로 읽되 "기준 0건"과 "기준을 못 읽음"을
    # 섞지 않기 위해 원본은 그대로 두고 읽는 쪽에서만 기본값을 쓴다.
    doc.setdefault("criteria", [])
    # v1·v2 문서에는 수준 판단이 없다. `None` 으로 읽되 "판단 0건"과 "읽지 못함"을
    # 섞지 않기 위해 원본은 그대로 두고 읽는 쪽에서만 기본값을 쓴다.
    doc.setdefault("sizing", None)
    # v1~v3 문서에는 Profile 이 없다. `None` 으로 읽고 항목 순서는 공통 여섯 항목이다.
    # **현재 Profile 로 채우지 않는다** — 그러면 옛 문서가 항목이 빠진 문서로 읽힌다.
    doc.setdefault("profile", None)
    doc.setdefault("profile_version", None)
    doc.setdefault("field_order", [f.value for f in FIELD_ORDER])
    # v1~v4 문서에는 목적 선언이 없다. `None` 이며 빈 목록으로 바꾸지 않는다.
    doc.setdefault("objectives", None)
    return doc


def structure(body: bytes, previous: bytes | None = None) -> dict[str, Any]:
    """제어부에 보고할 구조를 만든다.

    **본문은 넣지 않는다.** 항목은 상태·출처·변화 여부만, 질문은 짧은 요약만 올린다.
    질문 요약을 두는 이유는 화면 목록에서 어떤 결정이 남았는지 알아야 하기 때문이며
    (intent-artifacts 3절이 서버에 요약을 두도록 허용한다), 질문의 대상·근거·선택·영향
    전체는 이 원문 안에 남는다.
    """
    doc = parse(body)
    prev_doc = parse(previous) if previous else None

    fields: list[dict[str, Any]] = []
    for name in doc["field_order"]:
        current = doc["fields"][name]
        if prev_doc is None:
            change = FieldChange.INITIAL
        else:
            prev = prev_doc["fields"].get(name, {})
            same = (
                prev.get("text") == current["text"]
                and prev.get("state") == current["state"]
                and prev.get("origin") == current["origin"]
            )
            change = FieldChange.UNCHANGED if same else FieldChange.CHANGED
        fields.append(
            {
                "field": name,
                "state": current["state"],
                "origin": current["origin"],
                "change_from_prev": change.value,
            }
        )

    # 제어부로 올라가는 것은 **작성자가 쓴 요약**이지 본문 발췌가 아니다.
    questions = [
        {
            "key": q["key"],
            "summary": q["summary"],
            "decide_at": q["decide_at"],
            "blocks": q["blocks"],
        }
        for q in doc["questions"]
    ]

    # 기준도 **요약만** 올린다. 기대값과 확인 방법의 본문은 이 원문 안에 남는다.
    criteria = []
    for c in doc["criteria"]:
        item = {
            "key": c["key"],
            "relates_to": c["relates_to"],
            "summary": c["summary"],
            "method_summary": c["method_summary"],
        }
        # 의무·결론 요구는 **열거값**이다. 원문이 적었을 때만 올린다(v5).
        for name in ("obligation", "conclusion_rule"):
            if c.get(name):
                item[name] = c[name]
        criteria.append(item)

    # 수준 판단도 **요약만** 올린다. 축별 근거의 서술은 이 원문 안에 남는다.
    # `sizing` 이 없으면 `None` 이다 — 빈 축 목록으로 바꾸지 않는다. "판단하지
    # 않았다"와 "판단했는데 축이 0건이다"는 다르고, 둘 다 수준 결정이 아니다.
    sizing_report: dict[str, Any] | None = None
    if doc.get("sizing"):
        sizing_report = {
            "recommended_level": doc["sizing"]["recommended_level"],
            "axes": [
                {
                    "axis": a["axis"],
                    "weight": a["weight"],
                    "judgement_summary": a["judgement"],
                    "unconfirmed_summary": a.get("unconfirmed") or "",
                }
                for a in doc["sizing"]["axes"]
            ],
        }

    prev_keys = {q["key"] for q in prev_doc["questions"]} if prev_doc else set()
    current_keys = {q["key"] for q in questions}
    return {
        "profile": doc.get("profile"),
        "profile_version": doc.get("profile_version"),
        "fields": fields,
        "questions": questions,
        "criteria": criteria,
        # 목적 선언은 열거값 목록이다. `None` 은 "선언 없음"이다(v1~v4 문서 포함).
        "objectives": doc.get("objectives"),
        "sizing": sizing_report,
        "question_diff": {
            "added": sorted(current_keys - prev_keys),
            "removed": sorted(prev_keys - current_keys),
        },
        "compared_with_previous": prev_doc is not None,
    }
