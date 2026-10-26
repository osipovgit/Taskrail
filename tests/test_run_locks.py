"""Runs on different projects proceed in parallel; one project runs one task at a time."""

import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from countersign.application.live import execute_task
from countersign.application.run_locks import INSTALL_LOCK, STATE, conflict, run_locks
from countersign.web.run_activity import BusyError, require_idle

BASE = Path(__file__).resolve().parents[1]


class RunLockTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.base / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_projects_lock_independently_and_installation_waits_for_all(self):
        first, second = self.base / "a", self.base / "b"
        with run_locks([first], self.base / "run-1") as reason:
            self.assertIsNone(reason)
            with run_locks([second], self.base / "run-2") as parallel:
                self.assertIsNone(parallel)
            with run_locks([second, first], self.base / "run-3") as blocked:
                self.assertEqual(blocked, f"Another task is running on {first}")
            with run_locks([second], self.base / "run-1") as same_run:
                self.assertEqual(same_run, "This run is already active")
            self.assertEqual(conflict([first]), f"Another task is running on {first}")
            installer = Path.home() / STATE / INSTALL_LOCK
            with installer.open("a") as stream, self.assertRaises(BlockingIOError):
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.assertIsNone(conflict([first]))
        with installer.open("a") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with run_locks([first], self.base / "run-4") as reason:
                self.assertEqual(reason, "An installation is in progress")

    def test_a_directory_excludes_its_subdirectories_and_aliases(self):
        parent, other = self.base / "p", self.base / "q"
        child = parent / "sub"
        child.mkdir(parents=True)
        other.mkdir()
        alias = self.base / "alias"
        alias.symlink_to(parent)
        with run_locks([parent], self.base / "run-1") as reason:
            self.assertIsNone(reason)
            for overlapping in (child, alias):
                with run_locks([overlapping], self.base / "run-2") as blocked:
                    self.assertEqual(blocked, f"Another task is running on {parent}")
            with run_locks([other], self.base / "run-3") as independent:
                self.assertIsNone(independent)
        with run_locks([child], self.base / "run-4") as reason:
            self.assertIsNone(reason)
            self.assertEqual(conflict([parent]), f"Another task is running on {parent}")
            self.assertIsNone(conflict([other]))

    def test_roots_of_one_repository_and_its_worktrees_exclude_each_other(self):
        repository, separate = self.repository("repo"), self.repository("separate")
        for name in ("a", "b"):
            (repository / name).mkdir()
        worktree = self.base / "worktree"
        self.git(repository, "worktree", "add", "-q", str(worktree))
        shared = f"Another task is running on the Git repository {repository / '.git'}"
        with run_locks([repository / "a"], self.base / "run-1") as reason:
            self.assertIsNone(reason)
            self.assertEqual(conflict([repository / "b"]), shared)
            self.assertEqual(conflict([worktree]), shared)
            self.assertIsNone(conflict([separate]))
        with run_locks([worktree], self.base / "run-2") as reason:
            self.assertIsNone(reason)
            self.assertEqual(conflict([repository]), shared)

    def repository(self, name):
        path = self.base / name
        path.mkdir()
        self.git(path, "init", "-q")
        self.git(path, "commit", "-q", "--allow-empty", "-m", "Initial commit")
        return path

    def git(self, cwd, *arguments):
        identity = ["-c", "user.name=Test", "-c", "user.email=test@example.com"]
        subprocess.run(["git", *identity, *arguments], cwd=cwd, check=True)

    def test_launcher_refuses_a_busy_project_or_run(self):
        project, other = str(self.base / "p"), str(self.base / "q")
        run = self.base / "runs/r1"
        require_idle({run: [project]}, None, [other])
        with self.assertRaisesRegex(BusyError, "Another task is running"):
            require_idle({run: [project]}, None, [project])
        with self.assertRaisesRegex(BusyError, "still active"):
            require_idle({run: [project]}, run, [other])
        with self.assertRaisesRegex(BusyError, f"running on {project}"):
            require_idle({run: [project]}, None, [f"{project}/sub"])
        with self.assertRaisesRegex(BusyError, f"running on {project}"):
            require_idle({run: [f"{project}/sub"]}, None, [project])
        with (
            run_locks([other], self.base / "runs/r2"),
            self.assertRaisesRegex(BusyError, "Another task is running"),
        ):
            require_idle({}, None, [other])

    def test_a_run_on_a_busy_project_is_blocked_without_touching_it(self):
        root = self.base / "repo"
        root.mkdir()
        (root / ".git").mkdir()
        (root / "hello.py").write_text("def hello():\n    return 1\n")
        task = self.base / "task.md"
        header = json.dumps({"roots": {"project": str(root)}, "isolation": "worktree"})
        task.write_text(f"```countersign-task\n{header}\n```\nReturn 2")
        settings = self.base / "settings.json"
        command = [sys.executable, str(BASE / "tests/fake_live.py"), "--profiles"]
        command += [str(self.base / "profiles"), "--mode", "ok"]
        settings.write_text(
            json.dumps(
                dict(
                    command=command,
                    agent_directory=str(self.base / "profiles"),
                    worktree_base=str(self.base / "worktrees"),
                )
            )
        )
        with run_locks([root.resolve()], self.base / "other-run"):
            run, status = execute_task(task, settings, run_dir=self.base / "blocked")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "BLOCKED")
        self.assertIn("Another task is running on", state["summary"])
        self.assertEqual(state["worktrees"], {})
        self.assertFalse((self.base / "worktrees").exists())
        self.assertIn("return 1", (root / "hello.py").read_text())


if __name__ == "__main__":
    unittest.main()
