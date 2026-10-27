"""A split continues after a failed task, after outside edits, and ends its reviews."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_reviewed_workflow import ReviewedFixture

from taskrail.application import outside_changes, transitions
from taskrail.application.live import execute_task
from taskrail.core.files import atomic_json
from taskrail.web import (
    delivery_state,
    epic_launch,
    epic_tasks,
    integration_review,
    lifecycle,
    requests,
    run_activity,
    run_list,
)
from taskrail.web.run_view import run_view
from taskrail.web.submissions import TaskLauncher

FIELDS = dict(goal="Return 2 and add the new module", criteria="Both outputs work")


class SplitRecoveryTests(ReviewedFixture, unittest.TestCase):
    def split(self):
        fields = dict(FIELDS, roots=[dict(alias="project", path=str(self.root))])
        parent, status, state = self.execute("parent", fields, "two-tasks")
        self.assertEqual(status, "TASKS_READY", state.get("summary"))
        return parent, state

    def start(self, parent, state, epic, task, name, mode="ok"):
        """Link the attempt like the launcher does, then run it."""
        epic["tasks"][task] = name
        epic.setdefault("attempts", {}).setdefault(task, []).append(name)
        atomic_json(parent / "epic.json", epic)
        entries = epic_tasks.tasks(parent, state)
        current = next(entry for entry in entries if entry["id"] == task)
        return self.execute(name, epic_launch.payload(parent, state, entries, current), mode)

    def test_a_retry_continues_from_the_failed_attempt_and_the_next_task_follows(self):
        parent, state = self.split()
        epic = dict(tasks={})
        _, status, failed = self.start(parent, state, epic, "T1", "t1-a", "writer-prose-always")
        self.assertEqual(status, "INVALID_RESULT", failed.get("summary"))
        self.assertIn("return 2", (self.root / "hello.py").read_text())
        retry, status, retried = self.start(parent, state, epic, "T1", "t1-b")
        self.assertEqual(status, "READY_FOR_REVIEW", retried.get("summary"))
        request = (retry / "01-implement/request.md").read_text()
        self.assertIn("An earlier attempt of this task (run t1-a) ended as INVALID_RESULT", request)
        self.assertIn("-    return 1", (retry / "changes.diff").read_text())
        _, status, second = self.start(parent, state, epic, "T2", "t2")
        self.assertEqual(status, "READY_FOR_REVIEW", second.get("summary"))

    def test_outside_edits_between_tasks_reach_the_next_task_and_its_report(self):
        parent, state = self.split()
        epic = dict(tasks={})
        _, status, first = self.start(parent, state, epic, "T1", "t1")
        self.assertEqual(status, "READY_FOR_REVIEW", first.get("summary"))
        hello = self.root / "hello.py"
        hello.write_text("# operator edit\n" + hello.read_text())
        (self.root / "notes.txt").write_text("unrelated\n")
        second, status, done = self.start(parent, state, epic, "T2", "t2")
        self.assertEqual(status, "READY_FOR_REVIEW", done.get("summary"))
        outside = ["project/hello.py", "project/notes.txt"]
        self.assertEqual(done["outside_changes"], dict(files=outside, git=False))
        request = (second / "01-implement/request.md").read_text()
        self.assertIn("changed outside the tasks of this split", request)
        self.assertIn(str(self.root / "notes.txt"), request)
        self.assertIn("keep edits unrelated to it", request)
        report = (second / "report.md").read_text()
        self.assertIn("## Changed outside this task", report)
        self.assertIn(f"- {self.root / 'notes.txt'}", report)
        self.assertIn("# operator edit", hello.read_text())
        delivery = delivery_state.view(parent, json.loads((parent / "run.json").read_text()))
        self.assertEqual(delivery["tasks"][1]["outside_files"], outside)
        self.assertIn(
            "changed outside the split before it started: project/hello.py",
            integration_review.changes_by_task(delivery["tasks"]),
        )

    def retry_worker(self, folder, manifest, run, options):
        """Run the actual workflow synchronously after the launcher's durable link."""
        settings = json.loads(self.settings.read_text())
        settings["command"][-1] = "ok"
        atomic_json(self.settings, settings)
        execute_task(folder / "task.md", self.settings, run_dir=run)

    def test_child_restart_action_retains_assignment_and_cannot_repeat_old_attempt(self):
        parent, state = self.split()
        child, _, _ = self.start(
            parent, state, dict(tasks={}), "T1", "failed", "writer-prose-always"
        )
        launcher = TaskLauncher(self.runs, self.settings, recover=False)
        with patch("taskrail.web.submissions.start_worker", side_effect=self.retry_worker):
            result = launcher.action(dict(id=child.name, action="restart"))
        retry = self.runs / result["id"]
        retried = json.loads((retry / "run.json").read_text())
        self.assertEqual(retried["status"], "READY_FOR_REVIEW", retried["summary"])
        self.assertEqual(
            [attempt["stage"] for attempt in retried["attempts"]], ["implementer", "reviewer"]
        )
        self.assertEqual(
            retried["requirements"], json.loads((child / "run.json").read_text())["requirements"]
        )
        epic = json.loads((parent / "epic.json").read_text())
        self.assertEqual(epic["tasks"]["T1"], retry.name)
        self.assertEqual(epic["attempts"]["T1"], [child.name, retry.name])
        self.assertIn("-    return 1", (retry / "changes.diff").read_text())
        with self.assertRaisesRegex(ValueError, "latest attempt"):
            launcher.action(dict(id=child.name, action="restart"))
        # A task run never becomes a detached planner or conversation.
        for mode in ("restart", "followup", "answer", "design"):
            with self.subTest(mode=mode), self.assertRaisesRegex(ValueError, "belongs to a split"):
                requests.Submission(
                    dict(parent_run=child.name, submission_mode=mode, **FIELDS), self.runs
                )
        child_state = json.loads((child / "run.json").read_text())
        self.assertFalse(lifecycle.actions(child, child_state, run_activity.Activity())["followup"])
        listed = [entry["id"] for entry in run_list.list_runs(self.runs)]
        self.assertNotIn(child.name, listed)
        self.assertNotIn(retry.name, listed)
        parent_entry = next(
            entry for entry in run_list.list_runs(self.runs) if entry["id"] == parent.name
        )
        self.assertEqual(parent_entry["members"], sorted([child.name, retry.name]))
        delivery = delivery_state.view(parent, json.loads((parent / "run.json").read_text()))
        first = delivery["tasks"][0]
        self.assertEqual(
            (first["run"], [entry["run"] for entry in first["attempts"]]),
            (retry.name, [child.name]),
        )
        self.assertEqual(first["attempts"][0]["status"], "INVALID_RESULT")
        self.assertEqual(
            run_view(self.runs, retry.name)["parent"], dict(run=parent.name, slot="T1")
        )

    def test_a_restart_after_outside_edits_starts_and_names_them(self):
        parent, state = self.split()
        child, _, before = self.start(
            parent, state, dict(tasks={}), "T1", "failed", "writer-prose-always"
        )
        source = self.root / "hello.py"
        source.write_text(source.read_text() + "# external edit\n")
        _, status = execute_task(
            child / "00-input/task.md", self.settings, run_dir=child, resume=True
        )
        refused = json.loads((child / "run.json").read_text())
        self.assertEqual(status, "BLOCKED")
        self.assertIn("Use Restart reviewed task", refused["summary"])
        self.assertEqual(len(refused["attempts"]), len(before["attempts"]))
        launcher = TaskLauncher(self.runs, self.settings, recover=False)
        with patch("taskrail.web.submissions.start_worker", side_effect=self.retry_worker):
            result = launcher.action(dict(id=child.name, action="restart"))
        retried = json.loads((self.runs / result["id"] / "run.json").read_text())
        self.assertEqual(retried["status"], "READY_FOR_REVIEW", retried["summary"])
        self.assertEqual(retried["outside_changes"], dict(files=["project/hello.py"], git=False))
        self.assertIn("# external edit", source.read_text())


