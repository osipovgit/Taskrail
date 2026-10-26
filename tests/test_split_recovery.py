"""A split continues after a failed task, after intended edits, and ends its reviews."""

import json
import threading
import unittest
from types import SimpleNamespace

from test_reviewed_workflow import ReviewedFixture

from countersign.application import transitions
from countersign.core.files import atomic_json
from countersign.web import epic_baseline, epic_launch, epic_tasks

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

    def test_accepted_current_files_let_the_next_task_start(self):
        parent, state = self.split()
        epic = dict(tasks={})
        _, status, first = self.start(parent, state, epic, "T1", "t1")
        self.assertEqual(status, "READY_FOR_REVIEW", first.get("summary"))
        (self.root / "hello.py").write_text(
            "# operator edit\n" + (self.root / "hello.py").read_text()
        )
        _, status, refused = self.start(parent, state, epic, "T2", "t2-a")
        self.assertEqual(status, "BLOCKED")
        self.assertIn("accept the current files", refused["summary"])
        launcher = SimpleNamespace(lock=threading.RLock())
        self.assertEqual(epic_baseline.accept(launcher, parent, "T2")["status"], "SOURCES_ACCEPTED")
        epic = json.loads((parent / "epic.json").read_text())
        _, status, accepted = self.start(parent, state, epic, "T2", "t2-b")
        self.assertEqual(status, "READY_FOR_REVIEW", accepted.get("summary"))
        with self.assertRaisesRegex(ValueError, "Only the next task"):
            epic_baseline.accept(launcher, parent, "T1")


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
