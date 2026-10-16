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

from countersign.application.live import configuration
from countersign.core.runtime import run_storage, settings_path
from countersign.web.config_watch import ConfigurationWatch
from countersign.web.health import ready

BASE = Path(__file__).resolve().parents[1]


class ServiceTests(unittest.TestCase):
    def test_configuration_watch_tracks_role_edits_and_recovers_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            settings = folder / "settings.json"
            agents = folder / "agents"
            agents.mkdir()
            role = agents / "planner.md"
            role.write_text("first")
            settings.write_text('{"agent_source":"agents"}')
            watch = ConfigurationWatch(settings)
            watch.poll()
            role.write_text("second")
            with self.assertLogs(level="INFO") as logs:
                watch.poll()
            self.assertIn("new tasks load new settings", logs.output[0])
            with self.assertNoLogs():
                watch.poll()
            settings.write_text("{")
            with self.assertLogs(level="WARNING"):
                watch.poll()
            settings.write_text('{"timeout_seconds": 3600}')
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
                    agent_source=str(BASE / "agents"),
                    agent_directory=str(self.home / "profiles"),
                    timeout_seconds=3600,
                )
            )
        )
        self.environment = dict(os.environ, HOME=str(self.home), PYTHONPATH=str(BASE))
        self.environment.pop("COUNTERSIGN_SETTINGS", None)

    def test_configuration_defaults_to_one_hour_and_explicit_override_works(self):
        task = self.home / "task.md"
        task.write_text(
            "```countersign-task\n"
            + json.dumps(dict(roots={"project": str(self.repo)}))
            + "\n```\nExplain"
        )
        settings = json.loads(self.settings.read_text())
        settings.pop("timeout_seconds")
        self.settings.write_text(json.dumps(settings))
        self.assertEqual(configuration(task, self.settings)["timeout"], 3600)
        self.assertNotIn("stage_tools", configuration(task, self.settings))
        self.assertEqual(configuration(task, self.settings)["read_retries"], 3)
        self.assertEqual(configuration(task, self.settings)["max_repairs"], 3)
        self.assertEqual(configuration(task, self.settings)["stage_attempts"], 6)
        self.assertEqual(configuration(task, self.settings)["stage_seconds"], 14400)
        settings["timeout_seconds"] = 42
        self.settings.write_text(json.dumps(settings))
        self.assertEqual(configuration(task, self.settings)["timeout"], 42)

    def test_shared_configuration_and_relative_history_resolution(self):
        with patch.dict(os.environ, self.environment, clear=True):
            config = self.home / ".config/countersign/settings.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps(dict(run_base="my-runs")))
            self.assertEqual(settings_path(), config)
            self.assertEqual(run_storage(), config.parent / "my-runs")
            self.assertEqual(settings_path(self.settings), self.settings)

    def test_sigterm_stops_owned_worker_and_preserves_checkpoint(self):
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
                "countersign.web.service",
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
            token = json.load(response)["token"]
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
                "X-Countersign-Token": token,
            },
        )
        with opener.open(request) as response:
            run = runs / json.load(response)["id"]
        deadline = time.monotonic() + 10
        while not (run / "01-plan/stderr.log").exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        self.assertTrue((run / "01-plan/stderr.log").exists())
        process.send_signal(signal.SIGTERM)
        self.assertEqual(process.wait(timeout=15), 0, (self.home / "service.log").read_text())
        self.assertEqual(json.loads((run / "run.json").read_text())["status"], "INTERRUPTED")
        self.assertTrue((run / "checkpoint.json").is_file())
        self.assertIn("return 1", (self.repo / "hello.py").read_text())
        with (self.home / ".local/state/countersign/live.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def installer(self, *arguments):
        return subprocess.run(
            ["bash", str(BASE / "deploy/install.sh"), *arguments],
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
        self.environment["PATH"] = str(binaries) + os.pathsep + os.environ["PATH"]
        self.environment["PYTHON"] = sys.executable
        installed = self.installer(str(self.settings), "--autostart=yes")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertFalse((self.home / "loginctl.log").exists())
        log = self.home / "systemctl.log"
        self.assertIn("--user enable countersign.service", log.read_text())
        log.write_text("")
        current = self.home / ".local/share/countersign/current"
        first = current.resolve()
        config = self.home / ".config/countersign/settings.json"
        options = json.loads(config.read_text())
        self.assertEqual(options["timeout_seconds"], 3600)
        agents = Path(options["agent_source"])
        (agents / "planner.md").write_text("User-owned instructions")
        options["max_repairs"] = 1
        config.write_text(json.dumps(options))
        before = config.read_bytes()
        run = self.home / ".local/state/countersign/runs/preserved"
        run.mkdir()
        (run / "run.json").write_text("{}")
        updated = self.installer()
        self.assertEqual(updated.returncode, 0, updated.stderr)
        self.assertNotIn("--user enable ", log.read_text())
        disabled = self.installer("--autostart=no")
        self.assertEqual(disabled.returncode, 0, disabled.stderr)
        self.assertIn("--user disable countersign.service", log.read_text())
        invalid = self.installer("--wait=bad")
        self.assertEqual(invalid.returncode, 2)
        boot = self.installer("--boot=yes")
        self.assertEqual(boot.returncode, 0, boot.stderr)
        self.assertIn("enable-linger ", (self.home / "loginctl.log").read_text())
        self.assertNotEqual(first, current.resolve())
        self.assertTrue(first.is_dir())
        self.assertEqual(config.read_bytes(), before)
        self.assertEqual((agents / "planner.md").read_text(), "User-owned instructions")
        self.assertEqual((run / "run.json").read_text(), "{}")
        command = subprocess.run(
            [str(self.home / ".local/bin/countersign"), "status", str(run)],
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(command.returncode, 0, command.stderr)
        switched = self.installer("--agents=bundled", "--autostart=keep")
        self.assertEqual(switched.returncode, 0, switched.stderr)
        self.assertEqual(json.loads(config.read_text())["agent_source"], str(current / "agents"))
        self.assertEqual((agents / "planner.md").read_text(), "User-owned instructions")
        self.assertIn(
            before, [path.read_bytes() for path in config.parent.glob("settings.json.backup-*")]
        )
        with (self.home / ".local/state/countersign/live.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            rejected = self.installer()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("Stop the active task", rejected.stderr)
            with subprocess.Popen(
                ["bash", str(BASE / "deploy/install.sh"), "--wait=10"],
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
            unit = self.home / "countersign.service"
            unit.write_text(
                (BASE / "deploy/countersign.service").read_text().replace("%h", str(self.home))
            )
            checked = subprocess.run(
                ["systemd-analyze", "verify", str(unit)], capture_output=True, text=True
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_fresh_install_removes_managed_data_preserving_projects_and_cli_credentials(self):
        binaries = self.home / "bin"
        binaries.mkdir()
        for name in ("systemctl", "opencode"):
            executable = binaries / name
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
        self.environment["PATH"] = str(binaries) + os.pathsep + os.environ["PATH"]
        self.environment["PYTHON"] = sys.executable
        initial = self.installer(str(self.settings), "--autostart=no")
        self.assertEqual(initial.returncode, 0, initial.stderr)
        config = self.home / ".config/countersign/settings.json"
        app = self.home / ".local/share/countersign"
        old_release = (app / "current").resolve()
        history = self.home / "old-runs"
        run = history / "run-1"
        run.mkdir(parents=True)
        (run / "run.json").write_text(json.dumps({"roots": {"project": str(self.repo)}}))
        options = json.loads(config.read_text())
        options.update(run_base=str(history), timeout_seconds=9)
        config.write_text(json.dumps(options))
        profile = self.home / "profiles/countersign-planner.md"
        profile.parent.mkdir(exist_ok=True)
        profile.write_text("Managed Countersign workflow test")
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
        self.assertEqual(json.loads(config.read_text())["timeout_seconds"], 3600)
        self.assertTrue((app / "current/venv/bin/python").is_file())

    def test_fresh_refuses_a_mixed_custom_history_before_deletion(self):
        binaries = self.home / "bin"
        binaries.mkdir()
        systemctl = binaries / "systemctl"
        systemctl.write_text("#!/bin/sh\nexit 0\n")
        systemctl.chmod(0o755)
        self.environment["PATH"] = str(binaries) + os.pathsep + os.environ["PATH"]
        config = self.home / ".config/countersign"
        config.mkdir(parents=True)
        (config / "settings.json").write_text(json.dumps({"run_base": str(self.repo)}))
        result = self.installer("--fresh", "--autostart=keep")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("unrecognized", result.stderr)
        self.assertTrue((self.repo / "hello.py").exists())
        self.assertTrue((config / "settings.json").exists())
