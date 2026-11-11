"""Only current-format run directories can supply task inputs and controls."""

import json
import tempfile
import unittest
from pathlib import Path

from run_fixture import current_run

from taskrail.application import checkpoints, run_store
from taskrail.core.files import atomic_json
from taskrail.web import history, requests, restarts
from taskrail.web.run_list import list_runs
from taskrail.web.run_view import run_view


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.run = self.base / "old"
        self.run.mkdir()
        atomic_json(self.run / "run.json", dict(status="BLOCKED", contract_version=1))

    def test_unknown_formats_are_rejected_before_interpreting_other_fields(self):
        for value in (None, 1, 2, 4, True, "3", 3.0):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "run format"):
                run_store.validate(dict(run_format=value))
        with self.assertRaisesRegex(ValueError, "run format"):
            restarts.restart(None, self.run)
        with self.assertRaisesRegex(ValueError, "run format"):
            history.task_draft(self.run)
        with self.assertRaisesRegex(ValueError, "run format"):
            requests.Submission(dict(parent_run="old", submission_mode="restart"), self.base)

    def test_continue_requires_same_release_and_current_checkpoint(self):
        state = current_run(dict(status="INTERRUPTED"))
        atomic_json(self.run / "checkpoint.json", dict(run_format=3, stage="planner"))
        self.assertTrue(checkpoints.resume_available(self.run, state)[0])
        state["release_identity"] = "other-release"
        self.assertIn("Restart", checkpoints.resume_available(self.run, state)[1])
        state = current_run(dict(status="INTERRUPTED"))
        atomic_json(self.run / "checkpoint.json", dict(stage="planner"))
        self.assertIn("run format", checkpoints.resume_available(self.run, state)[1])

    def test_hidden_storage_and_unsupported_parents_do_not_hide_current_children(self):
        hidden = self.base / ".submissions"
        hidden.mkdir()
        state = current_run(dict(status="READY_FOR_REVIEW"))
        atomic_json(hidden / "run.json", state)
        child = self.base / "child"
        (child / "00-input").mkdir(parents=True)
        atomic_json(child / "run.json", state)
        metadata = dict(phase="task", assigned_contract=dict(parent_run="old", task_id="T1"))
        task = f"```taskrail-task\n{json.dumps(metadata)}\n```\n# Child\nWork in scope.\n"
        (child / history.TASK_FILE).write_text(task)
        self.assertEqual([entry["id"] for entry in list_runs(self.base)], ["child"])
        self.assertIsNone(run_view(self.base, "child")["parent"])
        with self.assertRaisesRegex(ValueError, "Invalid run ID"):
            run_view(self.base, hidden.name)

    def test_same_format_restart_uses_current_inputs_after_release_change(self):
        state = current_run(dict(status="BLOCKED", roots={}, release_identity="previous"))
        atomic_json(self.run / "run.json", state)
        inputs = self.run / "00-input"
        inputs.mkdir()
        (inputs / "task.md").write_text("# Task\nDo the requested work.\n")
        original = (self.run / "run.json").read_bytes()
        draft = restarts.restart(None, self.run)["draft"]
        self.assertEqual(draft["goal"], "Do the requested work.")
        self.assertEqual((self.run / "run.json").read_bytes(), original)
