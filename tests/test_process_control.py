"""UI-02 — CLI 프로세스 트리 제어를 **실제 OS 프로세스**로 확인한다.

가짜 실행기로는 볼 수 없는 것이다: 손자 프로세스까지 끝났는가, 루트가 끝난 뒤 남은 것이
있는가, 소유 프로세스가 죽으면 트리가 함께 끝나는가. 판정은 job 의 보고가 아니라 **OS 에서
그 pid 가 살아 있는가**로 따로 본다(P1-03 이 부수효과로 판정한 것과 같은 방식).

`CliExecutor` 시험은 PATH 앞에 둔 시험용 `codex.cmd`(→ `tests/fake_cli/fake_codex.py`)를
부른다. **AI 를 부르지 않는다.** 제품 어댑터는 그것이 가짜인지 모르고 실제 경로 그대로 돈다.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest

from domain.models import Permission, RunOutcome
from runner import cli_adapter, process_tree

pytestmark = pytest.mark.skipif(
    not process_tree.IS_WINDOWS, reason="프로세스 트리 제어는 Windows 에서만 지원한다"
)

FAKE_CLI = Path(__file__).resolve().parent / "fake_cli" / "fake_codex.py"

#: 손자 프로세스를 하나 만들고 pid 를 한 줄 쓴 뒤 오래 잔다.
TREE = (
    "import subprocess, sys, time\n"
    "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(gc.pid, flush=True)\n"
    "time.sleep(120)\n"
)
#: 손자 프로세스를 남기고 바로 끝난다.
LEAVE = (
    "import subprocess, sys\n"
    "gc = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(120)'])\n"
    "print(gc.pid, flush=True)\n"
)


def _wait_dead(pid: int, created: int | None = None, timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process_tree.process_alive(pid, created) is False:
            return True
        time.sleep(0.05)
    return False


def _job(tmp_path: Path, tag: str) -> process_tree.JobTree:
    return process_tree.JobTree.create(process_tree.job_name_for("test", f"{tmp_path.name}-{tag}", 1))


# ============================================================== JobTree


def test_stopping_ends_the_whole_tree_and_confirms_zero(tmp_path):
    """AC-3 — 중단은 손자까지 끝내고 **활성 0 을 확인한 뒤** `none` 이다."""
    job = _job(tmp_path, "stop")
    try:
        proc = job.spawn_suspended([sys.executable, "-c", TREE], stdout=subprocess.PIPE)
        root = process_tree.JobTree.launch_identity(proc)
        process_tree.JobTree.resume(proc)
        grandchild = int(proc.stdout.readline().decode().strip())
        assert process_tree.process_alive(grandchild, None) is True
        assert job.active_processes() >= 2

        observation = job.terminate_and_confirm()

        assert observation.residual == "none"
        assert observation.basis == process_tree.BASIS_JOB_TERMINATED
        assert observation.terminated >= 2
        # job 의 보고와 따로 **OS 에서** 본다.
        assert _wait_dead(root["pid"], root["pid_created"])
        assert _wait_dead(grandchild)
        proc.stdout.close()
    finally:
        job.close()


def test_what_a_finished_root_leaves_behind_is_ended_and_counted(tmp_path):
    """AC-4 — 루트가 정상 종료한 뒤 남은 프로세스는 그 실행의 잔류다. 끝내고 수를 남긴다."""
    job = _job(tmp_path, "leave")
    try:
        proc = job.spawn_suspended([sys.executable, "-c", LEAVE], stdout=subprocess.PIPE)
        process_tree.JobTree.resume(proc)
        leftover = int(proc.stdout.readline().decode().strip())
        proc.wait(timeout=30)
        assert process_tree.process_alive(leftover, None) is True
        assert job.active_processes() >= 1

        observation = job.terminate_and_confirm()

        assert (observation.residual, observation.basis) == ("none", "job_terminated")
        assert observation.terminated >= 1
        assert _wait_dead(leftover)
        proc.stdout.close()
    finally:
        job.close()


def test_a_clean_exit_leaves_an_empty_job(tmp_path):
    """AC-4 — 아무 것도 남기지 않은 실행은 종료하지 않고 `job_empty` 다."""
    job = _job(tmp_path, "clean")
    try:
        proc = job.spawn_suspended([sys.executable, "-c", "print('ok')"], stdout=subprocess.PIPE)
        process_tree.JobTree.resume(proc)
        proc.wait(timeout=30)
        assert job.wait_empty(10)
        observation = job.terminate_and_confirm()
        assert (observation.residual, observation.basis, observation.terminated) == (
            "none",
            "job_empty",
            0,
        )
        proc.stdout.close()
    finally:
        job.close()


def test_a_suspended_process_runs_nothing_before_it_is_resumed(tmp_path):
    """AC-5 — 재개 전에 소유자가 job 을 닫으면 CLI 는 **한 줄도 실행하지 않았다.**"""
    marker = tmp_path / "ran.txt"
    job = _job(tmp_path, "suspended")
    proc = job.spawn_suspended(
        [sys.executable, "-c", f"open(r'{marker}', 'w').write('ran')"],
    )
    identity = process_tree.JobTree.launch_identity(proc)
    time.sleep(0.5)
    job.close()  # 재개하지 않은 채 닫는다 — KILL_ON_JOB_CLOSE
    assert _wait_dead(identity["pid"], identity["pid_created"])
    assert not marker.exists()


def test_killing_the_owner_ends_the_tree_and_a_new_process_can_confirm_it(tmp_path):
    """AC-5·AC-10 — **소유 프로세스만** 강제 종료해도 트리가 끝나고, 다른 프로세스가 원장의
    시작 기록으로 그것을 확인한다(`job_closed_kill_on_close`)."""
    name = process_tree.job_name_for("test", f"{tmp_path.name}-owner", 1)
    helper = (
        "import json, subprocess, sys, time\n"
        f"sys.path.insert(0, r'{Path(__file__).resolve().parent.parent}')\n"
        "from runner import process_tree as pt\n"
        f"job = pt.JobTree.create(r'{name}')\n"
        f"proc = job.spawn_suspended([sys.executable, '-c', {TREE!r}], stdout=subprocess.PIPE)\n"
        "root = pt.JobTree.launch_identity(proc)\n"
        "pt.JobTree.resume(proc)\n"
        "gc = int(proc.stdout.readline().decode().strip())\n"
        "print(json.dumps({'root': root, 'gc': gc}), flush=True)\n"
        "time.sleep(120)\n"
    )
    owner = subprocess.Popen([sys.executable, "-c", helper], stdout=subprocess.PIPE)
    try:
        info = json.loads(owner.stdout.readline().decode())
        root, grandchild = info["root"], info["gc"]
        assert process_tree.process_alive(grandchild, None) is True
        # 트리가 아니라 **그 프로세스 하나**만 끝낸다(`/T` 없음) — Runner 가 죽은 모양이다.
        subprocess.run(["taskkill", "/F", "/PID", str(owner.pid)], capture_output=True)
        owner.wait(timeout=30)

        assert _wait_dead(root["pid"], root["pid_created"])
        assert _wait_dead(grandchild)
        launch = {"job_name": name, "kill_on_close": True, **root}
        observation = process_tree.check_residual(launch, None)
        assert (observation.residual, observation.basis) == ("none", "job_closed_kill_on_close")
    finally:
        if owner.poll() is None:
            owner.kill()
        owner.stdout.close()


def test_a_live_job_found_later_is_ended_before_it_is_confirmed(tmp_path):
    """AC-10 — 재확인 때 job 이 아직 살아 있으면 **끝내고 확인한다**(끝난 실행의 잔류다)."""
    job = _job(tmp_path, "live")
    try:
        proc = job.spawn_suspended([sys.executable, "-c", TREE], stdout=subprocess.PIPE)
        root = process_tree.JobTree.launch_identity(proc)
        process_tree.JobTree.resume(proc)
        grandchild = int(proc.stdout.readline().decode().strip())
        launch = {"job_name": job.name, "kill_on_close": True, **root}

        observation = process_tree.check_residual(launch, None)

        assert (observation.residual, observation.basis) == ("none", "job_terminated")
        assert observation.terminated >= 2
        assert _wait_dead(grandchild)
        proc.stdout.close()
    finally:
        job.close()


def test_none_needs_a_confirming_basis(tmp_path):
    """AC-10 — 확인 근거가 없으면 `unknown` 이다. 루트가 살아 있으면 job 이 없어도 확인이 아니다."""
    me = process_tree.process_identity(__import__("os").getpid())
    missing = f"Local\\hads-run-test-{tmp_path.name}-missing"
    # job 은 없는데 루트(여기서는 이 시험 프로세스)가 같은 생성 시각으로 살아 있다.
    alive = process_tree.check_residual(
        {"job_name": missing, "kill_on_close": True, "pid": me["pid"], "pid_created": me["created"]},
        None,
    )
    assert (alive.residual, alive.basis) == ("unknown", "root_process_alive")
    # 시작 기록이 없으면(v1 원장) 재부팅만 근거가 된다.
    now = process_tree.host_boot_time() + timedelta(hours=1)
    assert process_tree.check_residual(None, now.isoformat()).to_dict() == {
        "residual": "unknown",
        "basis": "not_observable",
        "terminated": None,
    }
    before_boot = process_tree.host_boot_time() - timedelta(days=1)
    rebooted = process_tree.check_residual(None, before_boot.isoformat())
    assert (rebooted.residual, rebooted.basis) == ("none", "host_rebooted")
    # 트리 제어 없이 시작된 기록도 같다.
    unmanaged = process_tree.check_residual({"pid": None, "kill_on_close": False}, now.isoformat())
    assert unmanaged.residual == "unknown"
    # Runner 프로세스 안의 실행기는 그 프로세스와 함께 끝났다.
    assert process_tree.check_residual({"in_process": True}, None).basis == "in_process"


def test_a_reused_pid_is_not_the_same_process():
    """pid 는 재사용된다. 생성 시각이 다르면 다른 프로세스다."""
    me = process_tree.process_identity(__import__("os").getpid())
    assert process_tree.process_alive(me["pid"], me["created"]) is True
    assert process_tree.process_alive(me["pid"], me["created"] + 1) is False


# ============================================================ CliExecutor


@pytest.fixture
def fake_codex(tmp_path, monkeypatch):
    """PATH 앞에 시험용 `codex.cmd` 를 둔다. 제품 어댑터는 그대로 PATH 에서 찾는다."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "codex.cmd").write_text(
        f'@"{sys.executable}" "{FAKE_CLI}" %*\r\n', encoding="utf-8"
    )
    pids = tmp_path / "pids"
    monkeypatch.setenv("PATH", f"{bin_dir};{__import__('os').environ['PATH']}")
    monkeypatch.setenv("HADS_FAKE_PIDS", str(pids))
    work = tmp_path / "work"
    work.mkdir()
    return {
        "pids": pids,
        "work": work,
        "effects": tmp_path / "effects",
        "raw": tmp_path / "raw",
        "cmd": bin_dir / "codex.cmd",
    }


