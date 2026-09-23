"""P2-01 최소 실행기.

**이것은 코딩 CLI 어댑터가 아니다.** 코딩 CLI 연결은 P2-03에서
p1-environment-contract.md 6~8절의 공통 계약을 근거로 붙인다. 여기서는 골격이
한 줄로 연결되는지 확인하기 위한 가장 작은 실행기만 둔다.

다만 **결과와 이벤트는 같은 계약을 쓴다.** 그래야 P2-03에서 실행기를 바꿔도
제어부가 달라지지 않는다(NFR-07).

실행할 때마다 `effects/<case_id>.log` 에 한 줄을 덧붙인다. 이 줄 수가
"실제로 몇 번 실행했는가"의 관측 가능한 증거이고, 중복 실행 판정의 근거다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.models import EventType, RunOutcome

TOOL_ID = "local-echo"
TOOL_VERSION = "p2-01"
NATIVE_PREFIX = "p2-01-local-echo"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


@dataclass
class ExecutionOutput:
    events: list[dict[str, Any]]
    output_body: bytes
    outcome: RunOutcome
    exit_code: int
    usage: Any
    residual_activity: str
    #: UI-02. 잔류 값의 근거. 이 실행기는 Runner 프로세스 안에서 돈다.
    residual_basis: str | None = None


class LocalEchoExecutor:
    """지시 원문을 읽고 요약 한 편을 만들어 돌려주는 최소 실행기."""

    def __init__(self, effects_dir: Path) -> None:
        self.effects_dir = effects_dir
        self.effects_dir.mkdir(parents=True, exist_ok=True)

    def record_effect(self, case_id: str, run_id: str) -> Path:
        """실제 실행 1회를 파일에 남긴다. 실행되지 않으면 이 줄도 없다."""
        safe = case_id.replace("/", "_").replace("\\", "_")
        path = self.effects_dir / f"{safe}.log"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_now()}\t{run_id}\n")
            fh.flush()
            os.fsync(fh.fileno())
        return path

    def count_effects(self, case_id: str) -> int:
        safe = case_id.replace("/", "_").replace("\\", "_")
        path = self.effects_dir / f"{safe}.log"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def execute(self, run_id: str, case_id: str, instruction: bytes) -> ExecutionOutput:
        seq = 0

        def event(event_type: EventType, native_suffix: str) -> dict[str, Any]:
            nonlocal seq
            seq += 1
            return {
                "seq": seq,
                "ts": _now(),
                "type": event_type.value,
                "native_type": f"{NATIVE_PREFIX}.{native_suffix}",
                "raw_ref": None,
            }

        events = [event(EventType.RUN_STARTED, "start")]
        events.append(event(EventType.TOOL_CALL_STARTED, "read_instruction"))

        self.record_effect(case_id, run_id)
        text = instruction.decode("utf-8", errors="replace")
        line_count = len(text.splitlines())
        summary = (
            f"run_id={run_id}\n"
            f"case_id={case_id}\n"
            f"instruction_bytes={len(instruction)}\n"
            f"instruction_lines={line_count}\n"
            f"executed_at={_now()}\n"
            f"executor={TOOL_ID}/{TOOL_VERSION} (not a coding CLI)\n"
        )

        events.append(event(EventType.TOOL_CALL_FINISHED, "read_instruction"))
        events.append(event(EventType.ASSISTANT_MESSAGE, "summary"))
        events.append(event(EventType.RUN_FINISHED, "finish"))

        return ExecutionOutput(
            events=events,
            output_body=summary.encode("utf-8"),
            # 종료 코드만으로 완료를 선언하지 않는다. 여기서는 출력물까지
            # 실제로 만들었음을 보고 completed 로 판정한다(FR-28, P1 계약 7.2).
            outcome=RunOutcome.COMPLETED,
            exit_code=0,
            # 이 실행기는 사용량을 제공하지 않는다. 0으로 표시하지 않는다.
            usage="not_reported",
            # 자식 프로세스를 만들지 않으므로 잔여 활동 없음을 확인할 수 있다.
            residual_activity="none",
            residual_basis="in_process",
        )
