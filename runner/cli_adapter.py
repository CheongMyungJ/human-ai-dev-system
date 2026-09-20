"""설치된 코딩 CLI에 붙는 제품 어댑터 (P2-03).

P1에서 확인한 것을 제품 경로로 옮긴다. **새로 정한 것은 없다** — 명령 구성·권한
매핑·이벤트 스키마는 모두 [P1-02](../p1/evidence/P1-02-results.md)·
[P1-03](../p1/evidence/P1-03-results.md)의 실측 결과이고, 입력·이벤트·결과는
[공통 실행 계약](../p1-environment-contract.md) 6~8절 그대로다.

이 단계가 지키는 경계:

  **읽기 권한만 배정한다.** `workspace_write` 매핑은 P1에서 확인했지만 제어부가
  이 단계에서 배정하지 않는다(진입 검사에서 거부). 여기서 매핑을 지우지는 않는데,
  지우면 "지원하지 않는다"가 되어 사실과 달라지기 때문이다.

  **매핑할 수 없는 조합은 실행을 거부한다.** 더 넓은 권한으로 조용히 대체하지 않는다.

  **종료 코드만으로 완료를 선언하지 않는다.** 이벤트·결과물을 함께 보고 판정한다.

  **자격증명을 읽지도 주입하지도 않는다.** 로그인은 CLI 자신의 설정에 있다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from domain.models import CapabilityState, EventType, Permission, RunOutcome
from runner import cli_events

#: 추상 권한 → 실제 CLI 인자. p1-environment-contract.md 6절과 P1-02 관측 결과.
#:
#: Codex는 sandbox 축, Claude는 도구 목록·권한 모드 축으로 권한을 표현한다.
#: 두 축을 같은 것으로 취급하지 않고 추상 값에서 각각 매핑한다.
PERMISSION_MAP: dict[str, dict[str, list[str]]] = {
    "codex": {
        Permission.READ_ONLY.value: ["--sandbox", "read-only"],
        Permission.WORKSPACE_WRITE.value: ["--sandbox", "workspace-write"],
    },
    "claude": {
        # `--tools` 제한은 내장 도구만 줄이고 MCP 서버 도구는 그대로 남는다(P1-02 #9·#10).
        # 사용자 설정의 MCP 서버가 허용하지 않은 외부 쓰기를 하지 못하도록
        # `--strict-mcp-config` 를 함께 준다.
        Permission.READ_ONLY.value: [
            "--permission-mode", "manual",
            "--permission-prompts", "none",
            "--strict-mcp-config",
            "--tools", "Read,Grep,Glob",
        ],
        Permission.WORKSPACE_WRITE.value: [
            "--permission-mode", "acceptEdits",
            "--permission-prompts", "none",
            "--strict-mcp-config",
        ],
    },
}

DEFAULT_MODE = {"codex": "exec", "claude": "print"}

#: 이 어댑터가 다루는 도구. OpenCode는 설치 흔적이 없어 여기 없다(P1-04).
SUPPORTED_TOOLS = tuple(PERMISSION_MAP)


class AdapterError(RuntimeError):
    """실행을 시작할 수 없다. 더 넓은 권한이나 다른 도구로 대체하지 않는다."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def resolve_executable(tool_id: str) -> str | None:
    """PATH에서 실제로 해석되는지 확인한다.

    Windows에서는 npm 전역 설치가 `.ps1`/`.cmd` 로 오므로 `shutil.which` 의 결과를
    그대로 쓴다. 해석되지 않으면 `None` 이며 **미설치와 PATH 조회 실패를 구분하지
    못한다는 점은 그대로 남긴다**(P1-01 판정 규칙).
    """
    return shutil.which(tool_id)


