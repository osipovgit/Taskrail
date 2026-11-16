"""A task-selected inventory reaches the privileged ticket without exposing passwords."""

import io
import json
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
from taskrail.executor import action_schema, inventory
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
        return self.server.dispatch(payload, 1200)

    def test_planner_resolves_the_task_inventory_before_approved_inspection(self):
        goal = f"Inspect the k8s servers from {self.file}."
        args = cli_api.submit_parser().parse_args(["--goal", goal, "--root", f"repo={self.base}"])
        task, _ = task_form.build_task(cli_requests.task_payload(args), self.base.parent / "runs")
        submitted = self.base / "task.md"
        submitted.write_text(task)
        config = task_config.configuration(submitted, self.base / "settings.json")
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
                            "cluster.yaml",
                            "--inventory-group",
                            "k8s",
                        ]
                    ),
                    0,
                )
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
            self.server.dispatch(approval, 0)
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

    def test_inventory_request_rejects_other_paths_and_same_name_different_contents(self):
        project = self.base / "project"
        project.mkdir()
        alternate = project / self.file.name
        alternate.write_text(FIXTURE.replace("192.0.2.17", "192.0.2.21"))
        config = {"roots": {"repo": project}}
        lookup = {"path": str(alternate), "group": "k8s"}
        binding = inventory_lookup.source(config, lookup)
        with self.assertRaisesRegex(inventory.InventoryError, "differs"):
            inventory.load(binding)
        with self.assertRaises(ValueError):
            inventory_lookup.source(config, dict(lookup, path=str(self.file)))
        self.assertIn("unavailable", remote_catalog.available({}))

    def test_fifty_targets_are_inspected_in_reviewable_batches(self):
        group = {f"worker-{number}": {} for number in range(50)}
        self.file.write_text(
            json.dumps(
                {
                    "k8s": {
                        "hosts": group,
                        "vars": {
                            "ansible_user": "operator",
                            "ansible_password": SECRET,
                        },
                    }
                }
            )
        )
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
            self.file.write_text(body)
            failures = io.StringIO()
            with (
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
