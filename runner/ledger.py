"""실행 원장 — 중복 실행 방지의 두 번째 층.

제어부의 `run_id` 멱등성만으로는 부족하다. 실제로 막아야 하는 상황은 이것이다.

    Runner가 실행을 끝냈다 → 결과 보고가 유실됐다 → 제어부는 아직 미완료로 본다
    → 같은 run_id 를 다시 배정한다 → **Runner가 다시 실행하면 중복이다**

그래서 Runner는 실행 **전에** 원장에 착수를 적고, 끝나면 결과를 적는다.
같은 run_id 가 다시 오면 executor를 부르지 않고 저장된 결과를 다시 보고한다.
착수만 적히고 결과가 없는 경우(실행 중 강제 종료)는 `started` 로 남으며,
이는 "성공"도 "미실행"도 아니다. 결과를 모르는 상태로 표시한다.

P1에서 P2-01로 이월한 '지연 이벤트·응답 유실에서 중복 호출하지 않음' 항목이 여기에 걸린다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_STARTED = "started"
STATE_FINISHED = "finished"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


class ExecutionLedger:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, run_id: str) -> Path:
        safe = run_id.replace("/", "_").replace("\\", "_")
        return self.root / f"{safe}.json"

    def read(self, run_id: str) -> dict[str, Any] | None:
        path = self._path(run_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _write(self, run_id: str, record: dict[str, Any]) -> None:
        path = self._path(run_id)
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(record, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)

    def claim(self, run_id: str, generation: int) -> tuple[bool, dict[str, Any] | None]:
        """이 run_id 를 실행해도 되는지 판단한다.

        반환: (실행해야 하면 True, 기존 기록)
        기존 기록이 있으면 절대 다시 실행하지 않는다.
        """
        existing = self.read(run_id)
        if existing is not None:
            return False, existing
        self._write(
            run_id,
            {
                "run_id": run_id,
                "generation": generation,
                "state": STATE_STARTED,
                "started_at": _now(),
            },
        )
        return True, None

    def finish(self, run_id: str, result: dict[str, Any]) -> dict[str, Any]:
        record = self.read(run_id) or {"run_id": run_id}
        record.update(
            {
                "state": STATE_FINISHED,
                "finished_at": _now(),
                "result": result,
            }
        )
        self._write(run_id, record)
        return record
