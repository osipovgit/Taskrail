"""Only authenticated, current parent contracts can skip a child's planning stages."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from countersign.application import (
    check_configuration,
    reviewed_artifacts,
    reviewed_input,
    reviewed_start,
)
from countersign.application.source_guard import SourceGuard
from countersign.core import plan_document, task_lineage, task_spec
from countersign.core.files import atomic_json, digest


class ReviewedStartTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        (self.root / "a.py").write_text("answer = 1\n")
        self.parent = self.base / "parent"
        self.child = self.base / "child"
        (self.child / "00-input").mkdir(parents=True)
        (self.parent / "01-plan").mkdir(parents=True)
        (self.parent / "00-input").mkdir()
        (self.parent / "02-plan-review").mkdir()
        requirements = [
            dict(id="R1", kind="task", text="Return 2", source=dict(field="goal", start=0, end=8)),
            dict(
                id="R2",
                kind="task",
                text="Document the result",
                source=dict(field="criteria", start=0, end=19),
            ),
        ]
        plan = plan_document.payload(
            "Decision: split\nSummary: Return 2\n## Requirements\nR1 -> T1\nR2 -> T2\n"
            "## T1: Return 2\nDepends on: none\nFiles: project/a.py\n"
            "Done when: answer is 2\nVerify: Read the assignment\n"
            "## T2: Document\nDepends on: T1\nFiles: project/README.md\n"
            "Done when: The answer is documented\nVerify: Read the documentation\n",
            requirements,
            {"project": self.root},
        )
        atomic_json(self.parent / "01-plan/result.json", plan)
        atomic_json(self.parent / "02-plan-review/result.json", dict(status="APPROVE"))
        self.parent_state = dict(
            status="TASKS_READY",
            roots={"project": str(self.root)},
            requirements=requirements,
            results={"plan": "01-plan/result.json", "plan-review": "02-plan-review/result.json"},
            reviewed_plan_sha256=digest((self.parent / "01-plan/result.json").read_bytes()),
        )
        frozen = dict(check_recipes={}, verify_commands=[])
        check_configuration.capture(frozen, self.parent_state)
        atomic_json(self.parent / "run.json", self.parent_state)
        atomic_json(self.parent / "00-input/settings.json", frozen)
        atomic_json(self.child / "00-input/settings.json", frozen)
        guard = SourceGuard({"project": self.root})
        guard.capture()
        atomic_json(
            self.parent / "checkpoint.json",
            dict(expected=guard.expected, git_before=guard.git_before),
        )
        state = dict(
            requirements=task_lineage.for_step(requirements, plan["steps"][0]),
            roots=self.parent_state["roots"],
            results={},
            preimages={},
        )
        config = dict(
            phase="task",
            assigned_contract=dict(parent_run="parent", task_id="T1"),
            task_scope=["project/a.py"],
            roots={"project": self.root},
            task_text="The submitted task remains unchanged.",
            task_spec={"fields": [{"name": "goal", "text": "answer is 2"}]},
        )
        self.workflow = SimpleNamespace(
            run=self.child, state=state, config=config, guard=guard, flow={"stage": "planner"}
        )

    def test_authenticated_child_starts_writer_with_preimages_and_one_exact_scope(self):
        reviewed_start.begin(self.workflow)
        self.assertEqual(self.workflow.flow["stage"], "implementer")
        self.assertEqual(self.workflow.flow["allowed"], ["project/a.py"])
        self.assertEqual(self.workflow.flow["plan"]["steps"][0]["depends_on"], [])
        original = self.child / self.workflow.state["preimages"]["project/a.py"]
        self.assertEqual(original.read_text(), "answer = 1\n")
        self.assertEqual((self.root / "a.py").read_text(), "answer = 1\n")

    def test_legacy_unsealed_parent_keeps_independent_child_planning(self):
        self.parent_state.pop(reviewed_artifacts.SEAL)
        atomic_json(self.parent / "run.json", self.parent_state)
        reviewed_start.begin(self.workflow)
        self.assertEqual(self.workflow.flow["stage"], "planner")
        self.assertFalse((self.child / reviewed_start.REFERENCE).exists())

    def test_legacy_sealed_parent_without_field_provenance_keeps_child_planning(self):
        self.parent_state["requirements"][0].pop("source")
        atomic_json(self.parent / "run.json", self.parent_state)
        reviewed_start.begin(self.workflow)
        self.assertEqual(self.workflow.flow["stage"], "planner")
        self.assertFalse((self.child / reviewed_input.REFERENCE).exists())

    def test_changed_parent_artifact_cannot_reuse_prior_approval(self):
        with (self.parent / "01-plan/result.json").open("a") as stream:
            stream.write("\n")
        with self.assertRaisesRegex(ValueError, "Reviewed parent plan changed"):
            reviewed_start.begin(self.workflow)

    def test_changed_child_requirements_or_goal_require_parent_replanning(self):
        self.workflow.state["requirements"][0]["text"] = "Return 99"
        with self.assertRaisesRegex(ValueError, "Child criteria changed"):
            reviewed_start.begin(self.workflow)

    def test_new_source_snapshot_cannot_reuse_parent_plan(self):
        (self.root / "a.py").write_text("answer = 3\n")
        self.workflow.guard.capture()
        with self.assertRaisesRegex(ValueError, "Sources changed"):
            reviewed_start.begin(self.workflow)

    def test_integration_starts_one_independent_reviewer_without_write_authority(self):
        self.workflow.config["phase"] = "integration"
        reviewed_start.begin(self.workflow)
        self.assertEqual(self.workflow.flow["stage"], "reviewer")
        self.assertEqual(self.workflow.flow["allowed"], [])
        self.assertEqual(self.workflow.flow["plan"]["evidence"], [])
        self.assertEqual(self.workflow.state["preimages"], {})

    def test_parent_path_cannot_escape_run_storage(self):
        self.workflow.config["assigned_contract"]["parent_run"] = "../parent"
        with self.assertRaisesRegex(ValueError, "Invalid run ID"):
            reviewed_start.begin(self.workflow)

    def test_supplied_child_display_fields_cannot_reach_the_approved_writer(self):
        fields = self.workflow.config["task_spec"]["fields"]
        for name in ("title", "criteria", "current_behavior", "entry_points"):
            fields.append(dict(name=name, text=f"Unapproved instruction in {name}"))
        self.workflow.config["task_spec"]["context"] = "Unapproved sibling instruction"
        reviewed_start.begin(self.workflow)
        prompt = task_spec.prompt_text(self.workflow.config["task_spec"])
        self.assertEqual(self.workflow.flow["stage"], "implementer")
        self.assertNotIn("Unapproved", prompt)
        self.assertIn("Return 2", prompt)
        self.assertIn("Read the assignment", prompt)
        self.assertEqual(
            self.workflow.config["task_text"],
            "The submitted task remains unchanged.",
        )
        self.assertNotIn("Unapproved", (self.child / reviewed_input.REFERENCE).read_text())

    def test_resume_restores_sealed_inputs_without_reopening_parent_or_supplied_context(self):
        reviewed_start.begin(self.workflow)
        original = task_spec.prompt_text(self.workflow.config["task_spec"])
        self.workflow.config["task_spec"] = dict(fields=[], context="Unapproved original context")
        (self.parent / "run.json").unlink()
        reviewed_input.restore(self.workflow)
        self.assertEqual(task_spec.prompt_text(self.workflow.config["task_spec"]), original)
        self.assertTrue(self.workflow.config["reviewed_input"])
        with (self.child / reviewed_input.REFERENCE).open("a") as stream:
            stream.write(" ")
        with self.assertRaisesRegex(ValueError, "Reviewed child input changed"):
            reviewed_input.restore(self.workflow)
