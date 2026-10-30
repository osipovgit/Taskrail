"""Local commands run without a decision inside the bubblewrap sandbox."""

import json
import os
import sys
import tempfile
import unittest
import venv
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from live_fixture import LiveFixture
from test_sandbox_mounts import SECRETS

from taskrail.application import check_runner
from taskrail.application.live import execute_task
from taskrail.core import protected_paths
from taskrail.infrastructure import sandbox, sandbox_mounts, sandbox_paths, socket_filter
from taskrail.interactions import approval_policy, local, local_journal, local_route, local_sandbox

PROBE = r"""
import os, socket
def attempt(name, action):
    try:
        action()
        print(name, "ok")
    except OSError as error:
        print(name, "refused", error.errno)
attempt("network", lambda: socket.create_connection(("192.0.2.1", 9), timeout=1))
attempt("local", lambda: socket.socket(socket.AF_UNIX).close())
attempt("keys", lambda: os.listdir(os.path.expanduser("~/.ssh")))
attempt("visible", lambda: os.listdir(os.path.expanduser("~/projects")))
attempt("secret", lambda: open(".env").read())
attempt("write", lambda: open("made.txt", "w").write("x"))
attempt("metadata", lambda: open(".git/made", "w").write("x"))
"""
AVAILABLE = sandbox.mode() is not None
PROTECTED = protected_paths.DEFAULT_PATTERNS


def request(**fields):
    payload = dict(schema_version=1, status="LOCAL_REQUEST", cwd="/r", argv=["ls"], reason="x")
    return dict(payload, **fields)


class SandboxSetupTests(unittest.TestCase):
    def setUp(self):
        for cached in (sandbox.mode, sandbox.attempts, sandbox.overlays):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)

    def test_probing_prefers_a_network_namespace_then_a_socket_filter(self):
        refused = SimpleNamespace(returncode=1, stderr="bwrap: loopback: Failed RTM_NEWADDR\n")
        outcomes = [refused, SimpleNamespace(returncode=0, stderr="")]
        with (
            patch.object(sandbox, "executable", return_value="/usr/bin/bwrap"),
            patch.object(sandbox.subprocess, "run", side_effect=outcomes) as probed,
        ):
            self.assertEqual(sandbox.mode(), sandbox.SOCKET_FILTER)
        first, second = (call.args[0] for call in probed.call_args_list)
        self.assertIn("--unshare-net", first)
        self.assertIn("--seccomp", second)
        self.assertEqual(sandbox.attempts()[0][1], "bwrap: loopback: Failed RTM_NEWADDR")

    def test_without_bubblewrap_or_a_working_probe_nothing_is_sandboxed(self):
        with patch.object(sandbox, "executable", return_value=None):
            self.assertIsNone(sandbox.mode())
        self.assertIn("bwrap not found", sandbox.health()[1])
        for cached in (sandbox.mode, sandbox.attempts):
            cached.cache_clear()
        failed = SimpleNamespace(
            returncode=1, stderr="bwrap: setting up uid map: Permission denied"
        )
        with (
            patch.object(sandbox, "executable", return_value="/usr/bin/bwrap"),
            patch.object(sandbox.subprocess, "run", return_value=failed),
        ):
            self.assertIsNone(sandbox.mode())
            line = sandbox.health()[1]
        self.assertIn("waits for approval", line)
        self.assertIn("socket filter: bwrap: setting up uid map: Permission denied", line)

    def test_the_check_names_how_local_commands_run(self):
        with patch.object(sandbox, "mode", return_value=sandbox.SOCKET_FILTER):
            self.assertIn("socket filter", sandbox.health()[1])
        with patch.object(sandbox, "mode", return_value=None):
            self.assertIn("waits for approval", sandbox.health()[1])

    def test_the_socket_filter_exists_only_for_known_architectures(self):
        with patch.object(socket_filter.platform, "machine", return_value="x86_64"):
            self.assertEqual(len(socket_filter.program()), 12 * 8)
        with patch.object(socket_filter.platform, "machine", return_value="riscv64"):
            self.assertIsNone(socket_filter.program())

    def test_required_ci_sandbox_cannot_silently_skip(self):
        if os.environ.get("TASKRAIL_REQUIRE_SANDBOX") == "1":
            self.assertTrue(AVAILABLE, sandbox.health()[1])

    def test_home_shows_runtime_components_without_unrelated_home_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for name in (".ssh", ".config", "projects", ".local/bin", "envs/tool/bin"):
                (home / name).mkdir(parents=True)
            with patch.object(sandbox_mounts.Path, "home", return_value=home):
                options = sandbox_mounts.home()
                venv = sandbox_mounts.installation(str(home / "envs/tool/bin/python"))
                local_bin = sandbox_mounts.installation(str(home / ".local/bin/tool"))
        shown = set(options[3::3])
        self.assertNotIn(str(home / "projects"), shown)
        self.assertIn(str(home / ".local/bin"), shown)
        self.assertFalse({str(home / ".ssh"), str(home / ".config")} & shown)
        self.assertEqual(options[:2], ["--tmpfs", str(home)])
        self.assertEqual(venv[1], str(home / "envs/tool/bin"))
        self.assertEqual(local_bin[1], str(home / ".local/bin"))
        self.assertEqual(sandbox_mounts.installation("tool"), [])
        self.assertEqual(sandbox_paths.installation("/usr/bin/python3"), [])

    def test_roots_keep_git_metadata_read_only_and_hide_protected_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".git").mkdir()
            (root / ".env").write_text("TOKEN=1\n")
            reading = sandbox_mounts.project({"p": root}, False, PROTECTED, overlays=False)
            discarding = sandbox_mounts.project({"p": root}, False, PROTECTED, overlays=True)
            writing = sandbox_mounts.project({"p": root}, True, PROTECTED, overlays=True)
        self.assertEqual(reading[:3], ["--ro-bind", str(root), str(root)])
        self.assertEqual(discarding[:4], sandbox_mounts.discarded(str(root)))
        self.assertEqual(writing[:3], ["--bind", str(root), str(root)])
        self.assertIn(["--ro-bind", str(root / ".git"), str(root / ".git")], triples(writing))
        self.assertIn(["--ro-bind", "/dev/null", str(root / ".env")], triples(writing))


