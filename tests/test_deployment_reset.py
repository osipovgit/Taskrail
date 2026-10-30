"""Fresh-install deletion is validated against every retained ownership record."""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from deployment_fixture import DeploymentFixture

from taskrail.core import approval_marks
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
                root.mkdir(parents=True, exist_ok=True)
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

    def test_valid_approval_sidecars_allow_reset_and_unknown_contents_block_it(self):
        approval_marks.revoke(self.history / "pending")
        inventory = prepare(self.home, [BASE])
        policy = self.history / approval_marks.DIRECTORY
        for filename, content in (
            ("unrelated.txt", "personal file"),
            ("pending.lock", "unrelated lock contents"),
            ("pending.off", '{"revoked_at": true}'),
            ("pending.off", '{"revoked_at": 1, "extra": "unknown"}'),
            ("pending.off", '{"revoked_at": NaN}'),
        ):
            with self.subTest(filename=filename, content=content):
                path = policy / filename
                original = path.read_bytes() if path.exists() else None
                path.write_text(content)
                with self.assertRaisesRegex(ValueError, "approval policy"):
                    prepare(self.home, [BASE])
                self.assertEqual(path.read_text(), content)
                if original is None:
                    path.unlink()
                else:
                    path.write_bytes(original)
        redirected = policy / "linked.off"
        redirected.symlink_to(policy / "pending.off")
        with self.assertRaisesRegex(ValueError, "approval policy"):
            prepare(self.home, [BASE])
        redirected.unlink()
        erase(inventory)
        self.assertFalse(policy.exists())

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

    def test_fresh_preserves_legacy_worktrees_even_when_history_names_them(self):
        worktree = self.state / "worktrees/run/project"
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: /existing/repository/worktrees/project\n")
        edits = worktree / "uncommitted.txt"
        edits.write_text("User work must survive a fresh install\n")
        record = self.record("isolated", worktree)
        state = json.loads(record.read_text())
        state["worktrees"] = dict(project=dict(source=str(self.project)))
        record.write_text(json.dumps(state))
        erase(prepare(self.home, [BASE]))
        self.assertEqual(edits.read_text(), "User work must survive a fresh install\n")
        self.assertTrue((worktree / ".git").is_file())

    def test_custom_worktree_base_inside_deleted_storage_blocks_fresh(self):
        options = json.loads((self.config / "settings.json").read_text())
        options["worktree_base"] = str(self.app / "custom-worktrees")
        (self.config / "settings.json").write_text(json.dumps(options))
        with self.assertRaisesRegex(ValueError, "preserved worktrees"):
            prepare(self.home, [BASE])
        self.assertTrue((self.config / "settings.json").exists())

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


class DeploymentImportPreflightTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.fixture = DeploymentFixture(self.home)
        self.release = self.fixture.source()
        self.environment = self.fixture.environment(dict(os.environ, HOME=str(self.home)))
        self.config = self.home / ".config/taskrail"
        self.config.mkdir(parents=True)
        self.settings = self.config / "settings.json"
        self.settings.write_text("{}\n")
        self.sentinel = self.home / ".local/share/taskrail/releases/old/preserved"
        self.sentinel.parent.mkdir(parents=True)
        self.sentinel.write_text("previous release")
        self.imported = self.home / "imported.json"
        self.command = [str(self.fixture.binaries / "opencode")]

    def install_fresh(self):
        return subprocess.run(
            [
                "bash",
                str(self.release / "deploy/install.sh"),
                str(self.imported),
                "--fresh",
                "--autostart=keep",
            ],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=15,
        )

    def assert_preserved(self, result):
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.sentinel.read_text(), "previous release")
        self.assertEqual(self.settings.read_text(), "{}\n")
        self.assertNotIn("--user stop", (self.home / "privilege.log").read_text())

    def test_invalid_settings_and_missing_roles_fail_before_reset(self):
        for content in (
            "{",
            json.dumps(dict(command=["/missing-agent-command"])),
            json.dumps(dict(command=self.command, agent_source="missing-roles")),
        ):
            with self.subTest(content=content):
                self.imported.write_text(content)
                self.assert_preserved(self.install_fresh())

    def test_imported_roles_cannot_be_destroyed_by_the_requested_reset(self):
        roles = self.config / "agents"
        shutil.copytree(BASE / "taskrail/agents", roles)
        custom = (roles / "planner.md").read_text()
        self.imported.write_text(json.dumps(dict(command=self.command, agent_source=str(roles))))
        result = self.install_fresh()
        self.assert_preserved(result)
        self.assertIn("outside reset directories", result.stderr)
        self.assertEqual((roles / "planner.md").read_text(), custom)

    def test_service_environment_is_validated_before_reset(self):
        self.imported.write_text(json.dumps(dict(command=self.command)))
        (self.config / "service.env").write_text("PATH=/previous\n")
        self.environment["PATH"] += ":invalid\nentry"
        result = self.install_fresh()
        self.assert_preserved(result)
        self.assertIn("PATH must not contain newlines", result.stderr)
        self.assertEqual((self.config / "service.env").read_text(), "PATH=/previous\n")

    def test_role_symlink_targets_must_survive_reset_and_broken_imports_fail_early(self):
        roles = self.home / "roles"
        shutil.copytree(BASE / "taskrail/agents", roles)
        target = self.config / "saved-planner.md"
        custom = (roles / "planner.md").read_text()
        target.write_text(custom)
        link = roles / "planner.md"
        link.unlink()
        link.symlink_to(target)
        self.imported.write_text(json.dumps(dict(command=self.command, agent_source=str(roles))))
        result = self.install_fresh()
        self.assert_preserved(result)
        self.assertIn("outside reset directories", result.stderr)
        self.assertEqual(target.read_text(), custom)
        target.unlink()
        result = self.install_fresh()
        self.assert_preserved(result)
        self.assertIn("Missing source agent: planner", result.stderr)

    def test_invalid_runtime_settings_and_empty_role_tree_fail_before_stop(self):
        roles = self.home / "empty-roles"
        roles.mkdir()
        for options in (dict(max_repairs="invalid"), dict(agent_source=str(roles))):
            with self.subTest(options=options):
                self.imported.write_text(json.dumps(dict(command=self.command, **options)))
                self.assert_preserved(self.install_fresh())

    def test_venv_failure_keeps_old_install_and_cleans_its_staging_directory(self):
        self.imported.write_text(json.dumps(dict(command=self.command)))
        python = self.home / "python-wrapper"
        python.write_text(
            '#!/bin/sh\nif [ "$1" = -m ] && [ "$2" = venv ]; then exit 72; fi\n'
            f'exec "{sys.executable}" "$@"\n'
        )
        python.chmod(0o755)
        self.environment["PYTHON"] = str(python)
        self.assert_preserved(self.install_fresh())
        self.assertEqual(list((self.home / ".local/share").glob(".taskrail-stage-*")), [])

    def test_release_import_failure_keeps_old_install_and_cleans_staging(self):
        self.imported.write_text(json.dumps(dict(command=self.command)))
        (self.release / "taskrail/web/service.py").write_text(
            "raise ImportError('broken release')\n"
        )
        result = self.install_fresh()
        self.assert_preserved(result)
        self.assertIn("broken release", result.stderr)
        self.assertEqual(list((self.home / ".local/share").glob(".taskrail-stage-*")), [])

    def test_application_stop_failure_does_not_reset_the_executor(self):
        self.imported.write_text(json.dumps(dict(command=self.command)))
        executor = self.fixture.system / "opt/taskrail-executor"
        executor.mkdir(parents=True)
        (executor / "keep").write_text("executor retained")
        systemctl = self.fixture.binaries / "systemctl"
        systemctl.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/privilege.log"\n'
            'if [ "$1 $2" = "--user stop" ]; then exit 1; fi\nexit 0\n'
        )
        result = self.install_fresh()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.sentinel.read_text(), "previous release")
        self.assertEqual((executor / "keep").read_text(), "executor retained")
        calls = (self.home / "privilege.log").read_text().splitlines()
        resets = [call for call in calls if "reset-executor.sh" in call]
        self.assertTrue(resets)
        self.assertTrue(all("--check" in call for call in resets))
