"""제어부 실행 설정.

데이터 경로는 저장소 아래 `var/controller/` 를 기본으로 하되 환경 변수로 바꿀 수 있다.
시험은 각자 임시 경로를 지정해 서로의 상태를 건드리지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ENV_DATA_ROOT = "HADS_CONTROLLER_DATA"
ENV_HOST = "HADS_CONTROLLER_HOST"
ENV_PORT = "HADS_CONTROLLER_PORT"
ENV_WEB_DIST = "HADS_WEB_DIST"

DEFAULT_HOST = "127.0.0.1"  # 로컬 기본 접점은 루프백이다(implementation-baseline 2절)
DEFAULT_PORT = 8765


@dataclass(frozen=True)
class ControllerConfig:
    data_root: Path
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    web_dist: Path | None = None

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
    return ControllerConfig(
        data_root=data_root,
        host=os.environ.get(ENV_HOST, DEFAULT_HOST),
        port=int(os.environ.get(ENV_PORT, DEFAULT_PORT)),
        web_dist=web_dist,
    )
