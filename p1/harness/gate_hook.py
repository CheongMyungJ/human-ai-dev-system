"""P1-03 도구 호출 경계 gate hook.

CLI가 다음 도구를 실행하기 **전에** 호출되어, 연결 상태 파일을 보고 허용/거부를 정한다.
`execution-workspace-review.md` 4절의 "단절 감지 → 다음 호출을 시작하지 않음"을 실제 제어
지점에서 구현할 수 있는지 확인하기 위한 P1 실증용이다. 제품 코드가 아니다.

사용법(두 CLI가 각자의 설정에서 이 명령을 부른다):
    python gate_hook.py <connection_state_file> <decision_log.jsonl>

동작:
- 연결 상태 파일의 내용이 `connected` 가 아니면 거부 결정을 stdout JSON으로 낸다.
- 모든 호출을 시각·도구명·상태·판정과 함께 로그에 남긴다. 허용도 남긴다.
- 상태 파일을 읽지 못하면 **거부**한다. 확인할 수 없는 상태를 허용으로 바꾸지 않는다.
"""

from __future__ import annotations

import json
import os
import sys
import time

DENY_REASON = "제어 서버 연결이 끊어졌습니다. 재연결 후 다음 도구 호출을 재개합니다."


def read_state(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError as exc:
        return f"unreadable:{exc.__class__.__name__}"


def log(path: str, record: dict) -> None:
    try:
        with open(path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass  # 로그 실패가 판정을 바꾸지 않는다


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: gate_hook.py <state_file> <log_file>", file=sys.stderr)
        return 1
    state_file, log_file = sys.argv[1], sys.argv[2]

    raw = sys.stdin.read()
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except json.JSONDecodeError:
        payload = {}

    state = read_state(state_file)
    allow = state == "connected"

    log(
        log_file,
        {
            "ts": time.time(),
            "ts_iso": time.strftime("%H:%M:%S", time.localtime()) ,
            "pid": os.getpid(),
            "hook_event": payload.get("hook_event_name") or payload.get("hookEventName"),
            "tool_name": payload.get("tool_name") or payload.get("toolName"),
            "connection_state": state,
            "decision": "allow" if allow else "deny",
            "payload_keys": sorted(payload.keys()),
        },
    )

    if allow:
        return 0

    print(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "PreToolUse",
                    "permissionDecision": "deny",
                    "permissionDecisionReason": DENY_REASON,
                }
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
