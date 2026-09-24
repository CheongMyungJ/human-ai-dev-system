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
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from domain.models import CapabilityState, EventType, Permission, RunOutcome
from runner import cli_events, process_tree

#: 추상 권한 → 실제 CLI 인자. p1-environment-contract.md 6절과 P1-02 관측 결과.
#:
#: Codex는 sandbox 축, Claude는 도구 목록·권한 모드 축으로 권한을 표현한다.
#: 두 축을 같은 것으로 취급하지 않고 추상 값에서 각각 매핑한다.
#:
#: **D-91(사용자 결정 2026-09-24, 이슈 #3): 쓰기 실행에는 CLI 샌드박스를 두지 않는다.** codex 의 Windows 제한
#: 토큰 샌드박스가 사용자 프로필 아래의 도구(JDK·Python)를 읽지 못해 구현·검증이 빌드·시험을 돌리지 못했고
#: (p4/evidence/P4-ENV-results.md), 폴더별 ACL 우회는 도구가 늘 때마다 같은 실패를 겪게 한다. 기능이 동작하는
#: 것이 우선이며 읽기 전용 실행만 샌드박스를 유지한다. 받아들인 손실(사용자 수용): 쓰기 실행은 사용자 계정
#: 권한으로 돌아 worktree 밖·자격증명에 닿고 AI 의 직접 push 를 막지 못한다 — 제품의 게시 규칙(P5)은 그대로다.
PERMISSION_MAP: dict[str, dict[str, list[str]]] = {
    "codex": {
        Permission.READ_ONLY.value: ["--sandbox", "read-only"],
        Permission.WORKSPACE_WRITE.value: ["--sandbox", "danger-full-access"],
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
        # D-91. 권한 확인을 건너뛴다(OS 샌드박스는 Windows 에 없다). `--strict-mcp-config` 는 남긴다 — 로컬
        # 환경이 아니라 사용자 설정의 외부 서비스 MCP 도구를 막는 것이라 이번 문제와 무관하고, 풀면 외부
        # 게시 경로가 하나 더 열린다(이슈 #3 "남는 제약", plan 의 상세 설계 선택).
        Permission.WORKSPACE_WRITE.value: [
            "--permission-mode", "bypassPermissions",
            "--permission-prompts", "none",
            "--strict-mcp-config",
        ],
    },
}

#: D-91. 쓰기 실행에 CLI 샌드박스가 없다는 사실의 근거 문구(능력 보고·화면이 그대로 보인다).
WRITE_SANDBOX_NOTE = (
    "D-91(2026-09-24, 이슈 #3): 쓰기 실행에는 CLI 샌드박스가 없다 — 사용자 계정 권한으로 돈다"
    " (읽기 전용 실행만 샌드박스 유지; p4/evidence/P4-ENV-results.md)"
)

DEFAULT_MODE = {"codex": "exec", "claude": "print"}

