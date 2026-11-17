"""Executor authority, immutable approvals and recovery tests; no real SSH."""

import io
import json
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from taskrail.application import (
    execution_requests,
    execution_wait,
    remote_catalog,
)
from taskrail.executor import (
    action_schema,
    client,
    hosts,
    protocol,
    transport,
    worker,
)
from taskrail.executor.service import ExecutorServer
from taskrail.executor.store import TicketStore, record_target
from taskrail.interactions import remote

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
        self.known_hosts = self.root / "known_hosts"
        lookup = patch.object(transport.host_keys, "trust_file", return_value=self.known_hosts)
        lookup.start()
        self.addCleanup(lookup.stop)

    def submit(self, action=None, key="request-1"):
        server = self.server()
        return server.dispatch(
            dict(operation="run-ssh", key=key, action=action or ACTION), server.client_uid
        )

    def test_concurrent_delivery_starts_one_worker(self):
        with patch.object(worker, "launch", return_value={"status": "RUNNING"}) as launch:
            with ThreadPoolExecutor(2) as pool:
                responses = list(pool.map(lambda _: self.submit(), range(2)))
            self.assertTrue(all(reply["status"] == "RUNNING" for reply in responses))
        launch.assert_called_once()
        self.assertNotIn(INVENTORY["server-a"]["password"], json.dumps(launch.call_args.args[1]))

    def test_invalid_or_obsolete_submissions_never_start_a_worker(self):
        server = self.server()
        cases = [
            dict(operation="run-ssh", action=ACTION, jenkins={}),
            dict(operation="run-ssh", kind="ssh", action=ACTION),
            dict(operation="submit", action=ACTION),
            dict(operation="run-ssh", jenkins={}),
        ]
        with patch.object(worker, "launch") as launch:
            for payload in cases:
                with self.subTest(payload=payload), self.assertRaises(ValueError):
                    server.dispatch(dict(payload, key="one"), server.client_uid)
            launch.assert_not_called()
        self.assertFalse(list(self.store.directory.iterdir()))

    def server(self):
        server = object.__new__(ExecutorServer)
        server.client_uid = 1000
        server.configs = {"ssh": INVENTORY, "jenkins": {}}
        server.store = self.store
        return server

    def test_wire_handler_uses_kernel_peer_uid(self):
        server = self.server()
        connection = MagicMock()
        connection.recvmsg.return_value = (b"{", [], 0, None)
        connection.getsockopt.return_value = struct.pack("3i", 123, 1000, 1000)
        connection.makefile.return_value = io.BytesIO(b'"operation":"catalog"}\n')
        server.finish_request(connection, None)
        response = json.loads(connection.sendall.call_args.args[0])
        self.assertEqual(response["hosts"]["server-a"]["hostname"], "192.0.2.10")
        self.assertNotIn("password", json.dumps(response))
        connection.getsockopt.return_value = struct.pack("3i", 123, 1001, 1001)
        connection.makefile.return_value = io.BytesIO(b'"operation":"catalog","uid":0}\n')
        server.finish_request(connection, None)
        self.assertIn("error", json.loads(connection.sendall.call_args.args[0]))

    def test_restart_marks_running_unknown_and_never_replays(self):
        with patch.object(threading.Thread, "start") as start:
            ticket = self.submit()
            record_target(
                self.store.directory,
                ticket["id"],
                0,
                {"target": "server-a", "status": "SUCCEEDED", "output": "done"},
            )
            self.store.recover()
            saved = self.submit()
            start.assert_called_once()
        self.assertEqual(saved["status"], "UNKNOWN")
        self.assertEqual(saved["results"][0]["output"], "done")

    def test_uncertain_host_and_failed_host_do_not_skip_later_hosts(self):
        server = self.server()
        server.configs["ssh"] = dict(INVENTORY, third=INVENTORY["server-b"])
        failure = dict(
            status="FAILED", output="private-test-password other-private-password", exit_code=1
        )
        success = dict(status="SUCCEEDED", output="ok", exit_code=0)
        with (
            patch.object(threading.Thread, "start", lambda thread: thread.run()),
            patch.object(
                transport, "execute", side_effect=[OSError(), failure, success]
            ) as execute,
        ):
            ticket = server.dispatch(
                dict(operation="run-ssh", key="group", action=dict(ACTION, targets="all")), 1000
            )
        stored = self.store.get(ticket["id"])
        self.assertEqual(execute.call_count, 3)
        self.assertEqual(stored["status"], "UNKNOWN")
        self.assertEqual(
            [row["status"] for row in stored["results"]], ["UNKNOWN", "FAILED", "SUCCEEDED"]
        )
        self.assertEqual(stored["results"][1]["output"], "[REDACTED] [REDACTED]")

    def test_ssh_does_not_inherit_agent_password_or_config_in_argv(self):
        argv = transport.command(INVENTORY["server-a"], self.known_hosts)
        self.assertIn("StrictHostKeyChecking=yes", argv)
        self.assertIn(f"UserKnownHostsFile={self.known_hosts}", argv)
        self.assertIn(f"GlobalKnownHostsFile={transport.host_keys.PINNED}", argv)
        self.assertIn("UpdateHostKeys=no", argv)
        self.assertIn("IdentityAgent=none", argv)
        self.assertNotIn(INVENTORY["server-a"]["password"], repr(argv))
        env = transport.environment(INVENTORY["server-a"])
        self.assertNotIn("SSH_AUTH_SOCK", env)
        self.assertEqual(env["SSH_ASKPASS_REQUIRE"], "force")

    def test_key_hosts_use_one_identity_and_no_password_helper(self):
        key_host = dict(INVENTORY["server-a"])
        key_host.pop("password")
        key_host["identity_file"] = "/etc/taskrail-executor/keys/server-a"
        hosts.validate(key_host)
        argv = transport.command(key_host, self.known_hosts)
        for option in (
            "IdentityFile=/etc/taskrail-executor/keys/server-a",
            "IdentitiesOnly=yes",
            "BatchMode=yes",
            "PasswordAuthentication=no",
            "IdentityAgent=none",
        ):
            self.assertIn(option, argv)
        self.assertNotIn("PreferredAuthentications=password", argv)
        env = transport.environment(key_host)
        self.assertNotIn("SSH_ASKPASS", env)
        self.assertNotIn("TASKRAIL_SSH_PASSWORD", env)
        self.assertEqual(hosts.redact("text", {"k": key_host}), "text")
        for identity in ("relative/key", "/root/.ssh/id_ed25519", "/etc/taskrail-executor/../x"):
            with self.subTest(identity=identity), self.assertRaises(ValueError):
                hosts.validate(dict(key_host, identity_file=identity))
        with self.assertRaises(ValueError):
            hosts.validate(dict(key_host, password="both"))

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
        for timeout in (True, -1, 0, "30"):
            with self.subTest(timeout=timeout), self.assertRaises(ValueError):
                action_schema.validate(dict(ACTION, timeout_seconds=timeout))
        with self.assertRaises(ValueError):
            action_schema.validate(dict(ACTION, targets=["server-a", "server-a"]))
        with self.assertRaises(ValueError):
            action_schema.validate(dict(ACTION, surprise=True))

    def test_ssh_has_no_fixed_command_deadline_or_payload_quota(self):
        action = dict(
            ACTION,
            targets=[f"node-{i}" for i in range(80)],
            files={f"data/{i}": "" for i in range(220)},
            script="x" * 600000,
            timeout_seconds=86400,
        )
        self.assertEqual(action_schema.validate(action), action)
        del action["timeout_seconds"]
        self.assertEqual(action_schema.validate(action), action)
        with patch("taskrail.executor.streams.execute", return_value=(0, "ok")) as execute:
            transport.execute(INVENTORY["server-a"], action)
        self.assertIsNone(execute.call_args.args[-1])

    def test_bundle_snapshot_has_no_local_file_references(self):
        action = dict(
            ACTION, files={"roles/main.yml": "- debug: msg=hello\n"}, script="cat roles/main.yml\n"
        )
        with patch.object(threading.Thread, "start"):
            ticket = self.submit(action)
        action["files"]["roles/main.yml"] = "changed"
        saved = self.store.get(ticket["id"])["action"]
        self.assertEqual(saved["files"]["roles/main.yml"], "- debug: msg=hello\n")
        script = transport.remote_script(saved)
        self.assertIn("mktemp -d", script)
        self.assertIn("base64 -d", script)
        self.assertIn("/bin/sh ./action.sh", script)

    def test_protocol_reads_complete_large_frames_and_rejects_invalid_messages(self):
        large = {"script": "x" * (2 * 1024 * 1024)}
        self.assertEqual(protocol.receive(io.BytesIO(protocol.encode(large))), large)
        for raw in (b"{}", b"[]\n", b'{"x": 1, "x": 2}\n'):
            with self.assertRaises(ValueError):
                protocol.receive(io.BytesIO(raw))
        for name in ("../escape", "", "-option", "x/y"):
            with self.assertRaises(ValueError):
                self.store.get(name)

    def test_every_project_stage_can_submit_an_agent_selected_pipeline(self):
        run = self.root / "inspection"
        script = "kubectl get pods -A | sort; ceph -s"
        with (
            patch.object(remote_catalog, "available", return_value={"hosts": INVENTORY}),
            patch.object(execution_wait, "resume", return_value="observed"),
        ):
            for role in ("planner", "plan-reviewer", "implementer", "reviewer"):
                self.assertEqual(
                    remote.consume(self.session(run, role, {}), self.request(script)), "observed"
                )
        entries = execution_wait.read(run)
        self.assertEqual([e["request"]["operation"] for e in entries], ["run-ssh"] * 4)
        self.assertTrue(all(e["request"]["action"]["script"] == script for e in entries))

    def test_missing_inspection_capability_returns_feedback_before_a_ticket_exists(self):
        run = self.root / "inspection"
        session = self.session(run, "planner", {})
        for catalog, detail in (
            ({"unavailable": "routes.ssh.denied"}, "socket access denied"),
            ({"hosts": {}}, "no configured targets"),
            ({"hosts": {"other": {}}}, "Unknown SSH targets: server-a"),
        ):
            with (
                self.subTest(catalog=catalog),
                patch.object(remote_catalog, "available", return_value=catalog),
            ):
                self.assertIn(detail, remote.consume(session, self.request("df -P")))
                self.assertEqual(execution_wait.read(run), [])

    def session(self, run, role, config):
        folder = run / "01-plan"
        folder.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(
            active=(folder, {"role": role}), environment=dict(run=run, config=config), state={}
        )

    def request(self, script):
        return dict(ACTION, script=script)

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
        execution_wait.submit(run, folder, execution_wait.ssh_request(ACTION))
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
            proof = run / "00-input/remote/ticket.json"
            self.assertIn(str(proof), context)
            self.assertEqual(json.loads(proof.read_text())["status"], "SUCCEEDED")
            self.assertEqual(request.call_count, 1)
        with patch.object(client, "request") as request:
            self.assertIn("Linux", execution_wait.resume(run, state))
            request.assert_not_called()

    def test_repeated_check_is_a_new_ticket_and_outages_are_retried(self):
        run = self.root / "run"
        folder = run / "01-plan"
        folder.mkdir(parents=True)
        execution_wait.submit(run, folder, execution_wait.ssh_request(ACTION))
        execution_wait.submit(run, folder, execution_wait.ssh_request(ACTION))
        first, second = execution_wait.read(run)
        self.assertNotEqual(first["request"]["key"], second["request"]["key"])
        outcome = dict(id="ticket", status="SUCCEEDED", results=[dict(output="Linux")])
        responses = [ConnectionRefusedError(), outcome]
        with (
            patch.object(client, "request", side_effect=responses) as request,
            patch.object(execution_wait.time, "sleep") as pause,
        ):
            self.assertIn("Linux", execution_wait.resume(run, {"attempts": []}))
        self.assertEqual(request.call_args_list[0], request.call_args_list[1])
        self.assertEqual(pause.call_count, 1)

    def test_unknown_ssh_outcome_returns_to_the_model_without_replay(self):
        run = self.root / "run"
        folder = run / "01-plan"
        folder.mkdir(parents=True)
        execution_wait.submit(run, folder, execution_wait.ssh_request(ACTION))
        with patch.object(
            client, "request", return_value=dict(id="ticket", status="UNKNOWN", results=[])
        ) as request:
            for _ in range(2):
                self.assertIn("UNKNOWN", execution_wait.resume(run, {"attempts": []}))
            request.assert_called_once()

    def test_timeout_and_disconnect_are_unknown(self):
        local = patch.object(transport, "command", return_value=["/bin/sh", "-s"])
        slow = dict(ACTION, script="sleep 30\n", timeout_seconds=1)
        with local:
            started = time.monotonic()
            outcome = transport.execute(INVENTORY["server-a"], slow)
        self.assertEqual((outcome["status"], outcome["exit_code"]), ("UNKNOWN", None))
        self.assertLess(time.monotonic() - started, 10)
        for code, expected in ((255, "UNKNOWN"), (-25, "UNKNOWN"), (0, "SUCCEEDED"), (1, "FAILED")):
            outcome = transport.captured("", code)
            self.assertEqual(outcome["status"], expected)
            self.assertEqual(outcome["exit_code"], code)

    def test_large_output_is_preserved_with_its_exit_code(self):
        script = "head -c 9000000 /dev/zero | tr '\\0' x\necho END\nexit 3\n"
        with patch.object(transport, "command", return_value=["/bin/sh", "-s"]):
            outcome = transport.execute(INVENTORY["server-a"], dict(ACTION, script=script))
        self.assertEqual((outcome["status"], outcome["exit_code"]), ("FAILED", 3))
        self.assertEqual(len(outcome["output"]), 9000004)
        self.assertTrue(outcome["output"].endswith("xEND\n"))

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

    def test_unbound_successful_ticket_cannot_prove_a_runtime_criterion(self):
        from taskrail.application.execution_evidence import claim_ids
        from taskrail.core.coverage import validate_outcome

        run = self.root / "runtime-proof"
        directory = run / "00-input/remote"
        directory.mkdir(parents=True)
        entry = {"id": "ticket", "status": "SUCCEEDED", "results": [{"output": "healthy"}]}
        (run / "remote-execution.json").write_text(json.dumps([entry]))
        path = directory / "ticket.json"
        path.write_text(json.dumps(entry))
        claims = [{"id": "E1", "path": str(path)}]
        self.assertEqual(claim_ids(run, claims), {})
        outcome = {"outcome": "satisfied", "evidence_ids": ["E1"]}
        with self.assertRaises(ValueError):
            validate_outcome(outcome, {"kind": "runtime"}, {"E1": {}}, ())
        with self.assertRaises(ValueError):
            validate_outcome(outcome, {"kind": "runtime"}, {"E1": {}}, {"E1"})
        path.write_text(json.dumps({**entry, "results": [{"output": "forged"}]}))
        self.assertEqual(claim_ids(run, claims), {})


if __name__ == "__main__":
    unittest.main()
