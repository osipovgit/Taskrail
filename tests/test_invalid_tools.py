"""Unexecuted unavailable-tool requests do not poison a later validated review."""

import json
import tempfile
import unittest
from pathlib import Path

from live_fixture import LiveFixture

from taskrail.infrastructure import invalid_tools, runner
from taskrail.infrastructure.event_summary import parse_events
from taskrail.infrastructure.opencode_events import EventTranslator

ERROR = "Model tried unavailable tool 'invalid'; tools: read, glob, grep, edit, write"


class InvalidToolEventsTests(unittest.TestCase):
    def events(self, final="The review is complete.\nDONE"):
        return [
            dict(
                type="tool_use",
                sessionID="s",
                part=dict(
                    id="bad",
                    partID="bad",
                    tool="invalid",
                    state=dict(status="error", input={}, error=ERROR),
                ),
            ),
            dict(type="text", sessionID="s", part=dict(id="text", messageID="m", text=final)),
            dict(
                type="step_finish",
                sessionID="s",
                part=dict(id="finish", messageID="m", reason="stop"),
            ),
        ]

    def parse(self, events, version="1.x"):
        with tempfile.TemporaryDirectory() as directory:
            lines = list(map(json.dumps, events))
            if version == "2.x":
                translator = EventTranslator(directory)
                lines = [translator.translate(line) for line in lines]
            path = Path(directory) / "events.jsonl"
            path.write_text("\n".join(line for line in lines if line))
            return parse_events(path)

    def test_a_completed_done_preserves_the_rejection_as_a_warning_on_both_interfaces(self):
        for version in ("1.x", "2.x"):
            with self.subTest(version=version):
                result = self.parse(self.events(), version)
                self.assertEqual(result["errors"], [])
                self.assertEqual(result["warnings"][0]["error"], ERROR)
                self.assertEqual(result["tool_errors"][0]["tool"], "invalid")
                self.assertEqual(runner.final_status("OK", 0, result, ""), "OK")

    def test_done_in_narrative_without_final_completion_is_not_recovery(self):
        for events in (self.events()[:-1], self.events("I will say DONE when ready")):
            result = self.parse(events)
            self.assertEqual(result["errors"], [ERROR])
            result.update(status="TOOL_ERROR", exit_code=0)
            self.assertEqual(invalid_tools.correction(result), [ERROR])

    def test_unknown_write_permission_and_fatal_provider_errors_remain_fatal(self):
        cases = []
        for tool, error in (
            ("write", ERROR),
            ("invalid", "Unexpected source failure"),
            ("invalid", "PermissionDenied: " + ERROR),
        ):
            events = self.events()
            events[0]["part"].update(tool=tool, state=dict(status="error", input={}, error=error))
            cases.append(events)
        cases.append([*self.events(), dict(type="error", error="Fatal provider gateway failure")])
        for events in cases:
            with self.subTest(events=events):
                result = self.parse(events)
                self.assertTrue(result["errors"])
                result.update(status="TOOL_ERROR", exit_code=1)
                self.assertEqual(invalid_tools.correction(result), [])


class InvalidToolWorkflowTests(LiveFixture, unittest.TestCase):
    def test_a_valid_review_with_done_after_invalid_tool_reaches_approval(self):
        _, status, state = self.run_mode("invalid-tool-recovered")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        result = state["attempts"][-1]
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"][0]["tool"], "invalid")

    def test_an_incomplete_review_gets_bounded_same_session_guidance(self):
        _, status, state = self.run_mode("invalid-tool-incomplete")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        self.assertEqual(state["stages"][-1]["session_turns"], 2)

    def test_done_cannot_approve_a_review_missing_requirement_results(self):
        _, status, state = self.run_mode("invalid-tool-bad-review")
        self.assertEqual(status, "INVALID_RESULT", state.get("summary"))


if __name__ == "__main__":
    unittest.main()
