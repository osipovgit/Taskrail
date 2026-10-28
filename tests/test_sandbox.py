"""Local commands run without a decision inside the bubblewrap sandbox."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from live_fixture import LiveFixture

from taskrail.application import check_runner
from taskrail.application.live import execute_task
from taskrail.infrastructure import sandbox, sandbox_mounts, socket_filter
from taskrail.interactions import approval_policy, local, local_journal, local_sandbox

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
PROTECTED = sandbox_mounts.protected_paths.DEFAULT_PATTERNS


def request(**fields):
    payload = dict(schema_version=1, status="LOCAL_REQUEST", cwd="/r", argv=["ls"], reason="x")
    return dict(payload, **fields)


class SandboxSetupTests(unittest.TestCase):
    def setUp(self):
        for cached in (sandbox.mode, sandbox.overlays):
            cached.cache_clear()
            self.addCleanup(cached.cache_clear)

    def test_probing_prefers_a_network_namespace_then_a_socket_filter(self):
        outcomes = [SimpleNamespace(returncode=1), SimpleNamespace(returncode=0)]
        with (
            patch.object(sandbox, "executable", return_value="/usr/bin/bwrap"),
            patch.object(sandbox.subprocess, "run", side_effect=outcomes) as probed,
        ):
            self.assertEqual(sandbox.mode(), sandbox.SOCKET_FILTER)
        first, second = (call.args[0] for call in probed.call_args_list)
        self.assertIn("--unshare-net", first)
        self.assertIn("--seccomp", second)

    def test_without_bubblewrap_or_a_working_probe_nothing_is_sandboxed(self):
        with patch.object(sandbox, "executable", return_value=None):
            self.assertIsNone(sandbox.mode())
        sandbox.mode.cache_clear()
        failed = SimpleNamespace(returncode=1)
        with (
            patch.object(sandbox, "executable", return_value="/usr/bin/bwrap"),
            patch.object(sandbox.subprocess, "run", return_value=failed),
        ):
            self.assertIsNone(sandbox.mode())

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

    def test_home_shows_visible_entries_toolchains_and_the_program_only(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            for name in (".ssh", ".config", "projects", ".local/share/opencode"):
                (home / name).mkdir(parents=True)
            with patch.object(sandbox_mounts.Path, "home", return_value=home):
                options = sandbox_mounts.home()
                venv = sandbox_mounts.installation(str(home / "envs/tool/bin/python"))
                local_bin = sandbox_mounts.installation(str(home / ".local/bin/tool"))
        shown = set(options[3::3])
        self.assertIn(str(home / "projects"), shown)
        self.assertIn(str(home / ".local/bin"), shown)
        self.assertFalse({str(home / ".ssh"), str(home / ".config")} & shown)
        self.assertEqual(options[:2], ["--tmpfs", str(home)])
        self.assertEqual(venv[1], str(home / "envs/tool"))
        self.assertEqual(local_bin[1], str(home / ".local/bin"))
        self.assertEqual(sandbox_mounts.installation("tool"), [])

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
        self.assertEqual(seen["visible"], "ok")
        self.assertTrue(seen["secret"].startswith("refused"))
        self.assertTrue(seen["metadata"].startswith("refused"))
        self.assertFalse((self.root / "made.txt").exists())

    def test_the_implementer_writes_its_roots_but_not_git_metadata(self):
        seen = self.probe(writes=True)
        self.assertEqual(seen["write"], "ok")
        self.assertTrue((self.root / "made.txt").exists())
        self.assertTrue(seen["metadata"].startswith("refused"))

    @unittest.skipIf(socket_filter.program() is None, "no socket filter for this architecture")
    def test_the_socket_filter_refuses_network_but_keeps_local_sockets(self):
        sandbox.overlays.cache_clear()
        self.addCleanup(sandbox.overlays.cache_clear)
        seen = self.probe(writes=False, kind=sandbox.SOCKET_FILTER)
        self.assertEqual(seen["network"], "refused 13")
        self.assertEqual(seen["local"], "ok")


class SandboxRouteTests(unittest.TestCase):
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
