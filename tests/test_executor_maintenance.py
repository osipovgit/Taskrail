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

from countersign.application import execution_wait
from countersign.executor import client, protocol
from countersign.executor.service import ExecutorServer
from countersign.executor.store import TicketStore

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
        self.unit = base / "countersign-executor.service"
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
        script = 'set -euo pipefail; source "$1"; shift; begin_maintenance "$@"'
        arguments = [str(LIBRARY), str(self.marker), str(self.state), str(self.unit), *statuses]
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
        self.assertIn("stop countersign-executor.service marker=yes", self.calls())
        self.assertTrue(self.marker.exists())

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


class MaintenanceScriptTests(unittest.TestCase):
    """The installer and reset take every step before they replace or delete anything."""

    def test_the_installer_swaps_a_prepared_package_only_after_maintenance(self):
        script = (BASE / "deploy/install-executor.sh").read_text()
        steps = ['cp -R -- "$source_root/countersign"', "begin_maintenance", 'mv -- "$staging']
        positions = [script.index(step) for step in steps]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("trap cleanup EXIT", script)
        self.assertNotIn("systemctl stop", script)
        self.assertNotIn("rm -rf -- /opt/countersign-executor/countersign", script)

    def test_the_reset_keeps_running_and_uncertain_journals(self):
        script = (BASE / "deploy/reset-executor.sh").read_text()
        maintenance = script.index('begin_maintenance "$marker"')
        self.assertIn("RUNNING UNKNOWN", script[maintenance : script.index("\n", maintenance)])
        self.assertLess(maintenance, script.index("rm -rf --"))
        self.assertIn("trap 'leave_maintenance", script)


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
