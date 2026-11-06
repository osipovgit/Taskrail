"""opencode owns native recovery; diagnostics never substitute for source evidence."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail.infrastructure.event_summary import parse_events
from taskrail.infrastructure.runner import final_status
from taskrail.interactions import turn_recovery


class NativeFailureTests(unittest.TestCase):
    def parse(self, events):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text("\n".join(map(json.dumps, events)))
            return parse_events(path)

    def failure(self, tool, error):
        return dict(
            type="tool_use",
            sessionID="session",
            part=dict(
                id="failed",
                tool=tool,
                state=dict(status="error", input=dict(filePath="/repo/file"), error=error),
            ),
        )

    def final(self):
        return [
            dict(type="text", sessionID="session", part=dict(messageID="answer", text="DONE")),
            dict(
                type="step_finish",
                sessionID="session",
                part=dict(messageID="answer", reason="stop"),
            ),
        ]

    def test_all_native_failures_remain_diagnostics_and_allow_final_validation(self):
        for tool in ("read", "grep", "edit", "write", "invalid"):
            for error in (
                "PermissionDeniedError",
                "Tool execution aborted",
                "Unknown error",
                "Error: No changes to apply: oldString and newString are identical.",
            ):
                with self.subTest(tool=tool, error=error):
                    outcome = self.parse([self.failure(tool, error), *self.final()])
                    self.assertEqual(final_status("OK", 0, outcome), "OK")
                    self.assertEqual(outcome["errors"], [])
                    self.assertEqual(outcome["warnings"][0]["error"], error)
                    self.assertEqual(outcome["tool_errors"][0]["input"]["filePath"], "/repo/file")
                    self.assertNotIn("recovered_by", outcome["warnings"][0])
                    self.assertEqual(final_status("OK", 1, outcome), "PROCESS_ERROR")

    def test_ruleset_dump_is_short_in_activity_with_the_path_and_recovery_intact(self):
        from taskrail.observability.telemetry_parts import ToolCalls

        error = 'PermissionDeniedError({"ruleset":[{"pattern":"/private/index","action":"deny"}]})'
        event = self.failure("read", error)
        outcome = self.parse([event, *self.final()])
        trace = ToolCalls().observe(event["part"], 0)
        self.assertEqual(final_status("OK", 0, outcome), "OK")
        self.assertIn("Permission denied", trace["error"])
        self.assertNotIn("ruleset", trace["error"])
        self.assertIn("/repo/file", trace["input"])
        self.assertEqual(outcome["warnings"][0]["error"], trace["error"])
        self.assertEqual(event["part"]["state"]["error"], error)

    def test_completed_invalid_sentinel_remains_a_diagnostic_error(self):
        from taskrail.observability.telemetry_parts import ToolCalls

        event = self.failure("invalid", "unavailable")
        event["part"]["state"] = dict(
            status="completed", input={"tool": "bash"}, output="Tool unavailable"
        )
        outcome = self.parse([event, *self.final()])
        self.assertEqual(final_status("OK", 0, outcome), "OK")
        self.assertEqual(outcome["tool_errors"][0]["error"], "Tool unavailable")
        calls = ToolCalls()
        trace = calls.observe(event["part"], 0)
        self.assertEqual(trace["status"], "error")
        self.assertEqual(trace["error"], "Tool unavailable")
        self.assertEqual(calls.summary()["tool_errors"], 1)

    def test_incomplete_native_work_cannot_reuse_an_earlier_final_answer(self):
        failure = self.failure("edit", "Tool execution aborted")
        for events in ([failure], [*self.final(), failure]):
            outcome = self.parse(events)
            self.assertEqual(final_status("OK", 0, outcome), "INCOMPLETE")
        for events, expected in (
            ([dict(type="error", error="network"), *self.final()], "OK"),
            ([*self.final(), dict(type="error", error="network")], "TURN_ERROR"),
        ):
            self.assertEqual(final_status("OK", 0, self.parse(events)), expected)

    def test_recovery_accepts_denials_and_partial_writers_but_not_integrity_stops(self):
        outcome = dict(
            status="INCOMPLETE",
            sessions=["session"],
            permission=True,
            tool_errors=[dict(tool="write", error="PermissionDeniedError")],
        )
        self.assertTrue(turn_recovery.eligible(outcome))
        for status in ("OK", "SCOPE_VIOLATION", "TIMEOUT", "CONTEXT_EXCEEDED", "SESSION_ERROR"):
            self.assertFalse(turn_recovery.eligible(dict(outcome, status=status)))
        self.assertFalse(turn_recovery.eligible(dict(outcome, sessions=[])))

    def test_repeated_interruptions_are_bounded_but_artifact_progress_can_continue(self):
        with tempfile.TemporaryDirectory() as temporary:
            own = Path(temporary) / "plan.md"
            own.write_text("first")
            session = SimpleNamespace(
                context={},
                environment=dict(expected={}, config={}),
                launch=dict(runtime=dict(attached_files=[own])),
            )
            outcome = dict(
                status="INCOMPLETE",
                sessions=["session"],
                tool_errors=[dict(tool="edit", error="aborted")],
            )
            with patch("taskrail.interactions.turn_recovery.events.correction"):
                for _ in range(turn_recovery.MAX_STALLS):
                    self.assertIsNotNone(turn_recovery.response(session, outcome))
                own.write_text("more progress")
                self.assertIsNotNone(turn_recovery.response(session, outcome))
                for _ in range(turn_recovery.MAX_STALLS):
                    turn_recovery.response(session, outcome)
                self.assertEqual(outcome["status"], "NO_PROGRESS")
