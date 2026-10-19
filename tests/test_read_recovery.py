import json
import tempfile
import unittest
from pathlib import Path

from countersign.infrastructure.event_summary import parse_events


class ReadRecoveryTests(unittest.TestCase):
    def error(self, message=None):
        return dict(
            type="tool_use",
            part=dict(
                id="failed",
                tool="read",
                state=dict(
                    status="error",
                    input=dict(filePath="/repo/a.yml", offset=1377),
                    error=message or "Error: Offset 1377 is out of range for this file (2 lines)",
                ),
            ),
        )

    def success(self, path="/repo/a.yml", offset=1, truncated=False):
        return dict(
            type="tool_use",
            part=dict(
                id="success",
                tool="read",
                callID="corrected",
                state=dict(
                    status="completed",
                    input=dict(filePath=path, offset=offset),
                    output="<content>1:a\n2:b\n(End of file - total 2 lines)\n</content>",
                    metadata=dict(truncated=truncated),
                ),
            ),
        )

    def parse(self, events):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            path.write_text("\n".join(json.dumps(event) for event in events))
            return parse_events(path)

    def test_rejected_arguments_executed_nothing_and_only_warn(self):
        rejected = self.error(
            "The read tool was called with invalid arguments: SchemaError(Expected number | "
            'undefined, got "1.0"\n  at ["offset"]).\nPlease rewrite the input.'
        )
        result = self.parse([rejected, self.success()])
        self.assertEqual(result["errors"], [])
        self.assertIn("nothing executed", result["warnings"][0]["resolution"])
        denied = self.error("PermissionDeniedError: Permission denied: read")
        self.assertEqual(len(self.parse([denied])["errors"]), 1)

    def test_later_full_read_recovers_only_offset_error(self):
        result = self.parse([self.error(), self.success()])
        self.assertEqual(result["errors"], [])
        self.assertEqual(result["warnings"][0]["recovered_by"]["call_id"], "corrected")
        self.assertEqual(len(result["tool_errors"]), 1)

    def test_offset_errors_warn_without_claiming_a_recovered_read(self):
        for events in (
            [self.error()],
            [self.success(), self.error()],
            [self.error(), self.success(path="/repo/b.yml")],
            [self.error(), self.success(offset=2)],
            [self.error(), self.success(truncated=True)],
        ):
            with self.subTest(events=events):
                result = self.parse(events)
                self.assertEqual(result["errors"], [])
                self.assertEqual(len(result["warnings"]), 1)
                self.assertNotIn("recovered_by", result["warnings"][0])

    def test_permission_and_other_errors_are_never_downgraded(self):
        for message in (
            "PermissionDeniedError",
            "Error: File not found",
            "Error: Tool execution aborted",
        ):
            result = self.parse([self.error(message), self.success()])
            self.assertEqual(result["errors"], [message])
            self.assertEqual(result["warnings"], [])
        self.assertTrue(
            self.parse([self.error("PermissionDeniedError"), self.success()])["permission"]
        )

    def test_text_claim_of_success_is_not_evidence(self):
        result = self.parse(
            [self.error(), dict(type="text", part=dict(text="Read the complete file successfully"))]
        )
        self.assertEqual(result["errors"], [])
        self.assertNotIn("recovered_by", result["warnings"][0])

    def test_missing_read_is_warning_even_without_later_success(self):
        message = "Error: File not found: /repo/a.yml"
        for suffix in ("", "\n\nDid you mean one of these?\n/repo/a.yaml"):
            with self.subTest(suffix=suffix):
                outcome = self.parse([self.error(message + suffix)])
                self.assertEqual(outcome["errors"], [])
                self.assertEqual(len(outcome["warnings"]), 1)
                self.assertEqual(outcome["tool_errors"][0]["error"], message + suffix)
                self.assertFalse(outcome["completed"])
                self.assertEqual(outcome["final_text"], "")

    def test_missing_write_mismatched_path_and_event_error_remain_fatal(self):
        message = "Error: File not found: /repo/a.yml"
        write = self.error(message)
        write["part"]["tool"] = "write"
        for event in (write, self.error(message + ".other"), dict(type="error", error=message)):
            with self.subTest(event=event):
                outcome = self.parse([event])
                self.assertTrue(outcome["errors"])
                self.assertEqual(outcome["warnings"], [])

    def test_missing_read_does_not_hide_other_failures(self):
        missing = self.error("Error: File not found: /repo/a.yml")
        denied = self.error("PermissionDeniedError")
        denied["part"]["id"] = "denied"
        outcome = self.parse([missing, denied])
        self.assertEqual(outcome["errors"], ["PermissionDeniedError"])
        self.assertTrue(outcome["permission"])
        self.assertEqual(len(outcome["warnings"]), 1)
