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
    ansible_inventory,
    execution_requests,
    execution_wait,
    remote_catalog,
    run_setup,
    task_config,
)
from taskrail.core import protected_paths
from taskrail.executor import client, inventory, inventory_file
from taskrail.executor.service import ExecutorServer
from taskrail.executor.store import TicketStore
from taskrail.git import process
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
            node2: {ansible_user: other, ansible_password: test-only-literal-extra, ansible_port: '2222'}
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

    def test_planner_resolves_the_task_inventory_and_runs_the_selected_command(self):
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
        resolved = {
            "node1": {
                "ansible_host": "192.0.2.17",
                "ansible_user": "operator",
                "ansible_password": SECRET,
            },
            "node2": {
                "ansible_user": "other",
                "ansible_password": SECRET + "-extra",
                "ansible_port": 2222,
            },
        }
        with (
            patch.object(ansible_inventory, "resolve", return_value=resolved),
            patch.object(remote_catalog.client, "request", side_effect=self.lookup),
        ):
            remote_catalog.protect_sources(config)
            self.assertIn(self.file.name, config["protected_paths"])
            self.assertIn(
                "INVENTORY_REQUEST",
                execution_requests.instructions(remote_catalog.available(), run),
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
        with (
            patch(
                "taskrail.executor.worker.transport.execute",
                return_value=dict(
                    status="SUCCEEDED", exit_code=0, output=f"42% {SECRET} {SECRET}-extra"
                ),
            ) as execute,
            patch.object(threading.Thread, "start", lambda thread: thread.run()),
        ):
            receipt = self.lookup(pending)
            result = self.store.get(receipt["id"])
            self.assertEqual(result["status"], "SUCCEEDED")
            self.assertEqual(result[inventory.KEY], selection)
            self.assertEqual(self.lookup(pending), result)
            execute.assert_called_once()
            self.assertEqual(execute.call_args.args[0]["password"], SECRET)
        self.assertEqual(result["results"][0]["output"], "42% [REDACTED] [REDACTED]")
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
        with patch("taskrail.executor.worker.launch", return_value={"status": "RUNNING"}) as launch:
            self.assertEqual(client.request(payload, address)["status"], "RUNNING")
            self.store.recover()
            alternate.unlink()
            self.assertEqual(client.request(payload, address)["status"], "UNKNOWN")
            with self.assertRaisesRegex(inventory.InventoryError, "unavailable"):
                client.request(dict(payload, key="new"), address)
            launch.assert_called_once()
        with self.assertRaises(ValueError):
            inventory_lookup.source(config, dict(lookup, path=str(self.file)))
        self.assertIn("unavailable", remote_catalog.available({}))

    def test_changed_inventory_returns_feedback_before_any_ssh_connection(self):
        selection = inventory_file.pin(inventory.selector(str(self.file), "k8s"))
        payload = dict(execution_wait.ssh_request(ACTION, selection), key="project")
        self.file.write_text(FIXTURE.replace("192.0.2.17", "192.0.2.21"))
        pending = {"request": payload}
        with (
            patch.object(remote_catalog.client, "request", side_effect=self.lookup),
            patch.object(threading.Thread, "start") as worker,
        ):
            execution_wait.observe(pending)
            self.assertEqual(pending["status"], "REJECTED")
            self.assertIn("changed", pending["inventory_error"])
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
        self.assertCountEqual(
            config["protected_paths"], [self.file.name, "second cluster/another.yml"]
        )

    def test_checkout_index_and_head_secrets_are_masked_before_capture_and_in_children(self):
        repo = self.base / "project"
        inventories = repo / "inventories"
        inventories.mkdir(parents=True)
        role = repo / "roles/service/tasks/main.yaml"
        role.parent.mkdir(parents=True)
        role.write_text("- name: Public task\n")
        committed, staged, working = (
            inventories / f"{name}.yaml" for name in ("main", "staged", "working")
        )
        clean = "all: {}\n"
        committed.write_text(FIXTURE)
        staged.write_text(clean)
        working.write_text(clean)
        process.checked(repo, ["init"])
        process.checked(repo, ["add", "."])
        process.checked(
            repo,
            [
                "-c",
                "user.name=Test",
                "-c",
                "user.email=t@example.invalid",
                "commit",
                "-m",
                "Initial",
            ],
        )
        committed.write_text(clean)
        staged.write_text(FIXTURE)
        process.checked(repo, ["add", "."])
        staged.write_text(clean)
        working.write_text(f"ansible_become_password: {SECRET}\n")
        task = self.base / "task.md"
        settings = self.base / "settings.json"
        settings.write_text(
            json.dumps({"opencode_version": "1.x", "worktree_base": str(self.base / "trees")})
        )
        header = json.dumps({"roots": {"repo": str(repo)}})
        task.write_text(
            f"```taskrail-task\n{header}\n```\n## Goal\nInspect {committed}, {staged} and {working}."
        )
        config = task_config.configuration(task, settings)
        run = self.base / "run"
        with patch.object(remote_catalog.client, "request", side_effect=ConnectionRefusedError):
            run_setup.open_state(config, run, dict(resume=False, plan_response=None), True)
        masks = protected_paths.patterns(config)
        target = config["roots"]["repo"]
        snapshot = run / "00-input/original"
        rows = [
            json.loads(line) for line in (snapshot / "status.jsonl").read_text().splitlines()[1:]
        ]
        self.assertEqual(
            {row["path"] for row in rows},
            {str(path.relative_to(repo)) for path in (committed, staged, working)},
        )
        self.assertTrue(all(row.get("unavailable") == "protected path" for row in rows))
        self.assertFalse((snapshot / "repo").exists())
        self.assertTrue(protected_paths.matches(target / "inventories/main.yaml", masks))
        self.assertFalse(protected_paths.matches(target / role.relative_to(repo), masks))
        frozen = json.loads((run / "00-input/settings.json").read_text())
        task.write_text(f"```taskrail-task\n{header}\n```\n## Goal\nSummarize the findings.")
        child = task_config.configuration(task, settings, checks_override=frozen)
        self.assertEqual(protected_paths.patterns(child), masks)

    def test_incomplete_or_failed_read_is_a_recoverable_inventory_refusal(self):
        selection = inventory_file.pin(inventory.selector(str(self.file), "k8s"))
        wire = dict(execution_wait.ssh_request(ACTION, selection), key="read")
        for outcome in (b"all: {}\n", OSError("fixture")):
            with (
                self.subTest(outcome=outcome),
                patch("os.pread", side_effect=[outcome]),
                patch.object(threading.Thread, "start") as start,
                self.assertRaisesRegex(inventory.InventoryError, "Repeat the lookup"),
            ):
                self.lookup(wire)
            start.assert_not_called()
        self.assertFalse(list(self.store.directory.iterdir()))

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

    def test_whole_group_runs_one_agent_chosen_script_without_batching(self):
        group = {f"worker-{number}": {} for number in range(50)}
        settings = {"ansible_user": "operator", "ansible_password": SECRET}
        fixture = json.dumps({"k8s": {"hosts": group, "vars": settings}}).encode()
        script = "kubectl get nodes | sort; ceph status"
        action = dict(targets="all", script=script, reason="Inspect cluster", files={})
        with (
            patch.object(inventory, "read", return_value=fixture),
            patch.object(threading.Thread, "start", lambda thread: thread.run()),
            patch(
                "taskrail.executor.worker.transport.execute",
                return_value=dict(status="SUCCEEDED", exit_code=0, output="ok"),
            ) as execute,
        ):
            receipt = self.lookup(
                dict(execution_wait.ssh_request(action, SELECTION), key="whole-group")
            )
            result = self.store.get(receipt["id"])
        self.assertEqual(result["status"], "SUCCEEDED")
        self.assertEqual(execute.call_count, len(group))
        self.assertCountEqual([row["target"] for row in result["results"]], group)
        self.assertTrue(all(call.args[1]["script"] == script for call in execute.call_args_list))

    def test_rejects_unknown_hosts_and_malformed_inventory(self):
        wire = dict(
            execution_wait.ssh_request(dict(ACTION, targets=["other-node"]), SELECTION),
            key="test-ticket",
        )
        with self.assertRaises(inventory.InventoryError):
            self.lookup(wire)
        for filename in ("../cluster.yaml", "/etc/shadow", "bad.yaml"):
            if filename == "bad.yaml":
                (self.base / filename).symlink_to(self.file)
            with self.subTest(filename=filename), self.assertRaises(ValueError):
                inventory.load(dict(SELECTION, file=filename))
        for body, group, message in (
            (FIXTURE, "missing", "selected group is absent"),
            ("k8s: [" + SECRET, "k8s", "Invalid static YAML"),
            ("k8s: {hosts: [" + SECRET + "]}", "k8s", "mapping for hosts"),
            ("k8s: {" + SECRET + ": {}}", "k8s", "only hosts, vars and children"),
            (FIXTURE.replace(SECRET, "{{ lookup() }}"), "k8s", "Invalid static YAML"),
            (
                FIXTURE.replace(
                    "ansible_user:", "ansible_group_priority: invalid\n    ansible_user:", 1
                ),
                "k8s",
                "ansible_group_priority must be an integer",
            ),
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
            self.assertIn(message, failures.getvalue())
            self.assertNotIn(SECRET, failures.getvalue())
        with patch.object(
            remote_catalog.client, "request", return_value={"hosts": {"other-node": {}}}
        ):
            self.assertEqual(
                remote_catalog.available(SELECTION)["unavailable"], "routes.ssh.update"
            )

    def test_discovery_explains_connection_failures_without_disclosing_yaml_values(self):
        login = {"ansible_user": "operator", "ansible_password": SECRET}
        for settings, detail in (
            ({"ansible_password": SECRET}, "Missing ansible_user"),
            ({"ansible_user": SECRET}, "Missing ansible_password"),
            (dict(login, ansible_password=None), "Missing ansible_password"),
            (dict(login, ansible_connection=SECRET), "ansible_connection"),
            (dict(login, ansible_ssh_common_args=SECRET), "ansible_ssh_common_args"),
            (
                dict(login, ansible_password="{{ " + SECRET + " }}"),
                "ansible_password must be literal",
            ),
            (dict(login, ansible_port=SECRET), "SSH port"),
            (dict(login, ansible_host=[SECRET]), "SSH hostname"),
            (dict(login, ansible_user=[SECRET]), "SSH username"),
            (dict(login, ansible_password=[SECRET]), "SSH password"),
        ):
            fixture = {
                "k8s": {
                    "hosts": {"first": login},
                    "children": {"workers": {"vars": settings, "hosts": {"second": None}}},
                }
            }
            with (
                self.subTest(detail=detail),
                patch.object(inventory, "read", return_value=json.dumps(fixture).encode()),
                patch.object(remote_catalog.client, "request", side_effect=self.lookup),
                patch.object(threading.Thread, "start") as start,
            ):
                message = remote_catalog.unavailable(remote_catalog.available(SELECTION))
                self.assertIn("Selected host #2:", message)
                self.assertIn(detail, message)
                self.assertIn("SSH executor did not connect", message)
                self.assertNotIn(SECRET, message)
                start.assert_not_called()
