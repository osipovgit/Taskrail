import json
import sys
import tempfile
import unittest
from pathlib import Path

from taskrail.infrastructure.runner import run_agent
from taskrail.observability.activity import Progress, event_activity


class ToolFailureTests(unittest.TestCase):
    def test_failed_read_before_an_executor_request_keeps_the_turn_ok(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "fake.py"
            request = '{"schema_version": 1, "status": "GIT_REQUEST", "root": "/repo", "argv": ["status"], "reason": "State"}'
            events = [
                dict(
                    type="tool_use",
                    part=dict(
                        id="r1",
                        tool="read",
                        state=dict(
                            status="error",
                            input=dict(filePath="/repo/roles"),
                            error="Error: /repo/roles is a directory",
                        ),
                    ),
                ),
                dict(
                    type="text",
                    part=dict(id="t1", messageID="m", text="Let me check Git.\n" + request),
                ),
                dict(type="step_finish", part=dict(id="s1", messageID="m", reason="stop")),
            ]
            script.write_text(
                "print(" + repr("\n".join(json.dumps(event) for event in events)) + ")"
            )
            prompt = root / "request.md"
            prompt.write_text("Plan the change")
            result = run_agent(
                dict(
                    command=[sys.executable, str(script)],
                    workspace=root,
                    agent="planner",
                    model="fake",
                    prompt=prompt,
                    attempt=root / "attempt",
                    timeout=5,
                )
            )
        self.assertEqual(result["status"], "OK", result["errors"])
        self.assertIn("GIT_REQUEST", result["final_text"])
        self.assertEqual(len(result["warnings"]), 1)


class ActivityTests(unittest.TestCase):
    def test_progress_shows_public_operation_current_time_and_silence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "activity.json"
            progress = Progress(path)
            self.assertIn("first public opencode event", progress.line(30, 0))
            event = dict(
                type="tool_use",
                timestamp=1791790000000,
                part=dict(
                    tool="read",
                    state=dict(
                        status="completed",
                        input=dict(filePath="/repo/file.py"),
                        output="private file contents",
                    ),
                ),
            )
            progress.observe([json.dumps(event).encode()])
            line = progress.line(120, 104546)
            self.assertRegex(line, r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[+-]\d{2}:\d{2}\]")
            self.assertIn("Tool read: completed /repo/file.py", line)
            self.assertIn("events=104546 bytes", line)
            self.assertNotIn("private file contents", line)
            self.assertEqual(json.loads(path.read_text())["event_timestamp"], event["timestamp"])

    def test_reasoning_malformed_and_partial_events_are_ignored(self):
        for value in (
            "{",
            "[]",
            json.dumps(dict(type="reasoning", part=dict(text="hidden thoughts"))),
        ):
            self.assertIsNone(event_activity(value))
        activity = event_activity(json.dumps(dict(type="text", part=dict(text="Reading\nfiles"))))
        self.assertEqual(activity["detail"], "Message: Reading files")
