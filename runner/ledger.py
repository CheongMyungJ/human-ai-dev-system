"""실행 원장 — 중복 실행 방지의 두 번째 층.

제어부의 `run_id` 멱등성만으로는 부족하다. 실제로 막아야 하는 상황은 이것이다.

    Runner가 실행을 끝냈다 → 결과 보고가 유실됐다 → 제어부는 아직 미완료로 본다
    → 같은 run_id 를 다시 배정한다 → **Runner가 다시 실행하면 중복이다**

그래서 Runner는 실행 **전에** 원장에 착수를 적고, 끝나면 결과를 적는다.
같은 run_id 가 다시 오면 executor를 부르지 않고 저장된 결과를 다시 보고한다.
착수만 적히고 결과가 없는 경우(실행 중 강제 종료)는 `started` 로 남으며,
이는 "성공"도 "미실행"도 아니다. 결과를 모르는 상태로 표시한다.

P1에서 P2-01로 이월한 '지연 이벤트·응답 유실에서 중복 호출하지 않음' 항목이 여기에 걸린다.

**UI-02: 원장 v2.** 착수 기록에 판(`ledger_version = 2`)과 그 실행을 맡은 Runner 프로세스의
정체(pid + 생성 시각)를 적고, CLI 를 **재개하기 전에** 시작 기록(`launch`: job 이름·루트
pid·생성 시각, 또는 `in_process`)을 따로 적는다. 그래서 재시작 뒤 "착수했는데 결과가 없다"를
둘로 나눌 수 있다.

    시작 기록 없음   CLI 가 재개되지 않았다 — 시작하지 않은 실행이다(소비 0)
    시작 기록 있음   CLI 가 돌았을 수 있다 — 결과는 불명이고, 잔류는 시작 기록으로 확인한다

v1 기록(판 표시 없음)은 이 구분이 없으므로 예전처럼 결과 불명으로만 다룬다.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_STARTED = "started"
STATE_FINISHED = "finished"

#: 이 판부터 시작 기록(`launch`)이 착수와 따로 있다(UI-02).
LEDGER_VERSION = 2


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

    def claim(
        self,
        run_id: str,
        generation: int,
        runner_process: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any] | None]:
        """이 run_id 를 실행해도 되는지 판단한다.

        반환: (실행해야 하면 True, 기존 기록)
        기존 기록이 있으면 절대 다시 실행하지 않는다.

        `runner_process` 는 이 실행을 맡은 Runner 프로세스의 정체다(UI-02). 재시작 대조가
        "그 프로세스가 아직 살아 있는가"를 볼 때 쓴다 — 살아 있으면 남의 실행을 끝내지 않는다.
        """
        existing = self.read(run_id)
        if existing is not None:
            return False, existing
        record: dict[str, Any] = {
            "run_id": run_id,
            "generation": generation,
            "state": STATE_STARTED,
            "started_at": _now(),
            "ledger_version": LEDGER_VERSION,
        }
        if runner_process is not None:
            record["runner_process"] = runner_process
        self._write(run_id, record)
        return True, None

    def _update(self, run_id: str, **fields: Any) -> dict[str, Any]:
        record = self.read(run_id)
        if record is None:
            raise KeyError(f"ledger has no claim for {run_id}")
        record.update(fields)
        self._write(run_id, record)
        return record

    def record_launch(self, run_id: str, launch: dict[str, Any]) -> dict[str, Any]:
        """CLI 를 **재개하기 전에** 시작 기록을 남긴다(fsync). 이 기록이 없으면 CLI 는 돌지 않았다."""
        return self._update(run_id, launch={**launch, "recorded_at": _now()})

    def record_workspace_before(self, run_id: str, before: dict[str, Any]) -> dict[str, Any]:
        """쓰기 실행의 **실행 전 작업 트리 관측**. 재시작 대조가 지금 트리와 대조해 이 실행
        이후의 변화를 드러낸다. 경로가 담긴 상태 줄은 이 Runner 에만 남는다(D-43)."""
        return self._update(run_id, workspace_before=before)

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
