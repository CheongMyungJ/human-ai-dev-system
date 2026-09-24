"""P4-09 (b) — 쓰기 실행의 CLI 샌드박스 해제(D-91, 이슈 #3)(plans/P4-PLAN-09.md AC-6·AC-7), **P4-10b 에서 D-96 으로 넓힘**
(plans/P4-PLAN-10b.md AC-1·AC-2).

D-96(사용자 결정 2026-09-25): 두 도구 모두 권한 확인을 건너뛰고 읽기 전용은 허용 도구로 제한한다. Codex 는 허용 도구 목록이
없어 읽기 전용을 막지 못한다 — Runner 가 실행 전후 대조로 알린다(`tests/test_read_only_change.py`). 이 파일은 **매핑 자체**를
고정한다. 실제 CLI 는 부르지 않는다(`resolve_executable` 을 바꿔 둔다).

    codex  읽기·쓰기 = `--dangerously-bypass-approvals-and-sandbox`
    claude 읽기·쓰기 = `--dangerously-skip-permissions` + `--strict-mcp-config`, 읽기만 `--tools Read,Grep,Glob`
    막지 못하는 것을 막는다고 적지 않는다   `write_sandbox = unsupported`, codex `read_only_enforcement = unsupported`
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


def test_every_run_skips_permission_checks_and_claude_read_only_is_limited_by_tools(tmp_path: Path):
    """P4-10b AC-1 (D-96) — 두 도구·두 권한의 실제 인자. 샌드박스·승인 인자는 어디에도 없다."""
    for permission in (Permission.WORKSPACE_WRITE, Permission.READ_ONLY):
        codex = cli_adapter.build_command("codex", "exec", permission, tmp_path)
        assert codex[-1] == "--dangerously-bypass-approvals-and-sandbox"
        assert "--sandbox" not in codex
        claude = cli_adapter.build_command("claude", "print", permission, tmp_path)
        assert "--dangerously-skip-permissions" in claude and "--permission-mode" not in claude
        assert "--strict-mcp-config" in claude  # 외부 서비스 MCP 는 계속 막는다(D-91 의 상세 설계 선택 그대로)
    claude_write = cli_adapter.build_command("claude", "print", Permission.WORKSPACE_WRITE, tmp_path)
    assert "--tools" not in claude_write
    claude_read = cli_adapter.build_command("claude", "print", Permission.READ_ONLY, tmp_path)
    assert claude_read[claude_read.index("--tools") + 1] == "Read,Grep,Glob"


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
    # P4-10b(D-96). 읽기 전용이 무엇으로 지켜지는가 — codex 는 막지 못하고(감지·알림), claude 는 도구 제한(미실증).
    assert "D-96" in rows["permission:read_only"]["source"]
    expected = CapabilityState.UNSUPPORTED if tool_id == "codex" else CapabilityState.DOC_ONLY
    assert rows["read_only_enforcement"]["state"] == expected.value and "D-96" in rows["read_only_enforcement"]["source"]
    assert rows["permission:explicit_escalated"]["state"] == CapabilityState.UNSUPPORTED.value
