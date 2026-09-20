"""AC-2 — 저장 완료로 응답한 기록이 프로세스 **강제 종료** 후 복원되는지.

NFR-01은 "저장 완료로 응답한 요청·결정·승인·상태는 프로세스 재시작 후 복원되어야 한다"를
요구한다. 여기서는 실제로 uvicorn을 자식 프로세스로 띄우고 `taskkill /F /T` 로 죽인다.
정상 종료(shutdown 훅이 도는 경로)로는 이 요구를 확인할 수 없다.

함께 확인하는 것: 저장 완료로 **응답하지 않은** 중계 중 원문은 재시작 후 사라지며,
그 사실이 `lost_before_persist` 로 드러난다. 서버에 영구 저장해 우회하지 않는다.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

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

    decision = httpx.post(
        f"{base}/api/cases/{case['id']}/decisions",
        json={
            "kind": "intent_agreement",
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
