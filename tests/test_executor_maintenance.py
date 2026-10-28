"""Executor updates and resets never race an approval or lose code or a journal."""

import json
import os
import socket
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from deployment_fixture import DeploymentFixture

from taskrail.application import execution_wait
from taskrail.executor import client, protocol
from taskrail.executor.service import ExecutorServer
from taskrail.executor.store import TicketStore

BASE = Path(__file__).resolve().parents[1]
LIBRARY = BASE / "deploy/executor-maintenance.sh"
SYSTEMCTL = """#!/bin/sh
printf '%s marker=%s\\n' "$*" "$(test -e "$MARKER" && echo yes || echo no)" >> "$LOG"
case "$1" in
  stop)
    if [ -n "$APPROVED_DURING_STOP" ]; then
      printf '{"status": "RUNNING"}' > "$STATE/late.json"
    fi
    exit "${STOP_EXIT:-0}" ;;
  is-active) exit "${ACTIVE_EXIT:-3}" ;;
esac
"""
ACTION = dict(targets=["a"], script="uname -a\n", files={}, reason="Inspect", timeout_seconds=30)
INVENTORY = {"a": {"hostname": "192.0.2.10", "port": 22, "username": "u", "password": "p"}}


class MaintenanceStepsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.config, self.state = base / "config", base / "state"
        self.config.mkdir()
        self.state.mkdir()
        self.marker = self.config / "maintenance"
        self.lock = base / "maintenance.lock"
        self.unit = base / "taskrail-executor.service"
        self.unit.write_text("[Unit]\n")
        self.log = base / "systemctl.log"
        binaries = base / "bin"
        binaries.mkdir()
        (binaries / "systemctl").write_text(SYSTEMCTL)
        (binaries / "systemctl").chmod(0o755)
        self.environment = dict(
            os.environ,
            PATH=f"{binaries}{os.pathsep}{os.environ['PATH']}",
            MARKER=str(self.marker),
            LOG=str(self.log),
            STATE=str(self.state),
        )

    def maintain(self, *statuses, **environment):
        script = (
            'set -euo pipefail; source "$1"; lock_executor_maintenance "$2"; shift 2; '
            'marker=$1; trap \'leave_maintenance "$marker"\' EXIT; begin_maintenance "$@"'
        )
        arguments = [
            str(LIBRARY),
            str(self.lock),
            str(self.marker),
            str(self.state),
            str(self.unit),
            *statuses,
        ]
        return subprocess.run(
            ["bash", "-c", script, "maintenance", *arguments],
            env=dict(self.environment, **environment),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def test_new_work_is_refused_before_the_service_stops(self):
        done = self.maintain("RUNNING")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("stop taskrail-executor.service marker=yes", self.calls())
        self.assertFalse(self.marker.exists())

    def test_a_running_action_stops_maintenance_before_the_service_stops(self):
        (self.state / "ticket.json").write_text(json.dumps(dict(status="RUNNING")))
        refused = self.maintain("RUNNING")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("ticket is RUNNING", refused.stderr)
        self.assertEqual(self.calls(), [])

    def test_a_failed_or_incomplete_stop_aborts(self):
        for environment in (dict(STOP_EXIT="1"), dict(ACTIVE_EXIT="0")):
            with self.subTest(environment=environment):
                self.assertNotEqual(self.maintain("RUNNING", **environment).returncode, 0)

    def test_an_action_approved_while_stopping_is_caught_after_the_stop(self):
        late = self.maintain("RUNNING", "UNKNOWN", APPROVED_DURING_STOP="1")
        self.assertNotEqual(late.returncode, 0)
        self.assertIn("late is RUNNING", late.stderr)

    def test_an_uninstalled_service_is_not_stopped(self):
        self.unit.unlink()
        self.assertEqual(self.maintain("RUNNING").returncode, 0)
        self.assertEqual(self.calls(), [])

    def test_an_existing_marker_is_neither_claimed_nor_removed(self):
        self.marker.write_text("interrupted owner")
        refused = self.maintain("RUNNING")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("inspect the interrupted maintenance", refused.stderr)
        self.assertEqual(self.marker.read_text(), "interrupted owner")
        self.assertEqual(self.calls(), [])

    def test_a_second_maintenance_process_cannot_clear_the_owners_marker(self):
        script = (
            'set -euo pipefail; source "$1"; lock_executor_maintenance "$2"; '
            "marker=$3; trap 'leave_maintenance \"$marker\"' EXIT; "
            'enter_maintenance "$marker"; echo ready; read -r finish'
        )
        with subprocess.Popen(
            ["bash", "-c", script, "owner", str(LIBRARY), str(self.lock), str(self.marker)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        ) as owner:
            self.assertEqual(owner.stdout.readline(), "ready\n")
            self.assertTrue(self.marker.exists())
            refused = self.maintain("RUNNING")
            self.assertNotEqual(refused.returncode, 0)
            self.assertIn("Another executor installation or reset", refused.stderr)
            self.assertTrue(self.marker.exists())
            _, error = owner.communicate("finish\n", timeout=5)
            self.assertEqual(owner.returncode, 0, error)
        self.assertFalse(self.marker.exists())

    def test_cleanup_after_preparation_failure_preserves_unowned_marker(self):
        self.marker.write_text("previous owner")
        script = (
            'set -euo pipefail; source "$1"; marker=$2; '
            "trap 'leave_maintenance \"$marker\"' EXIT; false"
        )
        failed = subprocess.run(
            ["bash", "-c", script, "prepare", str(LIBRARY), str(self.marker)],
            capture_output=True,
            text=True,
            timeout=5,
        )
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(self.marker.read_text(), "previous owner")


class MaintenanceScriptTests(unittest.TestCase):
    """The installer and reset take every step before they replace or delete anything."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        fixture = DeploymentFixture(self.home)
        self.release = fixture.source()
        for name in ("install-executor.sh", "reset-executor.sh"):
            script = self.release / "deploy" / name
            # Only the privilege guard changes; every host path and command is isolated.
            script.write_text(script.read_text().replace("$EUID", "0"))
        self.package = fixture.system / "opt/taskrail-executor/taskrail"
        self.config = fixture.system / "etc/taskrail-executor"
        self.state = fixture.system / "var/lib/taskrail-executor"
        self.unit = fixture.system / "etc/systemd/system/taskrail-executor.service"
        for directory in (
            self.package,
            self.config,
            self.state,
            self.unit.parent,
            fixture.system / "run",
            fixture.system / "usr/local/bin",
        ):
            directory.mkdir(parents=True, exist_ok=True)
        (self.package / "previous").write_text("previous package")
        (self.release / "taskrail/replacement").write_text("prepared package")
        self.unit.write_text("[Unit]\n")
        self.log = self.home / "operations.log"
        stubs = {
            "id": '#!/bin/sh\ncase "$1" in -u) echo 1000 ;; -nG) echo users ;; esac\n',
            "getent": "#!/bin/sh\nexit 0\n",
            "chown": "#!/bin/sh\nexit 0\n",
            "install": "#!/bin/bash\narguments=()\nwhile [[ $# -gt 0 ]]; do\n"
            'case "$1" in -o|-g) shift 2 ;; *) arguments+=("$1"); shift ;; esac\n'
            'done\nexec /usr/bin/install "${arguments[@]}"\n',
            "runuser": '#!/bin/sh\nprintf "prepare marker=%s\\n" '
            '"$(test -e "$MARKER" && echo yes || echo no)" >> "$LOG"\n'
            'exit "${PREPARE_EXIT:-0}"\n',
            "systemctl": '#!/bin/sh\nprintf "%s marker=%s previous=%s\\n" "$*" '
            '"$(test -e "$MARKER" && echo yes || echo no)" '
            '"$(test -e "$PACKAGE/previous" && echo yes || echo no)" >> "$LOG"\n'
            'case "$1" in stop) exit "${STOP_EXIT:-0}" ;; is-active) exit 3 ;; esac\n',
        }
        for name, source in stubs.items():
            executable = fixture.binaries / name
            executable.write_text(source)
            executable.chmod(0o755)
        self.environment = fixture.environment(
            dict(
                os.environ,
                HOME=str(self.home),
                MARKER=str(self.config / "maintenance"),
                LOG=str(self.log),
                PACKAGE=str(self.package),
            )
        )

    def execute(self, name, *arguments, **environment):
        return subprocess.run(
            ["bash", str(self.release / "deploy" / name), *arguments],
            env=dict(self.environment, **environment),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_the_installer_swaps_a_prepared_package_only_after_maintenance(self):
        installed = self.execute("install-executor.sh", "--client=fixture")
        self.assertEqual(installed.returncode, 0, installed.stderr)
        self.assertEqual((self.package / "replacement").read_text(), "prepared package")
        self.assertFalse((self.package / "previous").exists())
        self.assertEqual(
            self.log.read_text().splitlines()[:2],
            ["prepare marker=no", "stop taskrail-executor.service marker=yes previous=yes"],
        )
        self.assertFalse((self.config / "maintenance").exists())

    def test_failed_preparation_stop_and_running_work_preserve_the_old_package(self):
        for environment in (dict(PREPARE_EXIT="1"), dict(STOP_EXIT="1"), {}):
            with self.subTest(environment=environment):
                if not environment:
                    (self.state / "ticket.json").write_text('{"status":"RUNNING"}')
                failed = self.execute("install-executor.sh", "--client=fixture", **environment)
                self.assertNotEqual(failed.returncode, 0)
                self.assertEqual((self.package / "previous").read_text(), "previous package")
                self.assertFalse((self.package / "replacement").exists())
                self.assertFalse((self.config / "maintenance").exists())
                calls = self.log.read_text()
                if environment.get("PREPARE_EXIT") or not environment:
                    self.assertNotIn("stop ", calls)
                self.log.unlink()

    def test_the_reset_keeps_running_and_uncertain_journals(self):
        ticket = self.state / "ticket.json"
        for status in ("RUNNING", "UNKNOWN"):
            with self.subTest(status=status):
                ticket.write_text(json.dumps(dict(status=status)))
                refused = self.execute("reset-executor.sh")
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn(status, refused.stderr)
                self.assertEqual(json.loads(ticket.read_text())["status"], status)
                self.assertEqual((self.package / "previous").read_text(), "previous package")
                self.assertFalse(self.log.exists())
                self.assertFalse((self.config / "maintenance").exists())
        ticket.write_text('{"status":"COMPLETED"}')
        reset = self.execute("reset-executor.sh")
        self.assertEqual(reset.returncode, 0, reset.stderr)
        self.assertFalse(self.package.exists())
        self.assertFalse(ticket.exists())
        calls = self.log.read_text().splitlines()
        self.assertEqual(calls[0], "stop taskrail-executor.service marker=yes previous=yes")
        self.assertEqual(calls[-1], "daemon-reload marker=no previous=no")


class ExecutorPackageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.source = self.base / "source/taskrail"
        (self.source / "executor").mkdir(parents=True)
        for name in (
            "__init__.py",
            "executor/__init__.py",
            "executor/service.py",
            "executor/approval.py",
        ):
            (self.source / name).write_text('"""Import fixture."""\n')
        self.staging = self.base / "staging"
        self.staging.mkdir(mode=0o700)
        binaries = self.base / "bin"
        binaries.mkdir()
        (binaries / "chown").write_text("#!/bin/sh\nexit 0\n")
        (binaries / "runuser").write_text(
            '#!/bin/sh\nprintf "%s\\n" "$*" > "$PREFLIGHT_LOG"\nshift 3\nexec "$@"\n'
        )
        for binary in binaries.iterdir():
            binary.chmod(0o755)
        self.environment = dict(
            os.environ,
            PATH=str(binaries) + os.pathsep + os.environ["PATH"],
            PREFLIGHT_LOG=str(self.base / "preflight.log"),
        )

    def prepare_package(self):
        script = 'set -euo pipefail; source "$1"; prepare_executor_package "$2" "$3"'
        return subprocess.run(
            ["bash", "-c", script, "package", str(LIBRARY), str(self.source), str(self.staging)],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def test_private_source_modes_become_readable_without_write_access(self):
        for path in [self.source, *self.source.rglob("*")]:
            path.chmod(0o700 if path.is_dir() else 0o600)
        prepared = self.prepare_package()
        self.assertEqual(prepared.returncode, 0, prepared.stderr)
        for path in [self.staging, *self.staging.rglob("*")]:
            self.assertEqual(path.stat().st_mode & 0o777, 0o755 if path.is_dir() else 0o644)
        self.assertIn("-u taskrail-executor --", (self.base / "preflight.log").read_text())

    def test_broken_package_fails_the_import_preflight(self):
        (self.source / "executor/service.py").write_text("raise ImportError('broken package')\n")
        failed = self.prepare_package()
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("broken package", failed.stderr)

    def test_package_symlinks_are_refused_before_changing_their_targets(self):
        target = self.base / "outside.py"
        target.write_text("preserved")
        target.chmod(0o600)
        (self.source / "outside.py").symlink_to(target)
        failed = self.prepare_package()
        self.assertNotEqual(failed.returncode, 0)
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertFalse((self.base / "preflight.log").exists())


class MaintenanceServiceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.base = base
        self.store = TicketStore(base / "tickets")
        self.server = object.__new__(ExecutorServer)
        self.server.client_uid = 1000
        self.server.configs = {"ssh": INVENTORY, "jenkins": {}}
        self.server.store = self.store
        self.server.maintenance = base / "maintenance"

    def test_submissions_and_approvals_wait_for_maintenance_to_end(self):
        ticket = self.server.dispatch(dict(operation="submit", key="one", action=ACTION), 1000)
        self.server.maintenance.touch()
        approval = dict(operation="approve", id=ticket["id"], digest=ticket["digest"])
        for payload, uid in (
            (dict(operation="submit", key="two", action=ACTION), 1000),
            (approval, 0),
        ):
            with self.assertRaises(protocol.MaintenanceError):
                self.server.dispatch(payload, uid)
        self.assertEqual(self.store.get(ticket["id"])["status"], "PENDING_APPROVAL")
        self.assertEqual(
            self.server.dispatch(dict(operation="status", id=ticket["id"]), 1000), ticket
        )

    def test_a_refusal_reaches_the_application_as_an_outage(self):
        self.server.maintenance.touch()
        self.server.client_uid = os.getuid()
        address = str(self.base / "control.sock")
        with socket.socket(socket.AF_UNIX) as listener:
            listener.bind(address)
            listener.listen(1)
            serving = threading.Thread(target=self.answer_once, args=(listener,))
            serving.start()
            with self.assertRaises(protocol.MaintenanceError):
                client.request(dict(operation="submit", key="one", action=ACTION), address)
            serving.join(5)

    def answer_once(self, listener):
        connection, _ = listener.accept()
        with connection:
            self.server.finish_request(connection, None)

    def test_the_application_asks_again_during_maintenance(self):
        pending = dict(request=dict(operation="submit", key="one", action=ACTION))
        refusal = protocol.MaintenanceError("Executor maintenance is in progress")
        with patch.object(client, "request", side_effect=refusal):
            self.assertIn("retrying", execution_wait.observe(pending))
        self.assertNotIn("status", pending)


if __name__ == "__main__":
    unittest.main()
