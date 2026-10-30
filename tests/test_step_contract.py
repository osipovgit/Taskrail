"""Reviewed step gates and excluded deliverables survive direct child execution."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_plan_markdown import PLAN, REQUIREMENTS, ROOTS

from taskrail.application import check_selection, planned_checks, reviewed_plan, step_checks
from taskrail.core.plan_document import payload


class StepContractTests(unittest.TestCase):
    def test_markdown_retains_behavioral_exclusions_and_required_recipe_ids(self):
        text = PLAN.replace(
            "Notes: rename the variables",
            "Required checks:\n- lint\nNot ToDo: T2: web role fixes\nNotes: rename the variables",
        )
        plan = payload(text, REQUIREMENTS, ROOTS)
        first = plan["steps"][0]
        self.assertEqual(first["not_todo"], ["T2: web role fixes"])
        self.assertEqual(first["required_checks"], ["lint"])
        child = reviewed_plan.single(first, REQUIREMENTS)
        self.assertEqual(step_checks.names(child), ["lint"])
        self.assertEqual(child["steps"][0]["not_todo"], first["not_todo"])

    def test_exclusion_requires_another_known_owner(self):
        for text in ("T1: own work", "T3: absent task", "web role fixes", "T2:"):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, "Not ToDo"):
                payload(PLAN.replace("Notes:", f"Not ToDo: {text}\nNotes:"), REQUIREMENTS, ROOTS)

    def test_required_recipe_is_executed_without_inventing_criterion_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            target = Path(directory) / "worktree"
            source.mkdir()
            target.mkdir()
            command = dict(cwd=str(source), argv=["python3", "--version"], timeout_seconds=5)
            recipe = dict(kind="local", phase="check", adapter="exit-code", request=command)
            config = dict(
                roots={"p": target},
                worktrees={"p": dict(source=str(source), worktree=str(target))},
                check_recipes={"lint": recipe},
                verify_commands=[command],
            )
            plan = dict(steps=[dict(required_checks=["lint"])])
            workflow = SimpleNamespace(config=config, state=dict(requirements=[]), flow={})
            step_checks.install(workflow, plan)
            selected = check_selection.applicable(workflow)
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0]["recipe"]["request"]["cwd"], str(target))
            self.assertEqual(selected[0]["spec"]["criteria"], [])
            self.assertTrue(selected[0]["required"])
            self.assertEqual(workflow.state[step_checks.KEY], ["lint"])

    def test_unknown_remote_or_arbitrary_required_checks_never_run(self):
        catalog = {"remote": dict(kind="ssh", phase="server")}
        for names in (["missing"], ["remote"], [{"argv": ["evil"]}]):
            with self.subTest(names=names), self.assertRaises(ValueError):
                planned_checks.validate(
                    dict(steps=[dict(required_checks=names)]), dict(check_recipes=catalog)
                )

    def test_required_recipe_outside_roots_is_not_silently_skipped(self):
        recipe = dict(kind="local", phase="check", request=dict(cwd="/outside", argv=["lint"]))
        workflow = SimpleNamespace(
            config=dict(
                roots={"p": "/project"},
                check_recipes={"lint": recipe},
                required_local_checks=["lint"],
            ),
            state=dict(requirements=[]),
        )
        with self.assertRaisesRegex(ValueError, "outside the declared roots"):
            check_selection.applicable(workflow)
