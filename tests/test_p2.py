"""Continuation grants, frozen modules and deterministic stage boundaries."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from countersign.application import (
    budget_extensions,
    budgets,
    instruction_modules,
    transitions,
)
from countersign.core import work_packages
from countersign.web.lifecycle import actions
from countersign.web.submissions import worker_command


class P2Tests(unittest.TestCase):
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
        self.assertIn("verification v1:", text)
        self.assertIn("reading v1:", text)
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

    def test_large_plan_gets_decomposition_and_disjoint_modules_stay_absent(self):
        catalog = json.loads(instruction_modules.CATALOG.read_text())
        plan = dict(proposed_change_files=[f"/repo/{index}.sh" for index in range(4)])
        selected = instruction_modules.select(catalog, ("plan-reviewer", plan), {})
        self.assertEqual(
            {entry["id"] for entry in selected},
            {"reading", "shell", "verification", "decomposition"},
        )
        selected = instruction_modules.select(catalog, ("implementer", None), {})
        self.assertEqual([entry["id"] for entry in selected], ["reading"])

    def test_shared_packages_need_transitive_dependencies(self):
        steps = [
            dict(id="S1", action="Change producer", files=["a.py"], criteria=["R1"], depends_on=[]),
            dict(
                id="S2", action="Change caller", files=["b.py"], criteria=["R2"], depends_on=["S1"]
            ),
            dict(
                id="S3",
                action="Complete integration",
                files=["a.py"],
                criteria=["R3"],
                depends_on=["S2"],
            ),
        ]
        work_packages.validate(steps)
        steps[-1]["depends_on"] = []
        with self.assertRaisesRegex(ValueError, "explicit dependency"):
            work_packages.validate(steps)
        steps[-1]["depends_on"] = ["S2"]
        steps[-1]["action"] = steps[0]["action"]
        with self.assertRaisesRegex(ValueError, "distinct deliverables"):
            work_packages.validate(steps)

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
        flow = dict(stage="check", repair_count=0)
        transitions.checked(flow, state, 1)
        self.assertEqual(flow["stage"], "implementer")
        self.assertEqual(flow["repair_count"], 1)
        transitions.checked(flow, state, 1)
        self.assertEqual(state["status"], "CHECK_FAILED")
