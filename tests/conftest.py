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
from domain.models import CapabilityState, Permission, RunOutcome  # noqa: E402
from runner.agent import RunnerAgent, local_executor_capabilities  # noqa: E402
from runner.cli_adapter import ExecutionOutput  # noqa: E402
from runner.client import ControllerClient  # noqa: E402
from runner.config import RunnerConfig  # noqa: E402

RUNNER_ID = "runner-test-1"

#: 시험이 쓰는 가짜 코딩 CLI의 식별자.
#:
#: 이름을 `codex` 로 두는 이유는 제어부의 진입 검사·권한 매핑이 도구 이름으로
#: 판단하기 때문이다. **실제 codex 를 부르지는 않는다** — 실행기는 아래 가짜이고,
#: 실제 CLI 실행은 라이브 검증에서만 한다(P1-02가 세운 구분).
FAKE_TOOL_ID = "codex"
FAKE_TOOL_MODE = "exec"

#: 기본 AI 초안 응답. 여섯 항목을 모두 채우고 출처를 구분해 적는다.
FAKE_DRAFT_RESPONSE = """여기 초안입니다.

```json
{
  "fields": {
    "goal": {"text": "로그 파일에서 오류 줄만 뽑는 기능", "origin": "user_requirement"},
    "expected_outcome": {"text": "ERROR 로 시작하는 줄만 출력된다", "origin": "ai_proposal"},
    "scope": {"text": "읽기 전용 조회", "origin": "ai_proposal"},
    "exclusions": {"text": "로그 회전과 보존 정책은 다루지 않는다", "origin": "ai_proposal"},
    "constraints": {"text": "Windows 로컬 파일만", "origin": "observation"},
    "open_questions": {"text": "대소문자 구분 여부가 미정", "origin": "ai_assumption"}
  },
  "questions": []
}
```
"""

#: 기본 AI 검토 응답. 문제를 찾지 못한 경우.
FAKE_REVIEW_CLEAN = '{"findings": []}'


class FakeCliExecutor:
    """시험용 가짜 코딩 CLI 실행기.

    **실제 CLI를 부르지 않는다.** 자동 시험은 결정적이어야 하고, 사용자 계정의
    외부 AI 호출에 의존해서는 안 된다. 실제 CLI 연결의 증거는 라이브 검증에서
    따로 만든다(p2/evidence/P2-03-results.md).

    계약(`execute` 의 인자와 반환값)은 `runner.cli_adapter.CliExecutor` 와 같다.
    그래야 이 자리에 실제 실행기를 넣어도 Runner 코드가 달라지지 않는다.
    """

    def __init__(self, effects_dir: Path) -> None:
        self.effects_dir = Path(effects_dir)
        self.effects_dir.mkdir(parents=True, exist_ok=True)
        self.draft_response = FAKE_DRAFT_RESPONSE
        self.review_response = FAKE_REVIEW_CLEAN
        self.analysis_response = "저장소를 읽고 확인했습니다. 변경한 것은 없습니다."
        self.outcome = RunOutcome.COMPLETED
        #: 세션 식별자를 고정하면 "작성과 검토가 같은 세션"을 만들 수 있다.
        self.fixed_session_ref: str | None = None
        self.calls: list[dict[str, Any]] = []

    def _session_ref(self, run_id: str) -> str:
        return self.fixed_session_ref or f"fake-session-{run_id}"

    def _final_message(self, prompt: str) -> str:
        from runner import prompts as prompt_templates

        if prompt.startswith(prompt_templates.INTENT_AUTHORING_PROMPT[:40]):
            return self.draft_response
        if prompt.startswith(prompt_templates.GATE_REVIEW_PROMPT[:40]):
            return self.review_response
        return self.analysis_response

    def count_effects(self, case_id: str) -> int:
        safe = case_id.replace("/", "_").replace("\\", "_")
        path = self.effects_dir / f"{safe}.log"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def execute(
        self,
        run_id: str,
        case_id: str,
        prompt: str,
        tool_id: str,
        mode: str,
        permission: Permission,
        workspace: Path,
        raw_dir: Path | None = None,
    ) -> ExecutionOutput:
        # 실제 실행기와 같이 부수효과를 한 줄 남긴다. 중복 실행 판정의 근거다.
        safe = case_id.replace("/", "_").replace("\\", "_")
        with open(self.effects_dir / f"{safe}.log", "a", encoding="utf-8") as fh:
            fh.write(f"fake\t{run_id}\n")
        self.calls.append(
            {
                "run_id": run_id,
                "tool_id": tool_id,
                "mode": mode,
                "permission": permission.value,
                "workspace": str(workspace),
                "prompt": prompt,
            }
        )
        final = self._final_message(prompt)
        events = [
            {"seq": 1, "ts": "", "type": "run_started", "native_type": "fake.start", "raw_ref": None},
            {
                "seq": 2,
                "ts": "",
                "type": "session_identified",
                "native_type": "fake.session",
                "raw_ref": None,
            },
            {
                "seq": 3,
                "ts": "",
                "type": "assistant_message",
                "native_type": "fake.message",
                "raw_ref": None,
            },
            {"seq": 4, "ts": "", "type": "run_finished", "native_type": "fake.finish", "raw_ref": None},
        ]
        for event in events:
            event["ts"] = "2026-09-20T00:00:00.000000+00:00"
        return ExecutionOutput(
            events=events,
            output_body=f"fake run {run_id}\n{final}".encode("utf-8"),
            outcome=self.outcome,
            exit_code=0,
            usage="not_reported",
            residual_activity="unknown",
            session_ref=self._session_ref(run_id),
            observed_tool_version=f"{tool_id}/fake-for-tests",
            final_message=final,
        )