def triples(options):
    return [options[index : index + 3] for index in range(0, len(options), 3)]


@unittest.skipUnless(AVAILABLE, "needs a working bubblewrap")
class SandboxExecutionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.home = base / "home"
        (self.home / ".ssh").mkdir(parents=True)
        (self.home / "projects").mkdir()
        self.root = base / "root"
        (self.root / ".git").mkdir(parents=True)
        (self.root / ".env").write_text("TOKEN=1\n")
        patcher = patch.dict(os.environ, HOME=str(self.home))
        patcher.start()
        self.addCleanup(patcher.stop)

    def probe(self, writes, kind=None):
        context = dict(roots={"p": self.root}, run=self.root, timeout=30)
        context[local_sandbox.WRITES] = writes
        payload = request(cwd=str(self.root), argv=[sys.executable, "-c", PROBE])
        with patch.object(sandbox, "mode", return_value=kind or sandbox.mode()):
            outcome = local.execute(payload, context)
        self.assertEqual(outcome["exit_code"], 0, outcome["stderr"])
        return dict(line.split(" ", 1) for line in outcome["stdout"].splitlines())

    def test_a_reading_stage_reaches_no_network_secrets_or_roots(self):
        seen = self.probe(writes=False)
        self.assertTrue(seen["network"].startswith("refused"))
        self.assertTrue(seen["keys"].startswith("refused"))
        self.assertTrue(seen["visible"].startswith("refused"))
        self.assertTrue(seen["secret"].startswith("refused"))
        self.assertTrue(seen["metadata"].startswith("refused"))
        self.assertFalse((self.root / "made.txt").exists())

    def test_the_implementer_writes_its_roots_but_not_git_metadata(self):
        seen = self.probe(writes=True)
        self.assertEqual(seen["write"], "ok")
        self.assertTrue((self.root / "made.txt").exists())
        self.assertTrue(seen["metadata"].startswith("refused"))

    def test_mounted_caches_cannot_reveal_synthetic_credentials(self):
        for name in SECRETS:
            secret = self.home / name
            secret.parent.mkdir(parents=True, exist_ok=True)
            secret.write_text("DUMMY_ONLY")
        script = (
            "from pathlib import Path\n"
            f"paths = {list(SECRETS)!r}\n"
            "for name in paths:\n"
            "    try:\n"
            "        assert 'DUMMY_ONLY' not in (Path.home() / name).read_text(), name\n"
            "    except OSError:\n"
            "        pass\n"
        )
        context = dict(roots={"p": self.root}, run=self.root, timeout=30)
        context[local_sandbox.WRITES] = False
        outcome = local.execute(
            request(cwd=str(self.root), argv=[sys.executable, "-c", script]), context
        )
        self.assertEqual(outcome["exit_code"], 0, outcome["stderr"])

    def test_cache_symlink_binding_cannot_bypass_the_secret_mask(self):
        original = self.home / "runtime-cache"
        original.mkdir()
        (original / "auth.json").write_text("DUMMY_ONLY")
        (self.home / ".m2").mkdir()
        alias = self.home / ".m2/repository"
        alias.symlink_to(original, target_is_directory=True)
        script = (
            "from pathlib import Path\n"
            "try:\n"
            f"    assert 'DUMMY_ONLY' not in Path({str(alias / 'auth.json')!r}).read_text()\n"
            "except OSError:\n"
            "    pass\n"
        )
        context = dict(roots={"p": self.root}, run=self.root, timeout=30)
        context[local_sandbox.WRITES] = False
        outcome = local.execute(
            request(cwd=str(self.root), argv=[sys.executable, "-c", script]), context
        )
        self.assertEqual(outcome["exit_code"], 0, outcome["stderr"])

    def test_project_linter_config_is_visible_while_home_and_project_credentials_are_hidden(self):
        configuration = self.root / ".config"
        configuration.mkdir()
        (configuration / "ansible-lint.yml").write_text("profile: production\n")
        (configuration / "auth.json").write_text("DUMMY_ONLY")
        (configuration / "private.txt").write_text("DUMMY_ONLY")
        private = self.home / ".config/provider"
        private.mkdir(parents=True)
        (private / "settings.json").write_text("DUMMY_ONLY")
        (self.root / "home-config").symlink_to(private, target_is_directory=True)
        runtime = self.home / ".local/lib/tool/.config"
        runtime.mkdir(parents=True)
        (runtime / "settings.json").write_text("DUMMY_ONLY")
        secret_paths = [
            configuration / "auth.json",
            configuration / "private.txt",
            self.root / "home-config/settings.json",
            private / "settings.json",
            runtime / "settings.json",
        ]
        script = (
            "from pathlib import Path\n"
            "assert Path('.config/ansible-lint.yml').read_text() == 'profile: production\\n'\n"
            f"for name in {[str(path) for path in secret_paths]!r}:\n"
            "    try:\n"
            "        assert 'DUMMY_ONLY' not in Path(name).read_text(), name\n"
            "    except OSError:\n"
            "        pass\n"
        )
        context = dict(roots={"p": self.root}, run=self.root, timeout=30)
        context[local_sandbox.WRITES] = False
        context["config"] = dict(protected_paths=[".config/private.txt"])
        outcome = local.execute(
            request(cwd=str(self.root), argv=[sys.executable, "-c", script]), context
        )
        self.assertEqual(outcome["exit_code"], 0, outcome["stderr"])

    def test_an_installed_linter_virtualenv_runs_without_an_approval(self):
        prefix = self.home / "envs/linter"
        venv.create(prefix, symlinks=True)
        program = prefix / "bin/ansible-lint"
        program.write_text(f"#!{prefix}/bin/python\nimport sys\nprint(sys.prefix)\n")
        program.chmod(0o700)
        payload = request(cwd=str(self.root), argv=[str(program), "--version"])
        context = dict(roots={"p": self.root}, run=self.root, timeout=30)
        workflow = SimpleNamespace(run=self.root, state={}, config={})
        with patch("taskrail.interactions.approvals.wait") as asked:
            decision = check_runner.approve(workflow, payload, context)
            outcome = local.execute(payload, context)
        asked.assert_not_called()
        self.assertEqual(decision["rule"], approval_policy.SANDBOX)
        self.assertEqual(outcome["exit_code"], 0, outcome["stderr"])
        self.assertEqual(outcome["stdout"].strip(), str(prefix))

    def test_manager_shims_can_select_their_installed_runtime_without_credentials(self):
        managers = (
            (".pyenv", "libexec/pyenv", "version", "versions"),
            (".rbenv", "libexec/rbenv", "version", "versions"),
            (".asdf", "bin/asdf", "../.tool-versions", "installs/python"),
        )
        for name, backend, selector, versions in managers:
            with self.subTest(manager=name):
                directory = self.home / name
                tool = directory / versions / "fixture/bin/tool"
                tool.parent.mkdir(parents=True)
                tool.write_text("#!/bin/sh\nprintf 'managed tool\\n'\n")
                tool.chmod(0o700)
                chosen = directory / selector
                chosen.write_text("python fixture\n" if name == ".asdf" else "fixture\n")
                manager = directory / backend
                manager.parent.mkdir(parents=True)
                manager.write_text(
                    f"#!/bin/sh\nselected=$(awk '{{print $NF}}' \"{chosen}\")\n"
                    f'test ! -r "{directory}/credentials" || exit 9\n'
                    f'exec "{directory}/{versions}/$selected/bin/tool" "$@"\n'
                )
                manager.chmod(0o700)
                (directory / "credentials").write_text("DUMMY_ONLY")
                shim = directory / "shims/tool"
                shim.parent.mkdir()
                shim.write_text(f'#!/bin/sh\nexec "{manager}" "$@"\n')
                shim.chmod(0o700)
                context = dict(roots={"p": self.root}, run=self.root, timeout=30)
                context[local_sandbox.WRITES] = False
                outcome = local.execute(request(cwd=str(self.root), argv=[str(shim)]), context)
                self.assertEqual(outcome["exit_code"], 0, outcome["stderr"])
                self.assertEqual(outcome["stdout"], "managed tool\n")

    @unittest.skipIf(socket_filter.program() is None, "no socket filter for this architecture")
    def test_the_socket_filter_refuses_network_but_keeps_local_sockets(self):
        sandbox.overlays.cache_clear()
        self.addCleanup(sandbox.overlays.cache_clear)
        seen = self.probe(writes=False, kind=sandbox.SOCKET_FILTER)
        self.assertEqual(seen["network"], "refused 13")
        self.assertEqual(seen["local"], "ok")