def _pids(directory: Path, kind: str) -> list[int]:
    return [int(p.read_text()) for p in directory.glob(f"{kind}-*.pid")] if directory.exists() else []


def _execute(env, prompt: str, run_id: str, **kwargs):
    env["raw"].mkdir(exist_ok=True)
    executor = cli_adapter.CliExecutor(env["effects"], timeout=120)
    return executor.execute(
        run_id=run_id,
        case_id="case-pt",
        prompt=prompt,
        tool_id="codex",
        mode="exec",
        permission=Permission.READ_ONLY,
        workspace=env["work"],
        raw_dir=env["raw"],
        job_name=process_tree.job_name_for("test", run_id, 1),
        **kwargs,
    )


def test_the_adapter_records_the_launch_before_the_cli_runs_and_confirms_a_clean_end(fake_codex):
    """AC-3·AC-4 — 시작 기록은 CLI 가 돌기 **전에** 남고, 정상 종료는 `job_empty` 다."""
    launches: list[dict] = []

    def on_launch(launch):
        # 이 순간 CLI 는 아직 재개되지 않았다 — 자기 pid 를 쓰지 못했다.
        assert _pids(fake_codex["pids"], "cli") == []
        launches.append(launch)

    output = _execute(fake_codex, "안녕하세요", "run-pt-clean", on_launch=on_launch)

    assert output.outcome is RunOutcome.COMPLETED
    assert (output.residual_activity, output.residual_basis) == ("none", "job_empty")
    assert output.stop_reason is None
    assert launches and launches[0]["job_name"].startswith("Local\\hads-run-")
    assert launches[0]["kill_on_close"] is True and launches[0]["pid"]
    assert output.usage["tokens"]["input_tokens"] == 11