def fake_capabilities() -> list[dict[str, Any]]:
    """가짜 CLI의 능력 보고.

    실제 설치 여부를 조회하지 않는다. 시험 결과가 이 PC에 무엇이 깔려 있는지에
    좌우되면 안 되기 때문이다. `source` 에 가짜임을 적어 실측과 섞이지 않게 한다.
    """
    source = "시험용 가짜 CLI (실제 실행 아님)"
    rows = local_executor_capabilities()
    for capability, state in (
        ("installed", CapabilityState.VERIFIED),
        (f"permission:{Permission.READ_ONLY.value}", CapabilityState.VERIFIED),
        (f"permission:{Permission.WORKSPACE_WRITE.value}", CapabilityState.VERIFIED),
        ("structured_events", CapabilityState.VERIFIED),
        ("session_identity", CapabilityState.VERIFIED),
    ):
        rows.append(
            {
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "capability": capability,
                "state": state.value,
                "source": source,
            }
        )
    return rows


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

    def create_case(
        self, project_id: str, title: str = "첫 Case", kind: str = "feature"
    ) -> dict[str, Any]:
        """Case를 만든다.

        `kind` 를 인자로 받는 이유는 P2-03에서 **유형에 따라 진입 조건이 다르기**
        때문이다(FR-29: 비기능 조사에 기능 개발 문서 전체를 일괄 요구하지 않는다).
        실행 배관 자체를 보는 시험은 기능 Case가 아닌 유형을 쓰고, 기능 Case의
        진입 조건은 `test_admission.py` 가 따로 본다.
        """
        response = self.client.post(
            f"/api/projects/{project_id}/cases", json={"title": title, "kind": kind}
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

    def create_run(
        self,
        case_id: str,
        artifact_id: str,
        run_id: str,
        purpose: str = "limited_analysis",
        role: str = "author",
        tool_id: str = "local-echo",
        mode: str = "p2-01-local",
        permission: str = "read_only",
    ) -> dict[str, Any]:
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": artifact_id,
                "purpose": purpose,
                "role": role,
                "tool_id": tool_id,
                "mode": mode,
                "permission": permission,
            },
        )
        # 201 = 새로 만듦, 200 = 같은 run_id 의 재전송(만들지 않음)
        assert response.status_code in (200, 201), response.text
        return response.json()

    def effect_count(self, case_id: str) -> int:
        return self.agent.executor.count_effects(case_id)

    def cli_effect_count(self, case_id: str) -> int:
        """가짜 CLI가 **실제로 몇 번 불렸는지.** 중복 실행 판정의 근거."""
        return self.agent.cli_executor.count_effects(case_id)

    # ------------------------------------------------------ P2-03 도우미

    def ai_draft(
        self,
        case_id: str,
        request_text: str = "로그에서 오류 줄만 뽑아 주세요.",
        run_id: str = "run-draft-1",
    ) -> dict[str, Any]:
        """AI에게 의도 초안을 작성시킨다.

        부품을 이어 붙인 것이다 — 요청 원문 접수 → `intent_authoring` 목적의 Run →
        Runner가 실행하고 **초안을 만들어 의도 버전으로 등록**한다.
        """
        instruction = self.submit_artifact(
            case_id, request_text, kind="instruction", summary="초안 작성 요청"
        )
        created = self.create_run(
            case_id,
            instruction["artifact_id"],
            run_id,
            purpose="intent_authoring",
            role="author",
            tool_id=FAKE_TOOL_ID,
            mode=FAKE_TOOL_MODE,
        )
        self.agent.poll_once()
        return created

    def ai_gate_review(
        self, case_id: str, intent: dict[str, Any], run_id: str = "run-review-1"
    ) -> Any:
        """작성과 **별도 세션**에서 QG-01 의미 검토를 실행한다."""
        response = self.client.post(
            f"/api/cases/{case_id}/runs",
            json={
                "run_id": run_id,
                "instruction_artifact_id": intent["artifact_id"],
                "instruction_artifact_rev": intent["artifact_rev"],
                "purpose": "intent_gate_review",
                "role": "reviewer",
                "tool_id": FAKE_TOOL_ID,
                "mode": FAKE_TOOL_MODE,
                "permission": "read_only",
            },
        )
        if response.status_code in (200, 201):
            self.agent.poll_once()
        return response

    def gate(self, case_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/cases/{case_id}/gate")
        assert response.status_code == 200, response.text
        return response.json()

    def admission_checks(self, case_id: str) -> list[dict[str, Any]]:
        return self.client.get(f"/api/cases/{case_id}/admission-checks").json()

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
        agent = RunnerAgent(
            runner_config,
            ControllerClient("http://testserver", client=client),
            # 실제 코딩 CLI를 부르지 않는다. 능력 보고도 이 PC 조회가 아니라
            # 가짜 값이라 시험이 설치 상태에 좌우되지 않는다.
            cli_executor=FakeCliExecutor(runner_config.effects_dir),
            capabilities=fake_capabilities(),
        )
        agent.register()
        yield Harness(client, agent, controller_config, runner_config)
