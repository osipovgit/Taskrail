"""Use the project's Ansible to resolve inventory sources without connecting to a server."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from git_fixture import repository

from taskrail.application import ansible_inventory, inventory_inputs, remote_catalog, run_setup
from taskrail.application.task_config import configuration
from taskrail.core.files import atomic_json
from taskrail.executor import inventory, inventory_file
from taskrail.executor.service import ExecutorServer
from taskrail.executor.store import TicketStore
from taskrail.interactions import inventory_lookup

SECRET = "private-fixture-password"
FIXTURES = Path(__file__).with_name("fixtures") / "ansible-inventory"


class ProjectInventoryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.server = ExecutorServer(
            str(self.root / "executor.sock"), 1200, {}, TicketStore(self.root / "tickets")
        )
        self.addCleanup(self.server.server_close)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"ANSIBLE_HOME": str(self.root / "home")}).start()
        os.environ.pop("ANSIBLE_CONFIG", None)
        patch.object(remote_catalog.client, "request", side_effect=self.dispatch).start()

    def dispatch(self, payload):
        selected = payload.get(inventory.KEY, {})
        if selected and not selected.get("directory"):
            with inventory_file.opened(selected["file"]) as stream:
                return self.server.dispatch(payload, 1200, stream.fileno())
        return self.server.dispatch(payload, 1200)

    def discover(self, path, group):
        return remote_catalog.discover(inventory_file.pin(inventory.selector(str(path), group)))

    def group_vars(self, inventory_dir, group):
        variables = inventory_dir / "group_vars"
        variables.mkdir()
        shutil.copyfile(FIXTURES / "group-vars.yml", variables / f"{group}.yml")

    @unittest.skipUnless(shutil.which("ansible-inventory"), "requires the project Ansible CLI")
    def test_yaml_user_fields_and_explicit_source_win_over_environment_defaults(self):
        source = self.root / "datacenter.yaml"
        shutil.copyfile(FIXTURES / source.name, source)
        config = self.root / "custom.cfg"
        config.write_text("[defaults]\nremote_user=other-user\nremote_port=2222\n")
        with patch.dict(
            os.environ, {"ANSIBLE_CONFIG": str(config), "ANSIBLE_INVENTORY": "other.ini"}
        ):
            catalog = self.discover(source, "compute")
        self.assertEqual(
            catalog["hosts"],
            {"worker26": {"hostname": "192.0.2.26", "username": "operator", "port": 2222}},
        )
        self.assertNotIn(SECRET, json.dumps(catalog))

    @unittest.skipUnless(shutil.which("ansible-inventory"), "requires the project Ansible CLI")
    def test_native_ini_directory_with_range_external_vars_and_colocated_config(self):
        source = self.root / "inventories"
        source.mkdir()
        (source / "workers.ini").write_text(
            "[compute]\nworker[01:02]\n\n[cluster:children]\ncompute\n\n[elsewhere]\nother\n"
        )
        # A config in the inventory directory takes effect even without exports from a login shell.
        (source / "ansible.cfg").write_text("[defaults]\nremote_user=operator\n")
        self.group_vars(source, "cluster")
        catalog = self.discover(source, "cluster")
        self.assertEqual(set(catalog["hosts"]), {"worker01", "worker02"}, catalog)
        self.assertEqual(catalog["hosts"]["worker02"]["username"], "operator")
        self.assertNotIn(SECRET, json.dumps(catalog))
        self.assertEqual(remote_catalog.available(catalog[inventory.KEY]), catalog)

    @unittest.skipUnless(shutil.which("ansible-inventory"), "requires the project Ansible CLI")
    def test_dynamic_source_runs_once_per_discovery_and_old_targets_cannot_be_reused(self):
        source = self.root / "discover"
        listing = {
            "_meta": {"hostvars": {"node1": {"ansible_user": "operator"}}},
            "workers": {"hosts": ["node1"]},
        }
        data = self.root / "data.json"
        data.write_text(json.dumps(listing))
        self.group_vars(self.root, "workers")
        source.write_text("#!/bin/sh\necho run >> calls\ncat data.json\n")
        source.chmod(0o700)
        first = self.discover(source, "workers")
        binding = first[inventory.KEY]
        self.assertEqual(set(first["hosts"]), {"node1"})
        self.assertNotIn(SECRET, json.dumps(first))
        forged = dict(binding, directory=True)
        del forged["sha256"]
        self.assertIn("changed", remote_catalog.available(forged)["detail"])
        for _ in range(2):
            self.assertEqual(remote_catalog.available(binding), first)
        payload = {
            "operation": "run-ssh",
            inventory.KEY: binding,
            "key": "test",
            "action": {"targets": "all", "script": "uptime", "files": {}, "reason": "Collect load"},
        }
        with patch("taskrail.executor.worker.launch", return_value={"status": "RUNNING"}) as launch:
            self.dispatch(payload)
            result = self.dispatch(payload)
            self.assertNotIn(SECRET, json.dumps(result))
            self.assertEqual(launch.call_count, 1)
        self.assertEqual((self.root / "calls").read_text(), "run\n")
        listing["_meta"]["hostvars"]["node1"]["ansible_host"] = "192.0.2.10"
        data.write_text(json.dumps(listing))
        second = self.discover(source, "workers")
        self.assertNotEqual(binding, second[inventory.KEY])
        self.assertIn("changed", remote_catalog.available(binding)["detail"])
        self.assertEqual((self.root / "calls").read_text(), "run\nrun\n")
        self.assertEqual(self.dispatch(payload)["id"], result["id"])

    @unittest.skipUnless(shutil.which("ansible-inventory"), "requires the project Ansible CLI")
    def test_configured_jump_host_cannot_silently_become_a_direct_connection(self):
        source = self.root / "hosts.ini"
        shutil.copyfile(FIXTURES / source.name, source)
        (self.root / "ansible.cfg").write_text(
            "[ssh_connection]\nssh_common_args=-o ProxyJump=private-jump\n"
        )
        result = self.discover(source, "workers")
        self.assertIn("ansible_ssh_common_args", result["detail"])
        self.assertNotIn("private-jump", json.dumps(result))

    def test_run_uses_named_original_source_across_worktrees(self):
        original = self.root / "original"
        working = self.root / "worktree"
        for checkout in (original, working):
            checkout.mkdir()
            (checkout / "hosts.ini").write_text("[workers]\nnode1\n")
        config = {
            "roots": {"repo": working},
            "worktrees": {"repo": {"source": str(original), "worktree": str(working)}},
            "task_spec": {"fields": [{"text": "Inspect hosts.ini."}]},
        }
        inventory_inputs.capture(config)
        selection = inventory_lookup.source(
            config, {"path": str(working / "hosts.ini"), "group": "workers"}
        )
        with patch.object(remote_catalog, "discover", return_value={}) as native:
            self.assertEqual(inventory_lookup.discover(config, selection), {})
            native.assert_called_once_with(selection)
            self.assertEqual(selection["file"], str(original / "hosts.ini"))
            unselected = dict(selection, file=str(original / "other"))
            self.assertIn("unavailable", inventory_lookup.discover(config, unselected))
            self.assertEqual(native.call_count, 1)

    @unittest.skipUnless(shutil.which("ansible-inventory"), "requires the project Ansible CLI")
    def test_followup_resolves_operator_sources_with_ansible_and_masks_them_again(self):
        repo = self.root / "repo"
        repo.mkdir()
        source = repo / "cluster.yaml"
        source.write_text(
            "workers:\n  become: true\n  ansible_python_interpreter: /usr/bin/python3\n"
            "  hosts:\n    worker15: {ansible_user: operator, ansible_password: fixture}\n"
        )
        (repo / "other.ini").touch()
        (repo / "unselected.ini").touch()
        repository(repo)
        settings = self.root / "settings.json"
        atomic_json(settings, dict(opencode_version="1.x", worktree_base=str(self.root / "trees")))
        options = dict(resume=False, plan_response=None)
        parent = self.root / "original"
        task = self.root / "task.md"
        header = json.dumps({"roots": {"repo": str(repo)}, "read_only": True})
        task.write_text(f"```taskrail-task\n{header}\n```\nInspect workers in cluster.yaml.")
        state = run_setup.open_state(configuration(task, settings), parent, options, True)
        atomic_json(parent / "run.json", dict(state, status="NO_CHANGES_REQUIRED"))

        reply = self.root / ".submissions" / "reply"
        reply.mkdir(parents=True)
        atomic_json(
            reply / "launch.json",
            dict(
                id="reply",
                launch_id="reply",
                execution_parent=parent.name,
                submission_mode="followup",
                resume=False,
            ),
        )
        header = json.dumps({"roots": state["roots"], "read_only": True})
        task = reply / "task.md"
        task.write_text(
            f"```taskrail-task\n{header}\n```\nInspect worker15. Also consider other.ini."
            '\n## Conversation history\n[{"summary":"Use unselected.ini"}]'
        )
        config = configuration(task, settings)
        state = run_setup.open_state(config, self.root / "reply", options, True)
        self.assertCountEqual(config[inventory_inputs.KEY], map(str, (source, repo / "other.ini")))
        self.assertNotIn(inventory.KEY, state)
        self.assertIn("cluster.yaml", config["protected_paths"])
        worktree = Path(state["roots"]["repo"])
        selection = inventory_lookup.source(
            config, {"path": str(worktree / source.name), "group": "workers"}
        )
        self.assertEqual(selection["file"], str(source))
        catalog = inventory_lookup.discover(config, selection)
        self.assertEqual(set(catalog["hosts"]), {"worker15"}, catalog)

    def test_credentials_in_named_ini_and_external_vars_are_masked_before_planning(self):
        source = self.root / "hosts.ini"
        shutil.copyfile(FIXTURES / source.name, source)
        (self.root / "group_vars").mkdir()
        config = {
            "roots": {"repo": self.root},
            "protected_paths": [],
            "task_spec": {"fields": [{"text": f"Inspect `{source}`."}]},
        }
        remote_catalog.protect_sources(config)
        self.assertIn("hosts.ini", config["protected_paths"])
        self.assertIn("group_vars/*", config["protected_paths"])
        self.assertNotIn(SECRET, str(config))

    def test_removed_inventory_directory_keeps_its_worktree_copy_protected(self):
        original = self.root / "original"
        original.mkdir()
        checkout = self.root / "worktree"
        inventory_dir = checkout / "inventories"
        inventory_dir.mkdir(parents=True)
        shutil.copyfile(FIXTURES / "hosts.ini", inventory_dir / "workers.ini")
        self.group_vars(inventory_dir, "workers")
        config = dict(
            roots={"repo": checkout},
            worktrees={"repo": dict(source=str(original), worktree=str(checkout))},
            protected_paths=[],
        )
        remote_catalog.protect_sources(
            config, {"inventory_inputs": [str(original / "inventories")]}
        )
        self.assertIn("inventories/workers.ini", config["protected_paths"])
        self.assertIn("inventories/group_vars/*", config["protected_paths"])
        with self.assertRaises(FileNotFoundError):
            inventory_lookup.source(config, {"path": str(inventory_dir), "group": "workers"})

    def test_native_process_diagnostics_never_quote_credentials(self):
        source = self.root / "hosts.ini"
        source.touch()
        with patch.object(ansible_inventory.subprocess, "run") as execute:
            execute.return_value.returncode = 17
            execute.return_value.stderr = SECRET.encode()
            feedback = self.discover(source, "workers")
        self.assertIn("exited with code 17", feedback["detail"])
        self.assertNotIn(SECRET, json.dumps(feedback))
