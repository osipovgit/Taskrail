import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

from countersign.infrastructure.runner import recover_unavailable_format_tools, run_agent
from countersign.observability.progress import Progress, event_activity


class FormatTests(unittest.TestCase):
    def result(self):
        error = "Model tried to call unavailable tool 'invalid'. Available tools: ."
        return dict(
            completed=True,
            final_text='{"status":"BLOCKED"}',
            permission=False,
            tool_calls=1,
            errors=[error],
            tool_errors=[dict(tool="invalid", error=error)],
            warnings=[],
        )

    def test_only_unavailable_calls_with_no_available_tools_are_nonfatal(self):
        result = self.result()
        recover_unavailable_format_tools(result)
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(len(result["tool_errors"]), 1)
        for change in (
            dict(permission=True),
            dict(completed=False),
            dict(final_text=""),
            dict(tool_calls=2),
            dict(errors=["Transport failure"]),
        ):
            result = self.result()
            result.update(change)
            before = copy.deepcopy(result)
            recover_unavailable_format_tools(result)
            self.assertEqual(result, before)
        for error in (
            "PermissionDeniedError",
            "Tool execution aborted",
            "Model tried to call unavailable tool 'invalid'. Available tools: read, glob.",
        ):
            result = self.result()
            result["errors"] = [error]
            result["tool_errors"][0]["error"] = error
            before = copy.deepcopy(result)
            recover_unavailable_format_tools(result)
            self.assertEqual(result, before)

    def test_unavailable_tool_recovery_is_limited_to_format_only_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / "fake.py"
            error = "Model tried to call unavailable tool 'invalid'. Available tools: ."
            events = [
                dict(
                    type="tool_use",
                    part=dict(tool="invalid", state=dict(status="error", input={}, error=error)),
                ),
                dict(
                    type="text",
                    part=dict(
                        messageID="m",
                        text='{"status":"BLOCKED","summary":"Missing evidence","steps":[]}',
                    ),
                ),
                dict(type="step_finish", part=dict(messageID="m", reason="stop")),
            ]
            script.write_text(
                "print(" + repr("\n".join(json.dumps(event) for event in events)) + ")"
            )
            request = root / "request.md"
            request.write_text("Convert the supplied text only")
            for flag, expected in ((False, "TOOL_ERROR"), (True, "OK")):
                result = run_agent(
                    [sys.executable, str(script)],
                    root,
                    "converter",
                    "fake",
                    request,
                    root / str(flag),
                    5,
                    format_only=flag,
                )
                self.assertEqual(result["status"], expected)
                self.assertTrue(result["tool_errors"])
                if flag:
                    self.assertEqual(json.loads(result["final_text"])["status"], "BLOCKED")


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
