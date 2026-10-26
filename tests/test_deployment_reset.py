"""Fresh-install deletion is validated against every retained ownership record."""

import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from taskrail.deployment.fresh import erase, prepare

BASE = Path(__file__).resolve().parents[1]


class DeploymentResetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config = self.home / ".config/taskrail"
        self.app = self.home / ".local/share/taskrail"
        self.state = self.home / ".local/state/taskrail"
        self.history = self.home / "history"
        self.project = self.home / "project"
        for directory in (self.config, self.app, self.state, self.history, self.project):
            directory.mkdir(parents=True)
        self.profiles = self.home / "profiles"
        self.profiles.mkdir()
        (self.config / "settings.json").write_text(
            json.dumps(dict(run_base=str(self.history), agent_directory=str(self.profiles)))
        )

    def record(self, relative, root):
        path = self.history / relative / "run.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(roots=dict(project=str(root)))))
        return path

    def test_archived_roots_protect_every_recursive_deletion_target(self):
        for root in (
            self.config / "source",
            self.app / "source",
            self.state / "source",
            self.home / ".cache/taskrail/source",
            self.home / ".config/systemd/user/taskrail.service.d/source",
        ):
            with self.subTest(root=root):
                record = self.record(".trash/old/run", root)
                with self.assertRaisesRegex(ValueError, "overlap a declared project"):
                    prepare(self.home, [BASE])
                self.assertTrue(record.is_file())
                self.assertTrue((self.config / "settings.json").is_file())

    def test_failed_launch_roots_also_protect_sources(self):
        folder = self.history / ".submissions/failed"
        folder.mkdir(parents=True)
        (folder / "launch.json").write_text('{"status":"LAUNCH_ERROR"}')
        header = json.dumps(dict(roots=dict(project=str(self.app / "source"))))
        (folder / "task.md").write_text("```taskrail-task\n" + header + "\n```\nGoal")
        with self.assertRaisesRegex(ValueError, "overlap a declared project"):
            prepare(self.home, [BASE])

    def test_isolated_runs_protect_the_original_source_as_well_as_the_worktree(self):
        record = self.record(".trash/old/run", self.project)
        saved = json.loads(record.read_text())
        saved["worktrees"] = dict(project=dict(source=str(self.config / "source")))
        record.write_text(json.dumps(saved))
        with self.assertRaisesRegex(ValueError, "overlap a declared project"):
            prepare(self.home, [BASE])

    def test_unknown_files_in_hidden_history_containers_abort(self):
        for relative in (".trash/old/unrelated", ".submissions/unrelated"):
            with self.subTest(relative=relative):
                unrelated = self.history / relative
                unrelated.parent.mkdir(parents=True, exist_ok=True)
                unrelated.write_text("personal file")
                with self.assertRaisesRegex(ValueError, "unrecognized"):
                    prepare(self.home, [BASE])
                self.assertEqual(unrelated.read_text(), "personal file")
                unrelated.unlink()

    def test_release_and_supplied_settings_in_cache_are_protected(self):
        cache = self.home / ".cache/taskrail"
        for protected in (cache / "release", cache / "settings.json"):
            with (
                self.subTest(protected=protected),
                self.assertRaisesRegex(ValueError, "outside reset directories"),
            ):
                prepare(self.home, [protected])

    def test_generated_profile_inside_a_declared_source_is_protected(self):
        profile = self.profiles / "taskrail-planner.md"
        profile.write_text("Managed Taskrail workflow")
        self.record("completed", self.profiles)
        with self.assertRaisesRegex(ValueError, "overlap a declared project"):
            prepare(self.home, [BASE])
        self.assertTrue(profile.is_file())

    def test_apply_preserves_locked_inodes_sources_and_unmanaged_profiles(self):
        self.record(".trash/old/run", self.project)
        keep = self.profiles / "custom.md"
        keep.write_text("custom role")
        generated = self.profiles / "taskrail-planner.md"
        generated.write_text("Managed Taskrail workflow")
        locks = [self.app / "install.lock", self.state / "live.lock"]
        for lock in locks:
            lock.touch()
        inodes = [lock.stat().st_ino for lock in locks]
        erase(prepare(self.home, [BASE]))
        self.assertEqual([lock.stat().st_ino for lock in locks], inodes)
        self.assertTrue(self.project.is_dir())
        self.assertEqual(keep.read_text(), "custom role")
        self.assertFalse(generated.exists())
        self.assertFalse(self.history.exists())
        self.assertFalse(self.config.exists())

    def test_bash_gate_checks_scripts_after_the_first(self):
        valid, invalid = self.home / "valid.sh", self.home / "invalid.sh"
        valid.write_text("true\n")
        invalid.write_text("if then\n")
        result = subprocess.run(
            [
                "make",
                "--old-file=tool-versions",
                "lint-shell",
                f"SHELL_SCRIPTS={valid} {invalid}",
                "SHELLCHECK=/bin/true",
                "SHFMT=/bin/true",
            ],
            cwd=BASE,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid.sh", result.stderr)