def build_command(tool_id: str, mode: str, permission: Permission, workspace: Path) -> list[str]:
    """추상 실행 요청을 실제 CLI 인자로 바꾼다.

    **프롬프트는 인자가 아니라 stdin으로 넘긴다.** P1-02에서 Claude의 `--tools` 처럼
    값을 여러 개 받는 옵션이 뒤따르는 위치 인자를 삼키는 것을 관측했다. Windows
    명령줄 길이·인용 문제도 같이 피한다.
    """
    mapping = PERMISSION_MAP.get(tool_id)
    if mapping is None:
        raise AdapterError(f"어댑터가 없는 도구: {tool_id}")
    args = mapping.get(permission.value)
    if args is None:
        raise AdapterError(
            f"매핑 없음: tool={tool_id} permission={permission.value}."
            " 권한을 임의로 확대하지 않고 실행하지 않는다"
        )
    exe = resolve_executable(tool_id)
    if exe is None:
        raise AdapterError(f"{tool_id} 를 PATH에서 찾지 못했다")

    if tool_id == "codex" and mode == "exec":
        return [exe, "exec", "--json", "--skip-git-repo-check", "-C", str(workspace), *args]
    if tool_id == "claude" and mode == "print":
        return [exe, "-p", "--output-format", "stream-json", "--verbose", *args]
    raise AdapterError(f"지원하지 않는 조합: tool={tool_id} mode={mode}")


