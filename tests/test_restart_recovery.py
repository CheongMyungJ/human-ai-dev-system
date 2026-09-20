"""AC-2 — 저장 완료로 응답한 기록이 프로세스 **강제 종료** 후 복원되는지.

NFR-01은 "저장 완료로 응답한 요청·결정·승인·상태는 프로세스 재시작 후 복원되어야 한다"를
요구한다. 여기서는 실제로 uvicorn을 자식 프로세스로 띄우고 `taskkill /F /T` 로 죽인다.
정상 종료(shutdown 훅이 도는 경로)로는 이 요구를 확인할 수 없다.

함께 확인하는 것: 저장 완료로 **응답하지 않은** 중계 중 원문은 재시작 후 사라지며,
그 사실이 `lost_before_persist` 로 드러난다. 서버에 영구 저장해 우회하지 않는다.
"""

from __future__ import annotations

import base64
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from domain import intent_doc
from domain.models import IntentField

REPO_ROOT = Path(__file__).resolve().parent.parent
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
RUNNER_ID = "runner-restart-1"

pytestmark = pytest.mark.skipif(
    not PYTHON.exists(),
    reason="저장소 로컬 .venv 가 없다. scripts/bootstrap.ps1 을 먼저 실행한다",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ControllerProcess:
    """실제 uvicorn 자식 프로세스."""

    def __init__(self, data_root: Path, port: int) -> None:
        self.data_root = data_root
        self.port = port
        self.base_url = f"http://127.0.0.1:{port}"
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        env = dict(os.environ)
        env["HADS_CONTROLLER_DATA"] = str(self.data_root)
        env["HADS_WEB_DIST"] = ""  # 이 시험은 API만 본다
        env["PYTHONPATH"] = str(REPO_ROOT)
        self.proc = subprocess.Popen(
            [
                str(PYTHON),
                "-m",
                "uvicorn",
                "controller.app:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            cwd=str(REPO_ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        deadline = time.time() + 30
        while time.time() < deadline:
            if self.proc.poll() is not None:
                output = self.proc.stdout.read().decode("utf-8", "replace") if self.proc.stdout else ""
                raise RuntimeError(f"controller exited early:\n{output}")
            try:
                if httpx.get(f"{self.base_url}/api/health", timeout=1.0).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.2)
        raise RuntimeError("controller did not become healthy in time")

    def kill_hard(self) -> None:
        """강제 종료. 정리 훅이 돌 기회를 주지 않는다."""
        assert self.proc is not None
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)],
            check=False,
            capture_output=True,
        )
        self.proc.wait(timeout=30)
        if self.proc.stdout:
            self.proc.stdout.close()
        self.proc = None


@pytest.fixture
def controller(tmp_path):
    proc = ControllerProcess(tmp_path / "controller", _free_port())
    proc.start()
    try:
        yield proc
    finally:
        if proc.proc is not None:
            proc.kill_hard()


def _register_runner(base_url: str) -> None:
    httpx.post(
        f"{base_url}/api/runner/register",
        json={
            "runner_id": RUNNER_ID,
            "name": RUNNER_ID,
            "host": "test-host",
            "capabilities": [],
        },
        timeout=10.0,
    ).raise_for_status()


def test_saved_records_survive_a_forced_kill(controller, tmp_path):
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "restart-demo", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "재시작 복원 Case", "kind": "feature"},
        timeout=10.0,
    ).json()

    # 원문을 접수하고 Runner 역할로 영속 저장을 보고한다 → 저장 완료.
    accepted = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "instruction",
            "content": "재시작 뒤에도 남아야 하는 지시",
            "summary": "지시 원문",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    intakes = httpx.get(f"{base}/api/runner/{RUNNER_ID}/intakes", timeout=10.0).json()
    assert len(intakes) == 1
    httpx.post(
        f"{base}/api/runner/intakes/{accepted['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": accepted["content_hash"]},
        timeout=10.0,
    ).raise_for_status()

    run = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-restart-1", "instruction_artifact_id": accepted["artifact_id"]},
        timeout=10.0,
    ).json()
    assert run["created"] is True

    # 의도 동의는 전용 경로에서만 만들어진다(tests/test_intent.py). 여기서는 다른 종류의
    # 사람 결정이 강제 종료 후에도 남는지만 본다.
    decision = httpx.post(
        f"{base}/api/cases/{case['id']}/decisions",
        json={
            "kind": "design_review",
            "subject_type": "case",
            "subject_id": case["id"],
            "subject_revision": 1,
            "actor": "owner",
        },
        timeout=10.0,
    ).json()

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    restored_case = httpx.get(f"{base}/api/cases/{case['id']}", timeout=10.0).json()
    assert restored_case["title"] == "재시작 복원 Case"
    assert [d["id"] for d in restored_case["decisions"]] == [decision["id"]]
    assert restored_case["artifacts"][0]["availability"] == "available"

    restored_run = httpx.get(f"{base}/api/runs/run-restart-1", timeout=10.0).json()
    assert restored_run["case_id"] == case["id"]
    assert restored_run["status"] == "pending"
    assert restored_run["assignment_generation"] == 1

    # 재시작 뒤에도 같은 run_id 는 새 실행을 만들지 않는다.
    again = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-restart-1", "instruction_artifact_id": accepted["artifact_id"]},
        timeout=10.0,
    ).json()
    assert again["created"] is False


