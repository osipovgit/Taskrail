"""Independent review accepts only source delivered to its active model session."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail.application import (
    citation_review,
    evidence,
    evidence_delivery,
    result_validation,
    source_packet,
)
from taskrail.core.files import atomic_json
from taskrail.interactions.session import received_turn


class EvidenceAudienceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.root = base / "source"
        self.root.mkdir()
        self.path = self.root / "sample.py"
        self.path.write_text("".join(f"value_{number} = {number}\n" for number in range(1, 101)))
        self.run = base / "run"
        self.folder = self.run / "03-reviewer"
        self.folder.mkdir(parents=True)
        self.context = dict(
            role="reviewer",
            stage="reviewer",
            roots=dict(repo=self.root),
            run=self.run,
            folder=self.folder,
            session_id="current-session",
            changed=[str(self.path)],
            requirements=[dict(id="R-stable", kind="task", text="Return the intended value")],
            plan=dict(steps=[dict(id="T1")], proposed_change_files=[str(self.path)]),
            deliver_lines=False,
        )
        self.outcome = dict(status="OK", completed=True, sessions=["current-session"])

    def observe(self, folder, session):
        lines = self.path.read_text().splitlines()
        record = dict(
            tool="read",
            input=dict(filePath=str(self.path)),
            output="\n".join(f"{number}: {line}" for number, line in enumerate(lines, 1)),
            source_sha256=evidence.fingerprint(self.path),
            source_event=str(folder / "events.jsonl"),
            session_id=session,
            event_line=1,
        )
        atomic_json(self.run / evidence.OBSERVATIONS, dict(records=[record], omitted=0))

    def review(self, text):
        (self.run / "review.md").write_text(f"# Review\nSummary: Checked\nR1: {text}\n")
        return result_validation.validate("DONE", self.context)

    def test_other_stage_and_previous_session_reads_cannot_approve_absolute_citations(self):
        for folder, session in (
            (self.run / "01-planner", "planner-session"),
            (self.run / "02-reviewer", "previous-session"),
            (self.folder, "different-session"),
            (self.folder, None),
        ):
            with self.subTest(folder=folder, session=session):
                self.observe(folder, session)
                packet = source_packet.prepare(self.run, "reviewer", self.context["roots"])
                self.assertFalse(any("100" in entry["lines"] for entry in packet))
                self.assertEqual(self.review(f"done: {self.path}:100")["status"], "BLOCKED")
        self.observe(self.folder, "current-session")
        self.assertEqual(self.review(f"done: {self.path}:100")["status"], "APPROVE")

    def test_initial_packet_grants_only_its_received_lines_to_a_fresh_session(self):
        self.observe(self.run / "01-planner", "planner-session")
        source_packet.prepare(self.run, "reviewer", self.context["roots"])
        source_packet.queue_delivery(self.run, self.folder, "reviewer", "Frozen request")
        self.assertEqual(evidence_delivery.session_records(self.context), [])
        evidence_delivery.confirm(self.run, self.folder, "Frozen request", self.outcome)
        self.assertEqual(self.review(f"done: {self.path}:1")["status"], "APPROVE")
        self.assertEqual(self.review(f"done: {self.path}:100")["status"], "BLOCKED")
        self.context["session_id"] = "fresh-session"
        self.assertEqual(self.review(f"done: {self.path}:1")["status"], "BLOCKED")

    def feedback(self, count=6):
        claims = [
            dict(id=f"E{number}", path=str(self.path), line_start=number, line_end=number)
            for number in range(1, count + 1)
        ]
        with self.assertRaises(ValueError) as rejected:
            citation_review.validate(claims, [], dict(self.context, deliver_lines=True))
        return claims, str(rejected.exception)

    def test_omitted_corrections_never_become_delivered_evidence(self):
        claims, feedback = self.feedback()
        self.assertNotIn("6: value_6", feedback)
        self.assertEqual(evidence_delivery.session_records(self.context), [])
        evidence_delivery.confirm(self.run, self.folder, feedback, self.outcome)
        records = evidence_delivery.session_records(self.context)
        self.assertEqual(len(citation_review.validate(claims[:5], records, self.context)), 5)
        with self.assertRaises(ValueError):
            citation_review.validate(claims[5:], records, self.context)

    def test_unsent_failed_and_wrong_session_corrections_grant_nothing(self):
        for mode in ("unsent", "truncated", "failed", "incomplete", "different-session"):
            with self.subTest(mode=mode):
                _, feedback = self.feedback(1)
                outcome = dict(self.outcome)
                expected = "current-session"
                if mode == "unsent":
                    feedback = "Other response"
                if mode == "truncated":
                    feedback = feedback[:-1]
                if mode == "failed":
                    outcome["status"] = "PROCESS_ERROR"
                if mode == "incomplete":
                    outcome["completed"] = False
                if mode == "different-session":
                    outcome["sessions"] = ["other-session"]
                evidence_delivery.confirm(self.run, self.folder, feedback, outcome, expected)
                self.assertEqual(evidence_delivery.session_records(self.context), [])

    def test_a_restart_cannot_inherit_pending_undelivered_feedback(self):
        _, feedback = self.feedback(1)
        restarted = self.run / "04-reviewer"
        restarted.mkdir()
        self.context.update(folder=restarted, session_id="fresh-session")
        outcome = dict(self.outcome, sessions=["fresh-session"])
        evidence_delivery.confirm(self.run, restarted, feedback, outcome)
        self.assertEqual(evidence_delivery.session_records(self.context), [])

    def test_session_mismatch_cannot_approve_or_hide_a_transport_failure(self):
        prompt = self.folder / "request.md"
        prompt.write_text("Initial task")
        session = SimpleNamespace(
            launch=dict(prompt=prompt),
            context=dict(session_id="expected-session"),
            environment=dict(run=self.run),
            active=(self.folder, {}),
        )
        for status in ("OK", "PROCESS_ERROR", "TIMEOUT"):
            with self.subTest(status=status):
                response = dict(self.outcome, status=status)
                response["sessions"] = ["other-session"] if status == "OK" else []
                with patch("taskrail.interactions.session.run_agent", return_value=response):
                    result = received_turn(session, {})
                expected = "SESSION_ERROR" if status == "OK" else status
                self.assertEqual(result["status"], expected)
                self.assertEqual(evidence_delivery.session_records(self.context), [])

    def test_identical_reads_keep_their_distinct_session_audiences(self):
        earlier = self.run / "01-planner"
        earlier.mkdir()
        event = dict(
            type="tool_use",
            sessionID="current-session",
            part=dict(
                tool="read",
                callID="read",
                state=dict(
                    status="completed",
                    input=dict(filePath=str(self.path)),
                    output="1: value_1 = 1",
                ),
            ),
        )
        for folder in (earlier, self.folder):
            events = folder / "events.jsonl"
            events.write_text(json.dumps(event) + "\n")
            evidence.refresh(self.run, events, [self.root])
        self.assertEqual(len(evidence.validation_records(self.run)), 2)
        self.assertEqual(len(evidence_delivery.session_records(self.context)), 1)

    def test_no_change_approval_accepts_explained_not_applicable(self):
        self.context["plan"]["proposed_change_files"] = []
        self.assertEqual(
            self.review("n/a: The optional condition did not occur")["status"], "APPROVE"
        )
        with self.assertRaisesRegex(ValueError, "needs its reason"):
            self.review("n/a:")


if __name__ == "__main__":
    unittest.main()