class OutsideChangesTests(unittest.TestCase):
    def test_only_files_git_tracks_or_would_track_are_reported(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            (root / ".gitignore").write_text("build/\n*.log\n")
            (root / "build").mkdir()
            (root / "build/out.txt").write_text("generated")
            (root / "app.log").write_text("log")
            (root / "src.py").write_text("x = 1\n")
            (root / "new.py").write_text("y = 2\n")
            drift = outside_changes.Drift()
            drift.files.update(
                ["p/build/out.txt", "p/app.log", "p/src.py", "p/new.py", "p/.gitignore"]
            )
            summary = drift.summary({"p": str(root)})
        self.assertEqual(summary, dict(files=["p/.gitignore", "p/new.py", "p/src.py"], git=False))
        only_ignored = outside_changes.Drift()
        only_ignored.files.add("p/build/out.txt")
        with tempfile.TemporaryDirectory() as temp:
            subprocess.run(["git", "init", "-q", temp], check=True)
            Path(temp, ".gitignore").write_text("build/\n")
            Path(temp, "build").mkdir()
            Path(temp, "build/out.txt").write_text("generated")
            self.assertIsNone(only_ignored.summary({"p": temp}))


class ReviewOutcomeTests(unittest.TestCase):
    def test_findings_without_a_writer_end_the_run_instead_of_repeating_the_review(self):
        flow = dict(allowed=[], repair_count=0, stage="reviewer")
        state = dict(phase="integration")
        verdict = dict(status="REQUEST_CHANGES", summary="T2 broke T1", unverified=[])
        transitions.result_review(flow, state, verdict, 3)
        self.assertEqual(state["status"], "CHANGES_REQUESTED")
        self.assertEqual(flow["repair_count"], 0)
        writer = dict(allowed=["project/a.py"], repair_count=0, stage="reviewer")
        transitions.result_review(writer, {}, verdict, 3)
        self.assertEqual((writer["stage"], writer["repair_count"]), ("implementer", 1))


if __name__ == "__main__":
    unittest.main()
