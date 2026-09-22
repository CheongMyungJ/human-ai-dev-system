"""제어부·Runner 를 **실제 프로세스로** 띄우고 HTTP 로 몰아 보는 얇은 층.

자동 시험은 `TestClient` 로 같은 코드를 부른다. 여기서 확인하려는 것은 그것이
아니라 **실제 프로세스·실제 CLI·실제 git 저장소**에서 같은 규칙이 지켜지는가다.
그래서 이 층은 제품 코드를 import 하지 않고 HTTP 만 쓴다 — import 하면 제어부
안에서 우회한 호출이 되고, 우회로 확인한 것은 진입 검사를 확인한 것이 아니다.

**실행 id 에 시도마다 달라지는 값을 붙인다.** `create_run()` 은 `run_id` 로
멱등하므로 같은 id 를 재사용하면 이전 시도의 실행이 그대로 돌아온다 — P3-R4 의
라이브가 실제로 그 함정에 빠졌다(R4 결과 6.5).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"


class LiveError(RuntimeError):
    """라이브가 기대와 다르게 끝났다. **덮지 않고 그대로 올린다.**"""


@dataclass
class Log:
    """사람이 읽을 원문 로그. 화면과 파일에 함께 쓴다."""

    path: Path
    _handle: Any = field(default=None, init=False, repr=False)

    def __enter__(self) -> "Log":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handle is not None:
            self._handle.close()

    def __call__(self, message: str = "") -> None:
        print(message, flush=True)
        if self._handle is not None:
            self._handle.write(message + "\n")
            self._handle.flush()

    def head(self, title: str) -> None:
        self("")
        self("=" * 72)
        self(title)
        self("=" * 72)

    def json(self, title: str, value: Any) -> None:
        self(f"--- {title} ---")
        self(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=False))


@dataclass
class Processes:
    """제어부와 Runner. **띄운 것은 반드시 내린다.**"""

    data_root: Path
    log: Log
    port: int = 8790
    runner_id: str = "runner-p3-04-live"
    controller: subprocess.Popen[str] | None = None
    runner: subprocess.Popen[str] | None = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def _env(self, **extra: str) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        env.update(extra)
        return env

    def start(self) -> None:
        controller_data = self.data_root / "controller"
        runner_data = self.data_root / "runner"
        controller_data.mkdir(parents=True, exist_ok=True)
        runner_data.mkdir(parents=True, exist_ok=True)

        self.controller = subprocess.Popen(
            [
                str(PYTHON), "-m", "uvicorn", "controller.app:app",
                "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning",
            ],
            cwd=REPO_ROOT,
            env=self._env(HADS_CONTROLLER_DATA=str(controller_data)),
            stdout=(controller_data / "uvicorn.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._wait_for_health()

        self.runner = subprocess.Popen(
            [str(PYTHON), "-m", "runner.agent"],
            cwd=REPO_ROOT,
            env=self._env(
                HADS_RUNNER_DATA=str(runner_data),
                HADS_RUNNER_ID=self.runner_id,
                HADS_CONTROLLER_URL=self.base_url,
            ),
            stdout=(runner_data / "runner.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.log(f"제어부 pid={self.controller.pid} Runner pid={self.runner.pid}")

    def _wait_for_health(self, timeout: float = 30.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                response = httpx.get(f"{self.base_url}/api/health", timeout=2.0)
                if response.status_code == 200:
                    self.log(f"제어부 health: {response.json()}")
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.3)
        raise LiveError("제어부가 뜨지 않았다")

    def stop(self) -> None:
        for name, proc in (("runner", self.runner), ("controller", self.controller)):
            if proc is None:
                continue
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
            self.log(f"{name} 종료 (returncode={proc.returncode})")

    def kill_controller(self) -> None:
        """**강제 종료.** 정상 종료가 아니라 전원이 끊긴 것과 같은 상태를 만든다."""
        if self.controller is None:
            return
        self.controller.kill()
        self.controller.wait(timeout=10)
        self.log(f"제어부 강제 종료 (returncode={self.controller.returncode})")

    def restart_controller(self) -> None:
        controller_data = self.data_root / "controller"
        self.controller = subprocess.Popen(
            [
                str(PYTHON), "-m", "uvicorn", "controller.app:app",
                "--host", "127.0.0.1", "--port", str(self.port), "--log-level", "warning",
            ],
            cwd=REPO_ROOT,
            env=self._env(HADS_CONTROLLER_DATA=str(controller_data)),
            stdout=(controller_data / "uvicorn-restart.log").open("w", encoding="utf-8"),
            stderr=subprocess.STDOUT,
            text=True,
        )
        self._wait_for_health()


class Api:
    """제어부 HTTP. 실패를 조용히 삼키지 않는다."""

    def __init__(self, base_url: str, log: Log) -> None:
        self.base_url = base_url
        self.log = log
        # 실제 CLI 실행은 분 단위로 걸린다. 짧은 타임아웃은 제품 결함이 아니라
        # 하네스의 결함으로 나타난다.
        self.client = httpx.Client(base_url=base_url, timeout=600.0)

    def close(self) -> None:
        self.client.close()

    def reconnect(self) -> None:
        """연결을 새로 만든다. **제어부를 강제 종료한 뒤에 쓴다.**

        끊긴 프로세스로 열려 있던 연결은 재사용되면 그 자리에서 실패한다. httpx 는
        그것을 다시 시도하지 않으므로, 하네스의 연결 문제가 **제품의 복원 실패로
        보이지 않게** 여기서 끊고 다시 만든다.
        """
        self.client.close()
        self.client = httpx.Client(base_url=self.base_url, timeout=600.0)

    def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self.client.request(method, path, **kwargs)

    def ok(self, method: str, path: str, expect: tuple[int, ...] = (200, 201, 202), **kwargs: Any) -> Any:
        response = self.request(method, path, **kwargs)
        if response.status_code not in expect:
            raise LiveError(
                f"{method} {path} → {response.status_code}\n{response.text[:2000]}"
            )
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.ok("GET", path, expect=(200,), **kwargs)

    def refusals(self, response: httpx.Response) -> list[str]:
        """409 응답에서 사유 코드만 뽑는다. 두 모양을 모두 받는다."""
        try:
            detail = response.json().get("detail")
        except ValueError:
            return []
        if isinstance(detail, dict):
            if "admission" in detail:
                return list(detail["admission"].get("refusals") or [])
            if "refusals" in detail:
                return list(detail["refusals"] or [])
        return []


def wait_until(
    predicate: Any, what: str, timeout: float = 900.0, interval: float = 1.5
) -> Any:
    """Runner 가 일할 때까지 기다린다. **기다림에 상한을 둔다.**"""
    deadline = time.monotonic() + timeout
    last: Any = None
    while time.monotonic() < deadline:
        last = predicate()
        if last:
            return last
        time.sleep(interval)
    raise LiveError(f"{what} 를 {timeout}초 안에 보지 못했다 (마지막 값: {last!r})")


def stamp() -> str:
    """시도마다 달라지는 꼬리표. 멱등 함정을 피한다."""
    return time.strftime("%H%M%S") + f"{int(time.time() * 1000) % 1000:03d}"


def python_for_tests() -> str:
    """시험 저장소에서 테스트를 돌릴 인터프리터.

    저장소 로컬 `.venv` 를 쓴다. 그래야 CLI 가 `pytest` 를 찾을 수 있고, 그
    사실이 검증 실행의 명령 기록에 그대로 남는다.
    """
    return str(PYTHON) if PYTHON.exists() else sys.executable


def force_rmtree(path: Path) -> None:
    """읽기 전용 파일까지 지운다.

    git 의 object 파일은 Windows 에서 읽기 전용이라 `shutil.rmtree` 가 그대로는
    `PermissionError` 로 멈춘다. **이 저장소의 ``var`` 가 아니라 임시 라이브
    경로에만 쓴다.**
    """
    import shutil
    import stat

    if not path.exists():
        return

    def on_error(func: Any, target: str, _exc: Any) -> None:
        Path(target).chmod(stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onexc=on_error)
