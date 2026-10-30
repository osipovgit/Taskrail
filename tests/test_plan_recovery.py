"""A stopped planner proposal never bypasses validation or grants a writer recovery."""

import unittest
from unittest.mock import patch

from taskrail.application import plan_recovery


class PlanRecoveryTests(unittest.TestCase):
    def test_only_context_stopped_planner_is_eligible(self):
        cases = [
            ("implementer", "CONTEXT_EXCEEDED"),
            ("reviewer", "CONTEXT_EXCEEDED"),
            ("planner", "SCOPE_VIOLATION"),
            ("planner", "BLOCKED_PERMISSION"),
            ("planner", "INTERRUPTED"),
        ]
        for stage, status in cases:
            with self.subTest(stage=stage, status=status):
                outcome = dict(status=status)
                with patch.object(plan_recovery, "validated") as validate:
                    self.assertIsNone(plan_recovery.recover(None, dict(stage=stage), outcome))
                validate.assert_not_called()

    def test_legacy_admission_flag_does_not_override_current_plan_validation(self):
        verdict = dict(status="PLAN_READY")
        outcome = dict(status="CONTEXT_EXCEEDED", admission_blocked=True)
        record = dict(stage="planner")
        with patch.object(plan_recovery, "validated", return_value=verdict) as validate:
            self.assertEqual(plan_recovery.recover(None, record, outcome), verdict)
        validate.assert_called_once_with(None, record, outcome)
        self.assertEqual(record["plan_recovery"]["status"], "validated")

    def test_invalid_plan_keeps_transport_status_and_supplies_exact_repair_feedback(self):
        record = dict(stage="planner")
        outcome = dict(status="CONTEXT_EXCEEDED")
        with patch.object(plan_recovery, "validated", side_effect=ValueError("Stale evidence")):
            self.assertIsNone(plan_recovery.recover(None, record, outcome))
        self.assertEqual(outcome["status"], "CONTEXT_EXCEEDED")
        self.assertEqual(record["plan_recovery"]["status"], "rejected")
        self.assertIn("Stale evidence", plan_recovery.feedback(outcome))
        self.assertIn("Read the current plan file", plan_recovery.feedback(outcome))

    def test_blocked_partial_plan_is_not_accepted_as_ready_work(self):
        with patch.object(plan_recovery, "validated", return_value=dict(status="BLOCKED")):
            self.assertIsNone(
                plan_recovery.recover(None, dict(stage="planner"), dict(status="CONTEXT_EXCEEDED"))
            )
