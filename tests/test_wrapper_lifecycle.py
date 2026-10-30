"""Configured wrapper prefixes and credential policy survive the complete CLI lifecycle."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from test_opencode import FAKE_OPENCODE_2

from taskrail.infrastructure import opencode_api, opencode_serve, runner
from taskrail.infrastructure.permission_check import verify_launch

WRAPPER = """import json, os, sys
from pathlib import Path
assert sys.argv[1:3] == ['--profile', 'work profile']
assert os.environ.get('WRAPPER_TOKEN') == 'allowed'
assert 'HOST_SECRET_TOKEN' not in os.environ
assert os.environ['OPENCODE_DISABLE_AUTOUPDATE'] == 'true'
args = sys.argv[5:]
record = dict(args=args, cwd=os.getcwd(), compact=os.environ.get('OPENCODE_DISABLE_AUTOCOMPACT'))
with Path(os.environ['FAKE_STATE']).joinpath('wrapper.jsonl').open('a') as stream:
    stream.write(json.dumps(record) + '\\n')
if args == ['--version']:
    print('nga ' + ('1.19.3' if sys.argv[3] == '1.x' else '2.0.30'))
    sys.exit(0)
os.execv(sys.executable, [sys.executable, sys.argv[4], *args])
"""

ONE_X = """import json, os, sys, time
args = sys.argv[1:]
if args == ['run', '--help']:
    print('run --attach --session --file')
    sys.exit(0)
if args == ['agent', 'list']:
    print('managed (primary)')
    print(json.dumps([dict(permission='*', pattern='*', action='deny')]))
    sys.exit(0)
if args[0] == 'serve':
    assert os.environ['OPENCODE_SERVER_PASSWORD']
    print('opencode server listening on http://127.0.0.1:4321', flush=True)
    time.sleep(60)
assert args[0] == 'run' and args[args.index('--attach') + 1] == 'http://127.0.0.1:4321', args
assert os.environ['OPENCODE_SERVER_PASSWORD']
if os.environ.get('WRAPPER_GATEWAY'):
    print(json.dumps(dict(type='error', sessionID='session', error=dict(name='APIError', data=dict(message='Retries exhausted')))))
    sys.exit(0)
continued = '--session' in args
prefix = 'second' if continued else 'first'
if continued:
    assert args[args.index('--session') + 1] == 'session'
reply = 'DONE' if continued else json.dumps(dict(status='GIT_REQUEST', argv=['status']))
print(json.dumps(dict(type='text', sessionID='session', part=dict(id=prefix+'t', messageID=prefix, text=reply))))
print(json.dumps(dict(type='step_finish', sessionID='session', part=dict(id=prefix+'f', messageID=prefix, reason='stop', tokens=dict(input=int(os.environ.get('WRAPPER_INPUT', '10')), output=2, cache=dict(read=5, write=0))))))
"""


class WrapperLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.wrapper = self.root / "nga.py"
        self.wrapper.write_text(WRAPPER)
        self.prompt = self.root / "request.md"
        self.prompt.write_text("Inspect the task")
        environment = patch.dict(
            os.environ,
            dict(WRAPPER_TOKEN="allowed", HOST_SECRET_TOKEN="hidden", FAKE_STATE=str(self.root)),
        )
        environment.start()
        self.addCleanup(environment.stop)

    def command(self, version):
        target = self.root / "target.py"
        target.write_text(ONE_X if version == "1.x" else FAKE_OPENCODE_2)
        prefix = [
            sys.executable,
            str(self.wrapper),
            "--profile",
            "work profile",
            version,
            str(target),
        ]
        self.assertEqual(opencode_api.select("auto", prefix, ("WRAPPER_TOKEN",)), version)
        return opencode_api.launch_command(prefix, version)

    def launch(self, command, server, session=None):
        return runner.run_agent(
            dict(
                command=command,
                workspace=self.root,
                agent="managed",
                model=None,
                prompt=self.prompt,
                attempt=self.root / "attempt",
                timeout=10,
                runtime=dict(
                    env_allow=("WRAPPER_TOKEN",),
                    attachment=server.attachment(),
                    session_id=session,
                    context_budget=10000,
                ),
            )
        )

    def test_one_x_wrapper_keeps_credentials_prefix_and_session_for_executor_continuation(self):
        command = self.command("1.x")
        expected = [dict(permission="*", pattern="*", action="deny")]
        verify_launch(
            dict(command=command, agent_env_allow=("WRAPPER_TOKEN",)),
            self.root,
            "managed",
            expected,
            self.root / "permissions.log",
        )
        with opencode_api.stage_server(command, self.root, ("WRAPPER_TOKEN",), False) as server:
            first = self.launch(command, server)
            self.assertEqual(json.loads(first["final_text"])["status"], "GIT_REQUEST")
            self.prompt.write_text("Git executor completed; continue")
            second = self.launch(command, server, first["sessions"][0])
            self.assertEqual(second["status"], "OK", second)
            self.assertEqual(second["final_text"], "DONE")
        records = self.records()
        self.assertEqual(sum(record["args"][0] == "serve" for record in records), 1)
        self.assertTrue(any(record["args"] == ["run", "--help"] for record in records))
        self.assertTrue(any("--session" in record["args"] for record in records))

    def test_two_x_wrapper_keeps_its_environment_through_adapter_api_server_and_client(self):
        command = self.command("2.x")
        expected = [
            dict(permission="*", pattern="*", action="deny"),
            dict(permission="bash", pattern="*", action="deny"),
        ]
        verify_launch(
            dict(command=command, agent_env_allow=("WRAPPER_TOKEN",)),
            self.root,
            "managed",
            expected,
            self.root / "permissions.log",
        )
        with opencode_api.stage_server(command, self.root, ("WRAPPER_TOKEN",), False) as server:
            result = self.launch(command, server)
            self.assertEqual(result["status"], "OK", result)
            self.assertEqual(result["tokens"]["total"], 17)
        operations = {record["args"][0] for record in self.records()}
        self.assertLessEqual({"--version", "serve", "api", "run"}, operations)

    def test_gateway_and_reported_context_failures_keep_their_original_status(self):
        command = self.command("1.x")
        with opencode_api.stage_server(command, self.root, ("WRAPPER_TOKEN",), False) as server:
            with patch.dict(os.environ, WRAPPER_GATEWAY="1"):
                failure = self.launch(command, server)
            self.assertEqual(failure["status"], "TOOL_ERROR")
            self.assertIn("Retries exhausted", failure["errors"][0])
            with patch.dict(os.environ, WRAPPER_INPUT="20000"):
                failure = self.launch(command, server)
            self.assertEqual(failure["status"], "CONTEXT_EXCEEDED")

    def test_failed_help_probe_never_silently_disables_stage_session_support(self):
        command = self.command("1.x")
        for failure in (
            subprocess.CompletedProcess(command, 7, "--attach", "failure"),
            subprocess.TimeoutExpired(command, 30),
            OSError("missing"),
        ):
            with self.subTest(failure=failure):
                options = (
                    dict(side_effect=failure)
                    if isinstance(failure, Exception)
                    else dict(return_value=failure)
                )
                with (
                    patch.object(opencode_serve.subprocess, "run", **options),
                    self.assertRaisesRegex(ValueError, "probe|failed"),
                ):
                    opencode_api.stage_server(command, self.root, ("WRAPPER_TOKEN",))

    def records(self):
        return [json.loads(line) for line in (self.root / "wrapper.jsonl").read_text().splitlines()]


if __name__ == "__main__":
    unittest.main()
