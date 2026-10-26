"""Durable allowances cannot be reset by retry, continuation or a process crash."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import access_recovery, attempt_context, budgets


class BudgetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.limits = dict(timeout=60, seconds=100, attempts=3)

    def record(self, number, stage="planner"):
        record = dict(directory=f"{number:02d}-plan", stage=stage, mode="model")
        (self.run / record["directory"]).mkdir()
        return record

    def test_elapsed_and_attempts_survive_reload(self):
        first = self.record(1)
        budgets.reserve(self.run, first, self.limits)
        budgets.settle(self.run, first["directory"], dict(status="TIMEOUT", elapsed_seconds=60))
        second = self.record(2)
        remaining = budgets.reserve(self.run, second, self.limits)
        self.assertEqual(remaining["timeout"], 40)
        self.assertEqual(remaining["attempts_remaining"], 1)
        # An unclean crash consumes the reserved time, rather than granting another hour.
        with self.assertRaisesRegex(budgets.BudgetExceeded, "time allowance"):
            budgets.reserve(self.run, self.record(3), self.limits)

    def test_operator_extension_is_recorded(self):
        first = self.record(1)
        budgets.reserve(self.run, first, self.limits)
        limits = dict(self.limits, seconds=200)
        remaining = budgets.reserve(self.run, self.record(2), limits)
        self.assertEqual(remaining["stage_seconds_remaining"], 140)
        self.assertEqual(len(budgets.load(self.run)["limits"]), 2)

    def test_many_calls_do_not_reduce_time_or_launch_allowance(self):
        first = self.record(1)
        budgets.reserve(self.run, first, self.limits)
        (self.run / first["directory"] / "events.jsonl").write_text(
            "\n".join(json.dumps({"type": "tool_use"}) for _ in range(1000))
        )
        budgets.settle(self.run, first["directory"], dict(status="OK", elapsed_seconds=1))
        remaining = budgets.reserve(self.run, self.record(2), self.limits)
        self.assertEqual(remaining["stage_seconds_remaining"], 99)
        self.assertNotIn("tools", remaining)

    def test_repeated_denied_arguments_stay_known_after_resume(self):
        error = dict(
            tool="glob", input={"path": "/outside", "pattern": "*"}, error="PermissionDeniedError"
        )
        state = {
            "stages": [
                dict(
                    stage="reviewer",
                    mode="access-recovery",
                    tool_errors=[error],
                    errors=["PermissionDeniedError"],
                )
            ]
        }
        restored = access_recovery.restore(state, "reviewer")
        self.assertEqual(restored.count, 1)
        self.assertFalse(
            restored.accept(
                dict(tool_errors=[error], errors=["PermissionDeniedError"], elapsed_seconds=1), 3600
            )
        )
        self.assertEqual(access_recovery.restore(state, "planner").count, 0)

    def test_attempt_limit_applies_independently_to_each_stage(self):
        limits = dict(self.limits, attempts=1)
        budgets.reserve(self.run, self.record(1), limits)
        with self.assertRaisesRegex(budgets.BudgetExceeded, "attempt allowance"):
            budgets.reserve(self.run, self.record(2), limits)
        self.assertEqual(
            budgets.reserve(self.run, self.record(3, "reviewer"), limits)["timeout"], 60
        )

    def test_provenance_uses_recorded_role_source(self):
        inputs = self.run / "00-input"
        inputs.mkdir()
        (inputs / "contract.json").write_text("{}")
        record = dict(self.record(1), role="planner")
        state = {
            "agent_sources": {"planner": "saved-hash"},
            "contract_version": 1,
            "agent_source_directory": str(inputs / "agents"),
        }
        config = dict(timeout=60, stage_seconds=100, stage_attempts=3)
        attempt_context.prepare(self.run, record, config, state)
        self.assertEqual(record["agent_source"], str(inputs / "agents/planner.md"))
        self.assertEqual(record["agent_sha256"], "saved-hash")