class SandboxRouteTests(unittest.TestCase):
    def test_installed_ansible_lint_request_uses_the_sandbox_without_a_question(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            actions = SimpleNamespace(
                run=root,
                folder=root / "stage",
                session=SimpleNamespace(
                    environment=dict(roots={"p": root}), active=(None, dict(role="planner"))
                ),
            )
            payload = request(cwd=str(root), argv=["ansible-lint", "--version"])
            with (
                patch.object(sandbox, "mode", return_value=sandbox.NAMESPACE),
                patch("taskrail.interactions.local_request.missing_executable", return_value=None),
                patch.object(local_route, "executed", return_value="completed") as executed,
            ):
                self.assertEqual(local_route.without_decision(actions, payload), "completed")
            self.assertEqual(executed.call_args.args[2]["rule"], approval_policy.SANDBOX)

    def test_a_request_may_ask_for_the_host_and_is_then_another_action(self):
        on_host = local.extract(json.dumps(request(sandbox=False)))
        with patch.object(sandbox, "mode", return_value=sandbox.NAMESPACE):
            self.assertTrue(local_sandbox.sandboxed(request()))
            self.assertFalse(local_sandbox.sandboxed(on_host))
        with patch.object(sandbox, "mode", return_value=None):
            self.assertFalse(local_sandbox.sandboxed(request()))
        self.assertNotEqual(local_journal.signature(on_host), local_journal.signature(request()))
        with self.assertRaisesRegex(ValueError, "sandbox must be a boolean"):
            local.extract(json.dumps(request(sandbox="no")))

    def test_a_configured_check_runs_in_the_sandbox_without_a_decision(self):
        with tempfile.TemporaryDirectory() as directory:
            workflow = SimpleNamespace(run=Path(directory), state={}, config={})
            context = {}
            with (
                patch.object(sandbox, "mode", return_value=sandbox.NAMESPACE),
                patch.object(approval_policy.approvals, "wait") as asked,
            ):
                decision = check_runner.approve(workflow, request(), context)
        asked.assert_not_called()
        self.assertEqual(decision["rule"], approval_policy.SANDBOX)
        self.assertTrue(context[local_sandbox.WRITES])


@unittest.skipUnless(AVAILABLE, "needs a working bubblewrap")
class SandboxedRunTests(LiveFixture, unittest.TestCase):
    def test_a_planner_command_runs_without_a_decision_and_leaves_no_trace(self):
        self.real_repository()
        header = {"roots": {"project": str(self.root)}, "isolation": "in_place"}
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        self.configure_mode("local-effects")
        with patch("taskrail.interactions.approvals.wait") as asked:
            run, status = execute_task(self.task, self.settings, run_dir=self.base / "result")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        asked.assert_not_called()
        journal = json.loads((run / "local-actions.json").read_text())
        self.assertEqual(journal[0]["approval"]["rule"], approval_policy.SANDBOX)
        self.assertEqual(journal[0]["status"], "SUCCEEDED")
        self.assertNotIn("effects", journal[0])
        self.assertFalse((self.root / "notes.txt").exists())
        self.assertFalse((self.root / ".cache-tool").exists())


if __name__ == "__main__":
    unittest.main()
