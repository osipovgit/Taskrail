"""Real subprocess stages reuse approved child contracts and retain independent review."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

from taskrail.application.live import execute_task
from taskrail.core.files import atomic_json
from taskrail.web import (
    epic_launch,
    epic_tasks,
    integration_review,
    parent_context,
    requests,
    task_form,
)

BASE = Path(__file__).resolve().parents[1]


class ReviewedFixture:
    """A source tree, a run store and execute(), which submits a form like the browser."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        (self.root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.root / "hello.py").write_text("# user comment\ndef hello():\n    return 1\n")
        self.runs = self.base / "runs"
        self.runs.mkdir()
        self.settings = self.base / "settings.json"

    def execute(self, name, payload, mode="ok"):
        folder = self.base / "submitted" / name
        folder.mkdir(parents=True)
        submission = requests.Submission(payload, self.runs)
        text, _ = task_form.build_task(submission.fields, self.runs)
        task = folder / "task.md"
        task.write_text(submission.decorate(text))
        parent_context.write(folder, submission.delivery["parent_context"])
        atomic_json(
            self.settings,
            dict(
                command=[
                    sys.executable,
                    str(BASE / "tests/fake_live.py"),
                    "--profiles",
                    str(self.base / "profiles"),
                    "--mode",
                    mode,
                ],
                agent_source=str(BASE / "taskrail/agents"),
                agent_directory=str(self.base / "profiles"),
                timeout_seconds=1 if mode == "writer-timeout" else 10,
            ),
        )
        run, status = execute_task(task, self.settings, run_dir=self.runs / name)
        state = json.loads((run / "run.json").read_text())
        return run, status, state


class ReviewedWorkflowTests(ReviewedFixture, unittest.TestCase):
    def test_two_atomic_children_then_one_combined_reviewer(self):
        fields = dict(
            goal="Return 2 and add the new module",
            criteria="Both outputs work",
            constraints="Preserve the user comment",
            roots=[dict(alias="project", path=str(self.root))],
        )
        parent, status, state = self.execute("parent", fields, "two-tasks")
        self.assertEqual(status, "TASKS_READY", state.get("summary"))
        self.assertIn("reviewed_plan_sha256", state)
        linked = {}
        for number, mode in enumerate(("ok", "new"), 1):
            entries = epic_tasks.tasks(parent, state)
            current = entries[number - 1]
            payload = epic_launch.payload(parent, state, entries, current)
            child, status, child_state = self.execute(f"child-{number}", payload, mode)
            self.assertEqual(status, "READY_FOR_REVIEW", child_state.get("summary"))
            self.assertEqual(
                [record["stage"] for record in child_state["attempts"]], ["implementer", "reviewer"]
            )
            self.assertEqual(child_state["contract_start"]["stage"], "implementer")
            linked[current["id"]] = child.name
            atomic_json(parent / "epic.json", dict(tasks=linked))
        before = {name: (self.root / name).read_bytes() for name in ("hello.py", "new.py")}
        atomic_json(
            parent / "epic.json", dict(tasks=linked, phases=dict(integration="integration"))
        )
        review, status, review_state = self.execute(
            "integration", integration_review.payload(parent, state)
        )
        self.assertEqual(status, "NO_CHANGES_REQUIRED", review_state.get("summary"))
        combined = (review / "changes.diff").read_text()
        self.assertIn("+++ " + str(self.root / "new.py"), combined)
        self.assertIn("--- " + str(self.root / "hello.py"), combined)
        request = (review / "01-review/request.md").read_text()
        self.assertIn("Mode: integration review of a finished split", request)
        self.assertNotIn("Write Decision", request)
        self.assertIn("T1: ", request.split("## Task split context", 1)[1])
        self.assertEqual([record["stage"] for record in review_state["attempts"]], ["reviewer"])
        self.assertEqual(review_state["review_outcome"]["source_effect"], "unchanged")
        self.assertEqual(before, {name: (self.root / name).read_bytes() for name in before})
        self.assertTrue((review / "report.md").is_file())

    def test_interrupted_child_resume_uses_sealed_inputs_after_parent_removal(self):
        fields = dict(
            goal="Return 2 and add the new module",
            criteria="Both outputs work",
            roots=[dict(alias="project", path=str(self.root))],
        )
        parent, status, state = self.execute("parent", fields, "two-tasks")
        self.assertEqual(status, "TASKS_READY", state.get("summary"))
        entries = epic_tasks.tasks(parent, state)
        payload = epic_launch.payload(parent, state, entries, entries[0])
        for name in ("criteria", "current_behavior", "entry_points", "split_context"):
            payload[name] = f"Unapproved instruction in {name}"
        child, status, child_state = self.execute("child", payload, "writer-timeout")
        self.assertEqual(status, "TIMEOUT", child_state.get("summary"))
        self.assertIn("Unapproved", (child / "00-input/task.md").read_text())
        self.assertNotIn("Unapproved", (child / "01-implement/request.md").read_text())
        (parent / "run.json").unlink()
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        settings["timeout_seconds"] = 5
        atomic_json(self.settings, settings)
        _, status = execute_task(
            child / "00-input/task.md", self.settings, run_dir=child, resume=True
        )
        resumed = json.loads((child / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", resumed.get("summary"))
        for stage in resumed["stages"]:
            if stage["stage"] == "implementer":
                prompt = (child / stage["directory"] / "request.md").read_text()
                self.assertNotIn("Unapproved", prompt)
        self.assertEqual(
            [stage["stage"] for stage in resumed["attempts"]],
            ["implementer", "implementer", "reviewer"],
        )
