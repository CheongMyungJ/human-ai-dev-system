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
    return ControllerConfig(
        data_root=data_root,
        host=os.environ.get(ENV_HOST, DEFAULT_HOST),
        port=int(os.environ.get(ENV_PORT, DEFAULT_PORT)),
        web_dist=web_dist,
        context_inline_limit_bytes=inline_limit,
        runner_stale_seconds=stale_seconds,
    )
