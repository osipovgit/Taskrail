"""Child scope and inherited context contracts in disposable run directories."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from taskrail.application import child_inputs, plan_validation, task_config, task_scope
from taskrail.core import plan_contract, plan_document
from taskrail.web import epic_launch, epic_tasks, parent_context, requests, task_brief, task_form


class ChildContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.runs = self.base / "runs"
        self.runs.mkdir()
        self.parent = self.runs / "parent"
        (self.parent / "00-input").mkdir(parents=True)
        self.fields = dict(
            title="Parent goal",
            goal="Deliver both outputs",
            criteria="- First output is correct\n- Second output is correct",
            constraints="Preserve this exact constraint: café — unchanged.",
            roots=[dict(alias="project", path=str(self.root))],
        )
        self.original, _ = task_form.build_task(self.fields, self.runs)
        (self.parent / "00-input/task.md").write_text(self.original)
        (self.parent / "run.json").write_text(json.dumps(dict(roots={"project": str(self.root)})))
        self.settings = self.base / "settings.json"
        self.settings.write_text(json.dumps(dict(opencode_version="1.x")))

    def submit(self, payload):
        submission = requests.Submission(payload, self.runs)
        text, _ = task_form.build_task(submission.fields, self.runs)
        folder = self.base / "submitted"
        folder.mkdir()
        task = folder / "task.md"
        task.write_text(submission.decorate(text))
        parent_context.write(folder, submission.delivery["parent_context"])
        return task

    def test_real_markdown_split_scope_survives_epic_launch_and_child_validation(self):
        requirements = [dict(id="R1", text="First"), dict(id="R2", text="Second")]
        text = """# Plan
