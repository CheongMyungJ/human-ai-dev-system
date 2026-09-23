"""고정 문맥의 순수 규칙(P4-04).

**판정이 한 곳에 있어야 한다.** 무엇이 핵심인가·무엇을 생략하는가·실행이 무엇을 읽었는가는
진입 검사·Run 생성·재배정·조회·Runner 가 같은 답을 내야 한다. 두 벌로 쓰면 "검사는
통과했는데 생성이 다른 패키지를 만드는" 상태가 조용히 생긴다(P3-R3 의 예약이 같은 이유로
한 함수를 쓴다). 그래서 DB 를 모르는 함수로 둔다 — `domain/conversation.py` 와 같은 방식이다.

지키는 것 셋(review-context-contract 4절):

  **핵심을 한도 때문에 조용히 빼지 않는다.** 넘으면 보류한다.
  **생략은 기록이다.** 무엇을 왜 넣지 않았는지가 참조 행·조회·지시문에 남는다.
  **읽었다는 것은 Runner 가 해시를 대조해 확인한 것이다.** 계획을 읽음으로 적지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from domain.models import (
    ContextInclusion,
    ContextReceiptStatus,
    ContextRefRole,
    ContextTier,
    RunContextState,
)

#: 실행당 인라인 한도의 기본값(바이트). **상세 설계 제안값이며 사용자 확정 정책이
#: 아니다.** 한국어 본문 기준 약 8만 자이고, CLI 가 작업공간에서 직접 읽는 파일과
#: 자기 지시문을 위한 여유를 남긴다. 제어부 설정으로 바꾼다.
DEFAULT_INLINE_LIMIT_BYTES = 256 * 1024

#: 지시 원문의 영수증 순번. 참조의 순번은 1 부터다.
INSTRUCTION_SEQ = 0
INSTRUCTION_ROLE = "instruction"

#: **보조 등급은 이것뿐이다.** AI 의 이전 제안은 사용자의 결정이 아니다(D-60). 나머지
#: 역할은 요청·결정·금지·동의 범위·사람의 답·피드백이거나, 재작성이 잃으면 처음부터
#: 다시 쓰게 되는 이전 버전(P2-04)이다.
SUPPORTING_ROLES: frozenset[str] = frozenset(
    {
        ContextRefRole.CONVERSATION_ASSISTANT_MESSAGE.value,
        # P4-06. 참고·후보 지식은 보조다 — 부족해도 필수 규칙 위반이 아니고 무관한 업무를 막지
        # 않는다. **필수 지식과 그 권위 원문은 핵심**(모르는 역할과 같은 쪽)이다.
        ContextRefRole.KNOWLEDGE_REFERENCE.value,
        ContextRefRole.KNOWLEDGE_CANDIDATE.value,
    }
)

#: 읽지 못한 상태. 해시가 다른 본문은 **다른 원문**이므로 읽은 것이 아니다.
UNREAD_STATUSES: frozenset[str] = frozenset(
    {ContextReceiptStatus.MISSING.value, ContextReceiptStatus.HASH_MISMATCH.value}
)


def tier_for(role: str) -> ContextTier:
    """역할의 등급. **모르는 역할은 핵심이다** — 모르는 것을 생략 가능으로 읽지 않는다."""
    return ContextTier.SUPPORTING if role in SUPPORTING_ROLES else ContextTier.CORE


# ============================================================ 인라인 계획


@dataclass
class ContextPlan:
    """한 실행의 입력 패키지 계획.

    `refs` 는 들어온 순서 그대로이며 각 항목에 `tier`·`inclusion`·`byte_size` 가 붙는다.
    `over_limit` 이 참이면 **실행을 만들지 않는다** — 그때 `refs` 의 `inclusion` 은 전부
    인라인이며 기록되지 않는다.
    """

    refs: list[dict[str, Any]]
    limit: int
    instruction_bytes: int
    #: 지시 + 인라인 참조. 예약하는 `context_bytes` 가 이 값이다.
    inline_bytes: int
    #: 지시 + 핵심 참조. 이것이 한도를 넘으면 보류다.
    core_bytes: int
    #: 생략하지 않았다면 전달했을 크기.
    full_bytes: int
    over_limit: bool = False
    omitted: list[dict[str, Any]] = field(default_factory=list)
    #: P4-06. 지식 선택의 결정(`domain.knowledge.Selection.decisions()`). 제공한 항목은
    #: `ref_index` 로 `refs` 의 자리를 가리킨다. 진입 검사·생성·Manifest 가 이 한 목록을 쓴다.
    knowledge: list[dict[str, Any]] = field(default_factory=list)
    #: P4-06. 이 실행을 막는 지식 충돌(적용되는 필수 사이의 열린 충돌).
    knowledge_conflicts: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "limit": self.limit,
            "instruction_bytes": self.instruction_bytes,
            "inline_bytes": self.inline_bytes,
            "core_bytes": self.core_bytes,
            "full_bytes": self.full_bytes,
            "over_limit": self.over_limit,
            "omitted_count": len(self.omitted),
            "omitted_bytes": sum(int(r["byte_size"]) for r in self.omitted),
        }


def plan_inline(
    instruction_bytes: int, refs: Iterable[dict[str, Any]], limit: int
) -> ContextPlan:
    """무엇을 지시문에 넣을지 정한다.

    1. 전부 한도 안이면 **전부 넣는다.** 목록·순서가 P4-04 이전과 같다.
    2. 넘으면 **보조만, 앞(오래된 것)부터** 뺀다. 최근 제안이 지금 논의에 가깝다.
    3. 지시 + 핵심만으로 넘으면 **보류**한다. 핵심을 자르지 않는다.

    `refs` 의 각 항목에는 `role`·`byte_size` 가 있어야 한다.
    """
    if limit <= 0:
        raise ValueError("inline limit must be positive")
    planned: list[dict[str, Any]] = []
    for ref in refs:
        item = dict(ref)
        item["tier"] = tier_for(item["role"]).value
        item["byte_size"] = int(item["byte_size"])
        item["inclusion"] = ContextInclusion.INLINE.value
        planned.append(item)

    full = instruction_bytes + sum(r["byte_size"] for r in planned)
    core = instruction_bytes + sum(
        r["byte_size"] for r in planned if r["tier"] == ContextTier.CORE.value
    )
    plan = ContextPlan(
        refs=planned,
        limit=limit,
        instruction_bytes=instruction_bytes,
        inline_bytes=full,
        core_bytes=core,
        full_bytes=full,
    )
    if full <= limit:
        return plan
    if core > limit:
        plan.over_limit = True
        return plan

    total = full
    for item in planned:
        if total <= limit:
            break
        if item["tier"] != ContextTier.SUPPORTING.value:
            continue
        item["inclusion"] = ContextInclusion.OMITTED_SIZE_LIMIT.value
        total -= item["byte_size"]
        plan.omitted.append(item)
    plan.inline_bytes = total
    return plan


# ============================================================ 영수증


def effective_tier(stored: str | None, role: str) -> str:
    """참조 행의 등급. P4-04 이전 행(NULL)은 역할에서 도출한다 — 기록된 적은 없다."""
    return stored if stored else tier_for(role).value


def effective_inclusion(stored: str | None) -> str:
    """P4-04 이전 행(NULL)은 **전부 인라인이었다.** 그때는 생략하는 경로가 없었다."""
    return stored if stored else ContextInclusion.INLINE.value


def check_receipt(
    refs: list[dict[str, Any]], items: list[dict[str, Any]]
) -> list[str]:
    """Runner 가 보낸 영수증이 이 실행의 계획과 맞는가. 문제 목록을 돌려준다.

    - 순번은 지시(0)와 고정 참조의 순번을 **빠짐없이 한 번씩** 가져야 한다. 빠진
      참조는 "안 읽었다"도 "읽었다"도 아니게 된다.
    - **인라인으로 정한 참조를 `omitted` 로 주장하지 못한다.** Runner 가 핵심을 생략으로
      돌리면 보류해야 할 실행이 부분 문맥으로 돈다.
    - 생략으로 정한 참조는 `omitted` 여야 한다. 읽었다고 적으면 계획과 다른 입력이다.
    """
    problems: list[str] = []
    by_seq = {int(r["seq"]): r for r in refs}
    seen: set[int] = set()
    for item in items:
        seq = int(item["seq"])
        if seq in seen:
            problems.append(f"seq {seq} reported twice")
            continue
        seen.add(seq)
        status = item["status"]
        try:
            ContextReceiptStatus(status)
        except ValueError:
            problems.append(f"seq {seq}: unknown status {status!r}")
            continue
        if seq == INSTRUCTION_SEQ:
            if status == ContextReceiptStatus.OMITTED.value:
                problems.append("the instruction cannot be omitted")
            continue
        ref = by_seq.get(seq)
        if ref is None:
            problems.append(f"seq {seq} is not a context reference of this run")
            continue
        if item.get("role") not in (None, ref["role"]):
            problems.append(f"seq {seq}: role {item.get('role')!r} is not {ref['role']!r}")
        inclusion = effective_inclusion(ref.get("inclusion"))
        if status == ContextReceiptStatus.OMITTED.value:
            if inclusion != ContextInclusion.OMITTED_SIZE_LIMIT.value:
                problems.append(f"seq {seq} was planned inline; it cannot be reported omitted")
        elif inclusion == ContextInclusion.OMITTED_SIZE_LIMIT.value:
            problems.append(f"seq {seq} was planned omitted; it cannot be reported {status}")
    expected = {INSTRUCTION_SEQ, *by_seq}
    missing = sorted(expected - seen)
    if missing:
        problems.append(f"sequences not reported: {missing}")
    return problems


def context_state(
    refs: list[dict[str, Any]], receipt: list[dict[str, Any]]
) -> RunContextState:
    """한 실행의 문맥 상태. 영수증이 없으면 `NOT_REPORTED` 다 — 계획을 읽음으로 적지 않는다."""
    if not receipt:
        return RunContextState.NOT_REPORTED
    tiers = {int(r["seq"]): effective_tier(r.get("tier"), r["role"]) for r in refs}
    partial = False
    for item in receipt:
        seq = int(item["seq"])
        status = item["status"]
        core = seq == INSTRUCTION_SEQ or tiers.get(seq) != ContextTier.SUPPORTING.value
        if status in UNREAD_STATUSES:
            if core:
                return RunContextState.BLOCKED
            partial = True
        elif status == ContextReceiptStatus.OMITTED.value:
            partial = True
    return RunContextState.PARTIAL if partial else RunContextState.COMPLETE


def core_unreadable(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """실행을 멈춰야 하는 항목들 — 읽지 못한 지시 또는 핵심 참조."""
    return [
        item
        for item in items
        if item["status"] in UNREAD_STATUSES
        and (
            int(item["seq"]) == INSTRUCTION_SEQ
            or item.get("tier", ContextTier.CORE.value) != ContextTier.SUPPORTING.value
        )
    ]


# ============================================================ 최신성


def drift(
    pinned: Iterable[dict[str, Any]],
    current: Iterable[dict[str, Any]],
    own: Iterable[tuple[str, int]] = (),
) -> list[dict[str, Any]]:
    """고정한 뒤 **새로 생긴** 입력 — 그 실행이 보지 못한 것.

    `current − pinned − own`. **추가만 본다.** 실행이 피드백을 반영해 해결하면 그
    피드백이 지금 구성에서 빠지는 것이 정상이고, 그것을 "달라졌다"로 적으면 모든
    작성 실행이 stale 로 보인다. 자기 산출물(그 실행이 쓴 의도·준비·응답)도 뺀다.
    """
    seen = {(r["artifact_id"], int(r["revision"])) for r in pinned}
    mine = {(a, int(r)) for a, r in own}
    out: list[dict[str, Any]] = []
    for ref in current:
        key = (ref["artifact_id"], int(ref["revision"]))
        if key in seen or key in mine:
            continue
        seen.add(key)
        out.append(
            {"role": ref["role"], "artifact_id": ref["artifact_id"], "revision": key[1]}
        )
    return out


#: 최신성 기록에 참조를 몇 개까지 적는가. **수는 언제나 전부 센다** — 목록이 잘렸다는
#: 사실은 `added_count` 와 목록 길이의 차이로 드러난다. 참조 id 목록이며 본문이 아니다.
FRESHNESS_LIST_CAP = 50


def freshness(added: list[dict[str, Any]], measured_at: str, basis: str) -> dict[str, Any]:
    """최신성 기록. `basis` 는 `at_result`(결과 보고 시점) 또는 `live`(진행 중, 조회 시점)."""
    return {
        "state": "drifted" if added else "current",
        "added_count": len(added),
        "added": added[:FRESHNESS_LIST_CAP],
        "measured_at": measured_at,
        "basis": basis,
    }
