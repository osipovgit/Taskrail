import json
import tempfile
import unittest
from pathlib import Path

from countersign.application.recovery import collect_evidence, write_evidence


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = self.root / "events.jsonl"

    def event(self, key, output="source text", status="completed", path=None):
        return dict(
            type="tool_use",
            part=dict(
                callID=key,
                tool="read",
                state=dict(
                    status=status,
                    input=dict(filePath=path or str(self.root / "file.py")),
                    output=output,
                    metadata=dict(truncated=False),
                ),
            ),
        )

    def write(self, values):
        self.events.write_text("\n".join(json.dumps(v) for v in values) + "\n{unfinished")

    def test_only_successful_scoped_tool_data_with_provenance(self):
        self.write(
            [
                self.event("ok"),
                self.event("ok"),
                self.event("bad", status="error"),
                self.event("outside", path="/outside/file.py"),
                dict(type="text", part=dict(text="An unsupported model claim")),
                dict(type="reasoning", part=dict(text="Private reasoning")),
            ]
        )
        result = collect_evidence(self.events, [self.root])
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(result["records"][0]["event_line"], 1)
        output = self.root / "recovery.md"
        write_evidence(output, result)
        self.assertIn("source text", output.read_text())
        self.assertNotIn("unsupported model claim", output.read_text())
        self.assertNotIn("Private reasoning", output.read_text())

    def test_truncation_limits_and_omission_are_explicit(self):
        self.write([self.event(str(i), "abcdefghij") for i in range(3)])
        result = collect_evidence(self.events, [self.root], per_output=5, total_output=7)
        self.assertEqual([v["saved_chars"] for v in result["records"]], [5, 2])
        self.assertTrue(all(v["output_clipped"] for v in result["records"]))
        self.assertEqual(result["omitted"], 1)

    def test_empty_evidence_does_not_claim_previous_research(self):
        self.write([])
        output = self.root / "recovery.md"
        write_evidence(output, collect_evidence(self.events, [self.root]))
        self.assertIn("Research is still required", output.read_text())

    def test_upstream_truncation_is_preserved(self):
        event = self.event("one")
        event["part"]["state"]["metadata"]["truncated"] = True
        self.write([event])
        self.assertTrue(
            collect_evidence(self.events, [self.root])["records"][0]["upstream_truncated"]
        )
