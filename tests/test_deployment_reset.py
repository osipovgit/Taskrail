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
from taskrail.infrastructure.agent_profile import make_profile

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

    def generated_profile(self, directory, name="taskrail-planner"):
        role = BASE / "taskrail/agents/planner.md"
        access = dict(roots=[self.project], readable=[], writable=[])
        path, _ = make_profile(role, directory, name, access)
        return path

    def test_archived_roots_protect_every_recursive_deletion_target(self):
        for root in (
            self.config / "source",
            self.app / "source",
            self.state / "source",
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

    def test_generated_profile_inside_a_declared_source_is_protected(self):
        profile = self.generated_profile(self.profiles)
        self.record("completed", self.profiles)
        with self.assertRaisesRegex(ValueError, "overlap a declared project"):
            prepare(self.home, [BASE])
        self.assertTrue(profile.is_file())

    def test_prior_service_profile_directory_is_used_only_as_the_default(self):
        default = self.home / "old service profile directory"
        default.mkdir()
        generated = self.generated_profile(default, "taskrail-previous")
        keep = default / "taskrail-personal.md"
        keep.write_text(
            '---\n{"mode":"primary"}\n---\nInstructions about Managed Taskrail workflow'
        )
        self.assertNotIn(generated, prepare(self.home, [BASE], profile_directory=default).targets)
        (self.config / "settings.json").write_text("{}")
        erase(prepare(self.home, [BASE], profile_directory=default))
        self.assertFalse(generated.exists())
        self.assertTrue(keep.exists())

    def test_apply_preserves_locked_inodes_sources_and_unmanaged_profiles(self):
        self.record(".trash/old/run", self.project)
        keep = self.profiles / "custom.md"
        keep.write_text("custom role")
        generated = self.generated_profile(self.profiles)
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

    def test_projects_under_state_worktrees_are_protected_like_other_roots(self):
        worktree = self.state / "worktrees/run/project"
        worktree.mkdir(parents=True)
        (worktree / ".git").write_text("gitdir: /existing/repository/worktrees/project\n")
        edits = worktree / "uncommitted.txt"
        edits.write_text("User work must survive a fresh install\n")
        record = self.record("isolated", worktree)
        state = json.loads(record.read_text())
        state["worktrees"] = dict(project=dict(source=str(self.project)))
        record.write_text(json.dumps(state))
        with self.assertRaisesRegex(ValueError, "overlap a declared project"):
            prepare(self.home, [BASE])
        self.assertTrue(edits.is_file())
        self.assertTrue(self.project.is_dir())

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

    def install_reset(self, *options, mode="--fresh"):
        return subprocess.run(
            [
                "bash",
                str(self.release / "deploy/install.sh"),
                str(self.imported),
                mode,
                "--autostart=keep",
                *options,
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
                self.assert_preserved(self.install_reset())

    def test_imported_roles_cannot_be_destroyed_by_the_requested_reset(self):
        roles = self.config / "agents"
        shutil.copytree(BASE / "taskrail/agents", roles)
        custom = (roles / "planner.md").read_text()
        self.imported.write_text(json.dumps(dict(command=self.command, agent_source=str(roles))))
        for mode in ("--fresh", "--force-update"):
            with self.subTest(mode=mode):
                result = self.install_reset(mode=mode)
                self.assert_preserved(result)
                self.assertIn("outside reset directories", result.stderr)
                self.assertEqual((roles / "planner.md").read_text(), custom)
        result = self.install_reset("--agents=bundled", mode="--force-update")
        self.assertEqual(result.returncode, 0, result.stderr)
        selected = Path(json.loads(self.settings.read_text())["agent_source"])
        self.assertEqual(selected, self.home / ".local/share/taskrail/current/taskrail/agents")
        self.assertTrue((selected / "planner.md").is_file())
        self.assertFalse(roles.exists())

    def test_incoming_worktree_directory_survives_a_force_reinstall(self):
        worktrees = self.config / "pending-worktrees"
        worktrees.mkdir()
        edits = worktrees / "uncommitted"
        edits.write_text("keep my edits")
        self.imported.write_text(
            json.dumps(dict(command=self.command, worktree_base=str(worktrees)))
        )
        result = self.install_reset(mode="--force-update")
        self.assert_preserved(result)
        self.assertIn("preserved worktrees", result.stderr)
        self.assertEqual(edits.read_text(), "keep my edits")

    def test_service_environment_is_validated_before_reset(self):
        self.imported.write_text(json.dumps(dict(command=self.command)))
        (self.config / "service.env").write_text("PATH=/previous\n")
        self.environment["PATH"] += ":invalid\nentry"
        result = self.install_reset()
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
        result = self.install_reset()
        self.assert_preserved(result)
        self.assertIn("outside reset directories", result.stderr)
        self.assertEqual(target.read_text(), custom)
        target.unlink()
        result = self.install_reset()
        self.assert_preserved(result)
        self.assertIn("Missing source agent: planner", result.stderr)

    def test_fresh_preserves_the_selected_cli_and_its_file_arguments(self):
        inside = self.config / "backend"
        inside.symlink_to(self.command[0])
        self.imported.write_text(json.dumps(dict(command=self.command)))
        result = self.install_reset(f"--opencode={inside}")
        self.assert_preserved(result)
        self.assertIn("outside reset directories", result.stderr)
        self.assertTrue(inside.is_symlink())

        inside.unlink()
        shutil.copy2(self.command[0], inside)
        argument = self.home / "backend argument"
        argument.symlink_to(inside)
        self.imported.write_text(json.dumps(dict(command=["/bin/sh", str(argument)])))
        result = self.install_reset()
        self.assert_preserved(result)
        self.assertIn("outside reset directories", result.stderr)
        self.assertTrue(inside.is_file())

    def test_invalid_runtime_settings_and_empty_role_tree_fail_before_stop(self):
        roles = self.home / "empty-roles"
        roles.mkdir()
        for options in (dict(max_integration_corrections="invalid"), dict(agent_source=str(roles))):
            with self.subTest(options=options):
                self.imported.write_text(json.dumps(dict(command=self.command, **options)))
                self.assert_preserved(self.install_reset())

    def test_venv_failure_keeps_old_install_and_cleans_its_staging_directory(self):
        self.imported.write_text(json.dumps(dict(command=self.command)))
        python = self.home / "python-wrapper"
        python.write_text(
            '#!/bin/sh\nif [ "$1" = -m ] && [ "$2" = venv ]; then exit 72; fi\n'
            f'exec "{sys.executable}" "$@"\n'
        )
        python.chmod(0o755)
        self.environment["PYTHON"] = str(python)
        self.assert_preserved(self.install_reset())
        self.assertEqual(list((self.home / ".local/share").glob(".taskrail-stage-*")), [])

    def test_force_update_revalidates_after_stop_and_restores_service_on_refusal(self):
        history = self.home / ".local/state/taskrail/runs"
        history.mkdir(parents=True)
        systemctl = self.fixture.binaries / "systemctl"
        systemctl.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/privilege.log"\n'
            'if [ "$1 $2" = "--user stop" ]; then\n'
            '    touch "$HOME/.local/state/taskrail/runs/unknown"\nfi\n'
        )
        result = subprocess.run(
            ["bash", str(self.release / "deploy/install.sh"), "--force-update"],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized", result.stderr)
        self.assertTrue((history / "unknown").is_file())
        self.assertEqual(self.sentinel.read_text(), "previous release")
        self.assertIn("--user start taskrail.service", (self.home / "privilege.log").read_text())

    def test_unusable_replacement_history_blocks_force_update_before_service_stop(self):
        existing = self.home / "regular-file"
        existing.write_text("operator data")
        dangling = self.home / "dangling"
        dangling.symlink_to(self.home / "missing")
        for history in (existing, existing / "subdir/history", dangling / "history"):
            with self.subTest(history=history):
                self.imported.write_text(
                    json.dumps(dict(command=self.command, run_base=str(history)))
                )
                result = self.install_reset(mode="--force-update")
                self.assert_preserved(result)
                self.assertIn("Run history requires a writable directory", result.stderr)
        self.assertEqual(existing.read_text(), "operator data")
        self.assertFalse((self.home / "missing").exists())

    def test_force_reinstall_restores_service_if_imported_role_source_disappears_on_stop(self):
        roles = self.home / "external-roles"
        shutil.copytree(BASE / "taskrail/agents", roles)
        self.imported.write_text(json.dumps(dict(command=self.command, agent_source=str(roles))))
        systemctl = self.fixture.binaries / "systemctl"
        systemctl.write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/privilege.log"\n'
            'if [ "$1 $2" = "--user stop" ]; then echo "{}" > "$HOME/imported.json"; fi\n'
        )
        result = self.install_reset(mode="--force-update")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("no longer name the imported role source", result.stderr)
        self.assertTrue(self.sentinel.is_file())
        self.assertIn("--user start taskrail.service", (self.home / "privilege.log").read_text())

    def test_release_import_failure_keeps_old_install_and_cleans_staging(self):
        self.imported.write_text(json.dumps(dict(command=self.command)))
        (self.release / "taskrail/web/service.py").write_text(
            "raise ImportError('broken release')\n"
        )
        result = self.install_reset()
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
        result = self.install_reset()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.sentinel.read_text(), "previous release")
        self.assertEqual((executor / "keep").read_text(), "executor retained")
        calls = (self.home / "privilege.log").read_text().splitlines()
        resets = [call for call in calls if "reset-executor.sh" in call]
        self.assertTrue(resets)
        self.assertTrue(all("--check" in call for call in resets))
