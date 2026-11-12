"""A planned local recipe follows real Markdown ownership into its atomic child."""

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from run_fixture import current_run

from taskrail.application import (
    check_catalog,
    check_planning,
    check_results,
    evidence,
    execution_evidence,
    plan_commands,
    plan_projection,
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
            sessionID="planner-session",
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

    def parsed(self, text=PLAN, feedback=None):
        (self.run / "plan.md").write_text(text)
        state = dict(run_format=3, requirements=self.requirements, changed_files=[])
        record = dict(number=1, role="planner", stage="planner", directory="01-plan")
        environment = dict(roots=self.roots, run=self.run, plan=None, check_config=self.config)
        environment["feedback"] = feedback
        outcome = dict(final_text="DONE", sessions=["planner-session"])
        plan = result_context.parse(outcome, record, state, environment)
        plan_validation.canonical_plan(plan, self.roots)
        plan_validation.validate_plan(plan, self.roots, self.base / "task.md", self.config)
        return plan

    def test_verify_bullet_keeps_argv_literal_through_plan_and_review_projection(self):
        executable = 'Run: {"root":"project","argv":["check","project/data,a;b"]}'
        with self.assertRaisesRegex(ValueError, "T1 Verify promises"):
            self.parsed(PLAN.replace("Run the unit-tests recipe", "lint --json exits 0"))
        text = PLAN.replace("Verify: Run the unit-tests recipe", "Verify:\n- " + executable)
        plan = self.parsed(text)
        chosen = plan_commands.entries(plan, self.roots)
        self.assertEqual(chosen[0]["recipe"]["request"]["argv"], ["check", "project/data,a;b"])
        execution = ("plan-reviewer", plan)
        view = plan_projection.plan_context(execution, self.config["task_spec"], self.roots)
        self.assertEqual(view["steps"][0]["verify"], [executable])

    def test_step_owns_ordinary_verify_command_with_empty_recipe_catalog(self):
        command = "ansible-playbook --syntax-check site.yml"
        self.requirements[1].update(kind="task", text="Check playbook syntax")
        self.config["check_recipes"] = {}
        text = PLAN.replace("## Check selections\n- unit-tests: R2\n", "")
        plan = self.parsed(text.replace("Run the unit-tests recipe", command))
        execution = ("plan-reviewer", plan)
        projection = plan_projection.plan_context(execution, self.config["task_spec"], self.roots)
        step = projection["steps"][0]
        self.assertEqual((step["id"], step["verify"]), ("T1", [command]))
        self.assertNotIn("required_checks", step)
        self.assertEqual(
            check_catalog.context(self.config, execution[0], projection)["check_catalog"], []
        )
        (self.run / "review.md").write_text(
            "## Requirements\nR1: planned\nR2: planned\nR3: planned\n"
        )
        review = result_validation.validate("DONE", self.context(plan))
        self.assertEqual(review["status"], "APPROVE")
        self.assertEqual(review["coverage"][1]["outcome"], "planned")

    def test_planner_must_answer_each_open_id_even_on_checkpoint_continuation(self):
        folder = self.run / "03-plan-review"
        folder.mkdir()
        prior = dict(findings=[dict(id="F3-1", criterion="R-docs")])
        atomic_json(folder / "result.json", prior)
        feedback = dict(previous_feedback=dict(findings_file=str(folder / "findings.json")))
        for response, message in (
            ("", "Missing: F3-1"),
            ("F3-1: disputed:", "use the issued finding ID"),
            ("F3-1: fixed: revised\nF3-1: disputed: reason", "has two decisions"),
            ("F3-2: fixed: revised", "Unknown or already closed: F3-2"),
        ):
            with self.subTest(response=response), self.assertRaisesRegex(ValueError, message):
                self.parsed(PLAN + "\n## Finding responses\n" + response, feedback)
        plan = self.parsed(
            PLAN + "\n## Finding responses\nF3-1: disputed: See T2: output docs.", feedback
        )
        self.assertEqual(
            plan["finding_responses"],
            [dict(id="F3-1", status="disputed", reason="See T2: output docs.")],
        )

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
        state = current_run(
            dict(
                requirements=self.requirements,
                status="TASKS_READY",
                plan_review=review,
                attempts=[],
            )
        )
        parent = SimpleNamespace(
            run=self.run, config=self.config, state=state, flow=dict(plan=plan, allowed=[])
        )
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
        (child / "00-input").mkdir()
        (child / "00-input/task.md").write_text("Verify the selected local check.\n")
        state = dict(
            roots={"project": str(self.root)}, requirements=requirements, auto_approve=True
        )
        atomic_json(child / "run.json", current_run(state))
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