def test_a_stop_signal_ends_the_cli_tree_mid_run(fake_codex):
    """AC-3 — 중단 신호가 오면 트리를 끝내고 `cancelled` + `none`(`job_terminated`) 이다.
    끊긴 데까지의 원시 출력은 남는다."""
    stop = threading.Event()
    result: dict = {}

    def run():
        result["output"] = _execute(
            fake_codex, "HADS_FAKE_SLEEP=90 기다려 주세요", "run-pt-stop", stop_event=stop
        )

    worker = threading.Thread(target=run)
    started = time.monotonic()
    worker.start()
    deadline = time.monotonic() + 30
    while not _pids(fake_codex["pids"], "grandchild") and time.monotonic() < deadline:
        time.sleep(0.1)
    grandchildren = _pids(fake_codex["pids"], "grandchild")
    assert grandchildren, "가짜 CLI 가 손자 프로세스를 만들지 못했다"
    stop.set()
    worker.join(timeout=60)
    assert not worker.is_alive()

    output = result["output"]
    assert output.outcome is RunOutcome.CANCELLED
    assert output.stop_reason == "stop_requested"
    assert (output.residual_activity, output.residual_basis) == ("none", "job_terminated")
    assert output.residual_terminated >= 2
    assert time.monotonic() - started < 45  # 90초 실행을 기다리지 않았다
    for pid in grandchildren + _pids(fake_codex["pids"], "cli"):
        assert _wait_dead(pid), pid
    raw = (fake_codex["raw"] / "run-pt-stop.stdout.jsonl").read_text(encoding="utf-8")
    assert "thread.started" in raw and "turn.completed" not in raw


