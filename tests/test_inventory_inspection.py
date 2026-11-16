"""A task-selected inventory reaches the privileged ticket without exposing passwords."""

import io
import json
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail import cli_api, cli_requests, cli_service
from taskrail.application import (
    execution_requests,
    execution_wait,
    remote_catalog,
    task_config,
)
from taskrail.executor import action_schema, client, inventory, inventory_file
from taskrail.executor.service import ExecutorServer
from taskrail.executor.store import TicketStore
from taskrail.interactions import inventory_lookup, request_routes
from taskrail.web import task_form

SELECTION = {"file": "cluster.yaml", "group": "k8s"}
ACTION = dict(
    targets=["node1"], script="df -PT\n", files={}, reason="Disk usage", timeout_seconds=10
)
SECRET = "test-only-literal"
FIXTURE = """
all:
  vars:
    ansible_user: operator
    ansible_password: test-only-literal
  children:
    k8s:
      children:
        workers:
          hosts:
            node1: {ansible_host: 192.0.2.17}
            node2: {ansible_user: other, ansible_port: '2222'}
    elsewhere:
      hosts:
        other-node: {ansible_host: 192.0.2.19}
"""


class InventoryInspectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.file = self.base / "cluster.yaml"
        self.file.write_text(FIXTURE)
        directory = patch.object(inventory, "DIRECTORY", self.base)
        directory.start()
        self.addCleanup(directory.stop)
        self.store = TicketStore(self.base / "tickets")
        self.server = ExecutorServer(str(self.base / "executor.sock"), 1200, {}, self.store)
        self.addCleanup(self.server.server_close)

    def lookup(self, payload):
        selected = payload.get(inventory.KEY)
        if inventory_file.project(selected):
            with inventory_file.opened(selected["file"]) as stream:
                return self.server.dispatch(payload, 1200, stream.fileno())
        return self.server.dispatch(payload, 1200)

    def test_planner_resolves_the_task_inventory_before_approved_inspection(self):
        goal = f"Inspect the k8s servers from {self.file}."
        args = cli_api.submit_parser().parse_args(["--goal", goal, "--root", f"repo={self.base}"])
        task, _ = task_form.build_task(cli_requests.task_payload(args), self.base.parent / "runs")
        submitted = self.base / "task.md"
        submitted.write_text(task)
        settings = self.base / "settings.json"
        settings.write_text(json.dumps({"opencode_version": "1.x"}))
        config = task_config.configuration(submitted, settings)
        run = self.base / "run"
        folder = run / "02-plan"
        folder.mkdir(parents=True)
        (folder / "events.jsonl").touch()
        state = {"attempts": [], "roots": {"repo": str(self.base)}}
        session = SimpleNamespace(
            state=state,
            active=(folder, {"role": "planner", "stage": "planner"}),
            environment={"config": config, "run": run},
        )
        actions = SimpleNamespace(run=run, folder=folder, session=session)
        request = dict(
            schema_version=1, status="INVENTORY_REQUEST", path=str(self.file), group="k8s"
        )
        outcome = dict(
            final_text=json.dumps(request),
            sessions=["test-session"],
            final_message_id="response-1",
            status="OK",
        )
        with patch.object(remote_catalog.client, "request", side_effect=self.lookup):
            remote_catalog.protect_sources(config)
            self.assertIn(self.file.name, config["protected_paths"])
            self.assertIn(
                "INVENTORY_REQUEST",
                execution_requests.instructions(config, "planner", run, remote_catalog.available()),
            )
            rendered = request_routes.route(actions, outcome)
            selection = json.loads((run / "run.json").read_text())[inventory.KEY]
            catalog = remote_catalog.available(selection)
            self.assertEqual(set(catalog["hosts"]), {"node1", "node2"})
            self.assertIn("node1", rendered)
            self.assertNotIn("other-node", rendered)
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(
                    cli_service.check_command(
                        [
                            "check",
                            "--ssh",
                            "--inventory-file",
                            str(self.file),
                            "--inventory-group",
                            "k8s",
                        ]
                    ),
                    0,
                )
            with redirect_stdout(output):
                self.assertEqual(cli_service.check_command(["check", "--ssh"]), 0)
        self.assertIn("SSH executor ready", output.getvalue())
        self.assertIn("node1, node2", output.getvalue())
        self.assertEqual(catalog["hosts"]["node2"]["port"], 2222)
        remote = execution_wait.ssh_request(ACTION, selection)
        execution_wait.submit(run, run / "02-plan", remote)
        pending = execution_wait.read(run)[0]["request"]
        ticket = self.lookup(pending)
        self.assertEqual(ticket["status"], "PENDING_APPROVAL")
        self.assertEqual(ticket[inventory.KEY], selection)
        self.assertEqual(ticket, self.lookup(pending))
        with patch.object(
            inventory, "load", side_effect=inventory.InventoryError("Inventory changed.")
        ):
            self.assertEqual(ticket, self.lookup(pending))
            rejected = {"request": dict(pending, key="new-ticket"), "status": "SUBMITTING"}
            with patch.object(remote_catalog.client, "request", side_effect=self.lookup):
                execution_wait.observe(rejected)
            self.assertEqual(rejected["status"], "REJECTED")
        approval = dict(operation="approve", id=ticket["id"], digest=ticket["digest"])
        with self.assertRaises(ValueError):
            self.lookup(approval)
        with (
            patch(
                "taskrail.executor.worker.transport.execute",
                return_value=dict(status="SUCCEEDED", exit_code=0, output="42% " + SECRET),
            ) as execute,
            patch.object(threading.Thread, "start", lambda thread: thread.run()),
        ):
            self.assertEqual(self.server.dispatch(approval, 0)["status"], "APPROVED")
            observed = dict(request=pending, id=ticket["id"], status="PENDING_APPROVAL")
            with patch.object(remote_catalog.client, "request", side_effect=self.lookup):
                execution_wait.observe(observed)
                self.assertEqual(observed["status"], "APPROVED")
                execution_wait.observe(observed)
            self.assertEqual(execute.call_args.args[0]["password"], SECRET)
        result = self.store.get(ticket["id"])
        self.assertEqual(result["results"][0]["output"], "42% [REDACTED]")
        for artifact in (
            rendered,
            output.getvalue(),
            task,
            json.dumps(catalog),
            json.dumps(result),
            json.dumps(pending),
        ):
            self.assertNotIn(SECRET, artifact)

    def test_project_path_selects_the_exact_file_across_socket_and_restart(self):
        project = self.base / "project"
        project.mkdir()
        alternate = project / self.file.name
        alternate.write_text(FIXTURE.replace("192.0.2.17", "192.0.2.21"))
        config = {"roots": {"repo": project}}
        lookup = {"path": str(alternate), "group": "k8s"}
        binding = inventory_lookup.source(config, lookup)
        self.server.client_uid = os.getuid()
        listener = threading.Thread(target=self.server.serve_forever, daemon=True)
        listener.start()
        self.addCleanup(self.server.shutdown)
        address = self.server.server_address
        for path, expected in ((alternate, "192.0.2.21"), (self.file, "192.0.2.17")):
            selected = inventory_file.pin(inventory.selector(str(path), "k8s"))
            response = client.request(dict(operation="catalog", ssh_inventory=selected), address)
            self.assertEqual(response["hosts"]["node1"]["hostname"], expected)
            self.assertNotIn(SECRET, json.dumps(response))
        payload = dict(execution_wait.ssh_request(ACTION, binding), key="inspection")
        ticket = client.request(payload, address)
        start = dict(operation="start-inspection", id=ticket["id"], ssh_inventory=binding)
        self.assertEqual(client.request(start, address)["status"], "PENDING_APPROVAL")
        self.server.dispatch(dict(operation="approve", id=ticket["id"], digest=ticket["digest"]), 0)
        self.store.recover()
        alternate.unlink()
        self.assertEqual(client.request(start, address)["status"], "REJECTED")
        self.assertEqual(client.request(payload, address)["id"], ticket["id"])
        self.assertFalse(self.store.get(ticket["id"])["results"])
        with self.assertRaises(ValueError):
            inventory_lookup.source(config, dict(lookup, path=str(self.file)))
        self.assertIn("unavailable", remote_catalog.available({}))

    def test_a_changed_or_revoked_approved_inventory_never_starts_ssh(self):
        selection = inventory_file.pin(inventory.selector(str(self.file), "k8s"))
        payload = dict(execution_wait.ssh_request(ACTION, selection), key="project")
        ticket = self.lookup(payload)
        decision = dict(id=ticket["id"], digest=ticket["digest"])
        self.server.dispatch(dict(decision, operation="approve"), 0)
        start = dict(operation="start-inspection", id=ticket["id"], ssh_inventory=selection)
        self.file.write_text(FIXTURE.replace("192.0.2.17", "192.0.2.21"))
        with patch.object(threading.Thread, "start") as worker:
            self.assertIn("changed", self.lookup(start)["inventory_error"])
            self.file.write_text(FIXTURE)
            ticket = self.lookup(dict(payload, key="another-ticket"))
            decision = dict(id=ticket["id"], digest=ticket["digest"])
            self.server.dispatch(dict(decision, operation="approve"), 0)
            self.server.dispatch(dict(decision, operation="reject"), 0)
            self.assertEqual(self.lookup(dict(start, id=ticket["id"]))["status"], "REJECTED")
            worker.assert_not_called()

    def test_named_credentials_are_masked_before_model_start_without_executor(self):
        directory = self.base / "second cluster"
        directory.mkdir()
        second = directory / "another.yml"
        second.write_bytes(self.file.read_bytes())
        ordinary = self.base / "playbook.yaml"
        ordinary.write_text("- hosts: workers\n")
        goal = f"Check {self.file} and {second}. Also inspect {ordinary} and create new.yaml."
        config = dict(
            roots={"repo": self.base}, protected_paths=[], task_spec={"fields": [{"text": goal}]}
        )
        with patch.object(remote_catalog.client, "request", side_effect=ConnectionRefusedError):
            remote_catalog.protect_sources(config)
        self.assertCountEqual(config["protected_paths"], [self.file.name, second.name])

    def test_project_inventory_rejects_link_swaps_in_any_component(self):
        selection = inventory_file.pin(inventory.selector(str(self.file), "k8s"))
        actual = self.base / "elsewhere"
        self.file.rename(actual)
        self.file.symlink_to(actual)
        with self.assertRaises(inventory.InventoryError):
            inventory_file.pin(selection)
        linked = self.base / "linked"
        linked.symlink_to(self.base, target_is_directory=True)
        with (
            self.assertRaises(inventory.InventoryError),
            inventory_file.opened(linked / actual.name),
        ):
            self.fail("opened inventory through an ancestor symlink")

    def test_fifty_targets_are_inspected_in_reviewable_batches(self):
        group = {f"worker-{number}": {} for number in range(50)}
        settings = {"ansible_user": "operator", "ansible_password": SECRET}
        fixture = json.dumps({"k8s": {"hosts": group, "vars": settings}}).encode()
        with patch.object(inventory, "read", return_value=fixture):
            self.inspect_batches(group)

    def inspect_batches(self, group):
        selected = list(self.lookup(dict(operation="catalog", ssh_inventory=SELECTION))["hosts"])
        self.assertCountEqual(selected, group)
        for command in (
            "df -PT",
            "vmstat 1 2",
            "systemctl list-units --type=service --state=running --no-pager",
        ):
            observed = []
            for start in range(0, len(selected), action_schema.MAX_TARGETS):
                batch = selected[start : start + action_schema.MAX_TARGETS]
                action = dict(ACTION, targets=batch, script=command)
                ticket = self.lookup(
                    dict(execution_wait.ssh_request(action, SELECTION), key="batch")
                )
                self.assertEqual(ticket["status"], "PENDING_APPROVAL")
                with (
                    patch(
                        "taskrail.executor.worker.transport.execute",
                        side_effect=lambda *_: dict(
                            status="SUCCEEDED", exit_code=0, output="sample"
                        ),
                    ),
                    patch.object(threading.Thread, "start", lambda thread: thread.run()),
                ):
                    self.server.dispatch(
                        dict(operation="approve", id=ticket["id"], digest=ticket["digest"]), 0
                    )
                results = self.store.get(ticket["id"])["results"]
                observed.extend(item["target"] for item in results if item["status"] == "SUCCEEDED")
            self.assertCountEqual(observed, group)

    def test_fails_closed_for_wrong_group_unsafe_actions_and_changed_connections(self):
        wire = dict(execution_wait.ssh_request(ACTION, SELECTION), key="test-ticket")
        for action in (
            dict(ACTION, targets=["other-node"]),
            dict(ACTION, script="systemctl restart kubelet"),
            dict(ACTION, files={"test": "payload"}),
        ):
            with self.subTest(action=action), self.assertRaises((ValueError, KeyError)):
                self.lookup(dict(wire, action=action))
        for filename in ("../cluster.yaml", "/etc/shadow", "bad.yaml"):
            if filename == "bad.yaml":
                (self.base / filename).symlink_to(self.file)
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                inventory.load(dict(SELECTION, file=filename))
        ticket = self.lookup(wire)
        self.file.write_text(FIXTURE.replace("192.0.2.17", "192.0.2.21"))
        with (
            self.assertRaisesRegex(ValueError, "identity changed"),
            patch.object(threading.Thread, "start") as start,
        ):
            self.server.dispatch(
                dict(operation="approve", id=ticket["id"], digest=ticket["digest"]), 0
            )
        start.assert_not_called()
        self.assertEqual(self.store.get(ticket["id"])["status"], "PENDING_APPROVAL")
        for body, group in (
            (FIXTURE, "missing"),
            ("k8s: [" + SECRET, "k8s"),
            (FIXTURE.replace(SECRET, "'{{ lookup() }}'"), "k8s"),
        ):
            failures = io.StringIO()
            with (
                patch.object(inventory, "read", return_value=body.encode()),
                patch.object(remote_catalog.client, "request", side_effect=self.lookup),
                redirect_stderr(failures),
            ):
                self.assertEqual(
                    cli_service.check_command(
                        [
                            "check",
                            "--ssh",
                            "--inventory-file",
                            "cluster.yaml",
                            "--inventory-group",
                            group,
                        ]
                    ),
                    1,
                )
            self.assertNotIn(SECRET, failures.getvalue())
        with patch.object(
            remote_catalog.client, "request", return_value={"hosts": {"other-node": {}}}
        ):
            self.assertEqual(
                remote_catalog.available(SELECTION)["unavailable"], "routes.ssh.update"
            )
