"""제어부 실행 설정.

데이터 경로는 저장소 아래 `var/controller/` 를 기본으로 하되 환경 변수로 바꿀 수 있다.
시험은 각자 임시 경로를 지정해 서로의 상태를 건드리지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from domain.context import DEFAULT_INLINE_LIMIT_BYTES
from domain.run_control import DEFAULT_RUNNER_STALE_SECONDS

REPO_ROOT = Path(__file__).resolve().parent.parent

ENV_DATA_ROOT = "HADS_CONTROLLER_DATA"
ENV_HOST = "HADS_CONTROLLER_HOST"
ENV_PORT = "HADS_CONTROLLER_PORT"
ENV_WEB_DIST = "HADS_WEB_DIST"
#: P4-04. 한 실행의 지시 + 인라인 고정 참조의 한도(바이트). 상세 설계 제안값이다.
ENV_CONTEXT_INLINE_LIMIT = "HADS_CONTEXT_INLINE_LIMIT_BYTES"
#: UI-02. 이만큼(초) heartbeat 가 없으면 PC 미연결로 본다. 상세 설계 제안값이다.
ENV_RUNNER_STALE_SECONDS = "HADS_RUNNER_STALE_SECONDS"
#: UI-03. 사용자 요청을 제어부가 논의 응답으로 자동 처리하는가. 기본 켜짐. 끄면 UI-01 의
#: 명시 처리 계약(처리하는 쪽이 실행을 만들고 종료를 적는다) 그대로다.
ENV_AUTO_PROCESS_REQUESTS = "HADS_AUTO_PROCESS_REQUESTS"
#: P4-05. 업무화 뒤 업무 단계의 다음 작업을 제어부가 스스로 잇는가. 기본 켜짐. 끄면 요청 처리기는
#: 논의 응답·업무화까지만 하고, 업무 단계는 관리 화면·하네스가 진행한다(UI-03 계약). 처리기가
#: 꺼져 있으면 이 값과 무관하게 진행기도 꺼진다.
ENV_AUTO_PROGRESS_WORK = "HADS_AUTO_PROGRESS_WORK"

DEFAULT_HOST = "127.0.0.1"  # 로컬 기본 접점은 루프백이다(implementation-baseline 2절)
DEFAULT_PORT = 8765


@dataclass(frozen=True)
class ControllerConfig:
    data_root: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    web_dist: Path | None = None
    #: P4-04. 이 값을 넘으면 보조 입력만 드러내어 생략하고, 핵심만으로 넘으면 보류한다.
    context_inline_limit_bytes: int = DEFAULT_INLINE_LIMIT_BYTES
    #: UI-02. PC 미연결 판정 기준(초). 미연결 PC 로 가는 사용자 입력은 받지 않는다(D-75).
    runner_stale_seconds: float = DEFAULT_RUNNER_STALE_SECONDS
    #: UI-03. 요청 처리기. 켜져 있으면 저장된 사용자 요청마다 읽기 전용 논의 응답 하나를 만들고
    #: 그 결과로 요청을 끝낸다. 운영 설정이며 시험 분기가 아니다.
    auto_process_requests: bool = True
    #: P4-05. 업무 단계 진행기. 처리기와 같은 종류의 운영 설정이며 시험 분기가 아니다.
    auto_progress_work: bool = True

    @property
    def progress_enabled(self) -> bool:
        """진행기가 켜져 있는가 — 처리기가 켜져 있고 이 설정도 켜져 있을 때다."""
        return self.auto_process_requests and self.auto_progress_work

    @property
    def db_path(self) -> Path:
        return self.data_root / "controller.sqlite3"

    @property
    def log_path(self) -> Path:
        return self.data_root / "controller.log"

    def ensure_dirs(self) -> None:
        self.data_root.mkdir(parents=True, exist_ok=True)


def load_config() -> ControllerConfig:
    data_root = Path(os.environ.get(ENV_DATA_ROOT) or (REPO_ROOT / "var" / "controller"))
    web_dist_raw = os.environ.get(ENV_WEB_DIST)
    if web_dist_raw:
        web_dist: Path | None = Path(web_dist_raw)
    else:
        candidate = REPO_ROOT / "web" / "dist"
        web_dist = candidate if candidate.is_dir() else None
    inline_limit = int(os.environ.get(ENV_CONTEXT_INLINE_LIMIT) or DEFAULT_INLINE_LIMIT_BYTES)
    if inline_limit <= 0:
        # 0 이하의 한도는 모든 실행을 보류시킨다. 기동 시점에 드러낸다 — 진입 검사에서
        # 처음 알게 되면 사람은 모든 실행이 왜 막히는지 찾아다녀야 한다.
        raise ValueError(f"{ENV_CONTEXT_INLINE_LIMIT} must be a positive number of bytes")
    stale_seconds = float(
        os.environ.get(ENV_RUNNER_STALE_SECONDS) or DEFAULT_RUNNER_STALE_SECONDS
    )
    if stale_seconds <= 0:
        # 0 이하면 모든 PC 가 늘 미연결이다. 기동 시점에 드러낸다.
        raise ValueError(f"{ENV_RUNNER_STALE_SECONDS} must be a positive number of seconds")
    auto_raw = (os.environ.get(ENV_AUTO_PROCESS_REQUESTS) or "1").strip().lower()
    if auto_raw not in ("1", "0", "true", "false", "on", "off"):
        # 모르는 값을 켜짐·꺼짐 어느 쪽으로도 읽지 않는다. 기동 시점에 드러낸다.
        raise ValueError(f"{ENV_AUTO_PROCESS_REQUESTS} must be 1 or 0")
    progress_raw = (os.environ.get(ENV_AUTO_PROGRESS_WORK) or "1").strip().lower()
    if progress_raw not in ("1", "0", "true", "false", "on", "off"):
        raise ValueError(f"{ENV_AUTO_PROGRESS_WORK} must be 1 or 0")
    return ControllerConfig(
        data_root=data_root,
        host=os.environ.get(ENV_HOST, DEFAULT_HOST),
        port=int(os.environ.get(ENV_PORT, DEFAULT_PORT)),
        web_dist=web_dist,
        context_inline_limit_bytes=inline_limit,
        runner_stale_seconds=stale_seconds,
        auto_process_requests=auto_raw in ("1", "true", "on"),
        auto_progress_work=progress_raw in ("1", "true", "on"),
    )
