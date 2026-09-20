"""코딩 CLI의 원문 이벤트를 공통 계약의 정규화 이벤트로 옮긴다.

분류 규칙은 P1-02에서 **이 PC에서 실제로 관측한** 스키마에서 나왔다
(codex-cli 0.154.0 `exec --json`, Claude Code 2.1.278 `-p --output-format stream-json`).
근거는 [P1-02 실증 결과](../p1/evidence/P1-02-results.md) 4절이고, 같은 규칙이
P1 harness(`p1/harness/run_cli.py`)에도 있다. **그쪽은 실증 도구이고 이쪽이 제품
코드다.** 두 곳이 갈라지면 제품 동작은 이 파일이 정본이며, harness는 P1 결과를
재현하기 위한 기록으로 그대로 둔다.

두 가지를 지킨다.

  분류하지 못한 원문은 **버리지 않고** `unmapped` 로 돌려준다. 매핑이 없다는
  사실도 capability 표에 남길 근거다(p1-environment-contract 7.1절).

  CLI가 주지 않은 값을 추정으로 채우지 않는다. 사용량이 없으면 `not_reported`,
  세션 식별자가 없으면 `None` 이다. 0으로 적지 않는다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from domain.models import EventType


@dataclass
class NormalizedStream:
    """정규화 결과.

    `events` 는 제어부로 올라가고, `derived` 는 결과(RunResult)를 만드는 데 쓴다.
    `final_message` 는 마지막 어시스턴트 메시지 본문이며 **Runner에만 남는다.**
    """

    events: list[dict[str, Any]] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)
    session_ref: str | None = None
    usage: Any = "not_reported"
    permission_decisions: list[dict[str, Any]] = field(default_factory=list)
    final_message: str = ""
    reported_error: bool = False


def classify_codex(obj: dict[str, Any], native: str) -> list[str] | None:
    """Codex 원문 이벤트 → 정규화 종류.

    `None` 은 "모르는 종류"이고 `[]` 는 "알지만 경계 의미가 없음"이다. 둘을 같은
    값으로 두면 미지의 이벤트가 조용히 무시된다.
    """
    item_type = (obj.get("item") or {}).get("type")
    if native == "thread.started":
        return [EventType.SESSION_IDENTIFIED.value]
    if native == "turn.started":
        return [EventType.RUN_STARTED.value]
    if native == "turn.completed":
        return (
            [EventType.USAGE_REPORTED.value, EventType.RUN_FINISHED.value]
            if obj.get("usage")
            else [EventType.RUN_FINISHED.value]
        )
    if native in {"turn.failed", "error"}:
        return [EventType.ERROR.value]
    if native in {"item.started", "item.updated", "item.completed"}:
        if item_type == "command_execution":
            if native == "item.started":
                return [EventType.TOOL_CALL_STARTED.value]
            return [EventType.TOOL_CALL_FINISHED.value] if native == "item.completed" else []
        if item_type == "agent_message":
            return [EventType.ASSISTANT_MESSAGE.value] if native == "item.completed" else []
        if item_type == "error":
            return [EventType.ERROR.value] if native == "item.completed" else []
        if item_type in {"reasoning", "todo_list"}:
            return []
        return None
    return None


def classify_claude(obj: dict[str, Any], native: str) -> list[str] | None:
    """Claude Code 원문 이벤트 → 정규화 종류."""
    if native == "system":
        subtype = obj.get("subtype")
        if subtype == "init":
            return [EventType.SESSION_IDENTIFIED.value]
        if subtype == "permission_denied":
            return [EventType.PERMISSION_DECIDED.value]
        if subtype == "hook_response":
            stdout = obj.get("stdout") or ""
            return [EventType.PERMISSION_DECIDED.value] if '"permissionDecision"' in stdout else []
        if subtype in {"thinking_tokens", "compact_boundary", "hook_started"}:
            return []
        return None
    if native == "assistant":
        content = (obj.get("message") or {}).get("content")
        kinds = [c.get("type") for c in content] if isinstance(content, list) else []
        if "tool_use" in kinds:
            return [EventType.TOOL_CALL_STARTED.value]
        if "text" in kinds:
            return [EventType.ASSISTANT_MESSAGE.value]
        if "thinking" in kinds:
            return []
        return None
    if native == "user":
        return (
            [EventType.TOOL_CALL_FINISHED.value] if obj.get("tool_use_result") is not None else []
        )
    if native == "rate_limit_event":
        return [EventType.USAGE_REPORTED.value]
    if native == "result":
        kinds = [EventType.USAGE_REPORTED.value] if obj.get("usage") else []
        return kinds + (
            [EventType.ERROR.value] if obj.get("is_error") else [EventType.RUN_FINISHED.value]
        )
    return None


def _collect_codex(obj: dict[str, Any], native: str, out: NormalizedStream) -> None:
    if native == "thread.started" and obj.get("thread_id"):
        out.session_ref = obj["thread_id"]
    if native == "turn.completed" and obj.get("usage"):
        out.usage = {"tokens": obj["usage"], "cost_usd": "not_reported"}
    if native in {"turn.failed", "error"}:
        out.reported_error = True
    item = obj.get("item") or {}
    if native == "item.completed" and item.get("type") == "agent_message":
        out.final_message = str(item.get("text") or "")
    if native == "item.completed" and item.get("type") == "error":
        out.reported_error = True


def _collect_claude(obj: dict[str, Any], native: str, out: NormalizedStream) -> None:
    if obj.get("session_id") and not out.session_ref:
        out.session_ref = obj["session_id"]
    if native == "system" and obj.get("subtype") == "permission_denied":
        out.permission_decisions.append(
            {
                "decision": "denied",
                "source": "permission_denied",
                "tool_name": obj.get("tool_name"),
            }
        )
    if native == "system" and obj.get("subtype") == "hook_response":
        stdout = obj.get("stdout") or ""
        if '"permissionDecision"' in stdout:
            try:
                decision = json.loads(stdout)["hookSpecificOutput"]["permissionDecision"]
            except (json.JSONDecodeError, KeyError, TypeError):
                decision = "unparsed"
            out.permission_decisions.append({"decision": decision, "source": "hook_response"})
        elif obj.get("outcome") == "error":
            # P1-03에서 관측한 fail-open. 훅이 실패해도 호출이 진행된다는 사실을 남긴다.
            out.permission_decisions.append(
                {"decision": "hook_failed_not_enforced", "source": "hook_response"}
            )
    if native == "assistant":
        content = (obj.get("message") or {}).get("content")
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            if texts:
                out.final_message = "\n".join(texts)
    if native == "result":
        if obj.get("usage"):
            out.usage = {
                "tokens": obj["usage"],
                "cost_usd": obj.get("total_cost_usd", "not_reported"),
            }
        if obj.get("is_error"):
            out.reported_error = True
        elif obj.get("result"):
            out.final_message = str(obj["result"])


def normalize(tool_id: str, stdout_lines: list[str]) -> NormalizedStream:
    """CLI 표준 출력 줄들을 정규화 이벤트로 바꾼다."""
    out = NormalizedStream()
    seq = 0
    for raw in stdout_lines:
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("{"):
            out.unmapped.append(line[:200])
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            out.unmapped.append(line[:200])
            continue

        native = obj.get("type", "unknown")
        if tool_id == "codex":
            kinds = classify_codex(obj, native)
            _collect_codex(obj, native, out)
        else:
            kinds = classify_claude(obj, native)
            _collect_claude(obj, native, out)

        if kinds is None:
            out.unmapped.append(f"{native}:{obj.get('subtype', '')}".rstrip(":"))
            continue
        for kind in kinds:
            seq += 1
            out.events.append(
                {
                    "seq": seq,
                    "ts": obj.get("timestamp") or "",
                    "type": kind,
                    "native_type": native,
                    "raw_ref": None,
                }
            )
    return out
