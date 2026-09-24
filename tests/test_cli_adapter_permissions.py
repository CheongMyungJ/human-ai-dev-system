"""P4-09 (b) — 쓰기 실행의 CLI 샌드박스 해제(D-91, 이슈 #3)(plans/P4-PLAN-09.md AC-6·AC-7).

읽기 전용 실행만 CLI 샌드박스를 유지하고 구현·검증·실험(쓰기) 실행은 CLI 권한 제약이 없다 — 기능이
동작하는 것이 우선이라는 사용자 결정이다. 이 파일은 **매핑 자체**를 고정한다(그 전에는 매핑을 직접
검사하는 시험이 없었다). 실제 CLI 는 부르지 않는다(`resolve_executable` 을 바꿔 둔다).

    쓰기 = 샌드박스 없음        codex `danger-full-access`, claude `bypassPermissions`
    읽기 = 그대로               codex `read-only`, claude `manual` + `--tools Read,Grep,Glob`
    막지 못하는 것을 막는다고 적지 않는다   능력 보고에 `write_sandbox = unsupported`
"""

from __future__ import annotations

from pathlib import Path

import pytest

from domain.models import CapabilityState, Permission
from runner import cli_adapter


@pytest.fixture(autouse=True)
def _fake_executables(monkeypatch):
    monkeypatch.setattr(cli_adapter, "resolve_executable", lambda tool_id: f"C:/fake/{tool_id}.cmd")
    monkeypatch.setattr(cli_adapter, "observed_version", lambda tool_id: f"{tool_id} 0.0.0-test")


def test_write_runs_get_no_cli_sandbox_and_read_only_runs_keep_it(tmp_path: Path):
    """AC-6 — 두 도구·두 권한의 실제 인자."""
    codex_write = cli_adapter.build_command("codex", "exec", Permission.WORKSPACE_WRITE, tmp_path)
    assert codex_write[-2:] == ["--sandbox", "danger-full-access"]
    codex_read = cli_adapter.build_command("codex", "exec", Permission.READ_ONLY, tmp_path)
    assert codex_read[-2:] == ["--sandbox", "read-only"]

    claude_write = cli_adapter.build_command("claude", "print", Permission.WORKSPACE_WRITE, tmp_path)
    assert "--permission-mode" in claude_write
    assert claude_write[claude_write.index("--permission-mode") + 1] == "bypassPermissions"
    assert "--strict-mcp-config" in claude_write  # 외부 서비스 MCP 는 계속 막는다(상세 설계 선택)
    assert "--tools" not in claude_write
    claude_read = cli_adapter.build_command("claude", "print", Permission.READ_ONLY, tmp_path)
    assert claude_read[claude_read.index("--permission-mode") + 1] == "manual"
    assert claude_read[claude_read.index("--tools") + 1] == "Read,Grep,Glob"
    assert "--strict-mcp-config" in claude_read


def test_escalated_permission_is_still_unmapped_and_refused(tmp_path: Path):
    """권한을 임의로 확대하지 않는다 — 매핑 없는 조합은 실행하지 않는다(그대로)."""
    with pytest.raises(cli_adapter.AdapterError):
        cli_adapter.build_command("codex", "exec", Permission.EXPLICIT_ESCALATED, tmp_path)


@pytest.mark.parametrize("tool_id", ["codex", "claude"])
def test_the_capability_report_says_write_runs_have_no_sandbox(tool_id: str):
    """AC-7 — `write_sandbox = unsupported` 와 D-91 근거. 읽기 전용의 근거는 P1-02 그대로."""
    rows = {r["capability"]: r for r in cli_adapter.capabilities_for(tool_id)}
    assert rows["write_sandbox"]["state"] == CapabilityState.UNSUPPORTED.value
    assert "D-91" in rows["write_sandbox"]["source"]
    assert rows["permission:workspace_write"]["state"] == CapabilityState.VERIFIED.value
    assert "D-91" in rows["permission:workspace_write"]["source"]
    assert rows["permission:read_only"]["state"] == CapabilityState.VERIFIED.value
    assert "P1-02" in rows["permission:read_only"]["source"]
    assert rows["permission:explicit_escalated"]["state"] == CapabilityState.UNSUPPORTED.value