def observed_version(tool_id: str) -> str | None:
    """실행 시점의 CLI 버전. 두 CLI 모두 자동 업데이트가 켜져 있어 매번 확인한다."""
    exe = resolve_executable(tool_id)
    if exe is None:
        return None
    try:
        proc = subprocess.run(
            [exe, "--version"], capture_output=True, timeout=60, text=True, encoding="utf-8"
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (proc.stdout or proc.stderr or "").strip().splitlines()[0] if proc.returncode == 0 else None


def capabilities_for(tool_id: str) -> list[dict[str, Any]]:
    """이 PC에서 이 도구가 지금 무엇을 할 수 있는지 보고한다.

    **`verified` 는 실측 근거가 있는 것만이다.** 설치 여부는 지금 직접 확인하고,
    나머지는 P1-02·P1-03에서 실제로 관측한 값을 근거 위치와 함께 올린다.
    확인하지 않은 능력은 `unknown` 이며 도움말에만 있는 것은 `doc_only` 다
    (p1-environment-contract.md 8절).
    """
    exe = resolve_executable(tool_id)
    installed = exe is not None
    version = observed_version(tool_id) if installed else None
    mode = DEFAULT_MODE.get(tool_id, "unknown")
    source_p102 = "P1-02 실증 결과 (p1/evidence/P1-02-results.md)"
    source_p103 = "P1-03 실증 결과 (p1/evidence/P1-03-results.md)"
    here = f"P2-03 Runner 기동 시 확인: {version or 'PATH에서 해석되지 않음'}"

    def cap(name: str, state: CapabilityState, source: str) -> dict[str, Any]:
        return {
            "tool_id": tool_id,
            "mode": mode,
            "capability": name,
            "state": state.value,
            "source": source,
        }

    rows = [
        cap(
            "installed",
            CapabilityState.VERIFIED if installed else CapabilityState.UNSUPPORTED,
            here,
        ),
        # **이 도구가 코딩 CLI인가.** P2-01의 골격 실행기와 구별하기 위해 둔다.
        # 의도 초안 작성과 의미 검토는 실제 AI가 해야 하고, 그 판단을 화면이 아니라
        # 제어부가 이 보고를 보고 한다(controller/admission.py).
        cap(
            "coding_cli",
            CapabilityState.VERIFIED if installed else CapabilityState.UNSUPPORTED,
            here,
        ),
    ]
    if not installed:
        # 미설치를 사용 가능으로 표시하지 않는다. 다른 능력은 지금 확인할 수 없다.
        return rows

    for permission, state, source in (
        (Permission.READ_ONLY, CapabilityState.VERIFIED, source_p102),
        (Permission.WORKSPACE_WRITE, CapabilityState.VERIFIED, source_p102),
        (Permission.EXPLICIT_ESCALATED, CapabilityState.UNKNOWN, "확인하지 않음"),
    ):
        mapped = PERMISSION_MAP[tool_id].get(permission.value) is not None
        rows.append(
            cap(
                f"permission:{permission.value}",
                state if mapped else CapabilityState.UNSUPPORTED,
                source if mapped else "이 어댑터에 매핑이 없다",
            )
        )

    rows += [
        cap("structured_events", CapabilityState.VERIFIED, source_p102),
        cap("session_identity", CapabilityState.VERIFIED, source_p102),
        cap("tool_boundary_observed", CapabilityState.VERIFIED, source_p102),
        cap("safe_stop_next_call", CapabilityState.VERIFIED, source_p103 + " (조건부)"),
        cap("session_resume", CapabilityState.DOC_ONLY, "--help 만 확인"),
        cap("cancel_confirmed", CapabilityState.UNKNOWN, source_p103 + ": 프로세스 잔류 관측"),
    ]
    rows.append(
        cap(
            "usage_reporting",
            CapabilityState.VERIFIED,
            source_p102 + (" — 토큰만, 비용 없음" if tool_id == "codex" else " — 토큰 + 비용"),
        )
    )
    return rows


@dataclass
class ExecutionOutput:
    """`runner.executor.LocalEchoExecutor` 와 같은 결과 모양.

    실행기를 바꿔도 제어부가 달라지지 않게 하기 위해 계약을 공유한다(NFR-07).
    """

    events: list[dict[str, Any]]
    output_body: bytes
    outcome: RunOutcome
    exit_code: int | None
    usage: Any
    residual_activity: str
    session_ref: str | None = None
    observed_tool_version: str | None = None
    final_message: str = ""
    unmapped: list[str] | None = None


class CliExecutor:
    """설치된 코딩 CLI를 자식 프로세스로 실행한다.

    `effects_dir` 에 실행 1회마다 한 줄을 남기는 것은 P2-01과 같다. 중복 실행 여부를
    로그가 아니라 **관측 가능한 부수효과**로 판정하기 위해서다.
    """

    def __init__(self, effects_dir: Path, timeout: float = 600.0) -> None:
        self.effects_dir = effects_dir
        self.effects_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout

    # 부수효과 기록은 P2-01 실행기와 같은 규칙을 쓴다.
    def record_effect(self, case_id: str, run_id: str) -> Path:
        safe = case_id.replace("/", "_").replace("\\", "_")
        path = self.effects_dir / f"{safe}.log"
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f"{_now()}\t{run_id}\n")
            fh.flush()
            os.fsync(fh.fileno())
        return path

    def count_effects(self, case_id: str) -> int:
        safe = case_id.replace("/", "_").replace("\\", "_")
        path = self.effects_dir / f"{safe}.log"
        if not path.exists():
            return 0
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())

    def execute(
        self,
        run_id: str,
        case_id: str,
        prompt: str,
        tool_id: str,
        mode: str,
        permission: Permission,
        workspace: Path,
        raw_dir: Path | None = None,
    ) -> ExecutionOutput:
        command = build_command(tool_id, mode, permission, workspace)
        version = observed_version(tool_id)
        if not workspace.is_dir():
            # 없는 작업공간을 만들어 주지 않는다. 프로젝트가 가리키는 저장소가
            # 이 PC에 없다는 사실을 빈 디렉터리로 가려서는 안 된다.
            raise AdapterError(f"작업공간이 이 호스트에 없다: {workspace}")

        self.record_effect(case_id, run_id)

        stdout_lines: list[str] = []
        stderr_lines: list[str] = []

        def consume(pipe, sink: list[str], raw_path: Path | None) -> None:
            # 원문은 바이트 그대로 남기고 해석용 복사본만 디코딩한다. 텍스트 모드로
            # 읽으면 UTF-8이 아닌 바이트에서 원문이 복구 불가능하게 손상된다(P1-02 관측).
            handle = open(raw_path, "wb") if raw_path else None
            try:
                for line in pipe:
                    if handle:
                        handle.write(line)
                    sink.append(line.decode("utf-8", errors="replace").rstrip("\r\n"))
            finally:
                if handle:
                    handle.close()

        try:
            proc = subprocess.Popen(
                command,
                cwd=str(workspace),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            raise AdapterError(f"프로세스를 시작하지 못했다: {exc}") from exc

        threads = [
            threading.Thread(
                target=consume,
                args=(proc.stdout, stdout_lines, raw_dir / f"{run_id}.stdout.jsonl" if raw_dir else None),
                daemon=True,
            ),
            threading.Thread(
                target=consume,
                args=(proc.stderr, stderr_lines, raw_dir / f"{run_id}.stderr.log" if raw_dir else None),
                daemon=True,
            ),
        ]
        for t in threads:
            t.start()

        assert proc.stdin is not None
        proc.stdin.write(prompt.encode("utf-8"))
        proc.stdin.close()

        timed_out = False
        try:
            exit_code = proc.wait(timeout=self.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            exit_code = proc.wait()
        for t in threads:
            t.join(timeout=10)

        stream = cli_events.normalize(tool_id, stdout_lines)
        for event in stream.events:
            if not event["ts"]:
                event["ts"] = _now()

        outcome = self._judge(stream, exit_code, timed_out)
        body = self._compose_output(
            run_id, case_id, tool_id, mode, permission, version, exit_code, outcome, stream
        )
        return ExecutionOutput(
            events=stream.events,
            output_body=body,
            outcome=outcome,
            exit_code=exit_code,
            usage=stream.usage,
            # 강제 종료는 안전 중지가 아니다. 자식 프로세스가 남았는지 확인할 수단이
            # 없으므로 확인하지 않은 것을 "없음"으로 적지 않는다(P1-03 3절).
            residual_activity="unknown",
            session_ref=stream.session_ref,
            observed_tool_version=version,
            final_message=stream.final_message,
            unmapped=stream.unmapped,
        )

    @staticmethod
    def _judge(stream: cli_events.NormalizedStream, exit_code: int | None, timed_out: bool) -> RunOutcome:
        """결과를 판정한다. **종료 코드만으로 완료를 선언하지 않는다**(FR-28).

        이벤트에 `run_finished` 가 있고 오류 보고가 없으며 최종 메시지가 실제로
        만들어졌을 때만 `completed` 다. 그 밖은 `failed` 이거나, 판단할 근거가
        없으면 `unknown` 으로 남긴다 — `unknown` 은 정식 값이며 실패로도 성공으로도
        바꾸지 않는다(p1-environment-contract 7.2절).
        """
        if timed_out:
            return RunOutcome.UNKNOWN
        finished = any(e["type"] == EventType.RUN_FINISHED.value for e in stream.events)
        if stream.reported_error:
            return RunOutcome.FAILED
        if exit_code not in (0, None):
            return RunOutcome.FAILED
        if finished and stream.final_message.strip():
            return RunOutcome.COMPLETED
        if not stream.events:
            return RunOutcome.UNKNOWN
        return RunOutcome.UNKNOWN

    @staticmethod
    def _compose_output(
        run_id: str,
        case_id: str,
        tool_id: str,
        mode: str,
        permission: Permission,
        version: str | None,
        exit_code: int | None,
        outcome: RunOutcome,
        stream: cli_events.NormalizedStream,
    ) -> bytes:
        """실행 결과 원문. **Runner에 저장되고 제어부에는 참조만 올라간다.**"""
        header = (
            f"run_id={run_id}\n"
            f"case_id={case_id}\n"
            f"tool={tool_id}/{mode} permission={permission.value}\n"
            f"observed_tool_version={version or 'unknown'}\n"
            f"session_ref={stream.session_ref or 'not_reported'}\n"
            f"exit_code={exit_code}\n"
            f"outcome={outcome.value}\n"
            f"normalized_events={len(stream.events)} unmapped={len(stream.unmapped)}\n"
            f"executed_at={_now()}\n"
            "--- final message ---\n"
        )
        return (header + stream.final_message).encode("utf-8")