def test_leftover_processes_of_a_finished_cli_are_ended_and_counted(fake_codex):
    """AC-4 — 정상 종료한 CLI 가 남긴 프로세스를 끝내고 그 수를 결과에 남긴다."""
    output = _execute(fake_codex, "HADS_FAKE_LEAVE_CHILD", "run-pt-leave")
    assert output.outcome is RunOutcome.COMPLETED
    assert (output.residual_activity, output.residual_basis) == ("none", "job_terminated")
    assert output.residual_terminated >= 1
    for pid in _pids(fake_codex["pids"], "leftover"):
        assert _wait_dead(pid), pid
    assert b"residual_activity=none (job_terminated" in output.output_body


def test_a_failing_launch_record_keeps_the_cli_from_running(fake_codex):
    """AC-5 — 시작 기록을 남기지 못하면 CLI 를 재개하지 않는다."""

    class Refused(RuntimeError):
        pass

    def on_launch(_launch):
        raise Refused("원장에 쓰지 못했다")

    with pytest.raises(Refused):
        _execute(fake_codex, "안녕하세요", "run-pt-refused", on_launch=on_launch)
    time.sleep(0.5)
    assert _pids(fake_codex["pids"], "cli") == []


def test_capabilities_say_which_cli_was_proven_to_stop(fake_codex, monkeypatch):
    """AC-19 — 트리 제어는 OS 수단이지만 **실제 CLI 로 실증한 도구만** `cancel_confirmed` 다."""
    codex = {r["capability"]: r for r in cli_adapter.capabilities_for("codex")}
    assert codex["process_tree_control"]["state"] == "verified"
    assert codex["cancel_confirmed"]["state"] == "verified"
    assert "UI-02" in codex["cancel_confirmed"]["source"]
    # claude 는 실제로 중단해 보지 않았다 — 설치돼 있어도 `unknown` 이다(D-76 "CLI별 실증").
    monkeypatch.setattr(cli_adapter, "resolve_executable", lambda _tool: str(fake_codex["cmd"]))
    claude = {r["capability"]: r for r in cli_adapter.capabilities_for("claude")}
    assert claude["process_tree_control"]["state"] == "verified"
    assert claude["cancel_confirmed"]["state"] == "unknown"
