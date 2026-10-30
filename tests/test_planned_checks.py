"""Reviewed check selections cannot widen command authority or skip read-only checks."""

import unittest
from types import SimpleNamespace

from taskrail.application import planned_checks, transitions


class PlannedCheckTests(unittest.TestCase):
    def setUp(self):
        command = dict(cwd="/project", argv=["python3", "--version"], timeout_seconds=5)
        self.recipe = dict(kind="local", phase="check", adapter="exit-code", request=command)
        self.requirements = [dict(id="runtime-1", kind="runtime", text="Tests pass")]
        self.selection = dict(recipe_id="tests", criteria=["runtime-1"])
        self.workflow = SimpleNamespace(
            config=dict(
                check_recipes={"tests": self.recipe},
                check_specs=[],
                roots={"project": "/project"},
            ),
            state=dict(
                requirements=self.requirements,
                status="NO_CHANGES_REQUIRED",
                plan_review=dict(status="APPROVE"),
            ),
            flow=dict(plan=dict(check_selections=[self.selection]), allowed=[]),
        )

    def test_no_change_still_executes_reviewed_local_check(self):
        planned_checks.activate(self.workflow)
        self.assertEqual(self.workflow.state["status"], "RUNNING")
        self.assertEqual(self.workflow.flow["stage"], "check")
        spec = self.workflow.state["check_specs"][0]
        self.assertEqual(spec["criteria"], ["runtime-1"])
        self.assertEqual(spec["phase"], "check")
        self.assertEqual(spec["parameters"], {})
        self.assertNotIn("effect", self.workflow.flow)
        planned_checks.activate(self.workflow)
        self.assertEqual(self.workflow.state["check_specs"], [spec])

    def test_unapproved_selection_cannot_schedule_a_command(self):
        self.workflow.state["plan_review"]["status"] = "REQUEST_CHANGES"
        planned_checks.activate(self.workflow)
        self.assertNotIn("check_specs", self.workflow.state)
        self.assertNotIn("stage", self.workflow.flow)

    def test_unknown_recipe_and_static_binding_fail_before_approval(self):
        config = dict(self.workflow.config, task_spec=dict(requirements=self.requirements))
        for selection in (
            dict(recipe_id="unknown", criteria=["runtime-1"]),
            dict(recipe_id="tests", criteria=["unowned"]),
            dict(self.selection, argv=["arbitrary"]),
        ):
            with self.subTest(selection=selection), self.assertRaises(ValueError):
                planned_checks.validate(dict(check_selections=[selection]), config)

    def test_child_inherits_only_owned_local_runtime_bindings(self):
        planned_checks.activate(self.workflow)
        parent = self.workflow.state
        local = parent["check_specs"][0]
        parent["check_specs"].append(dict(local, id="remote", phase="server"))
        child = [dict(id="scoped-1", parent_id="runtime-1", kind="runtime")]
        assigned = planned_checks.inherit(parent, child)
        self.assertEqual(assigned, [dict(local, criteria=["scoped-1"])])
        self.assertEqual(planned_checks.inherit(parent, []), [])

    def test_failed_read_only_check_cannot_enter_implementation(self):
        state = dict(checks=[dict(status="FAIL")], status="RUNNING")
        flow = dict(stage="check", allowed=[], repair_count=0)
        transitions.checked(flow, state, 2)
        self.assertEqual(state["status"], "CHECK_FAILED")
        self.assertEqual(flow["stage"], "check")
        transitions.result_review(flow, state, dict(status="APPROVE", summary="Checked"), 2)
        self.assertEqual(state["status"], "NO_CHANGES_REQUIRED")
