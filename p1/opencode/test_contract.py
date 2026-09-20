"""OpenCode 어댑터 계약 시험.

**이 시험의 통과는 실환경 검증이 아니다.** fixture는 공식 문서에서 재구성한 것이고
OpenCode를 실행한 적이 없다. 통과가 뜻하는 것은 "우리 어댑터가 우리가 가정한 형태를
계약대로 다룬다"뿐이다.

그래서 마지막 시험군은 **그 사실 자체를 검사한다.** fixture가 재구성물로 표시되어 있는지,
어떤 능력도 verified 로 올라가 있지 않은지를 확인한다. 누군가 나중에 이 시험을 통과시키려고
상태를 verified 로 바꾸면 시험이 깨진다.

실행: python -m unittest discover -s p1/opencode -t .
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import adapter  # noqa: E402


class TestPermissionMapping(unittest.TestCase):
    def test_read_only_denies_write_actions(self):
        rules = adapter.build_permission_rules("read_only")
        effects = {r["action"]: r["effect"] for r in rules}
        self.assertEqual(effects["edit"], "deny")
        self.assertEqual(effects["shell"], "deny")
        self.assertEqual(effects["read"], "allow")

    def test_workspace_write_still_denies_external_directory(self):
        rules = adapter.build_permission_rules("workspace_write")
        effects = {r["action"]: r["effect"] for r in rules}
        self.assertEqual(effects["edit"], "allow")
        self.assertEqual(
            effects["external_directory"],
            "deny",
            "작업공간 밖 경로는 쓰기 권한에서도 기본 불허여야 한다",
        )

    def test_unknown_permission_is_refused_not_widened(self):
        with self.assertRaises(adapter.UnsupportedCapability):
            adapter.build_permission_rules("explicit_escalated")

    def test_rules_are_copies(self):
        """호출자가 규칙을 바꿔도 모듈 기본값이 오염되지 않아야 한다."""
        rules = adapter.build_permission_rules("read_only")
        rules[0]["effect"] = "allow-everything"
        again = adapter.build_permission_rules("read_only")
        self.assertNotEqual(again[0]["effect"], "allow-everything")


class TestPermissionReply(unittest.TestCase):
    def test_once_is_allowed(self):
        self.assertEqual(adapter.choose_permission_reply("once"), "once")

    def test_always_is_refused_because_it_persists_project_patterns(self):
        with self.assertRaises(adapter.UnsupportedCapability):
            adapter.choose_permission_reply("always")

    def test_reject_is_refused_because_it_rejects_all_pending_requests(self):
        with self.assertRaises(adapter.UnsupportedCapability):
            adapter.choose_permission_reply("reject")

    def test_undocumented_reply_is_refused(self):
        with self.assertRaises(adapter.UnsupportedCapability):
            adapter.choose_permission_reply("deny")


class TestEventNormalization(unittest.TestCase):
    def setUp(self):
        self.lines = adapter.load_fixture("events_shell_run.jsonl")

    def test_shell_events_map_to_tool_call_boundary(self):
        events, _ = adapter.normalize_events(self.lines)
        kinds = [e["kind"] for e in events]
        self.assertEqual(kinds.count("tool_call_started"), 2)
        self.assertEqual(kinds.count("tool_call_finished"), 2)

    def test_sequence_is_monotonic(self):
        events, _ = adapter.normalize_events(self.lines)
        self.assertEqual([e["seq"] for e in events], list(range(1, len(events) + 1)))

    def test_unknown_event_is_reported_not_guessed(self):
        _, unmapped = adapter.normalize_events(self.lines)
        self.assertIn("some.unnamed.event", unmapped)

    def test_known_but_meaningless_event_is_not_reported_as_unmapped(self):
        _, unmapped = adapter.normalize_events(self.lines)
        self.assertNotIn("location.shutdown", unmapped)

    def test_no_run_finished_is_invented(self):
        """문서에서 종료 이벤트 이름을 확인하지 못했으므로 만들어내면 안 된다."""
        events, _ = adapter.normalize_events(self.lines)
        self.assertNotIn("run_finished", [e["kind"] for e in events])


class TestSessionFixture(unittest.TestCase):
    def test_session_id_is_present(self):
        data = adapter.load_fixture("session_create.json")
        self.assertTrue(data["id"])


class TestEvidenceBoundary(unittest.TestCase):
    """계약 시험이 실환경 검증으로 둔갑하지 않게 막는 시험."""

    FIXTURE_DIR = Path(__file__).parent / "fixtures"

    def test_every_fixture_declares_it_is_reconstructed(self):
        files = sorted(self.FIXTURE_DIR.iterdir())
        self.assertTrue(files, "fixture가 하나도 없다")
        for path in files:
            with self.subTest(fixture=path.name):
                text = path.read_text(encoding="utf-8")
                first = json.loads(text.splitlines()[0]) if path.suffix == ".jsonl" else json.loads(text)
                self.assertEqual(
                    first.get("_source"),
                    "reconstructed-from-docs",
                    f"{path.name} 에 재구성물 표시가 없다",
                )

    def test_no_capability_is_claimed_verified(self):
        states = adapter.capability_states()
        verified = [k for k, v in states.items() if v == "verified"]
        self.assertEqual(
            verified,
            [],
            "OpenCode를 실행한 적이 없으므로 verified 상태가 있어서는 안 된다",
        )

    def test_required_safe_pause_capability_stays_unknown(self):
        states = adapter.capability_states()
        self.assertEqual(
            states["next_call_blockable"],
            "unknown",
            "안전 중지는 후보만 있고 확인되지 않았다. 지원으로 표시하지 않는다",
        )

    def test_unresolved_event_kinds_are_not_secretly_mapped(self):
        mapped = {k for kinds in adapter.CONFIRMED_EVENT_MAP.values() for k in kinds}
        for kind in adapter.UNRESOLVED_EVENT_KINDS:
            with self.subTest(kind=kind):
                self.assertNotIn(kind, mapped)


if __name__ == "__main__":
    unittest.main()
