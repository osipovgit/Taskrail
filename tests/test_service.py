"""Deployment and managed process regressions, without a privileged systemd daemon."""

import fcntl
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.request import ProxyHandler, Request, build_opener

from deployment_fixture import DeploymentFixture
from git_fixture import repository
from run_fixture import current_run

from taskrail.application.task_config import configuration
from taskrail.core.release import VERSION
from taskrail.core.runtime import run_storage, settings_path
from taskrail.web.config_watch import ConfigurationWatch
from taskrail.web.health import ready

BASE = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def test_configuration_watch_tracks_role_edits_and_recovers_invalid_json(self):
        agents = shutil.copytree(BASE / "taskrail/agents", self.home / "agents")
        self.settings.write_text('{"agent_source":"agents"}')
        watch = ConfigurationWatch(self.settings)
        watch.poll()
        (agents / "notes.md").write_text("Unrelated documentation")
        with self.assertNoLogs():
            watch.poll()
        (agents / "planner.md").write_text("Updated role")
        with self.assertLogs(level="INFO") as logs:
            watch.poll()
        self.assertIn("new tasks load new settings", logs.output[0])
        self.settings.write_text("{")
        with self.assertLogs(level="WARNING"):
            watch.poll()
        self.settings.write_text("{}")
        with self.assertLogs(level="INFO"):
            watch.poll()

    def test_configuration_watch_uses_bundled_roles_for_settings_without_agent_source(self):
        agents = shutil.copytree(BASE / "taskrail/agents", self.home / "release/agents")
        self.settings.write_text("{}")
        with patch("taskrail.application.instruction_sources.BUNDLED_AGENTS", agents):
            watch = ConfigurationWatch(self.settings)
            watch.poll()
            (agents / "understanding.md").write_text("Updated bundled role")
            with self.assertLogs(level="INFO"):
                watch.poll()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.repo = self.home / "repo"
        self.repo.mkdir()
        (self.repo / ".git").mkdir()
        (self.repo / ".git/HEAD").write_text("ref: refs/heads/main\n")
        (self.repo / "hello.py").write_text("def hello():\n    return 1\n")
        self.settings = self.home / "old-settings.json"
        self.settings.write_text(
            json.dumps(
                dict(
                    command=[
                        sys.executable,
                        str(BASE / "tests/fake_live.py"),
                        "--profiles",
                        str(self.home / "profiles"),
                        "--mode",
                        "planner-timeout",
                    ],
                    agent_source=str(BASE / "taskrail/agents"),
                    agent_directory=str(self.home / "profiles"),
                    timeout_seconds=3600,
                )
            )
        )
        self.environment = dict(os.environ, HOME=str(self.home), PYTHONPATH=str(BASE))
        self.environment.pop("TASKRAIL_SETTINGS", None)
        self.deployment = DeploymentFixture(self.home)
        self.environment = self.deployment.environment(self.environment)

    def test_configuration_defaults_to_one_hour_and_explicit_override_works(self):
        task = self.home / "task.md"
        task.write_text(
            "```taskrail-task\n"
            + json.dumps(dict(roots={"project": str(self.repo)}))
            + "\n```\nExplain"
        )
        settings = json.loads(self.settings.read_text())
        settings.pop("timeout_seconds")
        self.settings.write_text(json.dumps(settings))
        self.assertEqual(configuration(task, self.settings)["timeout"], 3600)
        self.assertNotIn("stage_tools", configuration(task, self.settings))
        self.assertEqual(configuration(task, self.settings)["transport_retries"], 3)
        self.assertEqual(configuration(task, self.settings)["max_integration_corrections"], 3)
        self.assertNotIn("stage_attempts", configuration(task, self.settings))
        self.assertNotIn("stage_seconds", configuration(task, self.settings))
        settings["timeout_seconds"] = 42
        self.settings.write_text(json.dumps(settings))
        self.assertEqual(configuration(task, self.settings)["timeout"], 42)

    def test_shared_configuration_and_relative_history_resolution(self):
        with patch.dict(os.environ, self.environment, clear=True):
            config = self.home / ".config/taskrail/settings.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps(dict(run_base="my-runs")))
            self.assertEqual(settings_path(), config)
            self.assertEqual(run_storage(), config.parent / "my-runs")
            self.assertEqual(settings_path(self.settings), self.settings)

    def test_sigterm_stops_owned_worker_and_preserves_checkpoint(self):
        repository(self.repo)
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        runs = self.home / "runs"
        log = (self.home / "service.log").open("w")
        self.addCleanup(log.close)
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "taskrail.web.service",
                "--port",
                str(port),
                "--settings",
                str(self.settings),
                "--runs-dir",
                str(runs),
            ],
            env=self.environment,
            cwd=BASE,
            stdout=log,
            stderr=log,
        )
        self.addCleanup(lambda: process.kill() if process.poll() is None else None)
        deadline = time.monotonic() + 10
        while not ready(port) and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue(ready(port))
        opener = build_opener(ProxyHandler({}))
        url = f"http://127.0.0.1:{port}"
        with opener.open(url + "/api/session") as response:
            session = json.load(response)
            self.assertEqual(session["version"], VERSION)
            token = session["token"]
        with opener.open(url + "/") as response:
            self.assertIn(VERSION, response.read().decode())
        payload = dict(
            title="Stop test",
            goal="Return 2",
            criteria="Keep other files",
            roots=[dict(alias="project", path=str(self.repo))],
        )
        request = Request(
            url + "/api/tasks",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Origin": url,
                "X-Taskrail-Token": token,
            },
        )
        with opener.open(request) as response:
            run = runs / json.load(response)["id"]
        deadline = time.monotonic() + 10
        while not (run / "01-understand/stderr.log").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue((run / "01-understand/stderr.log").exists())
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=15), 0, (self.home / "service.log").read_text())
        self.assertEqual(json.loads((run / "run.json").read_text())["status"], "INTERRUPTED")
        self.assertTrue((run / "checkpoint.json").is_file())
        self.assertIn("return 1", (self.repo / "hello.py").read_text())
        with (self.home / ".local/state/taskrail/live.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def installer(self, *arguments):
        return subprocess.run(
            ["bash", str(self.deployment.source() / "deploy/install.sh"), *arguments],
            env=self.environment,
            cwd=BASE,
            capture_output=True,
            text=True,
            timeout=40,
        )

    def test_offline_install_update_preserves_settings_agents_and_history(self):
        binaries = self.home / "bin"
        binaries.mkdir()
        systemctl = binaries / "systemctl"
        systemctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/systemctl.log"\nexit 0\n')
        systemctl.chmod(0o755)
        loginctl = binaries / "loginctl"
        loginctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$HOME/loginctl.log"\n')
        loginctl.chmod(0o755)
        self.environment["PATH"] = str(binaries) + os.pathsep + self.environment["PATH"]
        self.environment["PYTHON"] = sys.executable
        extras = ("deploy/private.json", "taskrail/agents/custom.md", "taskrail/core/debug.json")
        source = self.deployment.source()
        for filename in extras:
            (source / filename).write_text("operator data")
        installed = self.installer(str(self.settings), "--autostart=yes")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertFalse((self.home / "loginctl.log").exists())
        log = self.home / "systemctl.log"
        self.assertIn("--user enable taskrail.service", log.read_text())
        log.write_text("")
        current = self.home / ".local/share/taskrail/current"
        first = current.resolve()
        shadow = self.home / "old-checkout/taskrail"
        shadow.mkdir(parents=True)
        (shadow / "__init__.py").touch()
        (shadow / "__main__.py").write_text("raise SystemExit('wrong checkout')")
        version = subprocess.check_output(
            [str(self.home / ".local/bin/taskrail"), "--version"],
            cwd=shadow.parent,
            env=self.environment,
            text=True,
        ).strip()
        self.assertEqual(version, f"Taskrail {VERSION}")
        self.assertTrue(first.name.startswith(f"{VERSION}-"))
        self.assertTrue((first / "taskrail/deployment/settings_stage.py").is_file())
        for filename in extras:
            self.assertFalse((first / filename).exists())
        self.assertFalse((first / "docs").exists())
        config = self.home / ".config/taskrail/settings.json"
        options = json.loads(config.read_text())
        self.assertEqual(options["timeout_seconds"], 3600)
        agents = Path(options["agent_source"])
        custom = "Instruction contract: 1.\nUser-owned instructions"
        (agents / "planner.md").write_text(custom)
        options["max_integration_corrections"] = 1
        config.write_text(json.dumps(options))
        before = config.read_bytes()
        run = self.home / ".local/state/taskrail/runs/preserved"
        run.mkdir(parents=True)
        (run / "run.json").write_text("{}")
        updated = self.installer()
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertNotIn("--user enable ", log.read_text())
        disabled = self.installer("--autostart=no")
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertIn("--user disable taskrail.service", log.read_text())
        invalid = self.installer("--wait=bad")
        self.assertEqual(invalid.returncode, 2)
        boot = self.installer("--boot=yes")
        self.assertEqual(boot.returncode, 0, boot.stderr)
        self.assertIn("enable-linger ", (self.home / "loginctl.log").read_text())
        self.assertNotEqual(first, current.resolve())
        self.assertFalse(first.is_dir())
        self.assertEqual(len(list((current.parent / "releases").iterdir())), 2)
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual((agents / "planner.md").read_text(), custom)
        self.assertEqual((run / "run.json").read_text(), "{}")
        command = subprocess.run(
            [str(self.home / ".local/bin/taskrail"), "status", str(run)],
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertNotEqual(command.returncode, 0)
        self.assertIn("Unsupported run format", command.stderr)
        switched = self.installer("--agents=bundled", "--autostart=keep")
        self.assertEqual(switched.returncode, 0, switched.stderr)
        self.assertEqual(
            json.loads(config.read_text())["agent_source"], str(current / "taskrail/agents")
        )
        self.assertEqual((agents / "planner.md").read_text(), custom)
        self.assertIn(
            before, [path.read_bytes() for path in config.parent.glob("settings.json.backup-*")]
        )
        with (self.home / ".local/state/taskrail/live.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            rejected = self.installer()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Stop the active task", rejected.stderr)
            with subprocess.Popen(
                ["bash", str(self.deployment.source() / "deploy/install.sh"), "--wait=10"],
                env=self.environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            ) as pending:
                time.sleep(0.3)
                self.assertIsNone(pending.poll())
                fcntl.flock(lock, fcntl.LOCK_UN)
                output, error = pending.communicate(timeout=30)
                self.assertEqual(pending.returncode, 0, output + error)
        if shutil.which("systemd-analyze"):
            unit = self.home / "taskrail.service"
            unit.write_text(
                (BASE / "deploy/taskrail.service").read_text().replace("%h", str(self.home))
            )
            checked = subprocess.run(
                ["systemd-analyze", "verify", str(unit)], capture_output=True, text=True
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_fresh_install_removes_managed_data_preserving_projects_and_cli_credentials(self):
        self.environment["PYTHON"] = sys.executable
        initial = self.installer(str(self.settings), "--autostart=no")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        config = self.home / ".config/taskrail/settings.json"
        app = self.home / ".local/share/taskrail"
        old_release = (app / "current").resolve()
        history = self.home / "old-runs"
        run = history / "run-1"
        run.mkdir(parents=True)
        (run / "run.json").write_text(
            json.dumps(current_run({"roots": {"project": str(self.repo)}}))
        )
        options = json.loads(config.read_text())
        options.update(run_base=str(history), timeout_seconds=9)
        config.write_text(json.dumps(options))
        profile = self.home / "profiles/taskrail-planner.md"
        profile.parent.mkdir(exist_ok=True)
        profile.write_text("Managed Taskrail workflow test")
        credential = self.home / ".config/opencode/auth.json"
        credential.parent.mkdir(parents=True)
        credential.write_text("synthetic credential")
        result = self.installer("--fresh", "--autostart=keep")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(history.exists())
        self.assertFalse(old_release.exists())
        self.assertFalse(profile.exists())
        self.assertEqual(credential.read_text(), "synthetic credential")
        self.assertIn("return 1", (self.repo / "hello.py").read_text())
        options = json.loads(config.read_text())
        self.assertEqual(options["timeout_seconds"], 3600)
        self.assertEqual(options["command"][0], str(self.deployment.binaries / "opencode"))
        self.assertTrue((app / "current/venv/bin/python").is_file())

    def test_force_update_rebuilds_only_managed_runtime_after_the_workflow_lock_is_free(self):
        initial = self.installer(str(self.settings), "--autostart=no")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        app = self.home / ".local/share/taskrail"
        state = self.home / ".local/state/taskrail"
        config = self.home / ".config/taskrail"
        release = (app / "current").resolve()
        settings = config / "settings.json"
        installed = json.loads(settings.read_text())
        installed.update(agent_directory="profiles", run_base="runs")
        settings.write_text(json.dumps(installed))
        run = config / "runs/completed"
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps(current_run(dict(roots={"p": str(self.repo)}))))
        worktree = self.home / ".local/share/taskrail-worktrees/task/project"
        worktree.mkdir(parents=True)
        (worktree / "pending.txt").write_text("pending edit")
        executor = self.deployment.system / "opt/taskrail-executor"
        executor.mkdir(parents=True)
        (executor / "approval").write_text("pending decision")
        profile = config / "profiles/taskrail-test.md"
        profile.parent.mkdir()
        profile.write_text("Managed Taskrail workflow")
        credentials = self.home / ".config/opencode/auth.json"
        credentials.parent.mkdir(parents=True)
        credentials.write_text("test credential")
        retained = (
            config / "service.env",
            config / "agents/planner.md",
            credentials,
            worktree / "pending.txt",
            executor / "approval",
            self.repo / "hello.py",
        )
        original = [path.read_bytes() for path in retained]
        log = self.home / "privilege.log"
        log.write_text("")
        with (state / "live.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            blocked = self.installer("--force-update")
            self.assertNotEqual(blocked.returncode, 0)
            self.assertTrue(run.is_dir())
            self.assertTrue(release.is_dir())
            self.assertIn("--user stop taskrail.service", log.read_text())
            self.assertIn("--user start taskrail.service", log.read_text())
        supplied = self.home / "replacement.json"
        supplied.write_text(json.dumps(dict(installed, timeout_seconds=19)))
        result = self.installer(str(supplied), "--force-update", "--opencode=opencode")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((app / "current/venv/bin/python").is_file())
        self.assertEqual(list(run.parent.iterdir()), [])
        self.assertFalse(release.exists())
        self.assertFalse(profile.exists())
        self.assertEqual([path.read_bytes() for path in retained], original)
        self.assertNotIn("sudo", log.read_text())
        selected = json.loads(settings.read_text())
        self.assertEqual(selected["command"], [str(self.deployment.binaries / "opencode")])
        self.assertEqual(selected["timeout_seconds"], 19)
        self.assertEqual(selected["run_base"], "runs")

    def test_fresh_refuses_a_mixed_custom_history_before_deletion(self):
        binaries = self.home / "bin"
        binaries.mkdir()
        systemctl = binaries / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 0\n")
        systemctl.chmod(0o755)
        self.environment["PATH"] = str(binaries) + os.pathsep + self.environment["PATH"]
        config = self.home / ".config/taskrail"
        config.mkdir(parents=True)
        (config / "settings.json").write_text(json.dumps({"run_base": str(self.repo)}))
        result = self.installer("--fresh", "--autostart=keep")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized", result.stderr)
        self.assertTrue((self.repo / "hello.py").exists())
        self.assertTrue((config / "settings.json").exists())

    def test_fresh_executor_reset_uses_only_private_host_paths_and_privilege_stubs(self):
        installed_executor = self.deployment.system / "opt/taskrail-executor"
        installed_executor.mkdir(parents=True)
        sentinel = installed_executor / "preserved-by-sudo-stub"
        sentinel.write_text("fixture")
        self.environment["PYTHON"] = sys.executable
        initial = self.installer(str(self.settings), "--autostart=no")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        fresh = self.installer("--fresh", "--autostart=keep")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        log = (self.home / "privilege.log").read_text()
        self.assertIn("reset-executor.sh", log)
        self.assertIn("install-executor.sh", log)
        self.assertTrue(sentinel.is_file())

    def test_fresh_refuses_archived_source_overlap_before_stopping_services(self):
        config = self.home / ".config/taskrail"
        config.mkdir(parents=True)
        history = self.home / "history"
        record = history / ".trash/old/run/run.json"
        record.parent.mkdir(parents=True)
        source = config / "source"
        source.mkdir()
        (source / "keep.py").write_text("original code")
        (config / "settings.json").write_text(json.dumps(dict(run_base=str(history))))
        record.write_text(json.dumps(dict(roots=dict(project=str(source)))))
        self.environment["PYTHON"] = sys.executable
        refused = self.installer("--fresh", "--autostart=keep")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("overlap a declared project", refused.stderr)
        self.assertNotIn(" stop ", (self.home / "privilege.log").read_text())
        self.assertEqual((source / "keep.py").read_text(), "original code")