def test_relayed_body_not_yet_persisted_is_reported_as_lost(controller):
    """저장 완료로 응답하지 않은 원문은 재시작 후 사라진 사실을 드러낸다."""
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "lost-demo", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "중계 중 재시작", "kind": "feature"},
        timeout=10.0,
    ).json()
    accepted = httpx.post(
        f"{base}/api/cases/{case['id']}/artifacts",
        json={
            "kind": "intent",
            "content": "Runner가 아직 저장하지 않은 의도 원문",
            "summary": "의도 초안",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()
    assert accepted["availability"] == "pending"

    controller.kill_hard()
    controller.start()

    intake = httpx.get(f"{base}/api/intakes/{accepted['intake_id']}", timeout=10.0).json()
    assert intake["state"] == "lost_before_persist"

    detail = httpx.get(f"{base}/api/cases/{case['id']}", timeout=10.0).json()
    assert detail["artifacts"][0]["availability"] == "lost_before_persist"
    # 빈 문서나 삭제로 표시하지 않는다. 참조와 해시는 남아 있다.
    assert detail["artifacts"][0]["content_hash"] == accepted["content_hash"]

    # 사라진 원문으로는 실행을 배정하지 않는다.
    refused = httpx.post(
        f"{base}/api/cases/{case['id']}/runs",
        json={"run_id": "run-lost-art", "instruction_artifact_id": accepted["artifact_id"]},
        timeout=10.0,
    )
    assert refused.status_code == 409


def test_runner_ledger_survives_its_own_restart(tmp_path):
    """Runner 원장은 파일에 있으므로 Runner 재시작 후에도 재실행을 막는다."""
    from runner.ledger import ExecutionLedger

    ledger_a = ExecutionLedger(tmp_path / "ledger")
    should_run, existing = ledger_a.claim("run-x", 1)
    assert should_run is True and existing is None
    ledger_a.finish("run-x", {"outcome": "completed"})

    # 새 프로세스를 흉내 내어 같은 경로로 다시 연다.
    ledger_b = ExecutionLedger(tmp_path / "ledger")
    should_run, existing = ledger_b.claim("run-x", 2)
    assert should_run is False
    assert existing["result"]["outcome"] == "completed"


def test_intent_agreement_and_structure_survive_a_forced_kill(controller):
    """AC-10 — 의도 버전·항목 상태·질문·피드백·동의가 강제 종료 후에도 복원된다.

    그리고 중계 중이던 **열람 응답**은 사라진다. 원문이 사라진 것이 아니라
    중계가 끊긴 것이므로 요청만 `expired` 로 닫히고 다시 요청할 수 있다.
    """
    base = controller.base_url
    _register_runner(base)

    project = httpx.post(
        f"{base}/api/projects",
        json={"name": "intent-restart", "repo_path": "C:/tmp/demo", "default_tool_id": "codex"},
        timeout=10.0,
    ).json()
    case = httpx.post(
        f"{base}/api/projects/{project['id']}/cases",
        json={"title": "의도 재시작 Case", "kind": "feature"},
        timeout=10.0,
    ).json()

    draft = httpx.post(
        f"{base}/api/cases/{case['id']}/intent-drafts",
        json={
            "summary": "의도 초안 v1",
            "target_runner_id": RUNNER_ID,
            "fields": {
                "goal": {
                    "text": "재시작 뒤에도 남아야 하는 목표",
                    "state": "proposed",
                    "origin": "user_requirement",
                }
            },
            "questions": [
                {
                    "key": "later",
                    "text": "설계에서 정할 질문",
                    "summary": "설계 단계 질문",
                    "decide_at": "design",
                }
            ],
        },
        timeout=10.0,
    ).json()

    # Runner 역할로 원문을 저장하고 구조를 보고한다.
    intakes = httpx.get(f"{base}/api/runner/{RUNNER_ID}/intakes", timeout=10.0).json()
    assert len(intakes) == 1 and intakes[0]["intent"]["intent_version_id"]
    body = base64.b64decode(intakes[0]["content_b64"])
    httpx.post(
        f"{base}/api/runner/intakes/{draft['intake_id']}/stored",
        json={"runner_id": RUNNER_ID, "content_hash": draft["content_hash"]},
        timeout=10.0,
    ).raise_for_status()
    structure = intent_doc.structure(body, None)
    httpx.post(
        f"{base}/api/runner/intent-structure",
        json={
            "runner_id": RUNNER_ID,
            "intent_version_id": intakes[0]["intent"]["intent_version_id"],
            "fields": structure["fields"],
            "questions": structure["questions"],
        },
        timeout=10.0,
    ).raise_for_status()

    feedback = httpx.post(
        f"{base}/api/cases/{case['id']}/feedback",
        json={
            "target_intent_version_id": draft["intent_version"]["id"],
            "content": "재시작 뒤에도 남아야 하는 피드백",
            "summary": "피드백 하나",
            "target_runner_id": RUNNER_ID,
        },
        timeout=10.0,
    ).json()

    def relay_read() -> dict:
        """열람 요청을 열고 Runner 역할로 본문을 올린다(= 제어부 메모리에만 있는 상태)."""
        opened = httpx.post(
            f"{base}/api/artifacts/{draft['artifact_id']}/{draft['revision']}/read-requests",
            json={},
            timeout=10.0,
        ).json()
        httpx.post(
            f"{base}/api/runner/read-requests/{opened['id']}/content",
            json={
                "runner_id": RUNNER_ID,
                "content_b64": base64.b64encode(body).decode("ascii"),
                "content_hash": draft["content_hash"],
            },
            timeout=10.0,
        ).raise_for_status()
        return opened

    # 사람이 원문을 실제로 받아 봐야 동의할 수 있다.
    delivered = httpx.get(
        f"{base}/api/read-requests/{relay_read()['id']}", timeout=10.0
    ).json()
    assert delivered["content"] is not None

    agreed = httpx.post(
        f"{base}/api/cases/{case['id']}/intent-versions/{draft['intent_version']['id']}/agreement",
        json={
            "agree": True,
            "statement": "이 의도에 동의합니다.",
            "content_hash": draft["content_hash"],
            "actor": "owner",
        },
        timeout=10.0,
    )
    assert agreed.status_code == 201, agreed.text

    # 두 번째 열람은 **받아 가기 전에** 재시작을 맞는다.
    read_request = relay_read()

    # ---- 강제 종료 ----
    controller.kill_hard()
    controller.start()

    state = httpx.get(f"{base}/api/cases/{case['id']}/intent-state", timeout=10.0).json()
    assert state["agreement_state"] == "agreed_current"
    assert state["agreed_version"]["subject_content_hash"] == draft["content_hash"]

    latest = state["latest_intent_version"]
    assert {f["field"] for f in latest["fields"]} == {f.value for f in IntentField}
    assert [q["question_key"] for q in latest["questions"]] == ["later"]

    stored_feedback = httpx.get(f"{base}/api/cases/{case['id']}/feedback", timeout=10.0).json()
    assert [f["id"] for f in stored_feedback] == [feedback["feedback"]["id"]]

    # 중계 중이던 열람 응답은 이 프로세스에 없다. 빈 본문으로 채우지 않는다.
    after = httpx.get(f"{base}/api/read-requests/{read_request['id']}", timeout=10.0).json()
    assert after["content"] is None
    assert after["request"]["state"] == "expired"

    # 다시 요청하면 된다 — 원문은 Runner에 그대로 있다.
    retry = httpx.post(
        f"{base}/api/artifacts/{draft['artifact_id']}/{draft['revision']}/read-requests",
        json={},
        timeout=10.0,
    ).json()
    assert retry["state"] == "pending"
