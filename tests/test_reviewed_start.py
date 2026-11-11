"""Only authenticated, current parent contracts can skip a child's planning stages."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from run_fixture import current_run

from taskrail.application import (
    check_configuration,
    citation_review,
    evidence_scope,
    execution_context,
    plan_reports,
    plan_result,
    reviewed_artifacts,
    reviewed_input,
    reviewed_start,
    source_views,
    source_windows,
)
from taskrail.application.source_guard import SourceGuard
from taskrail.core import plan_document, task_lineage, task_spec
from taskrail.core.files import atomic_json, digest
from taskrail.infrastructure import artifact_access
from taskrail.interactions import transcripts


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
        execution_context.capture(
            self.parent, dict(roots={"project": self.root}, worktrees={}), self.parent_state
        )
        atomic_json(self.parent / "run.json", current_run(self.parent_state))
        atomic_json(self.parent / "00-input/settings.json", frozen)
        atomic_json(self.child / "00-input/settings.json", frozen)
        guard = SourceGuard({"project": self.root})
        guard.capture()
        atomic_json(
            self.parent / "checkpoint.json",
            current_run(dict(expected=guard.expected, git_before=guard.git_before)),
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

    def test_child_reads_its_own_snapshot_at_the_reviewed_lines(self):
        manifest = self.parent / "00-input/original/status.jsonl"
        manifest.parent.mkdir()
        manifest.write_text('{"changed_entries":0}\n')
        path = self.parent / "01-plan/result.json"
        plan = json.loads(path.read_text())
        guide = self.root / "guide with spaces.md"
        guide.write_text("Independent context for the task.\n")
        plan["steps"][0]["read"] = [f"{manifest}:1-1", str(guide)]
        atomic_json(path, plan)
        self.parent_state["reviewed_plan_sha256"] = digest(path.read_bytes())
        atomic_json(self.parent / "run.json", current_run(self.parent_state))
        reviewed_start.begin(self.workflow)
        child_manifest = self.child / "00-input/original/status.jsonl"
        self.assertEqual(child_manifest.read_bytes(), manifest.read_bytes())
        installed = self.workflow.flow["plan"]
        self.assertEqual(installed["steps"][0]["read"], [f"{child_manifest}:1-1", str(guide)])
        self.assertEqual(installed["evidence"], [])
        supplied = source_windows.observations(self.workflow.config, installed)
        self.assertEqual(supplied[0]["input"]["filePath"], str(guide))
        self.assertEqual(supplied[0]["output"], "1: Independent context for the task.")
        self.assertEqual(json.loads(path.read_text()), plan)

    def test_child_can_read_only_its_planners_frozen_reports_and_continue(self):
        folder = self.parent / "01-plan"
        request = dict(cwd=str(self.root), argv=["lint", "."])
        stdout = "source.py:51: unused import\n" * 125
        outcome = dict(status="FAILED", exit_code=2, stdout=stdout, stderr="")
        for reason in ("T1 report", "T2 report"):
            transcripts.command_snapshot(folder, dict(request, reason=reason), outcome)
        reports = self.parent / "00-input/local"
        receipt = reports / "01-plan-0.json"
        stream = reports / "01-plan-0.stdout.txt"
        sibling = reports / "01-plan-1.stdout.txt"
        source = folder / "result.json"
        text = (
            "Decision: split\nSummary: Return 2\n## Requirements\nR1 -> T1\nR2 -> T2\n"
            f"## T1: Return 2\nFiles: project/a.py\nRead: {receipt}\n"
            "Done when: answer is 2\nVerify: Read the assignment\n"
            f"## T2: Document\nDepends on: T1\nFiles: project/README.md\nRead: {sibling}:7-12\n"
            "Done when: The answer is documented\nVerify: Read the documentation\n"
        )
        (self.parent / "plan.md").write_text(text)
        context = dict(
            run=self.parent,
            folder=folder,
            roots=self.workflow.config["roots"],
            requirements=self.parent_state["requirements"],
            session_id=None,
        )
        plan = plan_result.stage_result(context)
        plan_reports.bind(plan, context)
        plan_reports.bind(plan, context, verify=True)
        atomic_json(source, plan)
        self.parent_state["reviewed_plan_sha256"] = digest(source.read_bytes())
        atomic_json(self.parent / "run.json", current_run(self.parent_state))
        original = receipt.read_bytes()
        changed = json.loads(original)
        changed["request"]["argv"] = ["other"]
        atomic_json(receipt, changed)
        with self.assertRaisesRegex(ValueError, "Plan report changed"):
            plan_reports.bind(plan, context, verify=True)
        receipt.write_bytes(original)
        stream.write_text("modified output")
        with self.assertRaisesRegex(ValueError, "executor output changed"):
            plan_reports.bind(plan, context, verify=True)
        stream.unlink()
        receipt.write_text("changed by a later process")
        reviewed_start.begin(self.workflow)
        packet = self.child / plan_reports.DIRECTORY
        files = self.workflow.flow["plan"]["steps"][0]["read"]
        local_receipt = packet / "local.01-plan-0.json"
        local_stream = packet / "local.01-plan-0.stdout.txt"
        self.assertEqual(files, [str(local_receipt), str(local_stream)])
        self.assertEqual(local_receipt.read_bytes(), original)
        self.assertEqual(local_stream.read_text(), stdout)
        self.assertEqual(
            {path.name for path in packet.iterdir()}, {local_receipt.name, local_stream.name}
        )
        readable = artifact_access.model_inputs(self.child, self.child / "01-implement")
        self.assertIn(packet, readable)
        self.assertFalse(any(path in receipt.parents or path == receipt for path in readable))
        reviewed_input.restore(self.workflow)
        local_stream.write_text("clean")
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            reviewed_input.restore(self.workflow)
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            evidence_scope.verify_dependencies(
                dict(run=self.child, check_config=self.workflow.config),
                [dict(path=str(local_stream))],
            )
        local_receipt.write_text(json.dumps({"tampered": list(range(800))}))
        view = source_views.prepare(self.child, local_receipt, self.workflow.config["roots"])
        context = dict(
            run=self.child, check_config=self.workflow.config, roots=self.workflow.config["roots"]
        )
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            citation_review.checked(dict(path=view["path"]), [], context)
        second = self.base / "second"
        (second / "00-input").mkdir(parents=True)
        inherited = plan_reports.inherit(second, plan["steps"][1], self.parent)
        second_stream = second / plan_reports.DIRECTORY / "local.01-plan-1.stdout.txt"
        self.assertEqual(inherited["read"][0], f"{second_stream}:7-12")
        self.assertEqual(second_stream.read_text(), stdout)

    def test_split_refuses_missing_protected_or_redirected_planner_report(self):
        folder = self.parent / "00-input/git"
        folder.mkdir()
        protected = folder / ".env"
        protected.write_text("test")
        redirected = folder / "02-plan-0.txt"
        redirected.symlink_to(self.root / "a.py")
        for path in (protected, redirected, folder / "missing.txt"):
            with self.subTest(path=path.name), self.assertRaisesRegex(ValueError, "Invalid report"):
                plan_reports.bind(
                    dict(decision="split", steps=[dict(read=[str(path)])]),
                    dict(run=self.parent),
                )

    def test_split_reports_redirect_private_hints_before_review(self):
        for path in ("01-plan/request.md", "00-input/source-views/example.json"):
            with (
                self.subTest(path=path),
                self.assertRaisesRegex(ValueError, "original project file or executor report"),
            ):
                plan_reports.bind(
                    dict(decision="split", steps=[dict(read=[str(self.parent / path)])]),
                    dict(run=self.parent),
                )

    def test_authenticated_child_starts_writer_with_preimages_and_one_exact_scope(self):
        reviewed_start.begin(self.workflow)
        self.assertEqual(self.workflow.flow["stage"], "implementer")
        self.assertEqual(self.workflow.flow["allowed"], ["project/a.py"])
        self.assertEqual(self.workflow.flow["plan"]["steps"][0]["depends_on"], [])
        original = self.child / self.workflow.state["preimages"]["project/a.py"]
        self.assertEqual(original.read_text(), "answer = 1\n")
        self.assertEqual((self.root / "a.py").read_text(), "answer = 1\n")

    def test_parent_without_seal_or_field_provenance_is_refused(self):
        unsealed = dict(self.parent_state)
        unsealed.pop(reviewed_artifacts.SEAL)
        untyped = json.loads(json.dumps(self.parent_state))
        untyped["requirements"][0].pop("source")
        for state in (unsealed, untyped):
            atomic_json(self.parent / "run.json", current_run(state))
            with (
                self.subTest(state=sorted(state)),
                self.assertRaisesRegex(ValueError, "seal or requirement provenance is missing"),
            ):
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

    def test_a_new_source_snapshot_starts_the_task_and_names_the_outside_change(self):
        (self.root / "a.py").write_text("answer = 3\n")
        self.workflow.guard.capture()
        reviewed_start.begin(self.workflow)
        outside = self.workflow.state["outside_changes"]
        self.assertEqual((len(outside["files"]), outside["git"]), (1, False))
        self.assertTrue(outside["files"][0].endswith("a.py"), outside)
        note = self.workflow.flow["feedback"]["outside_changes"]
        self.assertIn(str(self.root / "a.py"), note)
        self.assertIn("If your assigned change is already there", note)

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
        self.assertIn("Task T1 of a reviewed split", prompt)
        self.assertEqual(self.workflow.flow["plan"]["steps"][0]["checks"], ["Read the assignment"])
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