#: 실제 CLI 로 **중단 뒤 트리 종료를 확인한** 도구와 그 근거(UI-02). 여기 없는 도구는
#: `cancel_confirmed = unknown` 이다 — 같은 OS 수단을 쓰더라도 그 CLI 로 실증하지 않았다(D-76).
CANCEL_CONFIRMED_EVIDENCE: dict[str, str] = {
    "codex": (
        "UI-02 실증: codex-cli 0.154.0 실행 중 요청 중단·Runner 강제 종료 뒤 트리"
        "(cmd→node→codex.exe→명령 실행기→pwsh) 종료를 OS 목록으로 확인"
        " (ui/evidence/UI-02-results.md 3절)"
    ),
}

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
        # D-91. 쓰기 권한은 매핑돼 있지만 그 매핑은 **샌드박스가 아니다** — 근거가 그 사실을 말한다.
        (Permission.WORKSPACE_WRITE, CapabilityState.VERIFIED, WRITE_SANDBOX_NOTE),
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
        # D-91. **막지 못하는 것을 막는다고 적지 않는다.** 쓰기 실행의 CLI 샌드박스는 없다.
        cap("write_sandbox", CapabilityState.UNSUPPORTED, WRITE_SANDBOX_NOTE),
        cap("structured_events", CapabilityState.VERIFIED, source_p102),
        cap("session_identity", CapabilityState.VERIFIED, source_p102),
        cap("tool_boundary_observed", CapabilityState.VERIFIED, source_p102),
        cap("safe_stop_next_call", CapabilityState.VERIFIED, source_p103 + " (조건부)"),
        cap("session_resume", CapabilityState.DOC_ONLY, "--help 만 확인"),
        # **UI-02: 트리 종료와 그 확인은 OS 의 job object 가 한다.** 도구와 무관한 수단이지만
        # CLI 가 이탈(breakaway)을 요구하면 실행 자체가 막히므로 CLI 별 실증을 따로 적는다.
        cap(
            "process_tree_control",
            CapabilityState.VERIFIED if process_tree.IS_WINDOWS else CapabilityState.UNSUPPORTED,
            (
                "UI-02: Windows job object(KILL_ON_JOB_CLOSE, 이탈 불허) 트리 종료·활성 0 확인"
                " — tests/test_process_control.py"
                if process_tree.IS_WINDOWS
                else "UI-02: 비 Windows 는 트리 제어를 지원하지 않는다"
            ),
        ),
        cap(
            "cancel_confirmed",
            *(
                (CapabilityState.VERIFIED, CANCEL_CONFIRMED_EVIDENCE[tool_id])
                if process_tree.IS_WINDOWS and tool_id in CANCEL_CONFIRMED_EVIDENCE
                else (CapabilityState.UNKNOWN, source_p103 + ": 프로세스 잔류 관측")
            ),
        ),
        # **P3-03: 지원하지 않는 것을 지원하지 않는다고 보고한다.** Case 전용
        # worktree 는 파일 배치의 분리이며 다른 경로·공유 자격증명 접근을 막지
        # 못한다(D-44, execution-workspace-review 2절). 실행 전후 대조로 경계 밖
        # 변경을 **감지할 수는 있지만** 그것은 격리가 아니다.
        cap(
            "os_level_isolation",
            CapabilityState.UNSUPPORTED,
            "D-44: worktree 는 파일 배치 분리이며 OS 격리가 아니다",
        ),
        cap(
            "workspace_change_detection",
            CapabilityState.VERIFIED,
            "P3-03: 실행 전후 HEAD·작업 트리 대조 (막는 것이 아니라 드러내는 것)",
        ),
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
    #: 실행 전후 작업공간 대조의 결과(P3-03). 실행기가 아니라 **Runner 가 채운다** —
    #: 무엇이 바뀌었는지는 CLI 의 보고가 아니라 git 이 답한다. 관측하지 않았으면
    #: `None` 이며 그것은 "변경 없음"이 아니라 **모른다**이다.
    workspace_effect: dict[str, Any] | None = None
    #: UI-02. 잔류 활동 값의 **근거**(`process_tree.BASIS_*`). 없으면 근거를 보내지 않는다.
    residual_basis: str | None = None
    #: UI-02. 확인하면서 종료한 프로세스 수.
    residual_terminated: int | None = None
    #: UI-02. 실행을 끊은 이유(`stop_requested` · `timeout`). 끊지 않았으면 `None`.
    stop_reason: str | None = None
    #: P4-10(D-95). 이 호출에 실제로 적용한 제한 시간(초). 결과 보고에 실린다.
    timeout_seconds: float | None = None


#: P4-10(D-95, 사용자 결정 2026-09-24). 배정이 제한 시간을 싣지 않을 때(옛 제어부)의 기본값 — 모든 실행 1시간.
#: 그 전에는 600초 고정이었고 긴 빌드·에뮬레이터 검증이 매번 끊겼다(이슈 #8).
DEFAULT_TIMEOUT_SECONDS = 3600.0


