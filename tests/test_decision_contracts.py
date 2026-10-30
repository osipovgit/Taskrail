"""Small model results retain semantic review and exact delivered evidence."""

import tempfile
import unittest
from pathlib import Path

from taskrail.application import (
    evidence,
    evidence_delivery,
    result_validation,
    source_packet,
)
from taskrail.core.files import atomic_json
from taskrail.interactions import transcripts


class DecisionContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.path = self.root / "sample.py"
        self.path.write_text("value = 2\nother = 3\n")
        self.run = self.base / "run"
        self.folder = self.run / "03-reviewer"
        self.folder.mkdir(parents=True)
        self.context = dict(
            role="reviewer",
            stage="reviewer",
            roots=dict(repo=self.root),
            run=self.run,
            folder=self.folder,
            session_id="review-session",
            changed=[str(self.path)],
            requirements=[dict(id="R-stable", kind="task", text="Return two")],
            plan=dict(steps=[dict(id="T1")], proposed_change_files=[str(self.path)]),
        )
        self.observe()

    def observe(self):
        record = dict(
            tool="read",
            input=dict(filePath=str(self.path)),
            output="1: value = 2\n",
            source_sha256=evidence.fingerprint(self.path),
            source_event=str(self.folder / "events.jsonl"),
            session_id="review-session",
            event_line=1,
        )
        atomic_json(self.run / evidence.OBSERVATIONS, dict(records=[record], omitted=0))

    def test_implementation_derives_files_steps_and_status_from_its_final_word(self):
        self.context.update(role="implementer", stage="implementer")
        done = result_validation.validate(
            "Edited hello.py.\n**DONE:** hello() returns 2", self.context
        )
        self.assertEqual(done["status"], "IMPLEMENTED")
        self.assertEqual(done["summary"], "hello() returns 2")
        self.assertEqual(done["changed_files"], [str(self.path)])
        self.assertEqual(done["completed_steps"], ["T1"])
        self.assertEqual((done["coverage"], done["evidence"]), ([], []))
        blocked = result_validation.validate("BLOCKED: the inventory is missing", self.context)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["blocking_gaps"], ["the inventory is missing"])
        self.assertEqual(blocked["completed_steps"], [])
        with self.assertRaisesRegex(ValueError, "End your final message with DONE"):
            result_validation.validate('{"schema_version": 2}', self.context)

    def review(self, *lines, final=False):
        text = "# Review\nSummary: Checked.\n\n## Requirements\n" + "\n".join(lines) + "\n"
        (self.run / "review.md").write_text(text)
        return result_validation.validate("DONE", dict(self.context, deliver_lines=not final))

    def test_review_lines_become_the_stored_review_record(self):
        result = self.review(f"- R1: done: {self.path}:1")
        self.assertEqual((result["status"], result["schema_version"]), ("APPROVE", 1))
        self.assertEqual(result["coverage"][0]["outcome"], "satisfied")
        self.assertEqual(result["evidence"][0]["path"], str(self.path))
        self.assertEqual(result["summary"], "Checked.")
        self.assertTrue((self.folder / "review.md").is_file())

    def test_a_condition_that_did_not_occur_is_not_applicable_not_a_blocker(self):
        result = self.review("- R1: n/a: No optional source was unavailable")
        self.assertEqual(result["status"], "APPROVE")
        self.assertEqual(result["coverage"][0]["outcome"], "not_applicable")
        self.assertEqual(result["blocking_gaps"], [])
        with self.assertRaisesRegex(ValueError, "line 5: R1 needs its reason"):
            self.review("- R1: n/a:")

    def test_handles_only_cover_current_delivered_lines_of_this_stage(self):
        packet = source_packet.prepare(self.run, "reviewer", self.context["roots"])
        self.assertEqual(packet[0]["lines"], {"1": "value = 2"})
        self.assertEqual(self.review("- R1: done: S1:1")["status"], "APPROVE")
        with self.assertRaisesRegex(ValueError, "complete range"):
            self.review("- R1: done: S1:1-2")
        self.path.write_text("value = 3\n")
        with self.assertRaisesRegex(ValueError, "Stale source handle"):
            self.review("- R1: done: S1:1")

    def test_handles_are_not_available_to_a_different_stage(self):
        source_packet.prepare(self.run, "planner", self.context["roots"])
        with self.assertRaisesRegex(ValueError, "Unknown delivered"):
            self.review("- R1: done: S1:1")

    def test_a_failure_is_a_finding_at_its_observed_lines(self):
        result = self.review(f"- R1: fails: {self.path}:1 (returns the wrong value)")
        self.assertEqual(result["status"], "REQUEST_CHANGES")
        self.assertEqual(result["findings"][0]["file"], str(self.path))
        self.assertIn("returns the wrong value", result["findings"][0]["evidence"])
        with self.assertRaisesRegex(ValueError, "R1 needs its reason"):
            self.review(f"- R1: fails: {self.path}:1")

    def test_a_gap_blocks_with_its_reason(self):
        result = self.review("- R1: gap: The API contract is missing")
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocking_gaps"], ["R1: The API contract is missing"])
        self.assertFalse(result["input_complete"])

    def test_malformed_references_are_rejected_without_guessing_ranges(self):
        references = (
            f"{self.path}: command exited 0",
            f"{self.path}:0-1",
            f"{self.path}:2-1",
            "request.md:1-1",
            "S99:1-1",
        )
        for reference in references:
            with self.subTest(reference=reference), self.assertRaises(ValueError):
                self.review(f"- R1: done: {reference}")

    def test_executor_summary_needs_observed_snapshot_lines_not_commentary(self):
        (self.folder / "events.jsonl").write_text("")
        request = dict(cwd=str(self.root), argv=["ansible-lint", "roles/"], reason="Verify")
        outcome = dict(status="SUCCEEDED", exit_code=0, stdout="0 failure(s), 2 warning(s).")
        delivered = transcripts.local_snapshot(self.run, self.folder, request, outcome)
        evidence_delivery.confirm(
            self.run,
            self.folder,
            delivered,
            dict(status="OK", completed=True, sessions=["review-session"]),
        )
        snapshot = self.run / "00-input/local" / f"{self.folder.name}-0.json"
        with self.assertRaisesRegex(ValueError, "line 5"):
            self.review(f"- R1: done: {snapshot}: ansible-lint exit_code 0")
        number = next(
            index
            for index, line in enumerate(snapshot.read_text().splitlines(), 1)
            if '"exit_code": 0' in line
        )
        self.assertIn(str(snapshot), delivered)
        self.assertEqual(self.review(f"- R1: done: {snapshot}:{number}")["status"], "APPROVE")

    def test_every_requirement_needs_its_own_outcome_line(self):
        with self.assertRaisesRegex(ValueError, "no line for R1"):
            self.review("- Notes only")
        with self.assertRaisesRegex(ValueError, "R1 needs one outcome"):
            self.review("- R1: <outcome>")
        with self.assertRaisesRegex(ValueError, "R1 needs one outcome"):
            self.review("- R1: planned")
        with self.assertRaisesRegex(ValueError, "unknown or repeated"):
            self.review(f"- R1: done: {self.path}:1", f"- R1: done: {self.path}:1")

    def test_unconfirmed_evidence_becomes_a_gap_once_no_correction_follows(self):
        result = self.review(f"- R1: done: {self.path}:2", final=True)
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["coverage"][0]["outcome"], "gap")
        self.assertIn("evidence not confirmed", result["blocking_gaps"][0])
        self.assertEqual(result["evidence"], [])


if __name__ == "__main__":
    unittest.main()
