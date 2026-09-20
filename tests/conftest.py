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

    # ------------------------------------------------------ P2-02 도우미

    def submit_intent_draft(
        self,
        case_id: str,
        fields: dict[str, Any],
        questions: list[dict[str, Any]] | None = None,
        summary: str = "의도 초안",
        reflects_feedback: list[str] | None = None,
        not_reflected: dict[str, str] | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        """의도 초안을 제출하고(기본으로) Runner가 저장·구조 보고까지 하게 한다.

        `persist=False` 는 "아직 Runner가 저장하지 않은" 상태를 만들기 위한 것이다.
        """
        response = self.client.post(
            f"/api/cases/{case_id}/intent-drafts",
            json={
                "summary": summary,
                "target_runner_id": RUNNER_ID,
                "fields": fields,
                "questions": questions or [],
                "reflects_feedback": reflects_feedback or [],
                "not_reflected": not_reflected or {},
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        if persist:
            self.agent.persist_pending_intakes()
        return accepted

    def submit_feedback(
        self,
        case_id: str,
        intent_version_id: str,
        content: str,
        summary: str = "피드백",
        persist: bool = True,
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/api/cases/{case_id}/feedback",
            json={
                "target_intent_version_id": intent_version_id,
                "content": content,
                "summary": summary,
                "target_runner_id": RUNNER_ID,
            },
        )
        assert response.status_code == 202, response.text
        accepted = response.json()
        if persist:
            self.agent.persist_pending_intakes()
        return accepted

    def read_original(self, artifact_id: str, revision: int = 1, serve: bool = True):
        """원문 열람 한 바퀴. (요청 상태, 본문 또는 None) 을 돌려준다."""
        created = self.client.post(
            f"/api/artifacts/{artifact_id}/{revision}/read-requests", json={}
        )
        assert created.status_code == 201, created.text
        request_id = created.json()["id"]
        if serve:
            self.agent.serve_read_requests()
        response = self.client.get(f"/api/read-requests/{request_id}").json()
        return response["request"], response["content"]

    def read_intent_original(self, intent: dict[str, Any]) -> str:
        """의도 원문을 실제로 받아 본다. 이 전달이 열람 기록을 만든다."""
        _request, content = self.read_original(intent["artifact_id"], intent["artifact_rev"])
        assert content is not None, "원문이 전달되지 않았다"
        return content

    def intent_state(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/intent-state")
        assert response.status_code == 200, response.text
        return response.json()

    def latest_intent(self, case_id: str) -> dict[str, Any]:
        state = self.intent_state(case_id)
        assert state["latest_intent_version"] is not None
        return state["latest_intent_version"]

    def agree(
        self,
        case_id: str,
        intent: dict[str, Any],
        content_hash: str | None = None,
        agree: bool = True,
        statement: str = "이 버전의 의도에 동의합니다.",
    ):
        return self.client.post(
            f"/api/cases/{case_id}/intent-versions/{intent['id']}/agreement",
            json={
                "agree": agree,
                "statement": statement,
                "content_hash": content_hash or intent["content_hash"],
                "actor": "owner",
            },
        )


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