class CliExecutor:
    """설치된 코딩 CLI를 자식 프로세스로 실행한다.

    `effects_dir` 에 실행 1회마다 한 줄을 남기는 것은 P2-01과 같다. 중복 실행 여부를
    로그가 아니라 **관측 가능한 부수효과**로 판정하기 위해서다.
    """

    def __init__(
        self,
        effects_dir: Path,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
        confirm_timeout: float = process_tree.DEFAULT_CONFIRM_TIMEOUT,
    ) -> None:
        self.effects_dir = effects_dir
        self.effects_dir.mkdir(parents=True, exist_ok=True)
        self.timeout = timeout
        #: UI-02. 트리를 끝낸 뒤 활성 프로세스 0 을 기다리는 시간.
        self.confirm_timeout = confirm_timeout

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
        *,
        on_launch: Callable[[dict[str, Any]], None] | None = None,
        stop_event: threading.Event | None = None,
        job_name: str | None = None,
        timeout: float | None = None,
    ) -> ExecutionOutput:
        """CLI 를 실행한다. **UI-02: 프로세스 트리를 job 안에서 돌리고 끝을 확인한다.**

        P4-10(D-95). `timeout` 은 이 호출의 제한 시간(초)이다 — 제어부가 실행을 만들 때 정해 배정에 실은 값.
        없으면 실행기의 기본값(1시간). 걸리면 `stop_reason = timeout`·결과 `unknown`.

        순서가 규칙이다(Windows).

            1. job 을 만든다(`KILL_ON_JOB_CLOSE`, 이탈 불허). 못 만들면 실행하지 않는다
            2. CLI 를 **일시 정지 상태로** 만들어 job 에 넣는다
            3. `on_launch` 로 시작 기록을 남긴다 — 호출자가 원장에 fsync 한다
            4. 재개한다. 여기서부터 CLI 가 돈다
            5. 루트가 끝나거나, 중단 신호가 오거나, 시간을 넘길 때까지 기다린다
            6. job 에 남은 것을 종료하고 **활성 0 을 확인한다**(`terminate_and_confirm`)
            7. job 핸들을 닫는다 — 그래도 남은 것이 있으면 OS 가 끝낸다

        중단 신호로 끊은 실행은 `cancelled`, 시간 초과는 `unknown` 이다. 원시 출력·이벤트는
        끊긴 데까지 그대로 남는다. 비 Windows 는 트리 제어가 없어 잔류가 `unknown` 이다.
        """
        command = build_command(tool_id, mode, permission, workspace)
        version = observed_version(tool_id)
        if not workspace.is_dir():
            # 없는 작업공간을 만들어 주지 않는다. 프로젝트가 가리키는 저장소가
            # 이 PC에 없다는 사실을 빈 디렉터리로 가려서는 안 된다.
            raise AdapterError(f"작업공간이 이 호스트에 없다: {workspace}")

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
                        # 원시 출력은 재시작 복구(P4-04)의 입력이다. 줄마다 내보낸다.
                        handle.flush()
                    sink.append(line.decode("utf-8", errors="replace").rstrip("\r\n"))
            finally:
                if handle:
                    handle.close()

        popen_kwargs: dict[str, Any] = {
            "cwd": str(workspace),
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "stdin": subprocess.PIPE,
            "bufsize": 0,
        }
        tree: process_tree.JobTree | None = None
        if process_tree.IS_WINDOWS:
            # 못 만들면 `TreeControlUnavailable` 이 올라간다. **멈출 수 없는 CLI 를 조용히
            # 실행하지 않는다** — 호출자가 시작하지 않은 실행으로 보고한다.
            tree = process_tree.JobTree.create(
                job_name or process_tree.job_name_for("runner", run_id, 0)
            )
        try:
            try:
                if tree is not None:
                    proc = tree.spawn_suspended(command, **popen_kwargs)
                    launch: dict[str, Any] = {
                        "job_name": tree.name,
                        "kill_on_close": True,
                        **process_tree.JobTree.launch_identity(proc),
                    }
                else:
                    proc = subprocess.Popen(command, **popen_kwargs)
                    launch = {"pid": proc.pid, "kill_on_close": False}
            except OSError as exc:
                raise AdapterError(f"프로세스를 시작하지 못했다: {exc}") from exc
            launch["launched_at"] = _now()
            if on_launch is not None:
                # 재개 전에 기록한다. 여기서 실패하면 CLI 는 한 줄도 돌지 않았고, job 을 닫을
                # 때 정지된 프로세스가 끝난다.
                on_launch(launch)
            self.record_effect(case_id, run_id)
            if tree is not None:
                process_tree.JobTree.resume(proc)

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
            try:
                proc.stdin.write(prompt.encode("utf-8"))
                proc.stdin.close()
            except OSError:
                # CLI 가 입력을 받기 전에 끝났다. 판정은 아래에서 이벤트·종료 코드로 한다.
                pass

            applied_timeout = float(timeout) if timeout else float(self.timeout)
            deadline = time.monotonic() + applied_timeout
            stop_reason: str | None = None
            exit_code: int | None = None
            while True:
                try:
                    exit_code = proc.wait(timeout=0.2)
                    break
                except subprocess.TimeoutExpired:
                    pass
                if stop_event is not None and stop_event.is_set():
                    stop_reason = "stop_requested"
                    break
                if time.monotonic() >= deadline:
                    stop_reason = "timeout"
                    break

            if tree is not None:
                if stop_reason is None:
                    # 루트와 함께 끝나는 중인 자식이 잔류로 세어지지 않게 잠깐 기다린다.
                    # 이 뒤에도 남은 것이 그 실행의 잔류 활동이다.
                    tree.wait_empty(min(1.0, self.confirm_timeout))
                # **남은 것을 끝내고 0 을 확인한다.** 중단이면 루트까지, 정상 종료면 루트가
                # 남긴 잔류 프로세스를. 처음부터 0 이면 아무 것도 종료하지 않는다.
                observation = tree.terminate_and_confirm(self.confirm_timeout)
            else:
                if stop_reason is not None:
                    proc.kill()
                observation = process_tree.ResidualObservation(
                    "unknown", process_tree.BASIS_NOT_OBSERVABLE
                )
            if exit_code is None:
                try:
                    exit_code = proc.wait(timeout=self.confirm_timeout)
                except subprocess.TimeoutExpired:
                    exit_code = None
            for t in threads:
                t.join(timeout=10)
        finally:
            if tree is not None:
                tree.close()

        stream = cli_events.normalize(tool_id, stdout_lines)
        for event in stream.events:
            if not event["ts"]:
                event["ts"] = _now()

        if stop_reason == "stop_requested":
            # 끊은 실행은 결과가 아니라 **중단**이다. 끊긴 데까지의 출력이 성공으로 읽히지
            # 않게 판정을 따로 둔다(P1 계약 7.2 의 `cancelled`).
            outcome = RunOutcome.CANCELLED
        else:
            outcome = self._judge(stream, exit_code, stop_reason == "timeout")
        body = self._compose_output(
            run_id, case_id, tool_id, mode, permission, version, exit_code, outcome, stream,
            stop_reason=stop_reason, observation=observation, timeout_seconds=applied_timeout,
        )
        return ExecutionOutput(
            events=stream.events,
            output_body=body,
            outcome=outcome,
            exit_code=exit_code,
            usage=stream.usage,
            # 확인했을 때만 `none` 이다. 트리 제어가 없으면 `unknown` 이다(P1-03 3절).
            residual_activity=observation.residual,
            session_ref=stream.session_ref,
            observed_tool_version=version,
            final_message=stream.final_message,
            unmapped=stream.unmapped,
            residual_basis=observation.basis,
            residual_terminated=observation.terminated,
            stop_reason=stop_reason,
            timeout_seconds=applied_timeout,
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
        stop_reason: str | None = None,
        observation: process_tree.ResidualObservation | None = None,
        timeout_seconds: float | None = None,
    ) -> bytes:
        """실행 결과 원문. **Runner에 저장되고 제어부에는 참조만 올라간다.**"""
        residual = (
            f"{observation.residual} ({observation.basis}, terminated={observation.terminated})"
            if observation is not None
            else "unknown"
        )
        header = (
            f"run_id={run_id}\n"
            f"case_id={case_id}\n"
            f"tool={tool_id}/{mode} permission={permission.value}\n"
            f"observed_tool_version={version or 'unknown'}\n"
            f"session_ref={stream.session_ref or 'not_reported'}\n"
            f"exit_code={exit_code}\n"
            f"outcome={outcome.value}\n"
            f"stop_reason={stop_reason or 'none'}\n"
            f"timeout_seconds={int(timeout_seconds) if timeout_seconds else 'unknown'}\n"
            f"residual_activity={residual}\n"
            f"normalized_events={len(stream.events)} unmapped={len(stream.unmapped)}\n"
            f"executed_at={_now()}\n"
            "--- final message ---\n"
        )
        return (header + stream.final_message).encode("utf-8")
