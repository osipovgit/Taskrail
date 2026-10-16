"""Executor authority, immutable approvals and recovery tests; no real SSH."""

import copy
import io
import json
import struct
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from countersign.application import execution_requests, execution_wait
from countersign.executor import action_schema, client, hosts, protocol, transport, worker
from countersign.executor.service import ExecutorServer
from countersign.executor.store import TicketStore

INVENTORY = {
    "server-a": dict(
        hostname="192.0.2.10", port=22, username="operator", password="private-test-password"
    ),
    "server-b": dict(
        hostname="192.0.2.11", port=22, username="operator", password="other-private-password"
    ),
}
ACTION = dict(
    targets=["server-a"], script="uname -a\n", files={}, reason="Inspect kernel", timeout_seconds=30
)


class ExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = TicketStore(self.root / "tickets")

    def submit(self, action=None, key="request-1"):
        return self.store.submit(
            dict(operation="submit", key=key, action=copy.deepcopy(action or ACTION)), INVENTORY
        )

    def test_submit_is_idempotent_and_does_not_execute(self):
        with patch.object(transport, "execute") as execute:
            first = self.submit()
            self.assertEqual(first, self.submit())
            execute.assert_not_called()
        self.assertEqual(first["status"], "PENDING_APPROVAL")
        self.assertNotIn(INVENTORY["server-a"]["password"], json.dumps(first))

    def test_exact_digest_and_single_use_approval(self):
        ticket = self.submit()
        with self.assertRaises(ValueError):
            self.store.approve(ticket["id"], "wrong", INVENTORY)
        approved = self.store.approve(ticket["id"], ticket["digest"], INVENTORY)
        self.assertEqual(approved["status"], "RUNNING")
        with self.assertRaises(ValueError):
            self.store.approve(ticket["id"], ticket["digest"], INVENTORY)

    def test_changes_require_new_approval(self):
        first = self.submit()
        updated = dict(ACTION, script="uname -r\n")
        second = self.submit(updated)
        self.assertNotEqual(first["digest"], second["digest"])
        changed_hosts = copy.deepcopy(INVENTORY)
        changed_hosts["server-a"]["hostname"] = "192.0.2.20"
        with self.assertRaises(ValueError):
            self.store.approve(first["id"], first["digest"], changed_hosts)

    def server(self):
        server = object.__new__(ExecutorServer)
        server.client_uid = 1000
        server.inventory = INVENTORY
        server.store = self.store
        return server

    def test_application_uid_cannot_approve(self):
        server = self.server()
        ticket = server.dispatch(dict(operation="submit", key="one", action=ACTION), 1000)
        with patch.object(threading.Thread, "start") as start:
            with self.assertRaises(ValueError):
                server.dispatch(
                    dict(operation="approve", id=ticket["id"], digest=ticket["digest"]), 1000
                )
            start.assert_not_called()
        with self.assertRaises(ValueError):
            server.dispatch(dict(operation="catalog"), 1001)

    def test_wire_handler_uses_kernel_peer_uid(self):
        server = self.server()
        connection = MagicMock()
        connection.getsockopt.return_value = struct.pack("3i", 123, 1000, 1000)
        connection.makefile.return_value = io.BytesIO(b'{"operation":"catalog"}\n')
        server.finish_request(connection, None)
        response = json.loads(connection.sendall.call_args.args[0])
        self.assertEqual(response["hosts"]["server-a"]["hostname"], "192.0.2.10")
        self.assertNotIn("password", json.dumps(response))
        connection.getsockopt.return_value = struct.pack("3i", 123, 1001, 1001)
        connection.makefile.return_value = io.BytesIO(b'{"operation":"catalog","uid":0}\n')
        server.finish_request(connection, None)
        self.assertIn("error", json.loads(connection.sendall.call_args.args[0]))

    def test_restart_marks_running_unknown_and_never_replays(self):
        ticket = self.submit()
        self.store.approve(ticket["id"], ticket["digest"], INVENTORY)
        with patch.object(transport, "execute") as execute:
            self.store.recover()
            execute.assert_not_called()
        self.assertEqual(self.store.get(ticket["id"])["status"], "UNKNOWN")
        self.assertEqual(self.submit()["status"], "UNKNOWN")

    def test_failed_target_stops_and_redacts_all_configured_passwords(self):
        ticket = self.submit(dict(ACTION, targets=["server-a", "server-b"]))
        ticket = self.store.approve(ticket["id"], ticket["digest"], INVENTORY)
        failure = dict(
            status="FAILED", output="private-test-password other-private-password", truncated=False
        )
        with patch.object(transport, "execute", return_value=failure) as execute:
            worker.perform(self.store, ticket, INVENTORY)
            self.assertEqual(execute.call_count, 1)
        stored = self.store.get(ticket["id"])
        self.assertEqual(stored["status"], "FAILED")
        self.assertEqual(stored["results"][0]["output"], "[REDACTED] [REDACTED]")

    def test_ssh_does_not_inherit_agent_password_or_config_in_argv(self):
        argv = transport.command(INVENTORY["server-a"])
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn("IdentityAgent=none", argv)
        self.assertNotIn(INVENTORY["server-a"]["password"], repr(argv))
        env = transport.environment(INVENTORY["server-a"])
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")

    def test_bundle_paths_and_timeout_validation(self):
        for path in (
            "../escape",
            "/etc/passwd",
            "a/../../escape",
            "./a",
            "action.sh",
            "-a",
            "a;id",
            "a//b",
        ):
            with self.subTest(path=path), self.assertRaises(ValueError):
                action_schema.validate(dict(ACTION, files={path: "text"}))
        for timeout in (True, -1, 0, 3601, "30"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                action_schema.validate(dict(ACTION, timeout_seconds=timeout))
        with self.assertRaises(ValueError):
            action_schema.validate(dict(ACTION, targets=["server-a", "server-a"]))
        with self.assertRaises(ValueError):
            action_schema.validate(dict(ACTION, surprise=True))

    def test_bundle_snapshot_has_no_local_file_references(self):
        action = dict(
            ACTION, files={"roles/main.yml": "- debug: msg=hello\n"}, script="cat roles/main.yml\n"
        )
        ticket = self.submit(action)
        action["files"]["roles/main.yml"] = "changed"
        saved = self.store.get(ticket["id"])["action"]
        self.assertEqual(saved["files"]["roles/main.yml"], "- debug: msg=hello\n")
        script = transport.remote_script(saved)
        self.assertIn("mktemp -d", script)
        self.assertIn("base64 -d", script)
        self.assertIn("/bin/sh ./action.sh", script)

    def test_protocol_size_limits_and_invalid_messages(self):
        for raw in (b"{}", b"[]\n", b"x" * (protocol.MAX_MESSAGE + 2)):
            with self.assertRaises(ValueError):
                protocol.receive(io.BytesIO(raw))
        with self.assertRaises(ValueError):
            protocol.encode(dict(text="x" * protocol.MAX_MESSAGE))
        for name in ("../escape", "", "-option", "x/y"):
            with self.assertRaises(ValueError):
                self.store.get(name)

    def test_action_contract_is_distinct_from_final_results(self):
        self.assertIsNone(execution_requests.extract('{"status":"PLAN_READY"}'))
        request = dict(schema_version=1, status="ACTION_REQUEST", action=ACTION)
        self.assertEqual(execution_requests.extract(json.dumps(request)), ACTION)
        with self.assertRaises(ValueError):
            execution_requests.extract(json.dumps(dict(request, schema_version=2)))

    def test_pending_action_survives_stop_and_resume(self):
        run = self.root / "run"
        folder = run / "01-plan"
        folder.mkdir(parents=True)
        execution_wait.submit(run, folder, ACTION)
        (run / "stop.request").touch()
        with self.assertRaises(KeyboardInterrupt), patch.object(client, "request") as request:
            execution_wait.resume(run, {})
            request.assert_not_called()
        (run / "stop.request").unlink()
        state = {"attempts": []}
        outcome = dict(id="ticket", status="SUCCEEDED", results=[dict(output="Linux")])
        with patch.object(client, "request", return_value=outcome) as request:
            context = execution_wait.resume(run, state)
            self.assertIn("Linux", context)
            proof = run / "00-input/ssh/ticket.json"
            self.assertIn(str(proof), context)
            self.assertEqual(json.loads(proof.read_text())[-1]["status"], "SUCCEEDED")
            self.assertEqual(request.call_count, 1)
        with patch.object(client, "request") as request:
            self.assertIn("Linux", execution_wait.resume(run, state))
            request.assert_not_called()

    def test_unknown_action_cannot_be_blindly_resumed(self):
        run = self.root / "run"
        folder = run / "01-plan"
        folder.mkdir(parents=True)
        execution_wait.submit(run, folder, ACTION)
        with patch.object(client, "request", return_value=dict(status="UNKNOWN")):
            with self.assertRaisesRegex(ValueError, "UNKNOWN"):
                execution_wait.resume(run, {"attempts": []})

    def test_rejection_is_terminal_and_never_executes(self):
        ticket = self.submit()
        rejected = self.store.reject(ticket["id"], ticket["digest"])
        self.assertEqual(rejected["status"], "REJECTED")
        with self.assertRaises(ValueError):
            self.store.approve(ticket["id"], ticket["digest"], INVENTORY)

    def test_root_approval_launches_once(self):
        server = self.server()
        ticket = self.submit()
        request = dict(operation="approve", id=ticket["id"], digest=ticket["digest"])
        with patch.object(threading.Thread, "start") as start:
            self.assertEqual(server.dispatch(request, 0)["status"], "RUNNING")
            with self.assertRaises(ValueError):
                server.dispatch(request, 0)
            self.assertEqual(start.call_count, 1)

    def test_timeout_and_disconnect_are_unknown(self):
        with patch.object(
            transport.subprocess, "run", side_effect=subprocess.TimeoutExpired("ssh", 30)
        ):
            self.assertEqual(transport.execute(INVENTORY["server-a"], ACTION)["status"], "UNKNOWN")
        for code, expected in ((255, "UNKNOWN"), (-25, "UNKNOWN"), (0, "SUCCEEDED"), (1, "FAILED")):
            with patch.object(
                transport.subprocess, "run", return_value=subprocess.CompletedProcess("ssh", code)
            ):
                outcome = transport.execute(INVENTORY["server-a"], ACTION)
                self.assertEqual(outcome["status"], expected)
                self.assertEqual(outcome["exit_code"], code)

    def test_complete_bundle_executes_only_in_temporary_directory(self):
        # Local execution here tests the generated transport fixture, never real SSH.
        destination = self.root / "bundle-output"
        action = dict(
            ACTION,
            files={"input.txt": "literal $(not-executed)\n"},
            script=f"cat input.txt > '{destination}'\n",
        )
        subprocess.run(["/bin/sh"], input=transport.remote_script(action), text=True, check=True)
        self.assertEqual(destination.read_text(), "literal $(not-executed)\n")

    def test_inventory_rejects_ssh_options_as_identity(self):
        for key, value in (
            ("hostname", "-oProxyCommand=id"),
            ("username", "-root"),
            ("port", True),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                hosts.validate(dict(INVENTORY["server-a"], **{key: value}))

    def test_runtime_evidence_requires_successful_matching_ticket_and_source_read(self):
        from countersign.application.execution_evidence import claim_ids
        from countersign.core.coverage import validate_outcome

        run = self.root / "runtime-proof"
        directory = run / "00-input/ssh"
        directory.mkdir(parents=True)
        entry = {"id": "ticket", "status": "SUCCEEDED", "results": [{"output": "healthy"}]}
        (run / "execution.json").write_text(json.dumps([entry]))
        path = directory / "ticket.json"
        path.write_text(json.dumps([entry]))
        claims = [{"id": "E1", "path": str(path)}]
        self.assertEqual(claim_ids(run, claims), {"E1"})
        outcome = {"outcome": "satisfied", "evidence_ids": ["E1"]}
        with self.assertRaises(ValueError):
            validate_outcome(outcome, {"kind": "runtime"}, {"E1": {}}, ())
        validate_outcome(outcome, {"kind": "runtime"}, {"E1": {}}, {"E1"})
        path.write_text(json.dumps([{**entry, "results": [{"output": "forged"}]}]))
        self.assertEqual(claim_ids(run, claims), set())


if __name__ == "__main__":
    unittest.main()
