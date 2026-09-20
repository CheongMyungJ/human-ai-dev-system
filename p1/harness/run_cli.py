"""P1-02 최소 실행 harness.

목적: 설치된 코딩 CLI를 자식 프로세스로 실행하고, 공통 실행 계약 초안
(p1-environment-contract.md 6~7절)의 입력·이벤트·결과를 실제로 만들어 볼 수 있는지
확인한다. 제품 코드가 아니라 P1 실증용 도구다.

원칙:
- 종료 코드만으로 outcome을 completed로 판정하지 않는다.
- 이벤트 원문은 가공 전에 그대로 파일에 남긴다.
- 확인하지 못한 것은 unknown으로 남기고 추정으로 채우지 않는다.
- 자격증명 파일을 읽거나 비밀값을 환경변수로 주입하지 않는다.

사용 예:
    python p1/harness/run_cli.py --tool codex --mode exec \
        --workspace C:\\Temp\\testrepo --permission read_only \
        --prompt "..." --evidence-dir C:\\Temp\\evidence
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

# --- 공통 계약 -> CLI 인자 매핑 ------------------------------------------------
# 추상 권한 값은 p1-environment-contract.md 6절을 따른다. 매핑할 수 없는 조합은
# 여기서 실행을 거부하고, 조용히 더 넓은 권한으로 대체하지 않는다.

PERMISSION_MAP = {
    # 관측(2026-09-20, codex-cli 0.154.0): `--ask-for-approval` 는 최상위 `codex` 에만
    # 있고 `codex exec` 는 거부한다(exit 2). 최상위 도움말의 옵션을 하위 명령에
    # 그대로 옮기지 않는다.
    "codex": {
        "read_only": ["--sandbox", "read-only"],
        "workspace_write": ["--sandbox", "workspace-write"],
    },
    # Codex는 sandbox 축으로, Claude는 도구 목록·권한 모드 축으로 권한을 표현한다.
    # 두 축을 같은 것으로 취급하지 않고 추상 값에서 각각 매핑한다.
    # 관측(2026-09-20): `--tools` 제한은 내장 도구만 줄이고 MCP 서버 도구는 그대로 남는다.
    # 사용자 설정의 MCP 서버가 시스템이 허용하지 않은 외부 쓰기를 할 수 있으므로
    # `--strict-mcp-config` 를 함께 준다(이 harness는 --mcp-config 를 주지 않으므로 MCP 없음).
    "claude": {
        "read_only": [
            "--permission-mode", "manual",
            "--permission-prompts", "none",
            "--strict-mcp-config",
            "--tools", "Read,Grep,Glob",
        ],
        "workspace_write": [
            "--permission-mode", "acceptEdits",
            "--permission-prompts", "none",
            "--strict-mcp-config",
        ],
    },
}


def build_command(tool: str, mode: str, args: argparse.Namespace) -> list[str]:
    """추상 RunRequest를 실제 CLI 인자로 바꾼다.

    프롬프트는 인자가 아니라 stdin으로 넘긴다. 관측(2026-09-20): Claude의
    `--tools`처럼 값을 여러 개 받는 옵션이 뒤따르는 위치 인자를 삼켜
    "Input must be provided either through stdin or as a prompt argument" 로 실패한다.
    두 CLI 모두 stdin 입력을 지원하므로 stdin 경로를 공통 규칙으로 쓴다.
    Windows 명령줄 길이·인용 문제도 같이 피한다.
    """
    perms = PERMISSION_MAP.get(tool, {})
    if args.permission not in perms:
        raise SystemExit(
            f"매핑 없음: tool={tool} permission={args.permission}. "
            "권한을 임의로 확대하지 않고 중단한다."
        )

    exe = resolve_executable(tool, args.executable)

    if tool == "codex" and mode == "exec":
        cmd = [exe, "exec", "--json", "--skip-git-repo-check", "-C", args.workspace]
        cmd += perms[args.permission]
        if args.gate_hook:
            # 비관리 hook은 신뢰 승인이 필요하다. 비대화식 실증에서는 이 플래그의 필요
            # 여부 자체가 관측 대상이며, 필요했다는 사실을 제약으로 기록한다.
            cmd.append("--dangerously-bypass-hook-trust")
        if args.model:
            cmd += ["-m", args.model]
        if args.output_last_message:
            cmd += ["-o", args.output_last_message]
        return cmd

    if tool == "claude" and mode == "print":
        cmd = [exe, "-p", "--output-format", "stream-json", "--verbose"]
        cmd += perms[args.permission]
        if args.gate_hook:
            cmd += ["--settings", str(args.gate_hook["config"]), "--include-hook-events"]
        if args.model:
            cmd += ["--model", args.model]
        if args.session_id:
            cmd += ["--session-id", args.session_id]
        return cmd

    raise SystemExit(f"지원하지 않는 조합: tool={tool} mode={mode}")


HOOK_SCRIPT = Path(__file__).with_name("gate_hook.py")


def install_gate_hook(tool: str, workspace: Path, evidence: Path, run_id: str) -> dict:
    """PreToolUse 훅을 **세션/저장소 한정으로** 설치한다.

    사용자 전역 설정(`~/.codex/config.toml`, `~/.claude/settings.json`)은 바꾸지 않는다.
    Codex는 저장소 로컬 `<repo>/.codex/hooks.json`, Claude는 `--settings <file>` 을 쓴다.
    """
    state_file = evidence / f"{run_id}.connection"
    hook_log = evidence / f"{run_id}.hooklog.jsonl"
    state_file.write_text("connected", encoding="utf-8")

    # 훅 명령의 실행 방식이 두 CLI에서 다르다(2026-09-20 관측).
    #  - Codex 0.154.0: 따옴표로 감싼 경로를 넣으면 훅이 **오류 없이 조용히 실행되지 않는다**.
    #    공백 없는 단일 토큰이어야 해서 인자를 박아 둔 .cmd 래퍼 경로만 넘긴다.
    #  - Claude Code 2.1.278: 훅을 **bash로 실행**한다. Windows 경로의 역슬래시가
    #    이스케이프로 먹혀 `C:UsersUSER...: command not found`(127)가 된다.
    #    슬래시 경로 + 따옴표로 준다.
    if tool == "codex":
        wrapper = evidence / f"{run_id}.hook.cmd"
        wrapper.write_text(
            "@echo off\r\n"
            f'"{sys.executable}" "{HOOK_SCRIPT}" "{state_file}" "{hook_log}"\r\n',
            encoding="ascii",
        )
        command = str(wrapper)
    else:
        def posix(p: object) -> str:
            return str(p).replace("\\", "/")

        command = (
            f'"{posix(sys.executable)}" "{posix(HOOK_SCRIPT)}" '
            f'"{posix(state_file)}" "{posix(hook_log)}"'
        )
    entry = {
        "hooks": {
            "PreToolUse": [
                {"hooks": [{"type": "command", "command": command, "timeout": 30}]}
            ]
        }
    }

    if tool == "codex":
        target = workspace / ".codex" / "hooks.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        target = evidence / f"{run_id}.settings.json"
        target.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"state_file": state_file, "hook_log": hook_log, "config": target}


def resolve_executable(tool: str, override: str | None) -> str:
    if override:
        return override
    found = shutil.which(tool)
    if not found:
        raise SystemExit(f"PATH에서 {tool} 을(를) 찾지 못함. 설치 여부는 별도 확인 필요")
    return found


# --- 작업공간 상태 ------------------------------------------------------------


def git_snapshot(workspace: Path) -> dict:
    """실행 전후 비교용 스냅샷. git 조회 실패도 사실로 기록한다."""

    def run(*a: str) -> str | None:
        try:
            out = subprocess.run(
                ["git", *a],
                cwd=workspace,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            return out.stdout.strip() if out.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    return {
        "head": run("rev-parse", "HEAD"),
        "branch": run("rev-parse", "--abbrev-ref", "HEAD"),
        "status_porcelain": run("status", "--porcelain"),
    }


# --- 실행 -------------------------------------------------------------------


@dataclass
class StreamCapture:
    """원문은 바이트 그대로 파일에 남기고, 해석용 복사본만 디코딩한다.

    텍스트 모드로 읽으면 CLI가 UTF-8이 아닌 바이트를 낼 때 원문이 복구 불가능하게
    손상된다(2026-09-20 관측). Runner도 같은 이유로 원문을 바이트로 보존해야 한다.
    """

    path: Path
    raw_lines: list[bytes] = field(default_factory=list)
    decode_errors: int = 0

    def consume(self, pipe) -> None:
        with self.path.open("wb") as fh:
            for line in pipe:
                self.raw_lines.append(line)
                fh.write(line)
                fh.flush()

    @property
    def lines(self) -> list[str]:
        out: list[str] = []
        for raw in self.raw_lines:
            try:
                out.append(raw.decode("utf-8").rstrip("\r\n"))
            except UnicodeDecodeError:
                self.decode_errors += 1
                out.append(raw.decode("utf-8", errors="replace").rstrip("\r\n"))
        return out


def normalize_events(tool: str, stdout_lines: list[str]) -> tuple[list[dict], list[str], dict]:
    """CLI 원문 이벤트를 정규화 종류로 분류한다.

    분류 규칙은 2026-09-20에 이 PC에서 **실제로 관측한** 스키마에서 끌어냈다
    (codex-cli 0.154.0 `exec --json`, Claude Code 2.1.278 `-p --output-format stream-json`).
    분류하지 못한 원문은 버리지 않고 unmapped 로 돌려준다. 매핑이 없다는 사실도
    capability 표에 남길 근거다.
    """
    events: list[dict] = []
    unmapped: list[str] = []
    derived: dict = {"session_ref": None, "usage": "not_reported", "permission_decisions": []}
    seq = 0

    for raw in stdout_lines:
        raw = raw.strip()
        if not raw or not raw.startswith("{"):
            if raw:
                unmapped.append(raw[:200])
            continue
        try:
            obj = json.loads(raw)
        except json.JSONDecodeError:
            unmapped.append(raw[:200])
            continue

        native = obj.get("type", "unknown")
        kinds = classify_codex(obj, native) if tool == "codex" else classify_claude(obj, native)
        collect_derived(tool, obj, native, derived)
        if kinds is None:  # 알지 못하는 원문 종류. []는 "알지만 경계 의미가 없음"
            unmapped.append(f"{native}:{obj.get('subtype', '')}".rstrip(":"))
            continue
        for kind in kinds:
            seq += 1
            events.append({"seq": seq, "kind": kind, "native_type": native})

    return events, unmapped, derived


def classify_codex(obj: dict, native: str) -> list[str] | None:
    item_type = (obj.get("item") or {}).get("type")
    if native == "thread.started":
        return ["session_identified"]
    if native == "turn.started":
        return ["run_started"]
    if native == "turn.completed":
        return ["usage_reported", "run_finished"] if obj.get("usage") else ["run_finished"]
    if native in {"turn.failed", "error"}:
        return ["error"]
    if native in {"item.started", "item.updated", "item.completed"}:
        if item_type == "command_execution":
            return ["tool_call_started"] if native == "item.started" else (
                ["tool_call_finished"] if native == "item.completed" else []
            )
        if item_type == "agent_message":
            return ["assistant_message"] if native == "item.completed" else []
        if item_type == "error":
            return ["error"] if native == "item.completed" else []
        if item_type in {"reasoning", "todo_list"}:
            return []
        return None  # 모르는 item 종류. 경계 의미를 추정하지 않는다
    return None


def classify_claude(obj: dict, native: str) -> list[str] | None:
    if native == "system":
        subtype = obj.get("subtype")
        if subtype == "init":
            return ["session_identified"]
        if subtype == "permission_denied":
            return ["permission_decided"]
        if subtype == "hook_response":
            # 관측(2026-09-20): 훅 거부는 permission_denied 가 아니라 hook_response 로 온다.
            # 도구 결과에는 오류로 표시된다. 두 경로를 같은 정규화 종류로 모은다.
            return ["permission_decided"] if '"permissionDecision"' in (obj.get("stdout") or "") else []
        if subtype in {"thinking_tokens", "compact_boundary", "hook_started"}:
            return []
        return None
    if native == "assistant":
        content = (obj.get("message") or {}).get("content")
        kinds = [c.get("type") for c in content] if isinstance(content, list) else []
        if "tool_use" in kinds:
            return ["tool_call_started"]
        if "text" in kinds:
            return ["assistant_message"]
        if "thinking" in kinds:
            return []
        return None
    if native == "user":
        return ["tool_call_finished"] if obj.get("tool_use_result") is not None else []
    if native == "rate_limit_event":
        return ["usage_reported"]
    if native == "result":
        kinds = ["usage_reported"] if obj.get("usage") else []
        return kinds + (["error"] if obj.get("is_error") else ["run_finished"])
    return None


def collect_derived(tool: str, obj: dict, native: str, derived: dict) -> None:
    """세션 식별자와 사용량은 관측된 필드에서만 채운다. 없으면 그대로 둔다."""
    if tool == "codex":
        if native == "thread.started" and obj.get("thread_id"):
            derived["session_ref"] = obj["thread_id"]
        if native == "turn.completed" and obj.get("usage"):
            derived["usage"] = {"tokens": obj["usage"], "cost_usd": "not_reported"}
    else:
        if obj.get("session_id") and not derived["session_ref"]:
            derived["session_ref"] = obj["session_id"]
        if native == "system" and obj.get("subtype") == "permission_denied":
            derived["permission_decisions"].append(
                {
                    "decision": "denied",
                    "source": "permission_denied",
                    "tool_name": obj.get("tool_name"),
                    "reason_type": obj.get("decision_reason_type"),
                }
            )
        if native == "system" and obj.get("subtype") == "hook_response":
            stdout = obj.get("stdout") or ""
            if '"permissionDecision"' in stdout:
                try:
                    decision = json.loads(stdout)["hookSpecificOutput"]["permissionDecision"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    decision = "unparsed"
                derived["permission_decisions"].append(
                    {
                        "decision": decision,
                        "source": "hook_response",
                        "tool_name": obj.get("hook_name"),
                        "hook_exit_code": obj.get("exit_code"),
                    }
                )
            elif obj.get("outcome") == "error":
                # 훅이 실패해도 호출이 계속되는 것을 관측했다(fail-open). 사실로 남긴다.
                derived["permission_decisions"].append(
                    {
                        "decision": "hook_failed_not_enforced",
                        "source": "hook_response",
                        "tool_name": obj.get("hook_name"),
                        "hook_exit_code": obj.get("exit_code"),
                    }
                )
        if native == "result" and obj.get("usage"):
            derived["usage"] = {
                "tokens": obj["usage"],
                "cost_usd": obj.get("total_cost_usd", "not_reported"),
            }


def inject_disconnect(
    tool: str,
    out_cap: "StreamCapture",
    after_n: int,
    state_file: Path,
    marker: dict,
    proc: subprocess.Popen,
) -> None:
    """이벤트 스트림을 실시간으로 보다가 도구 호출 N회 완료 시점에 단절을 주입한다.

    제어 서버 연결이 끊긴 상황을 모사한다. 프로세스를 죽이지 않는다 — 강제 종료가 아니라
    "다음 호출을 시작하지 않는" 안전 경계가 성립하는지 보는 것이 목적이다.
    """
    seen = 0
    cursor = 0
    while proc.poll() is None:
        raw_lines = out_cap.raw_lines
        while cursor < len(raw_lines):
            line = raw_lines[cursor].decode("utf-8", errors="replace").strip()
            cursor += 1
            if not line.startswith("{"):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            native = obj.get("type", "")
            kinds = classify_codex(obj, native) if tool == "codex" else classify_claude(obj, native)
            if kinds and "tool_call_finished" in kinds:
                seen += 1
                if seen >= after_n:
                    state_file.write_text("disconnected", encoding="utf-8")
                    marker["injected_at"] = time.time()
                    marker["after_tool_calls"] = seen
                    return
        time.sleep(0.05)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tool", required=True, choices=["codex", "claude"])
    ap.add_argument("--mode", required=True, choices=["exec", "print"])
    ap.add_argument("--workspace", required=True)
    ap.add_argument("--permission", required=True, choices=["read_only", "workspace_write"])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--evidence-dir", required=True)
    ap.add_argument("--label", default="run")
    ap.add_argument("--model", default=None)
    ap.add_argument("--session-id", default=None)
    ap.add_argument("--output-last-message", default=None)
    ap.add_argument("--executable", default=None)
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument(
        "--gate-hook",
        action="store_true",
        help="PreToolUse 훅으로 연결 상태를 확인하게 한다(세션/저장소 한정 설정)",
    )
    ap.add_argument(
        "--disconnect-after-tool-calls",
        type=int,
        default=None,
        metavar="N",
        help="도구 호출 N회 완료를 관측하면 연결 상태를 disconnected로 바꾼다",
    )
    args = ap.parse_args()

    workspace = Path(args.workspace).resolve()
    evidence = Path(args.evidence_dir).resolve()
    evidence.mkdir(parents=True, exist_ok=True)

    run_id = f"{args.label}-{uuid.uuid4().hex[:8]}"

    if args.disconnect_after_tool_calls is not None and not args.gate_hook:
        raise SystemExit("--disconnect-after-tool-calls 는 --gate-hook 과 함께 써야 한다")

    args.gate_hook = install_gate_hook(args.tool, workspace, evidence, run_id) if args.gate_hook else None
    cmd = build_command(args.tool, args.mode, args)

    before = git_snapshot(workspace)
    started = time.time()

    out_cap = StreamCapture(evidence / f"{run_id}.stdout.jsonl")
    err_cap = StreamCapture(evidence / f"{run_id}.stderr.log")

    try:
        proc = subprocess.Popen(
            cmd,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
            bufsize=0,
        )
    except OSError as exc:
        # 실행 자체가 안 된 경우도 정상적인 결과 형태로 남긴다. 예외로 끝내지 않는다.
        failure = {
            "run_id": run_id,
            "tool_id": args.tool,
            "mode": args.mode,
            "resolved_command": cmd,
            "outcome": "failed",
            "outcome_reason": f"프로세스를 시작하지 못함: {exc}",
            "exit_code": None,
        }
        (evidence / f"{run_id}.result.json").write_text(
            json.dumps(failure, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1

    # 프롬프트는 stdin으로만 전달하고 즉시 닫는다. 열어 두면 CLI가 추가 입력을 기다린다.
    proc.stdin.write(args.prompt.encode("utf-8"))
    proc.stdin.close()

    threads = [
        threading.Thread(target=out_cap.consume, args=(proc.stdout,), daemon=True),
        threading.Thread(target=err_cap.consume, args=(proc.stderr,), daemon=True),
    ]
    disconnect_marker: dict = {}
    if args.disconnect_after_tool_calls is not None:
        threads.append(
            threading.Thread(
                target=inject_disconnect,
                args=(
                    args.tool,
                    out_cap,
                    args.disconnect_after_tool_calls,
                    args.gate_hook["state_file"],
                    disconnect_marker,
                    proc,
                ),
                daemon=True,
            )
        )
    for t in threads:
        t.start()

    timed_out = False
    try:
        exit_code = proc.wait(timeout=args.timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        exit_code = proc.wait()

    for t in threads:
        t.join(timeout=10)

    duration = time.time() - started
    after = git_snapshot(workspace)
    stdout_text = out_cap.lines
    events, unmapped, derived = normalize_events(args.tool, stdout_text)

    # outcome: 종료 코드 단독 판정 금지. 스트림 증거가 없으면 unknown.
    if timed_out:
        outcome = "unknown"
        outcome_reason = "timeout 후 강제 종료. 남은 활동과 실제 결과는 확인하지 않음"
    elif exit_code != 0:
        outcome = "failed"
        outcome_reason = f"exit_code={exit_code}"
    elif not stdout_text:
        outcome = "unknown"
        outcome_reason = "exit_code=0 이지만 stdout 증거가 없음"
    elif any(e["kind"] == "run_finished" for e in events):
        outcome = "completed"
        outcome_reason = "exit_code=0 이고 종료 이벤트를 관측함"
    else:
        outcome = "unknown"
        outcome_reason = "exit_code=0 이지만 종료 이벤트를 식별하지 못함"

    result = {
        "run_id": run_id,
        "tool_id": args.tool,
        "mode": args.mode,
        "permission_requested": args.permission,
        "resolved_command": cmd,
        "workspace": str(workspace),
        "outcome": outcome,
        "outcome_reason": outcome_reason,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "duration_sec": round(duration, 2),
        "stdout_lines": len(out_cap.raw_lines),
        "stderr_lines": len(err_cap.raw_lines),
        "stdout_utf8_decode_errors": out_cap.decode_errors,
        "normalized_events": summarize(events),
        "unmapped_native_types": sorted(set(unmapped))[:20],
        "workspace_effect": {
            "head_before": before["head"],
            "head_after": after["head"],
            "status_before": before["status_porcelain"],
            "status_after": after["status_porcelain"],
            "changed": before["status_porcelain"] != after["status_porcelain"]
            or before["head"] != after["head"],
        },
        "session_ref": derived["session_ref"],
        "permission_decisions": derived["permission_decisions"],
        "gate_hook": (
            {
                "config": str(args.gate_hook["config"]),
                "hook_log": str(args.gate_hook["hook_log"]),
                "state_file": str(args.gate_hook["state_file"]),
                "final_state": args.gate_hook["state_file"].read_text(encoding="utf-8"),
                "hook_invocations": count_lines(args.gate_hook["hook_log"]),
            }
            if args.gate_hook
            else None
        ),
        "disconnect_injection": disconnect_marker or None,
        "residual_activity": "unknown",
        "usage": derived["usage"],
        "raw_stdout": str(out_cap.path),
        "raw_stderr": str(err_cap.path),
    }

    result_path = evidence / f"{run_id}.result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def count_lines(path: Path) -> int:
    try:
        return sum(1 for _ in path.open(encoding="utf-8"))
    except OSError:
        return 0


def summarize(events: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for e in events:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    return counts


if __name__ == "__main__":
    sys.exit(main())
