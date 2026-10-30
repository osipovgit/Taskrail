"""Damaged task authority cannot crash delivery advancement or disappear from the UI."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail.web import delivery_launch, run_errors, run_list, run_view


class CorruptRunTests(unittest.TestCase):
    def test_damaged_epic_does_not_hide_other_runs_or_overwrite_authority(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            damaged = self.make_run(base, "damaged")
            healthy = self.make_run(base, "healthy")
            (damaged / "epic.json").write_text("{broken")
            visited = []
            original = delivery_launch.proceed

            def advance(launcher, run):
                visited.append(run.name)
                return original(launcher, run)

            with patch.object(delivery_launch, "proceed", side_effect=advance):
                delivery_launch.advance(SimpleNamespace(base=base))
            self.assertEqual(set(visited), {damaged.name, healthy.name})
            self.assertEqual((damaged / "epic.json").read_text(), "{broken")
            self.assertTrue((damaged / "recovery-required.json").is_file())
            listed = {entry["id"]: entry for entry in run_list.list_runs(base)}
            self.assertEqual(listed["damaged"]["status"], "RECOVERY_REQUIRED")
            self.assertEqual(listed["healthy"]["status"], "BLOCKED")
            view = run_view.run_view(base, "damaged")
            self.assertEqual(view["status"], "RECOVERY_REQUIRED")
            self.assertEqual(view["actions"], {})
            (damaged / "epic.json").write_text('{"tasks": {}}')
            delivery_launch.advance(SimpleNamespace(base=base))
            self.assertFalse((damaged / "recovery-required.json").exists())

    def test_invalid_index_and_task_shape_stay_visible_without_crashing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            for name, malformed in (("json", "{broken"), ("shape", "[]")):
                run = self.make_run(base, name)
                (run / "run.json").write_text(malformed)
            delivery_launch.advance(SimpleNamespace(base=base))
            self.assertEqual(len(run_list.list_runs(base)), 2)
            for entry in run_list.list_runs(base):
                self.assertEqual(entry["status"], "RECOVERY_REQUIRED")
                self.assertEqual(
                    run_view.run_view(base, entry["id"])["status"], "RECOVERY_REQUIRED"
                )

    def test_invalid_nested_epic_is_preserved_by_failure_handler(self):
        malformed = (
            dict(tasks=[], phases={}),
            dict(tasks={}, phases=[]),
            dict(tasks={}, attempts={"T1": 3}),
            dict(tasks={}, phase_history=[[]]),
        )
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            self.make_run(base, "healthy")
            for number, epic in enumerate(malformed):
                run = self.make_run(base, f"damaged-{number}")
                original = json.dumps(epic)
                (run / "epic.json").write_text(original)
                run_errors.launch_failure(run, ValueError("Invalid saved delivery data"))
                self.assertTrue((run / "recovery-required.json").is_file())
            delivery_launch.advance(SimpleNamespace(base=base))
            listed = {entry["id"]: entry for entry in run_list.list_runs(base)}
            self.assertEqual(listed["healthy"]["status"], "BLOCKED")
            for number, epic in enumerate(malformed):
                run = base / f"damaged-{number}"
                self.assertEqual((run / "epic.json").read_text(), json.dumps(epic))
                self.assertTrue((run / "recovery-required.json").is_file())
                self.assertEqual(listed[run.name]["status"], "RECOVERY_REQUIRED")
                self.assertEqual(run_view.run_view(base, run.name)["actions"], {})

    @staticmethod
    def make_run(base, name):
        run = base / name
        (run / "00-input").mkdir(parents=True)
        (run / "00-input/task.md").write_text("# Example\n\nRepair source")
        (run / "run.json").write_text(json.dumps(dict(status="BLOCKED", roots={}, results={})))
        return run
