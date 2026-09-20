"""OpenCode V2 어댑터 — 문서 기반 골격.

이 모듈은 **실행하지 않고 만든 계약**이다(`contract.md` 참조). OpenCode는 이 PC에 설치되어
있지 않으며, 여기의 어떤 매핑도 실제 응답으로 확인하지 않았다. 목적은 두 가지다.

1. 공통 어댑터 인터페이스에서 OpenCode 자리를 비워 두되, 무엇이 비었는지 코드로 드러내기
2. 설치 후 실물 스키마가 생기면 이 파일의 매핑만 바꿔 끼울 수 있게 하기

규칙은 Codex·Claude 어댑터와 같다. **모르는 것은 추정으로 채우지 않는다.**
"""

from __future__ import annotations

import json
from pathlib import Path

# 공식 V2 문서에서 이름을 실제로 확인한 이벤트만 매핑한다.
# 근거: https://opencode.ai/v2/docs/api
CONFIRMED_EVENT_MAP = {
    "shell.started": ["tool_call_started"],
    "shell.ended": ["tool_call_finished"],
    "location.shutdown": [],  # 알고 있으나 호출 경계 의미가 없다
}

# 아직 이름을 확인하지 못해 비워 둔 정규화 종류. contract.md 4절과 같은 목록이어야 한다.
UNRESOLVED_EVENT_KINDS = (
    "session_identified",
    "assistant_message",
    "permission_requested",
    "permission_decided",
    "usage_reported",
    "run_finished",
)

# 추상 권한 -> OpenCode permissions 규칙. 근거: https://opencode.ai/v2/docs/permissions
PERMISSION_RULES = {
    "read_only": [
        {"action": "read", "resource": "**", "effect": "allow"},
        {"action": "glob", "resource": "**", "effect": "allow"},
        {"action": "grep", "resource": "**", "effect": "allow"},
        {"action": "edit", "resource": "**", "effect": "deny"},
        {"action": "shell", "resource": "**", "effect": "deny"},
        {"action": "external_directory", "resource": "**", "effect": "deny"},
    ],
    "workspace_write": [
        {"action": "read", "resource": "**", "effect": "allow"},
        {"action": "glob", "resource": "**", "effect": "allow"},
        {"action": "grep", "resource": "**", "effect": "allow"},
        {"action": "edit", "resource": "**", "effect": "allow"},
        {"action": "shell", "resource": "**", "effect": "allow"},
        {"action": "external_directory", "resource": "**", "effect": "deny"},
    ],
}

# 클라이언트가 보낼 수 있는 권한 응답. 근거: https://opencode.ai/v2/docs/permissions
# `always` 는 프로젝트에 패턴을 저장하고, `reject` 는 그 세션의 **모든** 대기 요청을 거부한다.
# 둘 다 "이번 호출 하나만"이라는 의미가 아니므로 어댑터에서 사용을 금지한다.
PERMISSION_REPLIES = {"once", "always", "reject"}
ALLOWED_REPLIES = {"once"}


class UnsupportedCapability(Exception):
    """확인되지 않은 능력을 쓰려 할 때 올린다. 조용히 대체하지 않는다."""


def build_permission_rules(permission: str) -> list[dict]:
    if permission not in PERMISSION_RULES:
        raise UnsupportedCapability(
            f"매핑 없음: permission={permission}. 권한을 임의로 확대하지 않고 중단한다."
        )
    return [dict(rule) for rule in PERMISSION_RULES[permission]]


def choose_permission_reply(reply: str) -> str:
    if reply not in PERMISSION_REPLIES:
        raise UnsupportedCapability(f"문서에 없는 응답 값: {reply}")
    if reply not in ALLOWED_REPLIES:
        raise UnsupportedCapability(
            f"'{reply}' 는 단일 호출 승인이 아니다. always 는 프로젝트에 패턴을 저장하고 "
            "reject 는 세션의 모든 대기 요청을 거부한다. 어댑터는 once 만 쓴다."
        )
    return reply


def normalize_events(lines: list[str]) -> tuple[list[dict], list[str]]:
    """이벤트 줄을 정규화한다. 확인하지 못한 종류는 unmapped 로 남긴다."""
    events: list[dict] = []
    unmapped: list[str] = []
    seq = 0
    for raw in lines:
        raw = raw.strip()
        if not raw or not raw.startswith("{"):
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            unmapped.append(raw[:200])
            continue
        if "_source" in obj and "type" not in obj:
            continue  # fixture 머리말 줄
        native = obj.get("type", "")
        kinds = CONFIRMED_EVENT_MAP.get(native)
        if kinds is None:
            unmapped.append(native)
            continue
        for kind in kinds:
            seq += 1
            events.append({"seq": seq, "kind": kind, "native_type": native})
    return events, unmapped


def capability_states() -> dict[str, str]:
    """이 어댑터가 주장할 수 있는 능력 상태.

    실행으로 확인한 것이 하나도 없으므로 **`verified` 가 나와서는 안 된다.**
    계약 시험이 이 사실을 검사한다.
    """
    return {
        "install_launch": "unsupported",  # 이 PC에 설치 흔적 없음(P1-01 3절)
        "noninteractive_run": "doc_only",
        "structured_events": "doc_only",
        "tool_boundary_observed": "doc_only",
        "session_identity": "doc_only",
        "session_resume": "doc_only",
        "permission_scope": "doc_only",
        "residual_activity_query": "doc_only",
        "version_query": "doc_only",
        "next_call_blockable": "unknown",
        "hook_failure_behavior": "unknown",
        "usage_reported": "unknown",
        "structured_output_schema": "unknown",
        "reconnect_reconciled": "doc_only",
    }


def load_fixture(name: str) -> dict | list[str]:
    path = Path(__file__).parent / "fixtures" / name
    if path.suffix == ".jsonl":
        return path.read_text(encoding="utf-8").splitlines()
    return json.loads(path.read_text(encoding="utf-8"))
