"""Runner 실행 설정."""

from __future__ import annotations

import os
import socket
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ENV_DATA_ROOT = "HADS_RUNNER_DATA"
ENV_RUNNER_ID = "HADS_RUNNER_ID"
ENV_CONTROLLER_URL = "HADS_CONTROLLER_URL"

DEFAULT_RUNNER_ID = "runner-local-1"
DEFAULT_CONTROLLER_URL = "http://127.0.0.1:8765"


@dataclass(frozen=True)
class RunnerConfig:
    runner_id: str
    controller_url: str
    data_root: Path
    host_name: str

    @property
    def artifacts_dir(self) -> Path:
        return self.data_root / "artifacts"

    @property
    def ledger_dir(self) -> Path:
        return self.data_root / "ledger"

    @property
    def effects_dir(self) -> Path:
        """실행 부수효과 기록.

        중복 실행 여부를 로그가 아니라 관측 가능한 부수효과로 판정하기 위해 둔다.
        P1-03이 파일 존재로 판정한 것과 같은 방식이다.
        """
        return self.data_root / "effects"

    @property
    def raw_dir(self) -> Path:
        """CLI가 낸 원문 스트림을 그대로 두는 곳.

        정규화하기 전의 바이트를 남긴다. 분류 규칙이 틀렸을 때 무엇을 봤는지
        되짚을 수 있어야 하기 때문이며, 이것도 **Runner에만** 남는 원문이다.
        """
        return self.data_root / "raw"

    @property
    def worktrees_dir(self) -> Path:
        """Case 전용 worktree 를 두는 자리(P3-03).

        **대상 저장소 안이 아니다.** 저장소 안에 두면 그 파일들이 사용자의 원래
        작업 트리에 미추적 파일로 나타나 자기 변경과 구별할 수 없게 된다
        (FR-08 "기존 사용자 변경을 확인한다", execution-workspace-review 2절).
        """
        return self.data_root / "worktrees"

    def ensure_dirs(self) -> None:
        for path in (
            self.artifacts_dir,
            self.ledger_dir,
            self.effects_dir,
            self.raw_dir,
            self.worktrees_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)


def load_config() -> RunnerConfig:
    runner_id = os.environ.get(ENV_RUNNER_ID, DEFAULT_RUNNER_ID)
    data_root = Path(
        os.environ.get(ENV_DATA_ROOT) or (REPO_ROOT / "var" / "runner" / runner_id)
    )
    return RunnerConfig(
        runner_id=runner_id,
        controller_url=os.environ.get(ENV_CONTROLLER_URL, DEFAULT_CONTROLLER_URL),
        data_root=data_root,
        host_name=socket.gethostname(),
    )
