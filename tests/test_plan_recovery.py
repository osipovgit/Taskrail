"""A stopped planner proposal never bypasses validation or grants a writer recovery."""

import unittest
from unittest.mock import patch

from taskrail.application import plan_recovery


class PlanRecoveryTests(unittest.TestCase):
    def test_only_context_stopped_planner_is_eligible(self):
        cases = [
            ("implementer", "CONTEXT_EXCEEDED", False),
            ("reviewer", "CONTEXT_EXCEEDED", False),
            ("planner", "SCOPE_VIOLATION", False),
            ("planner", "BLOCKED_PERMISSION", False),
            ("planner", "INTERRUPTED", False),
            ("planner", "CONTEXT_EXCEEDED", True),
        ]
        for stage, status, admission in cases:
            with self.subTest(stage=stage, status=status, admission=admission):
                outcome = dict(status=status, admission_blocked=admission)
                with patch.object(plan_recovery, "validated") as validate:
                    self.assertIsNone(plan_recovery.recover(None, dict(stage=stage), outcome))
                validate.assert_not_called()

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
