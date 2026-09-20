"""시험 공통 설비.

각 시험은 자기만의 임시 데이터 경로를 쓴다. 개발용 `var/` 를 건드리지 않는다.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from controller.app import create_app  # noqa: E402
from controller.config import ControllerConfig  # noqa: E402
from runner.agent import RunnerAgent  # noqa: E402
from runner.client import ControllerClient  # noqa: E402
from runner.config import RunnerConfig  # noqa: E402

RUNNER_ID = "runner-test-1"


@dataclass
class Harness:
    """제어부(TestClient)와 Runner를 한 프로세스에서 연결한 시험 환경."""

    client: TestClient
    agent: RunnerAgent
    controller_config: ControllerConfig
    runner_config: RunnerConfig

    # ------------------------------------------------------------ 준비 도우미

    def create_project(self, name: str = "demo") -> dict[str, Any]:
        response = self.client.post(
            "/api/projects",
            json={"name": name, "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        )
        assert response.status_code == 201, response.text
        return response.json()

    def create_case(self, project_id: str, title: str = "첫 Case") -> dict[str, Any]:
        response = self.client.post(
            f"/api/projects/{project_id}/cases", json={"title": title, "kind": "feature"}
        )
        assert response.status_code == 201, response.text
        return response.json()

    def submit_artifact(
        self, case_id: str, content: str, kind: str = "instruction", summary: str = "지시 원문"
    ) -> dict[str, Any]:
        """원문을 접수하고 Runner가 영속 저장할 때까지 진행한다.

        반환값은 저장 완료된 artifact 참조다.
        """
        response = self.client.post(
            f"/api/cases/{case_id}/artifacts",
            json={
                "kind": kind,
                "content": content,
                "summary": summary,
                "target_runner_id": RUNNER_ID,
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert accepted["availability"] == "pending"
        self.agent.persist_pending_intakes()
        intake = self.client.get(f"/api/intakes/{accepted['intake_id']}").json()
        assert intake["state"] == "stored", intake
        return accepted

    def create_run(self, case_id: str, artifact_id: str, run_id: str) -> dict[str, Any]:
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={"run_id": run_id, "instruction_artifact_id": artifact_id},
        )
        # 201 = 새로 만듦, 200 = 같은 run_id 의 재전송(만들지 않음)
        assert response.status_code in (200, 201), response.text
        return response.json()

    def effect_count(self, case_id: str) -> int:
        return self.agent.executor.count_effects(case_id)


@pytest.fixture
def harness(tmp_path: Path):
    controller_config = ControllerConfig(data_root=tmp_path / "controller", web_dist=None)
    app = create_app(controller_config)
    with TestClient(app) as client:
        runner_config = RunnerConfig(
            runner_id=RUNNER_ID,
            controller_url="http://testserver",
            data_root=tmp_path / "runner",
            host_name="test-host",
        )
        agent = RunnerAgent(runner_config, ControllerClient("http://testserver", client=client))
        agent.register()
        yield Harness(client, agent, controller_config, runner_config)
