"""Continuation grants, frozen modules and deterministic stage boundaries."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.application import (
    budget_extensions,
    budgets,
    instruction_modules,
    transitions,
)
from taskrail.core import task_graph
from taskrail.web.lifecycle import actions
from taskrail.web.submissions import worker_command


class StageBoundaryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name)

    def test_explicit_grant_keeps_consumption_and_survives_reload(self):
        limits = dict(timeout=10, seconds=10, attempts=1)
        first = dict(directory="01-plan", stage="planner", mode="model")
        budgets.reserve(self.run, first, limits)
        budgets.settle(self.run, "01-plan", dict(status="TIMEOUT", elapsed_seconds=10))
        with self.assertRaises(budgets.BudgetExceeded):
            budgets.reserve(self.run, dict(first, directory="02-plan"), limits)
        budget_extensions.grant(
            self.run,
            "planner",
            dict(timeout=10, stage_seconds=10, stage_attempts=1),
        )
        allowance = budgets.reserve(self.run, dict(first, directory="02-plan"), limits)
        self.assertEqual(allowance["timeout"], 10)
        self.assertEqual(allowance["attempts_remaining"], 1)
        self.assertNotIn("tools", allowance)
        ledger = budgets.load(self.run)
        self.assertEqual(ledger["attempts"]["01-plan"]["elapsed"], 10)
        self.assertEqual(len(ledger["grants"]), 1)
        other = budgets.reserve(
            self.run, dict(first, directory="03-review", stage="reviewer"), limits
        )
        self.assertEqual(other["timeout"], 10)

    def test_budget_blocked_has_continue_and_delete_but_busy_run_does_not(self):
        state = dict(
            contract_version=1, status="STAGE_BUDGET_EXCEEDED", stages=[dict(mode="model")]
        )
        (self.run / "run.json").write_text(json.dumps(state))
        (self.run / "checkpoint.json").write_text(json.dumps(dict(stage="planner")))
        controls = actions(self.run, state, False)
        self.assertTrue(controls["resume_budget"])
        self.assertTrue(controls["delete"])
        self.assertTrue(controls["budget_paused"])
        self.assertFalse(actions(self.run, state, True)["resume_budget"])
        self.assertFalse(actions(self.run, state, True)["delete"])
        state["status"] = "BLOCKED"
        self.assertTrue(actions(self.run, state, False)["resume"])
        (self.run / "checkpoint.json").write_text(json.dumps(dict(stage="implementer")))
        self.assertTrue(actions(self.run, state, False)["resume"])
        state["status"] = "BLOCKED_PERMISSION"
        self.assertFalse(actions(self.run, state, False)["resume"])
        (self.run / "checkpoint.json").unlink()
        state["status"] = "INTERRUPTED"
        self.assertFalse(actions(self.run, state, False)["resume"])
        self.assertTrue(actions(self.run, state, False)["delete"])

    def test_worker_budget_flag_is_explicit(self):
        normal = worker_command(self.run, self.run, self.run / "missing", True, False)
        extended = worker_command(self.run, self.run, self.run / "missing", True, True)
        self.assertNotIn("--extend-budget", normal)
        self.assertIn("--extend-budget", extended)
        self.assertIn("--resume", extended)

    def test_modules_are_selected_frozen_and_tamper_checked(self):
        state = {}
        (self.run / "00-input").mkdir()
        plan = dict(files_read=["/repo/app.py"], proposed_change_files=["/repo/app.py"])
        execution = ("implementer", plan, [], None)
        text = instruction_modules.render(self.run, execution, state)
        self.assertIn("python v1:", text)
        self.assertIn("verification v2:", text)
        self.assertIn("reading v5:", text)
        self.assertNotIn("shell v1:", text)
        self.assertNotIn("ui v1:", text)
        with patch.object(instruction_modules, "CATALOG", self.run / "absent"):
            self.assertEqual(instruction_modules.render(self.run, execution, state), text)
        frozen = self.run / "00-input/modules.json"
        frozen.write_text("[]")
        with self.assertRaisesRegex(ValueError, "changed"):
            instruction_modules.render(self.run, execution, state)
        frozen.unlink()
        with self.assertRaisesRegex(ValueError, "missing"):
            instruction_modules.render(self.run, execution, state)

    def test_language_modules_follow_the_plan_and_disjoint_ones_stay_absent(self):
        catalog = json.loads(instruction_modules.CATALOG.read_text())
        plan = dict(proposed_change_files=[f"/repo/{index}.sh" for index in range(4)])
        selected = instruction_modules.select(catalog, ("plan-reviewer", plan), {})
        self.assertEqual({entry["id"] for entry in selected}, {"reading", "shell", "verification"})
        selected = instruction_modules.select(catalog, ("implementer", None), {})
        self.assertEqual([entry["id"] for entry in selected], ["reading"])

    def test_tasks_run_in_dependency_order_and_cycles_are_named(self):
        steps = [
            dict(id="T1", depends_on=["T3"]),
            dict(id="T2", depends_on=[]),
            dict(id="T3", depends_on=["T2"]),
            dict(id="T4", depends_on=["T2"]),
        ]
        self.assertEqual(task_graph.order(steps), ["T2", "T3", "T1", "T4"])
        self.assertEqual(task_graph.ancestors(steps, "T1"), {"T2", "T3"})
        steps[1]["depends_on"] = ["T1"]
        with self.assertRaisesRegex(ValueError, "cycle: T1 -> T3 -> T2 -> T1"):
            task_graph.order(steps)
        with self.assertRaisesRegex(ValueError, "T5 depends on an unknown task or itself"):
            task_graph.order([dict(id="T5", depends_on=["T5"])])

    def test_approved_no_change_plan_never_enters_writer(self):
        state = dict(status="RUNNING", results={})
        flow = dict(stage="plan-reviewer", plan={"proposed_change_files": []}, plan_repairs=0)
        verdict = dict(
            status="APPROVE", summary="Already satisfied", unverified=[], blocking_gaps=[]
        )
        transitions.advance(flow, state, verdict, "02-plan-review/result.json", 2)
        self.assertEqual(state["status"], "NO_CHANGES_REQUIRED")
        self.assertNotIn("effect", flow)

    def test_failed_checks_repair_once_then_stop(self):
        state = dict(status="RUNNING", checks=[dict(status="FAIL")])
        flow = dict(stage="check", repair_count=0, allowed=["project/example.py"])
        transitions.checked(flow, state, 1)
        self.assertEqual(flow["stage"], "implementer")
        self.assertEqual(flow["repair_count"], 1)
        transitions.checked(flow, state, 1)
        self.assertEqual(state["status"], "CHECK_FAILED")
