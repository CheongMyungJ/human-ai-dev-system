"""작업 PC 의 폴더·편집기 열기(UI-04c, D-89).

앱은 문서·diff·버전·근거를 **열람**하고 직접 파일 편집은 외부 편집기가 한다. 브라우저는 작업 PC 가
아닐 수 있으므로 열기는 **작업 PC(Runner)** 가 한다 — 제어부에 남은 요청을 heartbeat 제어로 받아
자기 worktree 를 연다(`runner/agent.py`).

**지원은 확인한 것만 보고한다.** 폴더 열기는 Windows 의 `os.startfile` 을, 편집기는 PATH 의 `code`
(VS Code)를 이 PC 에서 실제로 찾았을 때만 `verified` 다. 다른 OS·다른 편집기는 `unsupported` 로
보고하고 화면은 그 사유를 보인다. `HADS_RUNNER_DESKTOP=off` 면 이 PC 에서 열기를 끈다(둘 다
`unsupported`, 사유는 그 설정) — 자동 시험이 실제 창을 띄우지 않게 하는 데도 쓴다.

열기는 **쓰기 권한이 아니다.** 열린 편집기가 무엇을 하든 시스템의 저장소 쓰기 허용·진입 검사는
그대로이고, 외부 변경은 다음 쓰기 실행 전에 관측해 드러낸다(`workspace.compose_effect`).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Any, Callable

from domain.models import CapabilityState

#: 능력 행의 도구·모드. 코딩 CLI 가 아니라 **이 PC** 의 데스크톱 능력이다.
HOST_TOOL_ID = "runner-host"
HOST_MODE = "desktop"
ENV_DESKTOP = "HADS_RUNNER_DESKTOP"
TARGETS = ("folder", "editor")
CAPABILITY_FOR_TARGET = {"folder": "open_folder", "editor": "open_editor"}
EDITOR_COMMAND = "code"

Opener = Callable[[str, str], None]


def disabled() -> bool:
    return os.environ.get(ENV_DESKTOP, "").strip().lower() == "off"


def detect() -> dict[str, dict[str, str]]:
    """이 PC 에서 무엇을 열 수 있는가 — `{능력: {state, source}}`. 확인하지 않은 것을 `verified` 로 적지 않는다."""
    if disabled():
        source = f"{ENV_DESKTOP}=off (이 PC 에서 열기를 껐다)"
        return {
            "open_folder": {"state": CapabilityState.UNSUPPORTED.value, "source": source},
            "open_editor": {"state": CapabilityState.UNSUPPORTED.value, "source": source},
        }
    if os.name == "nt" and hasattr(os, "startfile"):
        folder = {"state": CapabilityState.VERIFIED.value, "source": "os.startfile (Windows)"}
    else:
        folder = {
            "state": CapabilityState.UNSUPPORTED.value,
            "source": "os.startfile 은 Windows 전용이다 — 이 OS 의 폴더 열기는 확인하지 않았다",
        }
    code = shutil.which(EDITOR_COMMAND)
    if code:
        editor = {"state": CapabilityState.VERIFIED.value, "source": f"{EDITOR_COMMAND} on PATH: {code}"}
    else:
        editor = {
            "state": CapabilityState.UNSUPPORTED.value,
            "source": f"PATH 에 {EDITOR_COMMAND}(VS Code) 가 없다 — 다른 편집기는 확인하지 않았다",
        }
    return {"open_folder": folder, "open_editor": editor}


def capabilities() -> list[dict[str, Any]]:
    """`runner_capability` 행 모양. `default_capabilities()` 가 코딩 CLI 능력에 더한다."""
    return [
        {
            "tool_id": HOST_TOOL_ID,
            "mode": HOST_MODE,
            "capability": capability,
            "state": found["state"],
            "source": found["source"],
        }
        for capability, found in detect().items()
    ]


def supported(target: str) -> tuple[bool, str]:
    """지금 이 PC 에서 그 대상을 열 수 있는가와 근거."""
    found = detect().get(CAPABILITY_FOR_TARGET.get(target, ""), None)
    if found is None:
        return False, f"unknown target: {target}"
    return found["state"] == CapabilityState.VERIFIED.value, found["source"]


def open_path(target: str, path: str) -> None:
    """실제로 연다. 실패는 예외로 남긴다(호출자가 `failed` 로 보고한다). **경로는 호출자가 검증한다.**"""
    ok, source = supported(target)
    if not ok:
        raise RuntimeError(f"unsupported: {source}")
    if target == "folder":
        os.startfile(path)  # type: ignore[attr-defined]  # Windows 에서만 `verified` 다
        return
    if target == "editor":
        command = shutil.which(EDITOR_COMMAND)
        if not command:
            raise RuntimeError(f"unsupported: PATH 에 {EDITOR_COMMAND} 가 없다")
        # 편집기는 붙잡지 않는다 — 이 프로세스가 편집기의 수명을 갖지 않는다.
        subprocess.Popen([command, path], close_fds=True)
        return
    raise RuntimeError(f"unknown target: {target}")
