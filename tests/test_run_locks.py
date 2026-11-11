"""Runs on different projects proceed in parallel; one project runs one task at a time."""

import contextlib
import fcntl
import json
import subprocess
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event, current_thread, main_thread
from unittest import mock

from run_fixture import workflow_workspace

from taskrail.application import run_locks as locks
from taskrail.application.live import execute_task
from taskrail.application.run_locks import INSTALL_LOCK, STATE, conflict, run_locks
from taskrail.core import file_lock
from taskrail.web.run_activity import BusyError, require_idle

BASE = Path(__file__).resolve().parents[1]


class RunLockTests(unittest.TestCase):
    def setUp(self):
        self.base = workflow_workspace(self)

    def test_a_stray_empty_git_directory_does_not_join_projects_into_one_repository(self):
        (self.base / ".git").mkdir()
        first, second = self.base / "a", self.base / "b"
        with run_locks([first], self.base / "run-1") as reason:
            self.assertIsNone(reason)
            with run_locks([second], self.base / "run-2") as parallel:
                self.assertIsNone(parallel)

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

    def test_probes_and_shared_holders_leave_no_resource_files(self):
        path = locks.lock_path(locks.ROOT, self.base)
        self.assertIsNone(conflict([self.base]))
        self.assertFalse(path.parent.exists())
        with locks.resource(locks.ROOT, self.base, file_lock.SHARED) as first:
            with locks.resource(locks.ROOT, self.base, file_lock.SHARED) as second:
                self.assertTrue(first and second)
            self.assertTrue(path.exists())
            self.assertIn("Another task", conflict([self.base]))
        self.assertEqual(list(path.parent.iterdir()), [])

    def test_open_descriptor_on_retired_inode_cannot_bypass_new_holder(self):
        opened, proceed = Event(), Event()
        open_file = file_lock.open_lock

        @contextlib.contextmanager
        def delayed_open(path):
            with open_file(path) as stream:
                if current_thread() is not main_thread() and not opened.is_set():
                    opened.set()
                    self.assertTrue(proceed.wait(5))
                yield stream

        def try_acquire():
            with locks.resource(locks.RUN, self.base, file_lock.EXCLUSIVE) as acquired:
                return acquired

        with (
            ThreadPoolExecutor(max_workers=1) as pool,
            mock.patch.object(file_lock, "open_lock", delayed_open),
        ):
            with locks.resource(locks.RUN, self.base, file_lock.EXCLUSIVE):
                waiter = pool.submit(try_acquire)
                self.assertTrue(opened.wait(5))
            with locks.resource(locks.RUN, self.base, file_lock.EXCLUSIVE):
                proceed.set()
                self.assertFalse(waiter.result(timeout=5))
        self.assertFalse(locks.lock_path(locks.RUN, self.base).exists())

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
        header = json.dumps({"roots": {"project": str(root)}})
        task.write_text(f"```taskrail-task\n{header}\n```\nReturn 2")
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
