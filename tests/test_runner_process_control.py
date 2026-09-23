"""UI-02 AC-18 — 실제 제어부(uvicorn)·실제 Runner 프로세스·실제 프로세스 트리로 본다.

한 흐름에서 넷을 확인한다.

    1. 긴 실행 중에도 Runner 가 다른 대화의 메시지를 저장하고 heartbeat·실행 중을 보고한다
    2. 요청 중단 → Runner 가 CLI 트리를 끝내고 확인 → 요청 `interrupted`, 전송 열림
    3. Runner **프로세스만** 강제 종료 → CLI 트리가 함께 끝남(KILL_ON_JOB_CLOSE) → PC 미연결로
       전송 거부 → Runner 재기동이 원장으로 대조(재실행·새 세대 없음) → 요청 `interrupted`
    4. 재연결 뒤 전송이 다시 열리고 자동으로 보내진 것은 없다

CLI 는 PATH 앞에 둔 시험용 `codex.cmd`(`tests/fake_cli/fake_codex.py`)다. **AI 를 부르지
않는다.** 제품 Runner 는 그것이 가짜인지 모르고 실제 경로(job 생성·정지 상태 생성·재개)를
그대로 탄다. 실제 codex 로 같은 것을 보는 라이브는 `ui/live/ui02_control.py` 다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import httpx
import pytest

from runner import process_tree
from tests.test_restart_recovery import PYTHON, REPO_ROOT, ControllerProcess, _free_port

FAKE_CLI = Path(__file__).resolve().parent / "fake_cli" / "fake_codex.py"
RUNNER_ID = "runner-ui02-proc"

pytestmark = [
    pytest.mark.skipif(not process_tree.IS_WINDOWS, reason="트리 제어는 Windows 에서만 지원한다"),
    pytest.mark.skipif(not PYTHON.exists(), reason="저장소 로컬 .venv 가 없다"),
]


class RunnerProcess:
    """실제 Runner(`python -m runner.agent`). PATH 앞에 시험용 codex 를 둔다."""

    def __init__(self, base_url: str, data_root: Path, bin_dir: Path, pids: Path, log: Path):
        self.env = dict(os.environ)
        self.env.update(
            {
                "HADS_RUNNER_ID": RUNNER_ID,
                "HADS_RUNNER_DATA": str(data_root),
                "HADS_CONTROLLER_URL": base_url,
                "HADS_FAKE_PIDS": str(pids),
                "PYTHONPATH": str(REPO_ROOT),
                "PATH": f"{bin_dir};{os.environ['PATH']}",
            }
        )
        self.log = log
        self.proc: subprocess.Popen | None = None

    def start(self) -> None:
        handle = open(self.log, "ab")
        self.proc = subprocess.Popen(
            [str(PYTHON), "-m", "runner.agent"],
            cwd=str(REPO_ROOT),
            env=self.env,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
        handle.close()

    def kill_tree(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True
            )
            self.proc.wait(timeout=30)
        self.proc = None


def _wait(predicate: Callable[[], Any], timeout: float, what: str) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except httpx.HTTPError:
            last = None
        if last:
            return last
        time.sleep(0.2)
    raise AssertionError(f"기다렸지만 오지 않았다: {what} (마지막 값 {last!r})")


def _pids(directory: Path, kind: str) -> list[int]:
    if not directory.exists():
        return []
    return [int(p.read_text()) for p in directory.glob(f"{kind}-*.pid")]


def _dead(pid: int, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process_tree.process_alive(pid, None) is False:
            return True
        time.sleep(0.1)
    return False


@pytest.fixture
def system(tmp_path, monkeypatch):
    # PC 미연결 판정을 빨리 보기 위해 기준을 줄인다(기본 15초).
    monkeypatch.setenv("HADS_RUNNER_STALE_SECONDS", "3")
    controller = ControllerProcess(tmp_path / "controller", _free_port())
    controller.start()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "codex.cmd").write_text(
        f'@"{sys.executable}" "{FAKE_CLI}" %*\r\n', encoding="utf-8"
    )
    pids = tmp_path / "pids"
    runner = RunnerProcess(
        controller.base_url, tmp_path / "runner", bin_dir, pids, tmp_path / "runner.log"
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    try:
        yield {
            "controller": controller,
            "runner": runner,
            "pids": pids,
            "repo": repo,
            "ledger": tmp_path / "runner" / "ledger",
            "api": httpx.Client(base_url=controller.base_url, timeout=30.0),
        }
    finally:
        runner.kill_tree()
        if controller.proc is not None:
            controller.kill_hard()
        # 시험이 실패해도 가짜 CLI 트리를 남기지 않는다.
        for pid in _pids(pids, "cli") + _pids(pids, "grandchild"):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)


def _send(api: httpx.Client, case_id: str, text: str, cid: str) -> httpx.Response:
    return api.post(
        f"/api/cases/{case_id}/messages",
        json={
            "client_message_id": cid,
            "kind": "general",
            "content": text,
            "summary": f"사용자 메시지 · {len(text)}자",
            "target_runner_id": RUNNER_ID,
        },
    )


def _stored(api: httpx.Client, case_id: str, cid: str) -> bool:
    response = api.get(f"/api/cases/{case_id}/messages/by-client-id/{cid}")
    return response.status_code == 200 and response.json()["receipt"] == "stored"


def _request(api: httpx.Client, case_id: str, request_id: str) -> dict[str, Any]:
    view = api.get(f"/api/cases/{case_id}/conversation").json()
    return next(r for r in view["requests"] if r["id"] == request_id)


def _long_reply(api: httpx.Client, case_id: str, text: str, cid: str, run_id: str) -> dict:
    sent = _send(api, case_id, text, cid)
    assert sent.status_code == 202, sent.text
    request_id = sent.json()["request"]["id"]
    _wait(lambda: _stored(api, case_id, cid), 20, f"{cid} 저장")
    message = sent.json()["message"]
    created = api.post(
        f"/api/cases/{case_id}/runs",
        json={
            "run_id": run_id,
            "instruction_artifact_id": message["artifact_id"],
            "instruction_artifact_rev": message["artifact_rev"],
            "purpose": "discussion_reply",
            "role": "author",
            "tool_id": "codex",
            "mode": "exec",
            "permission": "read_only",
            "request_id": request_id,
        },
    )
    assert created.status_code == 201, created.text
    return {"request_id": request_id}


def test_a_real_runner_stops_a_real_tree_and_reconciles_after_its_own_crash(system):
    api: httpx.Client = system["api"]
    runner: RunnerProcess = system["runner"]
    pids: Path = system["pids"]
    runner.start()
    _wait(lambda: any(r["id"] == RUNNER_ID for r in api.get("/api/runners").json()), 30, "Runner 등록")

    project = api.post(
        "/api/projects",
        json={"name": "ui02-proc", "repo_path": str(system["repo"]), "default_tool_id": "codex"},
    ).json()
    main = api.post(f"/api/projects/{project['id']}/conversations", json={"title": "긴 실행"}).json()
    side = api.post(f"/api/projects/{project['id']}/conversations", json={"title": "옆 대화"}).json()
    case_id = main["case_id"]

    # ---------------------------------------------------- 1. 긴 실행 중 저장·보고
    first = _long_reply(api, case_id, "HADS_FAKE_SLEEP=90 천천히", "c-long-1", "run-proc-1")
    _wait(lambda: _pids(pids, "grandchild"), 40, "가짜 CLI 의 손자 프로세스")
    posted = _send(api, side["case_id"], "그동안 이것도 받아 주세요", "c-side-1")
    assert posted.status_code == 202
    _wait(lambda: _stored(api, side["case_id"], "c-side-1"), 10, "실행 중 메시지 저장")
    side_request = posted.json()["request"]["id"]
    closed = api.post(
        f"/api/cases/{side['case_id']}/requests/{side_request}/settle",
        json={"outcome": "completed", "actor": "system"},
    )
    assert closed.status_code == 200 and closed.json()["state"] == "completed"
    _wait(
        lambda: _request(api, case_id, first["request_id"])["runs"][0]["execution_state"]
        == "executing",
        10,
        "실행 중 보고",
    )
    run = api.get("/api/runs/run-proc-1").json()
    assert run["status"] in ("assigned", "running") and run["liveness_at"]

    # ---------------------------------------------------- 2. 중단 → 트리 종료 확인
    grandchildren = _pids(pids, "grandchild")
    stopped = api.post(
        f"/api/cases/{case_id}/requests/{first['request_id']}/stop",
        json={"actor": "owner", "reason": "그만 기다린다"},
    )
    assert stopped.status_code == 200 and stopped.json()["stopping"] is True
    done = _wait(
        lambda: (lambda r: r if r["state"] != "processing" else None)(
            _request(api, case_id, first["request_id"])
        ),
        30,
        "중단 확인",
    )
    assert (done["state"], done["outcome_reason"]) == ("interrupted", "stopped_by_request")
    run = api.get("/api/runs/run-proc-1").json()
    assert (run["outcome"], run["residual_activity"]) == ("cancelled", "none")
    assert run["stop_delivered_at"]
    [observation] = run["residual_observations"]
    assert observation["basis"] == "job_terminated" and observation["terminated"] >= 2
    for pid in grandchildren + _pids(pids, "cli"):
        assert _dead(pid), f"pid {pid} 가 남았다"

    # ---------------------------------------------------- 3. Runner 만 강제 종료
    second = _long_reply(api, case_id, "HADS_FAKE_SLEEP=90 다시", "c-long-2", "run-proc-2")
    _wait(lambda: len(_pids(pids, "grandchild")) >= 2, 40, "두 번째 손자 프로세스")
    ledger = json.loads((system["ledger"] / "run-proc-2.json").read_text(encoding="utf-8"))
    assert ledger["ledger_version"] == 2 and ledger["launch"]["kill_on_close"] is True
    runner_pid = ledger["runner_process"]["pid"]
    live_tree = [p for p in _pids(pids, "grandchild") + _pids(pids, "cli") if process_tree.process_alive(p, None)]
    assert live_tree
    # **트리가 아니라 그 프로세스 하나만** 끝낸다(`/T` 없음) — Runner 가 죽은 모양이다.
    subprocess.run(["taskkill", "/F", "/PID", str(runner_pid)], capture_output=True)
    for pid in live_tree:
        assert _dead(pid), f"Runner 가 죽었는데 CLI 트리의 pid {pid} 가 남았다"
    runner.kill_tree()  # 남은 가상환경 진입점 정리

    # PC 미연결 — 사용자 입력을 받지 않는다(대기열 없음).
    _wait(
        lambda: api.get(f"/api/cases/{side['case_id']}/conversation").json()["send"][
            "runner_connection"
        ]["state"]
        == "disconnected",
        15,
        "PC 미연결 판정",
    )
    refused = _send(api, side["case_id"], "끊긴 동안", "c-side-2")
    assert refused.status_code == 409
    assert refused.json()["detail"]["refusals"] == ["runner_disconnected"]
    assert api.get("/api/runs/run-proc-2").json()["status"] in ("assigned", "running")

    # ---------------------------------------------------- 4. 재기동 → 원장 대조
    cli_runs_before = len(_pids(pids, "cli"))
    runner.start()
    reported = _wait(
        lambda: (lambda r: r if r["status"] == "finished" else None)(
            api.get("/api/runs/run-proc-2").json()
        ),
        40,
        "재시작 대조",
    )
    assert reported["outcome"] == "unknown"
    assert reported["residual_activity"] == "none"
    assert [(o["source"], o["basis"]) for o in reported["residual_observations"]] == [
        ("reconcile", "job_closed_kill_on_close")
    ]
    assert reported["assignment_generation"] == 1  # 세대를 올리지 않았다
    assert reported["session_ref"]  # 원시 출력에서 되찾았다
    time.sleep(2)
    assert len(_pids(pids, "cli")) == cli_runs_before  # CLI 를 다시 부르지 않았다
    budget = api.get(f"/api/cases/{case_id}/budget").json()
    assert {r["generation"] for r in budget["reservations"] if r["run_id"] == "run-proc-2"} == {1}

    settled = api.post(
        f"/api/cases/{case_id}/requests/{second['request_id']}/settle",
        json={"outcome": "failed", "actor": "system"},
    ).json()
    assert (settled["state"], settled["outcome_reason"]) == (
        "interrupted", "execution_ended_result_unknown"
    )
    # 재연결 뒤 — 자동으로 보내진 것은 없고, 사람이 보내면 받는다.
    _wait(
        lambda: api.get(f"/api/cases/{side['case_id']}/conversation").json()["send"][
            "runner_connection"
        ]["state"]
        == "connected",
        15,
        "재연결",
    )
    side_view = api.get(f"/api/cases/{side['case_id']}/conversation").json()
    assert [m["client_message_id"] for m in side_view["messages"]] == ["c-side-1"]
    resent = _send(api, side["case_id"], "끊긴 동안", "c-side-2")
    assert resent.status_code == 202, resent.text
    assert _send(api, case_id, "이어서 이야기해요", "c-long-3").status_code == 202
