"""제어부에 연결하는 Runner 쪽 클라이언트.

Runner가 연결을 시작한다. 제어부가 Runner로 접속하지 않는다
(implementation-baseline 2절: PC 수신 포트를 필수로 열지 않는다).

시험이 "결과 보고 유실"을 주입할 수 있도록 메서드를 얇게 유지한다.
"""

from __future__ import annotations

from typing import Any

import httpx


class ControllerClient:
    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(base_url=self.base_url, timeout=30.0)

    def close(self) -> None:
        self._client.close()

    def _post(self, path: str, json: Any = None) -> Any:
        response = self._client.post(path, json=json)
        response.raise_for_status()
        return response.json()

    def _get(self, path: str) -> Any:
        response = self._client.get(path)
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------- 등록·생존

    def register(self, runner_id: str, name: str, host: str, capabilities: list[dict]) -> Any:
        return self._post(
            "/api/runner/register",
            {"runner_id": runner_id, "name": name, "host": host, "capabilities": capabilities},
        )

    def heartbeat(self, runner_id: str) -> Any:
        return self._post(f"/api/runner/{runner_id}/heartbeat")

    # ----------------------------------------------------------------- 원문

    def pending_intakes(self, runner_id: str) -> list[dict]:
        return self._get(f"/api/runner/{runner_id}/intakes")

    def report_stored(self, intake_id: str, runner_id: str, content_hash: str) -> Any:
        return self._post(
            f"/api/runner/intakes/{intake_id}/stored",
            {"runner_id": runner_id, "content_hash": content_hash},
        )

    def register_artifact(self, payload: dict) -> Any:
        return self._post("/api/runner/artifacts", payload)

    # ----------------------------------------------------------------- 실행

    def claim_assignments(self, runner_id: str) -> list[dict]:
        return self._post(f"/api/runner/{runner_id}/assignments")

    def send_events(self, run_id: str, runner_id: str, generation: int, events: list[dict]) -> Any:
        return self._post(
            f"/api/runner/runs/{run_id}/events",
            {"runner_id": runner_id, "generation": generation, "events": events},
        )

    def send_result(self, run_id: str, payload: dict) -> Any:
        return self._post(f"/api/runner/runs/{run_id}/result", payload)
