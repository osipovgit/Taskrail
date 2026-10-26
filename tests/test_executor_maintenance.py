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

    def migrate(self, root):
        for name in ("getent", "id", "groupmod", "usermod"):
            stub = Path(self.environment["PATH"].split(os.pathsep)[0]) / name
            stub.write_text(f'#!/bin/sh\nprintf "{name} %s\\n" "$*" >> "$LOG"\n')
            stub.chmod(0o755)
        script = (
            'set -euo pipefail; source "$1"; lock_executor_maintenance "$2"; '
            'migrate_previous_executor "$3" "$4" "$5"'
        )
        new_config, new_state = root / "etc/taskrail-executor", root / "var/lib/taskrail-executor"
        arguments = [str(LIBRARY), str(self.lock), str(new_config), str(new_state), str(root)]
        result = subprocess.run(
            ["bash", "-c", script, "migrate", *arguments],
            env=self.environment,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result, new_config, new_state

    def previous_executor(self, root, status):
        old = "countersign-executor"
        (root / f"etc/{old}").mkdir(parents=True)
        (root / f"etc/{old}/hosts.json").write_text("{}")
        (root / f"var/lib/{old}").mkdir(parents=True)
        (root / f"var/lib/{old}/t1.json").write_text(json.dumps(dict(status=status)))
        (root / "etc/systemd/system").mkdir(parents=True)
        (root / f"etc/systemd/system/{old}.service").write_text("[Unit]\n")
        (root / f"opt/{old}").mkdir(parents=True)

    def test_a_previous_executor_moves_once_with_its_credentials_and_journal(self):
        root = Path(self.state.parent) / "root"
        self.previous_executor(root, "SUCCEEDED")
        result, config, state = self.migrate(root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((config / "hosts.json").read_text(), "{}")
        self.assertTrue((state / "t1.json").is_file())
        self.assertFalse((root / "etc/countersign-executor").exists())
        self.assertFalse((root / "etc/systemd/system/countersign-executor.service").exists())
        self.assertFalse((root / "opt/countersign-executor").exists())
        log = self.log.read_text()
        self.assertIn("stop countersign-executor.service", log)
        self.assertIn("groupmod -n taskrail-executor-clients countersign-executor-clients", log)
        self.assertIn("usermod -l taskrail-executor countersign-executor", log)
        again, _, _ = self.migrate(root)
        self.assertEqual(again.returncode, 0, again.stderr)
        self.assertEqual(self.log.read_text(), log)

    def test_a_previous_executor_with_a_running_action_is_not_moved(self):
        root = Path(self.state.parent) / "root"
        self.previous_executor(root, "RUNNING")
        result, config, _ = self.migrate(root)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("reconcile it first", result.stderr)
        self.assertFalse(config.exists())
        self.assertTrue((root / "etc/countersign-executor/hosts.json").is_file())

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

    def test_the_installer_swaps_a_prepared_package_only_after_maintenance(self):
        script = (BASE / "deploy/install-executor.sh").read_text()
        steps = [
            "lock_executor_maintenance",
            "prepare_executor_package",
            "begin_maintenance",
            'mv -- "$staging',
        ]
        positions = [script.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("trap cleanup EXIT", script)
        self.assertNotIn("systemctl stop", script)
        self.assertNotIn("rm -rf -- /opt/taskrail-executor/taskrail", script)

    def test_the_reset_keeps_running_and_uncertain_journals(self):
        script = (BASE / "deploy/reset-executor.sh").read_text()
        maintenance = script.index('begin_maintenance "$marker"')
        self.assertIn("RUNNING UNKNOWN", script[maintenance : script.index("\n", maintenance)])
        self.assertLess(maintenance, script.index("rm -rf --"))
        self.assertIn("trap 'leave_maintenance", script)


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
