"""Repair clipped executor citations without inheriting reads or trusting mutable sidecars."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import (
    citation_review,
    evidence,
    evidence_delivery,
    executor_streams,
    source_views,
)
from taskrail.interactions import transcripts


class ExecutorEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.run = self.base / "run"
        self.folder = self.run / "02-plan"
        self.folder.mkdir(parents=True)
        (self.folder / "events.jsonl").write_text("")
        self.context = dict(
            run=self.run,
            folder=self.folder,
            roots=dict(project=self.root),
            session_id="current",
            deliver_lines=True,
        )

    def snapshot(self, stdout):
        transcripts.local_snapshot(
            self.run,
            self.folder,
            dict(argv=["fixture"]),
            dict(status="SUCCEEDED", exit_code=0, stdout=stdout, stderr=""),
        )
        return self.run / "00-input/local/02-plan-0.json"

    def claim(self, path, line=1):
        return dict(id="E9", path=str(path), line_start=line, line_end=line)

    def feedback(self, claim):
        with self.assertRaises(ValueError) as rejected:
            citation_review.validate([claim], [], self.context)
        return str(rejected.exception)

    def test_short_executor_line_is_delivered_only_to_the_receiving_session(self):
        snapshot = self.snapshot("ansible-lint 26.9.0\n")
        line = next(
            i for i, text in enumerate(snapshot.read_text().splitlines(), 1) if '"stdout"' in text
        )
        claim = self.claim(snapshot, line)
        feedback = self.feedback(claim)
        self.assertIn("ansible-lint 26.9.0", feedback)
        self.assertIn("now recorded as read", feedback)
        self.assertEqual(evidence_delivery.session_records(self.context), [])
        outcome = dict(status="OK", completed=True, sessions=["current"])
        evidence_delivery.confirm(self.run, self.folder, feedback, outcome, "current")
        records = evidence_delivery.session_records(self.context)
        self.assertEqual(len(citation_review.validate([claim], records, self.context)), 1)
        fresh = dict(self.context, session_id="fresh")
        self.assertEqual(evidence_delivery.session_records(fresh), [])

    def test_long_json_scalar_redirects_to_exact_output_without_claiming_it_was_read(self):
        stdout = "ansible-lint 26.9.0\r\n" + "detail line\r\n" * 1000
        snapshot = self.snapshot(stdout)
        line = next(
            i for i, text in enumerate(snapshot.read_text().splitlines(), 1) if '"stdout"' in text
        )
        feedback = self.feedback(self.claim(snapshot, line))
        stream = snapshot.with_suffix(".stdout.txt")
        self.assertIn(str(stream), feedback)
        self.assertIn("instead of the JSON string", feedback)
        self.assertNotIn("now recorded as read", feedback)
        self.assertEqual(evidence_delivery.session_records(self.context), [])
        claim = self.claim(stream)
        record = dict(
            tool="read",
            input=dict(filePath=str(stream)),
            output="1: ansible-lint 26.9.0",
            source_sha256=evidence.fingerprint(stream),
            source_event="events.jsonl",
            event_line=1,
        )
        self.assertEqual(len(citation_review.validate([claim], [record], self.context)), 1)
        stream.write_text("fabricated version\n")
        self.assertIsNone(executor_streams.guidance(self.run, snapshot))
        stream.unlink()
        original = self.root / "outside.txt"
        original.write_bytes(stdout.encode())
        stream.symlink_to(original)
        self.assertIsNone(executor_streams.guidance(self.run, snapshot))

    def test_remote_ticket_streams_are_single_ticket_and_content_checked(self):
        snapshot = self.run / "00-input/ssh/ticket.json"
        snapshot.parent.mkdir(parents=True)
        text = "remote result\n" * 300
        ticket = dict(results=[dict(stdout=text)])
        snapshot.write_text(json.dumps([ticket]))
        stream = snapshot.with_suffix(".1-stdout.txt")
        stream.write_text(text)
        self.assertIn(str(stream), executor_streams.guidance(self.run, snapshot))
        for payload in ([ticket, ticket], [None], [dict(results=[None])], dict(result=[])):
            with self.subTest(payload=str(payload)[:40]):
                snapshot.write_text(json.dumps(payload))
                self.assertIsNone(executor_streams.guidance(self.run, snapshot))

    def test_executor_json_views_preserve_provenance_and_exclude_other_run_artifacts(self):
        snapshot = self.run / "00-input/local/report.json"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text(json.dumps([dict(rule="name") for _ in range(200)]))
        entry = source_views.prepare(self.run, snapshot, self.context["roots"])
        self.assertIsNotNone(entry)
        self.assertEqual(source_views.validate(self.run, Path(entry["path"]), {}), entry)
        self.assertEqual(
            json.loads(Path(entry["path"]).read_text()), json.loads(snapshot.read_text())
        )
        for name in ("request.md", "recovery.md", "plan.md", "evidence.json"):
            forbidden = self.run / name
            forbidden.write_bytes(snapshot.read_bytes())
            self.assertIsNone(source_views.prepare(self.run, forbidden, dict(broad=self.base)))
        snapshot.write_text("[]")
        with self.assertRaisesRegex(ValueError, "source changed"):
            source_views.validate(self.run, Path(entry["path"]), {})
