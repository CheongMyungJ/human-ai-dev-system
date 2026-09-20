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

    # ------------------------------------------------- 원문 열람·의도 구조

    def pending_read_requests(self, runner_id: str) -> list[dict]:
        return self._get(f"/api/runner/{runner_id}/read-requests")

    def send_read_content(
        self, request_id: str, runner_id: str, content_b64: str, content_hash: str
    ) -> Any:
        return self._post(
            f"/api/runner/read-requests/{request_id}/content",
            {
                "runner_id": runner_id,
                "content_b64": content_b64,
                "content_hash": content_hash,
            },
        )

    def send_intent_structure(self, payload: dict) -> Any:
        return self._post("/api/runner/intent-structure", payload)

    # ----------------------------------------------------------- P2-03

    def create_intent_version(self, payload: dict) -> Any:
        """AI가 작성한 초안을 의도 버전으로 만든다.

        P2-02의 경로와 **방향이 반대다.** 거기서는 브라우저가 항목을 보내면
        제어부가 문서를 묶어 내려보냈다. 여기서는 초안이 이 Runner에서 태어나므로
        본문은 이미 여기 있고 제어부로는 참조만 올라간다.
        """
        return self._post("/api/runner/intent-versions", payload)

    def send_gate_review(self, payload: dict) -> Any:
        """AI 의미 검토가 찾은 것을 올린다. **판정은 제어부가 다시 계산한다.**"""
        return self._post("/api/runner/gate-reviews", payload)

    # ----------------------------------------------------------- P3-01

    def create_preparation_artifact(self, payload: dict) -> Any:
        """AI가 작성한 설계·계획을 준비 산출물로 등록한다.

        의도 초안 등록과 같은 방향이다 — 원문은 이미 이 Runner에 있고 제어부로는
        참조와 요약만 올라간다. 어느 의도 버전 위에 세운 것인지는 **제어부가 정한다.**
        """
        return self._post("/api/runner/preparation-artifacts", payload)

    def send_preparation_structure(self, payload: dict) -> Any:
        return self._post("/api/runner/preparation-structure", payload)
