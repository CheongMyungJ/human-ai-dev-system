"""프로젝트 지식의 순수 규칙 (P4-06).

**여기에는 DB 도 HTTP 도 없다.** `domain/context.py`·`domain/work_flow.py` 와 같은 자리이며 같은
이유로 그렇게 둔다 — 진입 검사·Run 생성·조회·시험이 **같은 함수를 봐야** 한다. "검사는 이 규칙을
주입한다고 했는데 생성은 다른 규칙을 넣은" 상태를 만들지 않는다.

이 파일이 답하는 질문은 넷이다.

    1. 이 실행은 어떤 활동인가         목적 → 활동(설계·구현·검증 …). 모르면 모든 항목을 받는다
    2. 이 항목을 이 실행에 주는가       활동 + 범위(Project / 저장소·경로)로 고른다
    3. 이 실행을 막는 충돌이 있는가     적용되는 필수 지식의 미해결 충돌
    4. 이 권위로 이 상태가 되는가       AI 제안은 필수 규칙이 되지 않는다(D-67·D-80)

이 파일이 지키는 것:

    모르는 것을 비적용으로 읽지 않는다  범위를 모르면 `scope_undetermined` 이지 "해당 없음"이 아니다
    단계와 종류를 일대일로 묶지 않는다  설계=ADR·구현=제약 같은 고정 대응을 두지 않는다(SC-11)
    주입은 준수가 아니다                여기서 고른 것은 "제공했다"의 근거일 뿐이다
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from domain.models import RunPurpose


class KnowledgeKind(str, Enum):
    """분류는 설명을 돕는 표식이며 고정 절차나 자동 권위를 만들지 않는다(project-knowledge 1절)."""

    DECISION = "decision"
    CONSTRAINT = "constraint"
    KNOWN_PROBLEM = "known_problem"
    OPERATION = "operation"


class KnowledgeObligation(str, Enum):
    REQUIRED = "required"
    REFERENCE = "reference"


class KnowledgeState(str, Enum):
    CANDIDATE = "candidate"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    INVALID = "invalid"


#: 주입 대상이 되는 상태. 대체·무효는 기본 주입에서 뺀다(이력은 남는다).
PROVIDED_STATES: frozenset[str] = frozenset(
    {KnowledgeState.CANDIDATE.value, KnowledgeState.ACTIVE.value}
)


class KnowledgeAuthority(str, Enum):
    """**권위의 근거.** 출처의 권위, 지식의 유효성, 코드의 구현 상태는 다른 정보다.

    `user_registration`  사람이 직접 등록했다. 기존 확정 결정·규칙의 충실한 등록이며
                         같은 내용을 다시 승인받지 않는다(D-80)
    `user_statement`     사용자가 대화에서 "이 프로젝트에서는 앞으로 …"라고 말한 것을 AI 가
                         옮겨 등록했다. 권위는 **그 사용자 메시지**다(사용자 결정 2026-09-24)
    `user_decision`      사람이 후보를 활성으로 바꿨다(새 버전)
    `ai_proposal`        AI 가 제안했다. **후보이며 의무를 만들지 않는다**(D-67)
    """

    USER_REGISTRATION = "user_registration"
    USER_STATEMENT = "user_statement"
    USER_DECISION = "user_decision"
    AI_PROPOSAL = "ai_proposal"


#: 사람의 권위. 활성 필수 규칙은 이것에서만 나온다.
HUMAN_AUTHORITIES: frozenset[str] = frozenset(
    {
        KnowledgeAuthority.USER_REGISTRATION.value,
        KnowledgeAuthority.USER_STATEMENT.value,
        KnowledgeAuthority.USER_DECISION.value,
    }
)


class ScopeKind(str, Enum):
    PROJECT = "project"
    REPOSITORY = "repository"


# ------------------------------------------------------------------ 활동


#: 실행 활동. **빈 목록 = 논의를 뺀 모든 작업 활동**이다 — 논의 응답에는 `discussion` 을 명시한
#: 항목만 간다. 대화 응답마다 필수 원문 가용성에 묶이면 말 한마디가 원문 하나 때문에 막힌다.
ACTIVITIES: tuple[str, ...] = (
    "discussion",
    "intent",
    "design",
    "plan",
    "implementation",
    "verification",
    "investigation",
    "review",
)

WORK_ACTIVITIES: frozenset[str] = frozenset(a for a in ACTIVITIES if a != "discussion")

#: 목적 → 활동. **배타적 단계 대응이 아니다** — 항목이 어느 활동에 걸리는지는 항목이 말한다.
ACTIVITY_BY_PURPOSE: dict[str, str] = {
    RunPurpose.DISCUSSION_REPLY.value: "discussion",
    RunPurpose.INTENT_AUTHORING.value: "intent",
    RunPurpose.INTENT_GATE_REVIEW.value: "review",
    RunPurpose.QUALITY_GATE_REVIEW.value: "review",
    RunPurpose.DESIGN_AUTHORING.value: "design",
    RunPurpose.PLAN_AUTHORING.value: "plan",
    RunPurpose.FEATURE_IMPLEMENTATION.value: "implementation",
    RunPurpose.VERIFICATION_RUN.value: "verification",
    RunPurpose.LIMITED_ANALYSIS.value: "investigation",
    RunPurpose.LOCAL_EXPERIMENT.value: "investigation",
}

#: 모르는 목적의 활동. 모든 항목을 받는다 — 모르는 것을 비적용으로 읽지 않는다.
UNKNOWN_ACTIVITY = "unknown"


def activity_for(purpose: str | RunPurpose) -> str:
    value = purpose.value if isinstance(purpose, RunPurpose) else str(purpose)
    return ACTIVITY_BY_PURPOSE.get(value, UNKNOWN_ACTIVITY)


def check_activities(values: Iterable[Any]) -> list[str]:
    """활동 목록을 검사한다. 모르는 이름은 `ValueError` — 조용히 버리면 범위가 넓어진다."""
    out: list[str] = []
    for value in values:
        name = str(value).strip()
        if name not in ACTIVITIES:
            raise ValueError(f"unknown activity {name!r}")
        if name not in out:
            out.append(name)
    return out


def check_paths(values: Iterable[Any]) -> list[str]:
    """저장소 안 경로 조건. 짧은 상대 경로·패턴만 받는다(메타데이터이며 본문이 아니다)."""
    out: list[str] = []
    for value in values:
        path = str(value).strip().replace("\\", "/")
        if not path:
            continue
        if len(path) > 200 or path.startswith("/") or ":" in path or ".." in path.split("/"):
            raise ValueError(f"path condition {path!r} must be a short path inside the repository")
        if path not in out:
            out.append(path)
    if len(out) > 20:
        raise ValueError("at most 20 path conditions")
    return out


def activity_applies(item_activities: list[str], activity: str) -> bool:
    if activity == UNKNOWN_ACTIVITY:
        return True
    if not item_activities:
        return activity in WORK_ACTIVITIES
    return activity in item_activities


# ------------------------------------------------------------------ 권위


def check_authority(
    authority: str, state: str, obligation: str
) -> None:
    """이 권위로 이 상태·효력을 기록해도 되는가. 안 되면 `ValueError`.

    **AI 제안은 후보로만 등록된다**(P4-06). 참고 지식의 자동 활성화("근거·조건을 확인해 참고로
    활성화할 수 있다")는 확인 절차가 필요하고 그것은 P4-07 의 몫이다. 활성 필수는 언제나 사람의
    권위다 — DB CHECK 가 마지막 방어선이다.
    """
    KnowledgeAuthority(authority)
    KnowledgeState(state)
    KnowledgeObligation(obligation)
    if authority == KnowledgeAuthority.AI_PROPOSAL.value and state != KnowledgeState.CANDIDATE.value:
        raise ValueError("an AI proposal is registered only as a candidate")
    if state not in (KnowledgeState.CANDIDATE.value, KnowledgeState.ACTIVE.value):
        raise ValueError("a new version starts as a candidate or active")


# ------------------------------------------------------------------ 선택


class Decision(str, Enum):
    """Manifest 의 결정. 제공한 것과 **왜 주지 않았는가**를 나눈다."""

    PROVIDED = "provided"
    OMITTED_SIZE_LIMIT = "omitted_size_limit"
    NOT_APPLICABLE_ACTIVITY = "not_applicable_activity"
    NOT_APPLICABLE_REPOSITORY = "not_applicable_repository"
    SCOPE_UNDETERMINED = "scope_undetermined"


class ScopeResolution(str, Enum):
    PROJECT = "project"
    REPOSITORY = "repository"
    #: 저장소는 맞고 경로 조건이 있다. 실행이 경로를 미리 말하지 않으므로 **조건으로 준다**.
    PATHS_UNRESOLVED = "paths_unresolved"
    #: 이 실행의 저장소를 모른다.
    UNDETERMINED = "undetermined"
    OTHER_REPOSITORY = "other_repository"


#: 참조 역할(`ContextRefRole` 값). 필수·권위 메시지는 핵심, 참고·후보는 보조다.
ROLE_REQUIRED = "knowledge_required"
ROLE_SOURCE = "knowledge_source"
ROLE_REFERENCE = "knowledge_reference"
ROLE_CANDIDATE = "knowledge_candidate"


def role_for(version: dict[str, Any]) -> str:
    if version["state"] == KnowledgeState.CANDIDATE.value:
        return ROLE_CANDIDATE
    if version["obligation"] == KnowledgeObligation.REQUIRED.value:
        return ROLE_REQUIRED
    return ROLE_REFERENCE


_ORDER = {ROLE_REQUIRED: 0, ROLE_REFERENCE: 1, ROLE_CANDIDATE: 2}


@dataclass
class Selection:
    """한 실행의 지식 선택. `applied` 는 주입 순서대로다."""

    activity: str
    repositories: list[str] | None
    applied: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)

    def decisions(self) -> list[dict[str, Any]]:
        return [*self.applied, *self.skipped]


def select(
    versions: Iterable[dict[str, Any]],
    activity: str,
    repositories: list[str] | None,
) -> Selection:
    """현재 버전들 중 이 실행에 줄 것을 고른다.

    `versions` 의 각 항목: `id`·`knowledge_id`·`knowledge_key`·`state`·`obligation`·`scope_kind`·
    `repository_id`·`paths`·`activities`. `repositories` 가 `None` 이면 **이 실행의 저장소를
    모른다** — 저장소 범위 항목은 `scope_undetermined` 이고 Project 범위는 준다.
    """
    selection = Selection(activity=activity, repositories=repositories)
    for version in versions:
        if version["state"] not in PROVIDED_STATES:
            continue
        base = {
            "version_id": version["id"],
            "knowledge_id": version["knowledge_id"],
            "knowledge_key": version.get("knowledge_key"),
            "obligation": version["obligation"],
            "state": version["state"],
            "role": role_for(version),
        }
        if not activity_applies(list(version.get("activities") or []), activity):
            selection.skipped.append(
                {**base, "decision": Decision.NOT_APPLICABLE_ACTIVITY.value,
                 "scope_resolution": None}
            )
            continue
        if version["scope_kind"] == ScopeKind.PROJECT.value:
            resolution = ScopeResolution.PROJECT.value
        elif repositories is None:
            selection.skipped.append(
                {**base, "decision": Decision.SCOPE_UNDETERMINED.value,
                 "scope_resolution": ScopeResolution.UNDETERMINED.value}
            )
            continue
        elif version.get("repository_id") in repositories:
            resolution = (
                ScopeResolution.PATHS_UNRESOLVED.value
                if version.get("paths")
                else ScopeResolution.REPOSITORY.value
            )
        else:
            selection.skipped.append(
                {**base, "decision": Decision.NOT_APPLICABLE_REPOSITORY.value,
                 "scope_resolution": ScopeResolution.OTHER_REPOSITORY.value}
            )
            continue
        selection.applied.append(
            {**base, "decision": Decision.PROVIDED.value, "scope_resolution": resolution}
        )
    selection.applied.sort(
        key=lambda d: (_ORDER.get(d["role"], 9), str(d.get("knowledge_key") or ""))
    )
    return selection


# ------------------------------------------------------------------ 충돌


def blocking_conflicts(
    conflicts: Iterable[dict[str, Any]], applied: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """이 실행을 막는 열린 충돌. **두 항목이 모두 이 실행에 적용되고 하나 이상이 활성 필수**일 때다.

    한쪽만 적용되면 그 실행에는 충돌이 없다 — 무관한 업무까지 멈추지 않는다(4절). 참고끼리의
    충돌은 막지 않고 둘 다 참고로 준다.
    """
    by_item = {d["knowledge_id"]: d for d in applied}
    out = []
    for conflict in conflicts:
        if conflict.get("state") != "open":
            continue
        a = by_item.get(conflict["knowledge_a"])
        b = by_item.get(conflict["knowledge_b"])
        if a is None or b is None:
            continue
        if ROLE_REQUIRED in (a["role"], b["role"]):
            out.append(conflict)
    return out


# ------------------------------------------------------------------ 자동 등록 보고


#: 논의 응답의 등록 블록에서 받는 항목 수 상한. 한 메시지가 규칙 수십 개를 만들지 않는다.
MAX_REPORT_ITEMS = 5


def parse_report_item(raw: Any) -> tuple[dict[str, Any] | None, str | None]:
    """Runner 가 보낸 등록 항목 하나(원문 참조 포함)를 검사한다. (항목, 거부 사유).

    **모르는 값을 지어내지 않는다** — 종류·효력이 틀리면 기본값으로 채우지 않고 거부한다.
    """
    if not isinstance(raw, dict):
        return None, "not_an_object"
    if raw.get("format_error"):
        return None, "format_error"
    try:
        kind = KnowledgeKind(str(raw.get("kind") or "")).value
        obligation = KnowledgeObligation(str(raw.get("obligation") or "")).value
    except ValueError:
        return None, "invalid_kind_or_obligation"
    summary = " ".join(str(raw.get("summary") or "").split())
    if not summary:
        return None, "summary_missing"
    artifact_id = raw.get("artifact_id")
    revision = raw.get("revision")
    if not artifact_id or not isinstance(revision, int):
        return None, "content_not_stored"
    try:
        activities = check_activities(raw.get("activities") or [])
        paths = check_paths(raw.get("paths") or [])
    except ValueError:
        return None, "invalid_scope"
    repository = raw.get("repository")
    repository = str(repository).strip() if repository else None
    if paths and not repository:
        return None, "paths_without_repository"
    supersedes = raw.get("supersedes")
    supersedes = str(supersedes).strip() if supersedes else None
    return {
        "kind": kind,
        "obligation": obligation,
        "summary": summary[:200],
        "artifact_id": str(artifact_id),
        "revision": int(revision),
        "activities": activities,
        "paths": paths,
        "repository": repository,
        "supersedes": supersedes,
    }, None


#: 논의 응답의 등록 블록. 해석 블록(`hads-interpretation`)과 별개이며 **필요할 때만** 붙는다.
_KNOWLEDGE_BLOCK = re.compile(r"```hads-knowledge\s*\n(.*?)\n?```", re.DOTALL)

#: 옮겨 적은 적용 내용 한 건의 상한(문자). 짧은 적용 내용이 계약이다 — 긴 문서를 지식으로 복제하지
#: 않는다(project-knowledge 1절).
MAX_CONTENT_CHARS = 4000


def split_knowledge(final_message: str) -> tuple[str, list[dict[str, Any]]]:
    """응답 글에서 등록 블록을 **떼어 낸다.** (사람이 읽을 글, 항목들)

    블록은 기계용이다 — 대화에 붙는 것은 나머지 글뿐이다. 형식이 틀린 블록은 항목
    `{"format_error": 이유}` 하나로 돌려준다(지어내지 않고, 조용히 버리지도 않는다 — 제어부가
    거부 사유로 남긴다). 항목의 `content` 는 **Runner 에 남는 원문**이며 제어부로 가지 않는다.
    """
    blocks = list(_KNOWLEDGE_BLOCK.finditer(final_message))
    if not blocks:
        return final_message, []
    text = _KNOWLEDGE_BLOCK.sub("", final_message).strip()
    items: list[dict[str, Any]] = []
    for block in blocks:
        try:
            value = json.loads(block.group(1))
        except ValueError:
            items.append({"format_error": "block is not JSON"})
            continue
        raw_items = value.get("items") if isinstance(value, dict) else None
        if not isinstance(raw_items, list):
            items.append({"format_error": "block has no items list"})
            continue
        for raw in raw_items:
            if not isinstance(raw, dict):
                items.append({"format_error": "item is not an object"})
                continue
            content = str(raw.get("content") or "").strip()
            if not content:
                items.append({"format_error": "content missing"})
                continue
            if len(content) > MAX_CONTENT_CHARS:
                items.append({"format_error": "content too long"})
                continue
            items.append(raw)
    return text, items
