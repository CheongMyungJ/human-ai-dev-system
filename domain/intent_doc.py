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

from domain.models import (
    AuthoringMode,
    ConfirmationState,
    ContentOrigin,
    DecideAt,
    FieldChange,
    IntentField,
)

DOC_TYPE = "hads.intent-draft"
#: v2 에서 성공 기준(`criteria`)이 문서 안으로 들어왔다. 기준을 별도 문서로 두면
#: "성공 기준은 의도에서 분리되지 않도록 연결한다"(intent-artifacts 1절)를 지키기
#: 어렵다. v1 문서도 계속 읽을 수 있고, 그 문서의 기준은 **0건**이다 —
#: 없던 기준을 지금 와서 만들어 내지 않는다.
DOC_VERSION = 2
SUPPORTED_DOC_VERSIONS = (1, 2)

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
) -> bytes:
    """여섯 항목과 질문 목록을 정규 문서 바이트로 만든다.

    비어 있는 항목은 **삭제하지 않고** 본문 없이 `undecided` 로 남긴다
    (intent-artifacts.md 1절). 여기서 값을 추정해 채우지 않는다.

    `authored_by` 와 `authoring_mode` 는 이 초안을 **실제로 쓴 주체**다.
    FR-03의 핵심은 여섯 항목이 기록되는 것이 아니라 AI가 제시하고 사람이 검토하는
    역할 분리이므로, 둘 중 어느 쪽이 썼는지를 문서가 스스로 말해야 한다.
    """
    body: dict[str, Any] = {
        "doc_type": DOC_TYPE,
        "doc_version": DOC_VERSION,
        "case_id": case_id,
        "authored_by": authored_by,
        "authoring_mode": AuthoringMode(authoring_mode).value,
        "author_run_id": author_run_id,
        "authoring_note": AUTHORING_NOTE[AuthoringMode(authoring_mode)],
        "fields": {},
        "questions": [],
        # 성공 기준은 **이 문서 안에** 있다. 기준마다 관련 의도 항목 → 확인 방법 →
        # 기대값을 이어서 적는다(intent-artifacts 1절). 제어부에는 짧은 요약만 간다.
        "criteria": [],
    }

    for field in FIELD_ORDER:
        given = fields.get(field.value) or {}
        text = str(given.get("text") or "").strip()
        if text:
            state = ConfirmationState(given.get("state") or ConfirmationState.PROPOSED.value)
            origin = ContentOrigin(given.get("origin") or ContentOrigin.AI_PROPOSAL.value)
            if origin is ContentOrigin.NONE:
                # 내용이 있는데 출처가 없다고 적지 않는다.
                raise ValueError(f"field {field.value} has text but origin 'none'")
        else:
            # 내용이 없으면 상태·출처를 추정하지 않는다.
            state = ConfirmationState.UNDECIDED
            origin = ContentOrigin.NONE
        body["fields"][field.value] = {
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
        relates_to = IntentField(raw.get("relates_to") or IntentField.EXPECTED_OUTCOME.value)
        body["criteria"].append(
            {
                "key": key,
                "relates_to": relates_to.value,
                "text": text,
                "method": method,
                "summary": summary,
                "method_summary": method_summary,
            }
        )

    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")


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
    for field in FIELD_ORDER:
        current = doc["fields"][field.value]
        if prev_doc is None:
            change = FieldChange.INITIAL
        else:
            prev = prev_doc["fields"].get(field.value, {})
            same = (
                prev.get("text") == current["text"]
                and prev.get("state") == current["state"]
                and prev.get("origin") == current["origin"]
            )
            change = FieldChange.UNCHANGED if same else FieldChange.CHANGED
        fields.append(
            {
                "field": field.value,
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
    criteria = [
        {
            "key": c["key"],
            "relates_to": c["relates_to"],
            "summary": c["summary"],
            "method_summary": c["method_summary"],
        }
        for c in doc["criteria"]
    ]

    prev_keys = {q["key"] for q in prev_doc["questions"]} if prev_doc else set()
    current_keys = {q["key"] for q in questions}
    return {
        "fields": fields,
        "questions": questions,
        "criteria": criteria,
        "question_diff": {
            "added": sorted(current_keys - prev_keys),
            "removed": sorted(prev_keys - current_keys),
        },
        "compared_with_previous": prev_doc is not None,
    }
