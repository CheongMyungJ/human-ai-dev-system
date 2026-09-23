"""시험용 가짜 codex CLI (UI-02).

**AI 를 부르지 않는다.** 실제 CLI 의 자리(PATH 의 `codex.cmd`)에 놓여 제품 어댑터
(`runner.cli_adapter.CliExecutor`)가 그대로 부르게 하고, 실제 프로세스 트리를 만든다 —
중단·잔류 확인은 가짜 실행기로는 시험할 수 없는 **OS 의 사실**이기 때문이다. 출력은 codex
`exec --json` 의 줄 형식(P1-02 관측)을 따른다.

지시문(stdin)에 든 표지로 동작을 고른다.

    HADS_FAKE_SLEEP=<초>     손자 프로세스를 하나 만들고 둘 다 그만큼 잔다(긴 실행)
    HADS_FAKE_LEAVE_CHILD    손자 프로세스를 남겨 두고 바로 끝낸다(정상 종료 뒤 잔류)
    HADS_FAKE_WRITE=<이름>   작업 디렉터리에 그 파일을 쓴다(부분 변경)
    HADS_FAKE_WORK=<Profile> (UI-03) 준비 단계 논의 응답이면 그 Profile 의 업무 요청으로 해석한다.
                             없으면 논의로 해석한다. 해석 규칙을 받지 않은 응답에는 블록을 붙이지 않는다

손자·자식의 pid 는 환경 변수 `HADS_FAKE_PIDS` 가 가리키는 디렉터리에 파일로 남긴다 —
시험이 OS 에서 그 프로세스가 정말 끝났는지 **독립적으로** 본다.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def note_pid(kind: str, pid: int) -> None:
    root = os.environ.get("HADS_FAKE_PIDS")
    if root:
        Path(root).mkdir(parents=True, exist_ok=True)
        (Path(root) / f"{kind}-{pid}.pid").write_text(str(pid), encoding="utf-8")


def main() -> int:
    if "--version" in sys.argv:
        print("codex-cli 0.0.0-fake")
        return 0
    prompt = sys.stdin.buffer.read().decode("utf-8", errors="replace")
    # 실제 codex 는 UTF-8 로 낸다. 파이프에 쓰는 파이썬의 기본(콘솔 코드 페이지)을 따르지 않는다.
    sys.stdout.reconfigure(encoding="utf-8")
    note_pid("cli", os.getpid())
    emit({"type": "thread.started", "thread_id": f"fake-thread-{os.getpid()}"})
    emit({"type": "turn.started"})

    written = re.search(r"HADS_FAKE_WRITE=([A-Za-z0-9_.-]+)", prompt)
    if written:
        Path(written.group(1)).write_text("partial change\n", encoding="utf-8")

    sleep = re.search(r"HADS_FAKE_SLEEP=(\d+)", prompt)
    if sleep:
        seconds = int(sleep.group(1))
        child = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({seconds})"])
        note_pid("grandchild", child.pid)
        emit(
            {
                "type": "item.started",
                "item": {"id": "item_1", "type": "command_execution", "command": "sleep"},
            }
        )
        time.sleep(seconds)
        child.wait()
        emit(
            {
                "type": "item.completed",
                "item": {"id": "item_1", "type": "command_execution", "command": "sleep"},
            }
        )

    if "HADS_FAKE_LEAVE_CHILD" in prompt:
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
        note_pid("leftover", child.pid)

    text = "가짜 응답입니다. 변경한 것은 없습니다."
    if "hads-interpretation" in prompt:
        # UI-03. 해석 규칙을 받은(준비 단계) 논의 응답이다. 실제 AI 처럼 답 글 끝에 블록을 둔다.
        work = re.search(r"HADS_FAKE_WORK=([a-z_]+)", prompt.split("hads-interpretation")[-1])
        verdict = (
            {"kind": "work_request", "profile": work.group(1)} if work else {"kind": "discussion"}
        )
        text += "\n\n```hads-interpretation\n" + json.dumps(verdict) + "\n```"
    emit(
        {
            "type": "item.completed",
            "item": {"id": "item_2", "type": "agent_message", "text": text},
        }
    )
    emit(
        {
            "type": "turn.completed",
            "usage": {"input_tokens": 11, "cached_input_tokens": 0, "output_tokens": 7},
        }
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
