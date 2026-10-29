"""A planned local recipe follows real Markdown ownership into its atomic child."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from taskrail.application import (
    check_planning,
    check_results,
    evidence,
    execution_evidence,
    plan_validation,
    planned_checks,
    result_context,
    result_validation,
    verify_commands,
)
from taskrail.application.source_guard import SourceGuard
from taskrail.core import coverage, task_lineage
from taskrail.core.files import atomic_json

PLAN = """Decision: split
Summary: Implement and verify one output, then document it.
## Requirements
- R1 → T1
- R2 → T1
- R3 → T2
## Check selections
- unit-tests: R2
## T1: Implement and verify the output
Depends on: none
Files: project/output.py
Done when: The output works
Verify: Run the unit-tests recipe
## T2: Document the output
Depends on: T1
Files: project/README.md
Done when: The output is documented
Verify: Read the documentation
"""


class PlannedRuntimeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        (self.root / "output.py").write_text("answer = 2\n")
        self.run = self.base / "parent"
        (self.run / "01-plan").mkdir(parents=True)
        events = self.run / "01-plan/events.jsonl"
        observed = dict(
            type="tool_use",
            part=dict(
                tool="read",
                callID="read-source",
                state=dict(
                    status="completed",
                    input=dict(filePath=str(self.root / "output.py")),
                    output="1: answer = 2\n",
                    metadata=dict(truncated=False),
                ),
            ),
        )
        events.write_text(json.dumps(observed) + "\n")
        evidence.refresh(self.run, events, [self.root])
        self.roots = dict(project=self.root)
        self.requirements = [
            dict(id="R-code", kind="task", text="Implement the output"),
            dict(id="R-tests", kind="runtime", text="Unit tests pass"),
            dict(id="R-docs", kind="task", text="Document the output"),
        ]
        recipe = dict(
            kind="local",
            phase="check",
            adapter="exit-code",
            request=dict(
                cwd=str(self.root), argv=[sys.executable, "-c", "print('pass')"], timeout_seconds=30
            ),
        )
        self.config = dict(
            roots=self.roots,
            check_recipes={"unit-tests": recipe},
            check_specs=[],
            verify_commands=[],
            worktrees={},
            task_spec=dict(requirements=self.requirements),
        )

    def parsed(self, text=PLAN):
        (self.run / "plan.md").write_text(text)
        state = dict(contract_version=1, requirements=self.requirements, changed_files=[])
        record = dict(role="planner", stage="planner", directory="01-plan")
        environment = dict(roots=self.roots, run=self.run, plan=None, check_config=self.config)
        plan = result_context.parse(dict(final_text="DONE"), record, state, environment)
        plan_validation.canonical_plan(plan, self.roots)
        plan_validation.validate_plan(plan, self.roots, self.base / "task.md", self.config)
        return plan

    def context(self, plan, stage="plan-reviewer"):
        return dict(
            role="reviewer",
            stage=stage,
            plan=plan,
            requirements=self.requirements,
            roots=self.roots,
            run=self.run,
            folder=self.run / "01-plan",
            changed=[],
            check_config=self.config,
            deliver_lines=True,
        )

    def test_markdown_and_compact_review_bind_the_local_check_to_its_child(self):
        plan = self.parsed()
        lines = "".join(f"- R{number}: planned\n" for number in range(1, 4))
        (self.run / "review.md").write_text(f"## Requirements\n{lines}")
        review = result_validation.validate("DONE", self.context(plan))
        self.assertEqual(review["status"], "APPROVE")
        state = dict(requirements=self.requirements, status="TASKS_READY", plan_review=review)
        parent = SimpleNamespace(config=self.config, state=state, flow=dict(plan=plan, allowed=[]))
        planned_checks.activate(parent)
        inherited = task_lineage.for_step(self.requirements, plan["steps"][0])
        specs = planned_checks.inherit(state, inherited)
        self.assertEqual(specs[0]["criteria"], ["R-tests"])
        self.assertEqual(
            planned_checks.inherit(
                state, task_lineage.for_step(self.requirements, plan["steps"][1])
            ),
            [],
        )
        self.execute_child(inherited, specs)

    def execute_child(self, requirements, specs):
        child = self.base / "child"
        folder = child / "01-check"
        folder.mkdir(parents=True)
        state = dict(
            roots={"project": str(self.root)}, requirements=requirements, auto_approve=True
        )
        atomic_json(child / "run.json", state)
        guard = SourceGuard(self.roots)
        guard.capture()
        workflow = SimpleNamespace(
            run=child,
            config=dict(self.config, check_specs=specs),
            state=state,
            guard=guard,
        )
        checks = verify_commands.run_commands(workflow, folder)
        self.assertEqual(checks[0]["status"], "PASS")
        record = check_results.read(child)[0]
        claims = [dict(id="E-check", path=record["path"])]
        trusted = execution_evidence.claim_ids(child, claims)
        outcome = dict(outcome="satisfied", evidence_ids=["E-check"])
        coverage.validate_outcome(outcome, requirements[1], {"E-check": {}}, trusted)

    def test_missing_selection_unknown_recipe_and_remote_recipe_cannot_plan_local_work(self):
        for text in (
            PLAN.replace("## Check selections\n- unit-tests: R2\n", ""),
            PLAN.replace("unit-tests: R2", "unknown-recipe: R2"),
        ):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parsed(text)
        self.config["check_recipes"]["unit-tests"]["phase"] = "validation"
        with self.assertRaisesRegex(ValueError, "owned local check recipe"):
            self.parsed()

    def test_runtime_plan_needs_owning_step_and_never_becomes_final_acceptance(self):
        plan = self.parsed()
        context = self.context(plan)
        permitted = check_planning.criteria(plan, context)
        self.assertEqual(permitted, {"R-tests"})
        missing_owner = copy.deepcopy(plan)
        missing_owner["steps"][0]["criteria"].remove("R-tests")
        self.assertEqual(check_planning.criteria(plan, self.context(missing_owner)), set())
        for stage in ("implementer", "reviewer"):
            with self.subTest(stage=stage), self.assertRaisesRegex(ValueError, "owned local"):
                coverage.validate_coverage(plan, self.requirements, stage, {}, permitted)
        with self.assertRaisesRegex(ValueError, "matching current CheckResult"):
            coverage.validate_outcome(
                dict(outcome="satisfied", evidence_ids=["E-source"]),
                self.requirements[1],
                {"E-source": {}},
            )


if __name__ == "__main__":
    unittest.main()
