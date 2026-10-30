"""Only provider errors stop a running turn for an explicit context rejection."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from taskrail.infrastructure.runner import run_agent


class ContextEventTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_events(self, events, pause=False):
        script = self.root / "provider.py"
        lines = "".join(json.dumps(event) + "\n" for event in events)
        script.write_text(
            "import sys, time\n"
            f"sys.stdout.write({lines!r})\n"
            "sys.stdout.flush()\n" + ("time.sleep(30)\n" if pause else "")
        )
        prompt = self.root / "prompt.md"
        prompt.write_text("Test")
        return run_agent(
            dict(
                command=[sys.executable, str(script)],
                workspace=self.root,
                agent="test",
                model=None,
                prompt=prompt,
                attempt=self.root / "attempt",
                timeout=5,
                runtime=dict(context_budget=86016),
            )
        )

    def test_explicit_provider_overflow_stops_before_a_lingering_process_times_out(self):
        error = dict(name="APIError", data=dict(message="context_length_exceeded"))
        result = self.run_events([dict(type="error", error=error)], pause=True)
        self.assertEqual(result["status"], "CONTEXT_EXCEEDED", result)
        self.assertLess(result["elapsed_seconds"], 3)
        self.assertTrue(result["provider_context_exceeded"])

    def test_permission_denial_keeps_precedence_over_provider_context_error(self):
        events = [
            dict(type="error", error="context_length_exceeded"),
            dict(type="error", error="PermissionDeniedError"),
        ]
        result = self.run_events(events, pause=True)
        self.assertEqual(result["status"], "BLOCKED_PERMISSION", result)
        self.assertLess(result["elapsed_seconds"], 3)

    def test_successful_read_quoting_context_failure_is_ordinary_content(self):
        state = dict(status="completed", input={}, output="context_length_exceeded")
        result = self.run_events(
            [dict(type="tool_use", part=dict(tool="read", state=state)), *finished()]
        )
        self.assertEqual(result["status"], "OK", result)
        self.assertFalse(result["provider_context_exceeded"])

    def test_failed_write_quoting_context_failure_is_a_tool_error(self):
        state = dict(status="error", input={}, error="Cannot write: context_length_exceeded")
        result = self.run_events(
            [dict(type="tool_use", part=dict(tool="write", state=state)), *finished()]
        )
        self.assertEqual(result["status"], "TOOL_ERROR", result)
        self.assertFalse(result["provider_context_exceeded"])


def finished():
    return [
        dict(type="text", part=dict(id="answer", messageID="result", text="DONE")),
        dict(type="step_finish", part=dict(id="finish", messageID="result", reason="stop")),
    ]


if __name__ == "__main__":
    unittest.main()