Decision: split
Summary: Two independent outputs.
## Requirements
- R1 → T1
- R2 → T2
## T1: First output
Depends on: none
Files: project/first.py
Done when: First output works
Verify: Run first check
## T2: Second output
Depends on: T1
Files: project/second.py
Done when: Second output works
Verify: Run second check
"""
        roots = {"project": self.root}
        plan = plan_document.payload(text, requirements, roots)
        plan_validation.canonical_plan(plan, roots)
        (self.parent / "plan.json").write_text(json.dumps(plan))
        state = dict(
            roots={"project": str(self.root)},
            results=dict(plan="plan.json"),
            requirements=requirements,
        )
        entries = epic_tasks.tasks(self.parent, state)
        self.assertEqual(entries[0]["files"], [str(self.root / "first.py")])
        task = self.submit(epic_launch.payload(self.parent, state, entries, entries[0]))
        config = task_config.configuration(task, self.settings)
        self.assertEqual(config["task_scope"], ["project/first.py"])
        single = dict(
            decision="single", steps=[dict(id="T1")], proposed_change_files=["project/first.py"]
        )
        task_scope.check(single, config)
        with self.assertRaisesRegex(ValueError, "replanning"):
            task_scope.check(dict(single, proposed_change_files=["project/second.py"]), config)
        with self.assertRaisesRegex(ValueError, "nested splits"):
            task_scope.check(dict(single, decision="split", steps=[{}, {}]), config)

    def test_child_scope_is_fail_closed_and_canonical(self):
        roots = {"project": self.root}
        for meta in (
            dict(phase="task"),
            dict(phase="task", task_scope="project/first.py"),
            dict(task_scope=["project/first.py"]),
            dict(phase="task", task_scope=["project/../outside.py"]),
            dict(phase="task", task_scope=["project/.git/config"]),
            dict(phase="task", task_scope=[str(self.base / "outside.py")]),
            dict(phase="task", task_scope=["project/first.py", str(self.root / "first.py")]),
            dict(phase="task", task_scope=["project/first.py"], decompose=True),
        ):
            with self.subTest(meta=meta), self.assertRaises(ValueError):
                task_scope.configured(meta, roots)
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "link").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "Symlink"):
            task_scope.configured(dict(phase="task", task_scope=["project/link/file.py"]), roots)

    def test_thirty_task_brief_is_bounded_and_snapshot_preserves_full_contracts(self):
        entries = []
        for number in range(1, 31):
            entries.append(
                dict(
                    id=f"T{number}",
                    title=f"Output {number}",
                    goal=f"Deliver output {number}",
                    done_when=[f"Output {number} works"],
                    checks=[f"Check {number}: " + "check " * 500],
                    notes=f"Notes {number}: " + "details " * 500,
                    files=[str(self.root / f"output{number}.py")],
                    requirements=["R1"],
                    scopes=[],
                    depends_on=[f"T{number - 1}"] if number > 1 else [],
                    status="READY_FOR_REVIEW" if number < 30 else None,
                    done=False,
                    changed_files=[f"project/output{number}.py"],
                    summary="Delivered " + "result " * 100,
                )
            )
        state = dict(
            roots={"project": str(self.root)}, requirements=[dict(id="R1", text="Correct outputs")]
        )
        payload = epic_launch.payload(self.parent, state, entries, entries[-1])
        self.assertLess(len(payload["split_context"]), task_form.FIELD_LIMIT)
        self.assertLess(len(payload["split_context"]), task_brief.BRIEF_BUDGET + 200)
        self.assertIn(entries[-1]["notes"], payload["split_context"])
        self.assertIn(entries[-1]["checks"][0], payload["split_context"])
        self.assertIn("never read the whole snapshot", payload["split_context"])
        self.assertIn(self.original, payload["parent_context"])
        for entry in entries:
            self.assertIn(entry["checks"][0], payload["parent_context"])
            self.assertIn(entry["notes"], payload["parent_context"])
        task = self.submit(payload)
        state = {}
        child = self.runs / "child"
        (child / "00-input").mkdir(parents=True)
        child_inputs.capture(task, child / "00-input", state)
        task.with_name(child_inputs.NAME).unlink()
        shutil.rmtree(self.parent)
        child_inputs.verify(child, state)
        preserved = child / "00-input" / child_inputs.NAME
        self.assertEqual(preserved.read_text(), payload["parent_context"])
        preserved.write_text(preserved.read_text() + "Changed")
        with self.assertRaisesRegex(ValueError, "changed"):
            child_inputs.verify(child, state)

    def test_parent_snapshot_missing_or_symlinked_cannot_resume(self):
        source = self.base / child_inputs.NAME
        source.write_text("Original parent")
        task = self.base / "task.md"
        task.write_text("task")
        child = self.runs / "child"
        inputs = child / "00-input"
        inputs.mkdir(parents=True)
        state = {}
        child_inputs.capture(task, inputs, state)
        target = inputs / child_inputs.NAME
        target.unlink()
        with self.assertRaisesRegex(ValueError, "Missing"):
            child_inputs.verify(child, state)
        target.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "Missing"):
            child_inputs.verify(child, state)

    def test_oversized_child_acceptance_fails_without_replacing_criteria_with_a_pointer(self):
        requirement = "Verify the original condition. " * 800
        state = dict(
            roots={"project": str(self.root)}, requirements=[dict(id="R1", text=requirement)]
        )
        current = dict(
            id="T1",
            title="Current",
            goal="Deliver current output",
            done_when=["Output works"],
            checks=["Check all criteria"],
            files=[str(self.root / "first.py")],
            requirements=["R1"],
            scopes=[],
            depends_on=[],
            status=None,
            done=False,
            changed_files=[],
            summary="",
            notes="Keep original conditions",
        )
        payload = epic_launch.payload(self.parent, state, [current], current)
        self.assertIn(requirement.strip(), payload["criteria"])
        with self.assertRaisesRegex(ValueError, "oversized field: criteria"):
            self.submit(payload)


class TaskConflictTests(unittest.TestCase):
    def step(self, name, path, dependencies=()):
        return dict(
            id=name,
            files=[path],
            depends_on=list(dependencies),
            criteria=["R1"],
            checks=["Verify output"],
        )

    def validate(self, steps):
        plan = dict(
            status="PLAN_READY",
            steps=steps,
            proposed_change_files=sorted({path for step in steps for path in step["files"]}),
            coverage=[dict(id="R1", outcome="planned")],
        )
        plan_contract.validate_plan_steps(plan, [dict(id="R1")])

    def test_unordered_tasks_cannot_own_the_same_file(self):
        steps = [self.step("T1", "/project/shared.py"), self.step("T2", "/project/shared.py")]
        with self.assertRaisesRegex(ValueError, "share files; declare a dependency"):
            self.validate(steps)

    def test_explicit_dependency_allows_sequential_writes_independent_of_list_order(self):
        self.validate(
            [
                self.step("T2", "/project/shared.py", ["T1"]),
                self.step("T1", "/project/shared.py"),
            ]
        )

    def test_transitive_dependency_orders_shared_writes(self):
        self.validate(
            [
                self.step("T1", "/project/shared.py"),
                self.step("T2", "/project/middle.py", ["T1"]),
                self.step("T3", "/project/shared.py", ["T2"]),
            ]
        )

    def test_distinct_files_need_no_dependency(self):
        self.validate([self.step("T1", "/project/first.py"), self.step("T2", "/project/second.py")])
