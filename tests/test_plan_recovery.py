"""A stopped planner proposal never bypasses validation or grants a writer recovery."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.application import plan_recovery


class PlanRecoveryTests(unittest.TestCase):
    def test_only_context_stopped_planner_is_eligible(self):
        cases = [
            ("implementer", "CONTEXT_EXCEEDED"),
            ("planner", "SCOPE_VIOLATION"),
            ("planner", "TURN_ERROR"),
            ("planner", "INTERRUPTED"),
        ]
        for stage, status in cases:
            with self.subTest(stage=stage, status=status):
                outcome = dict(status=status)
                with patch.object(plan_recovery, "validated") as validate:
                    self.assertIsNone(plan_recovery.recover(None, dict(stage=stage), outcome))
                validate.assert_not_called()

    def test_both_review_stages_salvage_only_a_validated_verdict(self):
        for stage in ("plan-reviewer", "reviewer"):
            saved = dict(status="REQUEST_CHANGES")
            with patch.object(plan_recovery, "validated", return_value=saved) as validate:
                record = dict(stage=stage)
                outcome = dict(status="CONTEXT_EXCEEDED")
                self.assertIs(plan_recovery.recover(None, record, outcome), saved)
                validate.assert_called_once_with(None, record, outcome)
            self.assertEqual(record["plan_recovery"]["status"], "validated")

    def test_invalid_plan_keeps_transport_status_and_supplies_exact_repair_feedback(self):
        record = dict(stage="planner")
        outcome = dict(status="CONTEXT_EXCEEDED")
        with patch.object(plan_recovery, "validated", side_effect=ValueError("Stale evidence")):
            self.assertIsNone(plan_recovery.recover(None, record, outcome))
        self.assertEqual(outcome["status"], "CONTEXT_EXCEEDED")
        self.assertEqual(record["plan_recovery"]["status"], "rejected")
        with tempfile.TemporaryDirectory() as directory:
            message = plan_recovery.feedback(outcome, Path(directory))
            self.assertIn("Stale evidence", message)
            self.assertIn("Read the current plan file", message)
            record["plan_recovery"]["reason"] = "Missing source window. " * 1000
            self.assertIn("validation.json", plan_recovery.feedback(outcome, Path(directory)))
            self.assertTrue(Path(directory, "validation.json").is_file())

    def test_blocked_partial_plan_is_not_accepted_as_ready_work(self):
        with patch.object(plan_recovery, "validated", return_value=dict(status="BLOCKED")):
            self.assertIsNone(
                plan_recovery.recover(None, dict(stage="planner"), dict(status="CONTEXT_EXCEEDED"))
            )
