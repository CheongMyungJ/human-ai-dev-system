"""설계안·개발계획의 정규 문서 형식 — 제어부와 Runner가 함께 쓰는 계약.

`domain/intent_doc.py` 와 같은 역할·같은 경계다.

    제어부는 `compose()` 로 받은 항목을 문서 바이트로 만들어 **중계만** 한다.
    `parse()`·`structure()` 는 **원문을 가진 Runner가** 부른다. 제어부에는 항목별
    상태·출처·필수 여부와 질문의 짧은 요약만 보고된다
    (data-boundary-review.md 1절).

**수준이 항목을 정한다.** 간소는 짧은 변경안·계획, 표준은 요구별 대응·인터페이스·
데이터·의존·통합 순서, 심층은 대안·실패 복구까지다(intent-artifacts.md 2절).
수준이 요구하지 않는 항목도 **삭제하지 않고** `undecided` 로 남긴다 — 의도 문서의
여섯 항목과 같은 규칙이며, 지우면 "이번에 다루지 않기로 했다"와 "아직 모른다"를
구별할 수 없다.

깊이를 높이는 것이 항목을 모두 늘리는 뜻은 아니므로 필수 항목은 최소로 둔다.
항목의 **내용이 충분한지**는 사람의 검토와 (P4의) 게이트가 본다. 여기서 보는 것은
필수 항목이 미정으로 비어 있는지까지다.
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
    PreparationStage,
    WorkLevel,
)

DOC_TYPE = "hads.preparation"
DOC_VERSION = 1
SUPPORTED_DOC_VERSIONS = (1,)

SUMMARY_LIMIT = 200

#: 단계별 항목의 고정 순서. 줄이지 않는다.
SECTION_ORDER: dict[PreparationStage, tuple[str, ...]] = {
    PreparationStage.DESIGN: (
        "change_summary",
        "requirement_mapping",
        "interfaces_and_data",
        "failure_handling",
        "alternatives",
        "recovery",
        "verifiability",
        "open_questions",
    ),
    PreparationStage.PLAN: (
        "tasks",
        "verification",
        "dependencies",
        "integration_order",
        "human_decision_points",
        "environment_prerequisites",
        "experiments",
        "failure_response",
        "open_questions",
    ),
}

#: 수준별 필수 항목. plan/P3-PLAN-01.md "수준별 필수 항목" 표와 같아야 한다.
#:
#: `open_questions` 는 **어느 수준에서도 필수가 아니다.** 질문이 남아 있는 것은
#: 문제가 아니고 숨기는 것이 문제라는 QG-01의 원칙을 그대로 따른다.
REQUIRED_SECTIONS: dict[PreparationStage, dict[WorkLevel, frozenset[str]]] = {
    PreparationStage.DESIGN: {
        WorkLevel.SIMPLE: frozenset({"change_summary", "verifiability"}),
        WorkLevel.STANDARD: frozenset(
            {
                "change_summary",
                "verifiability",
                "requirement_mapping",
                "interfaces_and_data",
                "failure_handling",
            }
        ),
        WorkLevel.DEEP: frozenset(
            {
                "change_summary",
                "verifiability",
                "requirement_mapping",
                "interfaces_and_data",
                "failure_handling",
                "alternatives",
                "recovery",
            }
        ),
    },
    PreparationStage.PLAN: {
        WorkLevel.SIMPLE: frozenset({"tasks", "verification"}),
        WorkLevel.STANDARD: frozenset(
            {
                "tasks",
                "verification",
                "dependencies",
                "integration_order",
                "human_decision_points",
                "environment_prerequisites",
            }
        ),
        WorkLevel.DEEP: frozenset(
            {
                "tasks",
                "verification",
                "dependencies",
                "integration_order",
                "human_decision_points",
                "environment_prerequisites",
                "experiments",
                "failure_response",
            }
        ),
    },
}

#: 사람이 읽는 항목 이름. 화면과 지시문이 같은 말을 쓰게 하기 위해 한 곳에 둔다.
SECTION_LABEL: dict[str, str] = {
    "change_summary": "변경 위치·동작·영향",
    "requirement_mapping": "요구별 설계 대응",
    "interfaces_and_data": "인터페이스·데이터",
    "failure_handling": "실패·예외 처리",
    "alternatives": "대안과 선택 이유",
    "recovery": "실패·복구 경로",
    "verifiability": "검증 가능성",
    "tasks": "작업별 목적·산출물·완료 조건",
    "verification": "검증 작업",
    "dependencies": "의존 관계",
    "integration_order": "통합 순서",
    "human_decision_points": "사람 판단이 필요한 지점",
    "environment_prerequisites": "실행 환경·선행 조건",
    "experiments": "실험·이행 검증",
    "failure_response": "실패 시 대응",
    "open_questions": "미정 질문",
}


def required_sections(stage: PreparationStage, level: WorkLevel) -> frozenset[str]:
    return REQUIRED_SECTIONS[PreparationStage(stage)][WorkLevel(level)]


def _short(text: str) -> str:
    one_line = " ".join(str(text).split())
    if len(one_line) <= SUMMARY_LIMIT:
        return one_line
    return one_line[: SUMMARY_LIMIT - 1] + "…"


AUTHORING_NOTE = {
    AuthoringMode.HUMAN_TYPED: "사람이 화면에서 직접 입력한 산출물이다.",
    AuthoringMode.AI_DRAFTED: (
        "AI 실행이 작성해 제시한 산출물이다. 사람은 열람·검토를 한다."
    ),
}


def compose(
    stage: PreparationStage,
    level: WorkLevel,
    sections: dict[str, dict[str, Any]],
    questions: list[dict[str, Any]],
    case_id: str,
    intent_version_id: str,
    authored_by: str,
    authoring_mode: AuthoringMode = AuthoringMode.AI_DRAFTED,
    author_run_id: str | None = None,
    context_notes: list[dict[str, Any]] | None = None,
) -> bytes:
    """항목과 질문을 정규 문서 바이트로 만든다.

    `intent_version_id` 를 문서 안에 적는다. **어느 의도 위에 세운 산출물인지가
    문서 스스로 말해야** 하며, 그래야 나중에 원문만 보고도 오래된 산출물을 알아볼
    수 있다(intent-artifacts 3절 "설계·계획이 참조한 의도 버전").

    `context_notes` 는 이 실행이 **실제로 읽은 참조**와 읽지 못한 참조다. 읽지 못한
    것을 비워 두지 않고 그대로 적는다 — 이전 버전을 보지 못한 채 쓴 산출물이
    그 사실을 숨기지 않게 하기 위해서다(P2-04 위험 1).
    """
    stage = PreparationStage(stage)
    level = WorkLevel(level)
    required = required_sections(stage, level)

    body: dict[str, Any] = {
        "doc_type": DOC_TYPE,
        "doc_version": DOC_VERSION,
        "stage": stage.value,
        "level": level.value,
        "case_id": case_id,
        "intent_version_id": intent_version_id,
        "authored_by": authored_by,
        "authoring_mode": AuthoringMode(authoring_mode).value,
        "author_run_id": author_run_id,
        "authoring_note": AUTHORING_NOTE[AuthoringMode(authoring_mode)],
        "context_notes": [],
        "sections": {},
        "questions": [],
    }

    for note in context_notes or []:
        body["context_notes"].append(
            {
                "role": str(note.get("role") or "unknown"),
                "artifact_id": str(note.get("artifact_id") or ""),
                "revision": int(note.get("revision") or 0),
                # 읽었는가. **읽지 못한 것을 읽은 것으로 적지 않는다.**
                "read": bool(note.get("read")),
            }
        )

    for section in SECTION_ORDER[stage]:
        given = sections.get(section) or {}
        text = str(given.get("text") or "").strip()
        if text:
            state = ConfirmationState(given.get("state") or ConfirmationState.PROPOSED.value)
            origin = ContentOrigin(given.get("origin") or ContentOrigin.AI_PROPOSAL.value)
            if origin is ContentOrigin.NONE:
                raise ValueError(f"section {section} has text but origin 'none'")
        else:
            state = ConfirmationState.UNDECIDED
            origin = ContentOrigin.NONE
        body["sections"][section] = {
            "text": text,
            "state": state.value,
            "origin": origin.value,
            "required": section in required,
        }

    seen: set[str] = set()
    for raw in questions:
        key = str(raw.get("key") or "").strip()
        text = str(raw.get("text") or "").strip()
        summary = _short(str(raw.get("summary") or "").strip())
        if not key or not text:
            raise ValueError("question needs both a key and a text")
        if not summary:
            raise ValueError(f"question {key} needs its own summary, not an excerpt of the text")
        if key in seen:
            raise ValueError(f"duplicate question key: {key}")
        seen.add(key)
        body["questions"].append(
            {
                "key": key,
                "text": text,
                "summary": summary,
                # 이 단계에서 만들어진 질문의 기본 결정 시점은 그 단계다.
                "decide_at": DecideAt(
                    raw.get("decide_at")
                    or (
                        DecideAt.DESIGN.value
                        if stage is PreparationStage.DESIGN
                        else DecideAt.PLAN.value
                    )
                ).value,
                "blocks": [str(b) for b in (raw.get("blocks") or [])],
            }
        )

    return json.dumps(body, ensure_ascii=False, indent=2, sort_keys=False).encode("utf-8")


def parse(body: bytes) -> dict[str, Any]:
    doc = json.loads(body.decode("utf-8"))
    if doc.get("doc_type") != DOC_TYPE:
        raise ValueError(f"not a preparation document: {doc.get('doc_type')!r}")
    if doc.get("doc_version") not in SUPPORTED_DOC_VERSIONS:
        raise ValueError(f"unsupported preparation document version: {doc.get('doc_version')!r}")
    if doc.get("stage") not in {s.value for s in PreparationStage}:
        raise ValueError(f"unknown preparation stage: {doc.get('stage')!r}")
    doc.setdefault("context_notes", [])
    return doc


def structure(body: bytes, previous: bytes | None = None) -> dict[str, Any]:
    """제어부에 보고할 구조를 만든다. **본문은 넣지 않는다.**

    항목은 상태·출처·필수 여부와 이전 버전 대비 변화만, 질문은 짧은 요약만 올린다.
    """
    doc = parse(body)
    prev_doc = parse(previous) if previous else None
    stage = PreparationStage(doc["stage"])

    sections: list[dict[str, Any]] = []
    for section in SECTION_ORDER[stage]:
        current = doc["sections"].get(section)
        if current is None:
            # 문서에 항목이 통째로 없다. 만들어 채우지 않고 미정으로 보고한다 —
            # 없는 것을 있는 것으로 만들면 진입 조건이 통과해 버린다.
            current = {
                "text": "",
                "state": ConfirmationState.UNDECIDED.value,
                "origin": ContentOrigin.NONE.value,
                "required": section in required_sections(stage, WorkLevel(doc["level"])),
            }
        if prev_doc is None:
            change = FieldChange.INITIAL
        else:
            prev = (prev_doc.get("sections") or {}).get(section, {})
            same = (
                prev.get("text") == current["text"]
                and prev.get("state") == current["state"]
                and prev.get("origin") == current["origin"]
            )
            change = FieldChange.UNCHANGED if same else FieldChange.CHANGED
        sections.append(
            {
                "section": section,
                "state": current["state"],
                "origin": current["origin"],
                "required": bool(current.get("required")),
                "change_from_prev": change.value,
            }
        )

    questions = [
        {
            "key": q["key"],
            "summary": q["summary"],
            "decide_at": q["decide_at"],
            "blocks": q.get("blocks") or [],
        }
        for q in doc["questions"]
    ]

    return {
        "stage": stage.value,
        "level": doc["level"],
        "intent_version_id": doc["intent_version_id"],
        "sections": sections,
        "questions": questions,
        # 이 산출물을 쓴 실행이 무엇을 읽었는지. 읽지 못한 참조도 그대로 올린다.
        "context_notes": doc["context_notes"],
        "compared_with_previous": prev_doc is not None,
    }
