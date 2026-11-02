"""Unsupported histories never enter workflows; archive preserves exact artifacts."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from run_fixture import current_run

from taskrail.application import checkpoints, run_locks, run_store
from taskrail.cli_history import archive_old
from taskrail.core.files import atomic_json
from taskrail.deployment.settings_cleanup import clean
from taskrail.web import history, requests, restarts


class RunStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.run = self.base / "old"
        self.run.mkdir()
        self.original = '{"status":"BLOCKED","roots":{},"contract_version":1}\n'
        (self.run / "run.json").write_text(self.original)

    def test_unknown_formats_are_rejected_before_interpreting_other_fields(self):
        for value in (None, 1, 3, True, "2", 2.0):
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
        atomic_json(self.run / "checkpoint.json", dict(run_format=2, stage="planner"))
        self.assertTrue(checkpoints.resume_available(self.run, state)[0])
        state["release_identity"] = "other-release"
        self.assertIn("Restart", checkpoints.resume_available(self.run, state)[1])
        state = current_run(dict(status="INTERRUPTED"))
        atomic_json(self.run / "checkpoint.json", dict(stage="planner"))
        self.assertIn("run format", checkpoints.resume_available(self.run, state)[1])

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

    def test_archive_is_lossless_and_skips_current_and_external_symlinks(self):
        current = self.base / "current"
        current.mkdir()
        atomic_json(current / "run.json", current_run(dict(status="BLOCKED")))
        (self.base / "alias").symlink_to(self.run, target_is_directory=True)
        project = self.base / "project.txt"
        project.write_text("unchanged")
        with patch("pathlib.Path.home", return_value=self.base):
            self.assertEqual(archive_old(self.base), ["old"])
            self.assertEqual(archive_old(self.base), [])
        self.assertEqual((self.base / ".trash/old/run/run.json").read_text(), self.original)
        self.assertTrue((current / "run.json").exists())
        self.assertEqual(project.read_text(), "unchanged")

    def test_stale_running_history_is_archived_only_without_active_workers(self):
        original = '{"status":"RUNNING","contract_version":1}\n'
        (self.run / "run.json").write_text(original)
        with patch("pathlib.Path.home", return_value=self.base):
            lock_path = self.base / run_locks.STATE / run_locks.INSTALL_LOCK
            with run_locks.lock_file(lock_path) as lock:
                self.assertTrue(run_locks.locked(lock, run_locks.SHARED))
                with self.assertRaisesRegex(ValueError, "Stop active tasks"):
                    archive_old(self.base)
                self.assertTrue(self.run.exists())
            self.assertEqual(archive_old(self.base), ["old"])
        self.assertEqual((self.base / ".trash/old/run/run.json").read_text(), original)

    def test_settings_backup_is_exact_and_retains_cli_configuration(self):
        path = self.base / "settings.json"
        original = json.dumps(
            dict(command=["opencode-myfork"], max_change_files=7, max_change_lines=90)
        )
        path.write_text(original)
        clean(path)
        self.assertEqual(json.loads(path.read_text()), dict(command=["opencode-myfork"]))
        backups = list(self.base.glob("settings.json.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), original)
        clean(path)
        self.assertEqual(len(list(self.base.glob("settings.json.backup-*"))), 1)
