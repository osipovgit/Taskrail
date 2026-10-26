import json
import re
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from taskrail.application.attempt_retries import overflow_outputs
from taskrail.application.evidence import MAX_CHARACTERS, bounded
from taskrail.application.recovery import collect_evidence, write_evidence
from taskrail.infrastructure.context_overflow import tool_outputs


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

    def test_index_points_at_each_recorded_output(self):
        windowed = self.event("window", "1: first\n2: second\n")
        windowed["part"]["state"]["input"].update(offset=40, limit=200)
        self.write([windowed, self.event("whole", "1: only")])
        output = self.root / "recovery.md"
        index_end = write_evidence(output, collect_evidence(self.events, [self.root]))
        lines = output.read_text().splitlines()
        entries = lines[index_end - 2 : index_end]
        self.assertIn('file.py {"offset": 40, "limit": 200} · 19 characters', entries[0])
        for number, entry in enumerate(entries, 1):
            first, last = map(int, re.search(r"lines (\d+)-(\d+)$", entry).groups())
            self.assertEqual(lines[first - 1], f"## Tool result {number}")
            self.assertEqual(lines[last - 1], "END TOOL OUTPUT")

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

    def test_legacy_size_metadata_is_optional_and_never_overrides_saved_output(self):
        self.write([self.event("old", "1: exact source\n")])
        evidence = collect_evidence(self.events, [self.root])
        record = evidence["records"][0]
        record.pop("saved_chars")
        record.pop("original_chars")
        record["upstream_truncated"] = True
        for size in (None, 999999):
            with self.subTest(size=size):
                if size is not None:
                    record["saved_chars"] = size
                output = self.root / "recovery.md"
                end = write_evidence(output, evidence)
                lines = output.read_text().splitlines()
                self.assertIn("16 characters", lines[end - 1])
                self.assertIn('"upstream_truncated": true', output.read_text())
                self.assertIn("1: exact source", output.read_text())

    def test_upstream_truncation_is_preserved(self):
        event = self.event("one")
        event["part"]["state"]["metadata"]["truncated"] = True
        self.write([event])
        self.assertTrue(
            collect_evidence(self.events, [self.root])["records"][0]["upstream_truncated"]
        )

    def test_oversized_observation_does_not_hide_older_useful_evidence(self):
        older = dict(output="older useful lines")
        newest = dict(output="newest useful lines")
        oversized = dict(output="x" * (MAX_CHARACTERS + 1))
        for records, expected in (
            ([older, oversized], [older]),
            ([older, oversized, newest], [older, newest]),
            ([older, dict(output="x" * MAX_CHARACTERS), newest], [older, newest]),
        ):
            with self.subTest(record_count=len(records)):
                self.assertEqual(bounded(records), expected)


class OverflowOutputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        self.events = self.run / "01-plan/events.jsonl"
        self.events.parent.mkdir()
        self.workflow = SimpleNamespace(
            run=self.run, state=dict(stages=[dict(directory="01-plan")])
        )

    def write(self, *outputs):
        parts = [
            dict(tool="read", state=dict(input=dict(filePath=f"/p/{size}"), output="x" * size))
            for size in outputs
        ]
        parts.append(dict(tool="read", state=dict(input=dict(filePath="/p/b"), error="missing")))
        lines = [json.dumps(dict(type="tool_use", part=part)) for part in parts]
        self.events.write_text("\n".join([*lines, "[]", "{unfinished"]))

    def test_each_returned_output_is_measured(self):
        self.write(50)
        self.assertEqual(tool_outputs(self.events), [(50, 'read {"filePath": "/p/50"}')])
        self.assertEqual(tool_outputs(self.run / "absent.jsonl"), [])

    def test_overflow_note_names_only_large_outputs(self):
        self.write(12000, 50)
        note = overflow_outputs(self.workflow)
        self.assertIn("received 12050 characters of tool output", note)
        self.assertIn('read {"filePath": "/p/12000"} (12000 characters).', note)
        self.assertNotIn("/p/50", note)
        self.write(50)
        self.assertEqual(overflow_outputs(self.workflow), "")
