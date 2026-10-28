"""Every turn of a 1.x stage runs on one private server, and sessions end before a full window."""

import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail.application import context_windows
from taskrail.application.attempt_retries import Retries
from taskrail.infrastructure import opencode_api, opencode_serve, runner, server_readiness

FAKE_CLI = """\
#!{python}
import os, sys, time
arguments = sys.argv[1:]
if arguments[:2] == ["run", "--help"]:
    print("{help}")
    sys.exit(0)
if arguments[:1] == ["serve"]:
    with open(os.environ["SERVE_LOG"], "w") as log:
        log.write(" ".join(arguments) + "\\n" + os.environ.get("OPENCODE_SERVER_PASSWORD", ""))
    print("opencode server listening on http://127.0.0.1:4321", flush=True)
    time.sleep(60)
"""


class StageServerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        opencode_serve.supported.cache_clear()
        self.addCleanup(opencode_serve.supported.cache_clear)

    def cli(self, help_text):
        script = self.base / "opencode"
        script.write_text(FAKE_CLI.format(python=sys.executable, help=help_text))
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        return [str(script)]

    def test_a_cli_with_attach_serves_the_whole_stage_behind_a_password(self):
        command = self.cli("--attach  attach to a running opencode server")
        log = self.base / "serve.log"
        with patch.dict(os.environ, SERVE_LOG=str(log)):
            with opencode_api.stage_server(command, self.base, ()) as server:
                attachment = server.attachment()
                arguments, password = log.read_text().split("\n")
                self.assertEqual(server.process.poll(), None)
            self.assertIsNotNone(server.process.poll())
        self.assertEqual(attachment[opencode_serve.ATTACH], "http://127.0.0.1:4321")
        self.assertEqual(attachment[opencode_serve.PASSWORD], password)
        self.assertGreater(len(password), 30)
        self.assertEqual(arguments, "serve --hostname 127.0.0.1 --port 0")

    def test_without_attach_or_when_disabled_each_turn_is_its_own_process(self):
        older = self.cli("--session  session id to continue")
        with opencode_api.stage_server(older, self.base, ()) as server:
            self.assertIsNone(server)
        current = self.cli("--attach")
        with opencode_api.stage_server(current, self.base, (), attach=False) as server:
            self.assertIsNone(server)

    def test_a_turn_attaches_to_the_stage_server(self):
        target = ("/w", "taskrail-implementer", ("/r/request.md",))
        attached = runner.arguments(target, False, "http://127.0.0.1:4321")
        self.assertEqual(attached[:2], ["--attach", "http://127.0.0.1:4321"])
        self.assertNotIn("--attach", runner.arguments(target, False))

    def test_readiness_accepts_a_listening_line_and_only_a_local_address(self):
        listening = b"opencode server listening on http://127.0.0.1:4096"
        self.assertEqual(server_readiness.address(listening), "http://127.0.0.1:4096")
        with self.assertRaises(ValueError):
            server_readiness.address(b"opencode server listening on http://example.com:80")
        self.assertEqual(
            server_readiness.address(json.dumps(dict(url="http://localhost:9")).encode()),
            "http://localhost:9",
        )


class ContextBoundaryTests(unittest.TestCase):
    def test_a_session_ends_between_ninety_and_ninety_five_percent_of_its_window(self):
        for window, reserve, boundary in (
            (94208, 8192, 86016),
            (32768, 8192, 29491),
            (200000, 8192, 190000),
        ):
            with self.subTest(window=window):
                config = dict(model_context_tokens=window, context_reserve_tokens=reserve)
                self.assertEqual(context_windows.capacity(config), boundary)


class WriterHandoffTests(unittest.TestCase):
    def retries(self, stage, retries=2):
        run = Path(tempfile.mkdtemp())
        self.addCleanup(subprocess.run, ["rm", "-rf", str(run)], check=False)
        (run / "03-implement").mkdir()
        (run / "03-implement/events.jsonl").write_text("")
        state = dict(
            stages=[dict(directory="03-implement")],
            changed_files=["project/hello.py"],
        )
        config = dict(read_retries=retries, roots={"project": Path("/repo")})
        workflow = SimpleNamespace(run=run, state=state, config=config, flow=dict(stage=stage))
        attempts = SimpleNamespace(
            workflow=workflow, request="REQUEST", format_only=False, recovery=None
        )
        with patch("taskrail.application.attempt_retries.access_recovery.restore") as access:
            access.return_value = SimpleNamespace(count=0)
            return Retries(attempts)

    def test_a_writer_that_filled_its_context_continues_in_a_fresh_session(self):
        retries = self.retries("implementer")
        with patch("taskrail.application.attempt_retries.evidence.load_index"):
            self.assertTrue(retries.allowed(dict(status="CONTEXT_EXCEEDED")))
            self.assertTrue(retries.allowed(dict(status="CONTEXT_EXCEEDED")))
            self.assertFalse(retries.allowed(dict(status="CONTEXT_EXCEEDED")))
        request = retries.attempts.request
        self.assertIn("FILLED ITS CONTEXT", request)
        self.assertIn("/repo/hello.py", request)
        self.assertEqual(request.count("FILLED ITS CONTEXT"), 1)

    def test_a_writer_is_never_retried_after_another_interruption(self):
        retries = self.retries("implementer")
        self.assertFalse(retries.allowed(dict(status="TIMEOUT")))
        self.assertEqual(retries.attempts.request, "REQUEST")


if __name__ == "__main__":
    unittest.main()
