import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taskrail.core import protected_paths
from taskrail.core.source_claims import matching_positions
from taskrail.infrastructure import (
    environment,
    opencode_api,
    opencode_cli,
    opencode_server,
    permission_check,
)
from taskrail.infrastructure.agent_profile import make_profile
from taskrail.infrastructure.agent_sync import launch_settings
from taskrail.infrastructure.event_summary import parse_events
from taskrail.infrastructure.opencode_events import EventTranslator
from taskrail.infrastructure.permission_check import verify_launch
from taskrail.infrastructure.profile_rules import permissions
from taskrail.infrastructure.runner import run_agent
from taskrail.interactions import provider_resume

RECORDER = """
import json, os, sys
from pathlib import Path
Path(os.environ["RECORD"]).write_text(json.dumps(dict(
    argv=sys.argv[1:], update=os.environ.get("OPENCODE_DISABLE_AUTOUPDATE")
)))
for event in (
    dict(type="text", sessionID="s", part=dict(id="t", messageID="m", text="done")),
    dict(type="step_finish", sessionID="s", part=dict(id="f", messageID="m", reason="stop")),
):
    print(json.dumps(event))
"""

FAKE_OPENCODE_2 = r"""
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
state = Path(os.environ["FAKE_STATE"])
if args[:1] == ["serve"]:
    (state / "serve-started").write_text("yes")
    print(json.dumps({"url": "http://127.0.0.1:9"}), flush=True)
    sys.stdin.read()
    sys.exit(0)
if args[:1] == ["api"]:
    calls = state / "api-calls"
    count = int(calls.read_text()) if calls.exists() else 0
    calls.write_text(str(count + 1))
    if not count and os.environ.get("FAKE_SLOW_API"):
        import time
        time.sleep(float(os.environ["FAKE_SLOW_API"]))
    rules = [
        {"action": "*", "resource": "*", "effect": "allow"},
        {"action": "*", "resource": "*", "effect": "deny"},
        {"action": "shell", "resource": "*", "effect": "deny"},
        {"action": "browser", "resource": "*", "effect": "deny"},
    ]
    agents = [{"id": "managed", "mode": "primary", "permissions": rules}]
    print(json.dumps({"data": agents if count else []}))
    sys.exit(0)
assert args[:3] == ["run", "--server", "http://127.0.0.1:9"], args
assert "--dir" not in args and os.environ["OPENCODE_PASSWORD"]
assert sys.stdin.read() == ""
(state / "run.json").write_text(json.dumps({"args": args, "pwd": os.environ["PWD"]}))
session, message = "ses_1", "msg_1"
read = {"status": "completed", "input": {"path": "a.py"}, "output": "Read file a.py, lines 1-2\n1: x = 1\n2: y = 2", "metadata": {"metadata": {"truncated": False}}}
denied = {"status": "error", "input": {"path": "/etc/hostname"}, "error": "Permission denied: external_directory"}
events = [
    {"type": "tool_use", "sessionID": session, "part": {"partID": "prt_1", "id": "call_1", "tool": "read", "state": read}},
    {"type": "step_finish", "sessionID": session, "part": {"id": "prt_2", "messageID": "msg_0", "reason": "tool-calls", "tokens": {"input": 10, "output": 2, "reasoning": 1, "cache": {"read": 5, "write": 0}}}},
    {"type": "tool_use", "sessionID": session, "part": {"partID": "prt_3", "id": "call_2", "tool": "grep", "state": {"status": "completed", "input": {"pattern": "x"}, "output": "", "metadata": {}}}},
    {"type": "text", "sessionID": session, "part": {"id": "prt_4", "messageID": message, "text": "done"}},
]
if os.environ.get("FAKE_DENY"):
    events.insert(1, {"type": "tool_use", "sessionID": session, "part": {"partID": "prt_9", "id": "call_9", "tool": "read", "state": denied}})
for event in events:
    print(json.dumps(event))
"""


class SettingsTests(unittest.TestCase):
    def test_defaults_launch_opencode_with_its_configured_model(self):
        with tempfile.TemporaryDirectory() as temp, mock.patch.dict(os.environ, {"PATH": temp}):
            base = Path(temp)
            launch = launch_settings({"agent_directory": "profiles"}, base)
            self.assertEqual(launch["command"], ["opencode"])
            self.assertEqual(launch["models"], {})
            self.assertEqual(launch["destination"], (base / "profiles").resolve())
            wrapped = launch_settings(
                {"command": ["/opt/bin/wrapper"], "models": {"a": "p/m"}}, base
            )
            self.assertEqual(wrapped["command"], ["/opt/bin/wrapper"])
            self.assertEqual(wrapped["models"], {"a": "p/m"})

    def test_invalid_command_and_models_fail_before_launch(self):
        for command in ([], "opencode", ["opencode", 1]):
            with self.assertRaisesRegex(ValueError, "argv array"):
                launch_settings({"command": command}, Path("/"))
        for models in ([], {"planner": ""}, {"planner": None}):
            with self.assertRaisesRegex(ValueError, "settings.models"):
                launch_settings({"models": models}, Path("/"))


class RepairToolTests(unittest.TestCase):
    def test_read_mode_keeps_reads_and_never_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            role = root / "role.md"
            role.write_text("role")
            target = root / "a.py"
            target.write_text("x")
            for mode, read in (("none", "deny"), ("read", "allow")):
                access = dict(roots=[root], readable=[], writable=[target])
                profile, _ = make_profile(role, root / "profiles", mode, access, format_only=mode)
                rules = json.loads(profile.read_text().split("---")[1])["permission"]
                self.assertEqual(rules["edit"], "deny")
                self.assertEqual(rules["glob"], read)
            self.assertEqual(
                launch_settings({"opencode_version": "1.x"}, root)["format_repair_tools"], "none"
            )
            with self.assertRaisesRegex(ValueError, "format_repair_tools"):
                launch_settings({"format_repair_tools": "all"}, root)


class DirectoryTests(unittest.TestCase):
    def test_profiles_and_tool_output_follow_opencode_environment(self):
        variables = {"XDG_CONFIG_HOME": "/x/config", "XDG_DATA_HOME": "/x/data"}
        with mock.patch.dict(os.environ, variables):
            os.environ.pop("OPENCODE_CONFIG_DIR", None)
            self.assertEqual(opencode_cli.agent_directory(), Path("/x/config/opencode/agent"))
            self.assertEqual(opencode_cli.tool_output_pattern(), "/x/data/opencode/tool-output/*")
            os.environ["OPENCODE_CONFIG_DIR"] = "/x/extra"
            self.assertEqual(opencode_cli.agent_directory(), Path("/x/extra/agent"))
        with mock.patch.dict(os.environ, {}):
            for name in ("OPENCODE_CONFIG_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME"):
                os.environ.pop(name, None)
            self.assertEqual(opencode_cli.agent_directory(), Path.home() / ".config/opencode/agent")


class LaunchTests(unittest.TestCase):
    def launch(self, root, model):
        script, record = root / "cli.py", root / "record.json"
        script.write_text(RECORDER)
        prompt = root / "request.md"
        prompt.write_text("task")
        with mock.patch.dict(os.environ, {"RECORD": str(record)}):
            result = run_agent(
                dict(
                    command=[sys.executable, str(script)],
                    workspace=root,
                    agent="agent",
                    model=model,
                    prompt=prompt,
                    attempt=root / "attempt",
                    timeout=10,
                )
            )
        self.assertEqual(result["status"], "OK")
        return json.loads(record.read_text())

    def test_launch_uses_only_upstream_flags(self):
        with tempfile.TemporaryDirectory() as temp:
            seen = self.launch(Path(temp), None)
            self.assertEqual(seen["argv"][0], "run")
            self.assertNotIn("--model", seen["argv"])
            self.assertEqual(seen["update"], "true")
            self.assertEqual(seen["argv"][-2:], ["--", "Execute_the_task_in_the_attached_file"])

    def test_configured_model_is_passed(self):
        with tempfile.TemporaryDirectory() as temp:
            argv = self.launch(Path(temp), "p/m")["argv"]
            self.assertEqual(argv[argv.index("--model") + 1], "p/m")


class EnvironmentTests(unittest.TestCase):
    def test_wrapper_receives_the_same_limited_environment_for_version_and_preflight(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wrapper = root / "wrapper.py"
            wrapper.write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "assert sys.argv[1:3] == ['--profile', 'test profile']\n"
                "assert os.environ['WRAPPER_TOKEN'] == 'wrapper-test-token'\n"
                "assert 'HOST_SECRET_TOKEN' not in os.environ\n"
                "path = Path(__file__).with_name('seen.jsonl')\n"
                "with path.open('a') as log: log.write(json.dumps(sys.argv[3:]) + '\\n')\n"
                "if sys.argv[3:] == ['--version']: print('wrapper 1.19.3')\n"
                "else:\n"
                " assert sys.argv[3:] == ['agent', 'list']\n"
                " print('managed (primary)')\n"
                " print(json.dumps([dict(permission='*', pattern='*', action='deny')]))\n"
            )
            command = [sys.executable, str(wrapper), "--profile", "test profile"]
            options = dict(
                command=command, agent_directory="profiles", agent_env_allow=["WRAPPER_TOKEN"]
            )
            variables = dict(
                WRAPPER_TOKEN="wrapper-test-token", HOST_SECRET_TOKEN="private-test-token"
            )
            with mock.patch.dict(os.environ, variables):
                launch = launch_settings(options, root)
                expected = [dict(permission="*", pattern="*", action="deny")]
                self.assertEqual(
                    verify_launch(launch, root, "managed", expected, root / "log"), expected
                )
                self.assertNotIn("WRAPPER_TOKEN", environment.filtered())
            seen = [json.loads(line) for line in (root / "seen.jsonl").read_text().splitlines()]
            self.assertEqual(seen, [["--version"], ["agent", "list"]])
            self.assertEqual(launch["command"], command)

    def test_secret_shaped_names_are_dropped_unless_allowed(self):
        for name in (
            "GITHUB_TOKEN",
            "DB_PASSWORD",
            "STRIPE_API_KEY",
            "TOKEN_FILE",
            "SSH_AUTH_SOCK",
        ):
            self.assertTrue(environment.secret(name), name)
        for name in ("PATH", "HOME", "KEYBOARD", "AWS_REGION", "PWD"):
            self.assertFalse(environment.secret(name), name)
        values = {"A_TOKEN": "x", "ANTHROPIC_API_KEY": "k", "HARMLESS": "1"}
        with mock.patch.dict(os.environ, values):
            kept = environment.filtered(environment.agent_allowlist(["A_TOKEN"]))
            self.assertEqual((kept["A_TOKEN"], kept["ANTHROPIC_API_KEY"]), ("x", "k"))
            local = environment.filtered()
            self.assertNotIn("A_TOKEN", local)
            self.assertNotIn("ANTHROPIC_API_KEY", local)
            self.assertEqual(local["HARMLESS"], "1")
        with self.assertRaisesRegex(ValueError, "agent_env_allow"):
            environment.agent_allowlist("A_TOKEN")

    def test_opencode_receives_only_allowed_secrets(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script, record = root / "cli.py", root / "env.json"
            script.write_text(
                "import json, os, sys\n"
                "from pathlib import Path\n"
                "Path(sys.argv[0]).with_name('env.json').write_text(json.dumps(dict(os.environ)))\n"
            )
            prompt = root / "request.md"
            prompt.write_text("task")
            values = {"HOST_SECRET_TOKEN": "x", "OPENAI_API_KEY": "k"}
            runtime = dict(env_allow=environment.agent_allowlist([]))
            with mock.patch.dict(os.environ, values):
                command = [sys.executable, str(script)]
                run_agent(
                    dict(
                        command=command,
                        workspace=root,
                        agent="a",
                        model=None,
                        prompt=prompt,
                        attempt=root / "t",
                        timeout=10,
                        runtime=runtime,
                    )
                )
            seen = json.loads(record.read_text())
            self.assertNotIn("HOST_SECRET_TOKEN", seen)
            self.assertEqual(seen["OPENAI_API_KEY"], "k")


class DenialTests(unittest.TestCase):
    def test_upstream_rule_denial_stops_the_turn_for_a_decision(self):
        message = (
            "The user has specified a rule which prevents you from using this specific "
            "tool call. Here are some of the relevant rules []"
        )
        state = dict(status="error", input=dict(filePath="/x/y.py"), error=message)
        event = dict(type="tool_use", part=dict(id="p", tool="edit", state=state))
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "cli.py"
            script.write_text(f"print({json.dumps(event)!r})\n")
            prompt = root / "request.md"
            prompt.write_text("task")
            result = run_agent(
                dict(
                    command=[sys.executable, str(script)],
                    workspace=root,
                    agent="a",
                    model=None,
                    prompt=prompt,
                    attempt=root / "t",
                    timeout=10,
                )
            )
        self.assertEqual(result["status"], "BLOCKED_PERMISSION")
        self.assertTrue(
            opencode_cli.permission_error("PermissionDeniedError: Permission denied: read")
        )
        self.assertFalse(opencode_cli.permission_error("File not found: /x"))


class PermissionListTests(unittest.TestCase):
    def test_agent_list_output_and_tool_output_guard_are_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            expected = [dict(permission="*", pattern="*", action="deny")]
            guard = dict(
                permission="external_directory",
                pattern=str(root / "data/opencode/tool-output/*"),
                action="allow",
            )
            listing = "build (primary)\n  []\nmanaged (primary)\n  " + json.dumps(
                [*expected, guard], indent=2
            )
            script = root / "cli.py"
            script.write_text(
                "import sys\nassert sys.argv[1:] == ['agent', 'list'], sys.argv\nprint("
                + repr(listing)
                + ")\n"
            )
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "data")}):
                launch = dict(command=[sys.executable, str(script)], agent_env_allow=())
                actual = verify_launch(launch, root, "managed", expected, root / "log")
                self.assertEqual(actual, [*expected, guard])
                launch["tool_output_dir"] = str(root / "custom-cli/tool-output")
                with self.assertRaisesRegex(ValueError, "differ"):
                    verify_launch(launch, root, "managed", expected, root / "log")
            elsewhere = dict(launch, tool_output_dir=str(root / "data/opencode/tool-output"))
            self.assertEqual(
                verify_launch(elsewhere, root, "managed", expected, root / "log"), actual
            )

    def test_slow_listing_blocks_with_a_clear_preflight_error(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = root / "cli.py"
            script.write_text("import time\ntime.sleep(30)\n")
            launch = dict(command=[sys.executable, str(script)], agent_env_allow=())
            with (
                mock.patch.object(permission_check, "LISTING_SECONDS", 0.2),
                self.assertRaisesRegex(ValueError, "no model launched"),
            ):
                verify_launch(launch, root, "managed", [], root / "log")

    def test_tool_output_dir_must_be_absolute(self):
        with tempfile.TemporaryDirectory() as temp:
            settings = dict(
                opencode_version="1.x", tool_output_dir="~/.local/share/custom-cli/tool-output"
            )
            launch = launch_settings(settings, Path(temp))
            self.assertEqual(
                launch["tool_output_dir"], str(Path.home() / ".local/share/custom-cli/tool-output")
            )
            self.assertIsNone(
                launch_settings(dict(opencode_version="1.x"), Path(temp))["tool_output_dir"]
            )
            for invalid in ("relative/tool-output", 3, ["/x"]):
                with (
                    self.subTest(invalid=invalid),
                    self.assertRaisesRegex(ValueError, "tool_output_dir"),
                ):
                    launch_settings(
                        dict(opencode_version="1.x", tool_output_dir=invalid), Path(temp)
                    )


class TranslationTests(unittest.TestCase):
    def translate(self, event, directory="/work"):
        return json.loads(EventTranslator(directory).translate(json.dumps(event)))

    def tool(self, state, tool="read"):
        event = dict(type="tool_use", part=dict(partID="prt", id="call", tool=tool, state=state))
        return self.translate(event)["part"]

    def test_complete_read_gets_absolute_path_identifiers_and_end_marker(self):
        state = dict(status="completed", input=dict(path="pkg/a.py"))
        state.update(output="Read file pkg/a.py, lines 1-2\n1: x\n2: y")
        state.update(metadata=dict(metadata=dict(truncated=False)))
        part = self.tool(state)
        self.assertEqual((part["id"], part["callID"]), ("prt", "call"))
        self.assertEqual(part["state"]["input"]["filePath"], "/work/pkg/a.py")
        self.assertIn("1: x\n2: y\n\n(End of file - total 2 lines)", part["state"]["output"])
        self.assertIs(part["state"]["metadata"]["truncated"], False)

    def test_partial_read_keeps_original_output(self):
        output = "Read file a.py, lines 3-4\n3: x\n4: y"
        state = dict(status="completed", input=dict(path="a.py", offset=3), output=output)
        state.update(metadata=dict(metadata=dict(truncated=False)))
        self.assertEqual(self.tool(state)["state"]["output"], output)
        state.update(input=dict(path="a.py"), metadata=dict(metadata=dict(truncated=True)))
        self.assertEqual(self.tool(state)["state"]["output"], output)

    def test_errors_use_the_classified_messages(self):
        denied = self.tool(
            dict(status="error", input=dict(path="x"), error="Permission denied: edit")
        )
        self.assertTrue(denied["state"]["error"].startswith("PermissionDeniedError"))
        missing = "File not found: x\n\nDid you mean one of these?\n/work/y"
        state = dict(status="error", input=dict(path="x"), error=missing)
        self.assertTrue(
            self.tool(state)["state"]["error"].startswith("Error: File not found: /work/x\n")
        )
        offset = "Offset 4 is out of range for this file (1 line)"
        state = dict(status="error", input=dict(path="/a"), error=offset)
        expected = "Error: Offset 4 is out of range for this file (1 lines)"
        self.assertEqual(self.tool(state)["state"]["error"], expected)

    def test_unknown_tool_call_continues_like_opencode_1(self):
        message = 'No tool named "GIT_REQUEST" is currently available. Please use a tool.'
        part = self.tool(dict(status="error", input=dict(root="/x"), error=message), "GIT_REQUEST")
        self.assertEqual(part["state"]["status"], "completed")
        self.assertEqual(part["state"]["output"], message)
        self.assertNotIn("error", part["state"])

    def test_step_total_and_missing_final_step(self):
        translator = EventTranslator("/work")
        tokens = dict(input=10, output=2, reasoning=1, cache=dict(read=5, write=1))
        step = dict(type="step_finish", part=dict(reason="tool-calls", tokens=tokens))
        self.assertEqual(
            json.loads(translator.translate(json.dumps(step)))["part"]["tokens"]["total"], 18
        )
        self.assertIsNone(translator.finish(0))
        text = dict(type="text", sessionID="s", part=dict(id="p", messageID="m", text="ok"))
        translator.translate(json.dumps(text))
        self.assertIsNone(translator.finish(1))
        stop = json.loads(translator.finish(0))
        self.assertEqual((stop["part"]["reason"], stop["part"]["messageID"]), ("stop", "m"))
        failing = EventTranslator("/work")
        failing.translate(json.dumps(text))
        failing.translate(json.dumps(dict(type="error", error=dict(message="boom"))))
        self.assertIsNone(failing.finish(0))
        self.assertEqual(failing.translate("not json"), "not json")


def supports(record, claim, excerpt):
    """Every cited position is in the returned output of this file, with the excerpt's text."""
    if record["input"]["filePath"] != claim["path"]:
        return False
    expected = dict(enumerate(excerpt.split("\n"), claim["line_start"]))
    return len(matching_positions(record, expected)) == len(expected)


class CitationTests(unittest.TestCase):
    def test_inline_read_envelopes_preserve_first_last_and_literal_source_lines(self):
        claim = dict(path="/readme.md", line_start=1, line_end=3)
        excerpt = "# Setup\n<content>literal source</content>\n"
        numbered = "1:# Setup\n2:<content>literal source</content>\n3:"
        wrappers = (
            "<content>{0}</content>",
            "<file>{0}</file>",
            "<path>/readme.md</path>\n<type>file</type>\n<content>{0}\n"
            "\n(End of file - total 3 lines)\n</content>",
            "<path>/readme.md</path>\r\n<type>file</type>\r\n<content>\r\n{0}\r\n</content>",
        )
        for wrapper in wrappers:
            with self.subTest(wrapper=wrapper):
                record = dict(input=dict(filePath=claim["path"]), output=wrapper.format(numbered))
                self.assertTrue(supports(record, claim, excerpt))
                self.assertFalse(supports(record, claim, excerpt + "unseen"))

    def test_wrapped_reads_do_not_accept_footer_lines_or_clipped_and_reordered_content(self):
        claim = dict(path="/readme.md", line_start=1, line_end=2)
        for output in (
            "<content>1: one</content>\n2: two",
            "<content>1: one\n1: one\n2: two</content>",
            "<content>2: two\n1: one</content>",
        ):
            with self.subTest(output=output):
                record = dict(input=dict(filePath=claim["path"]), output=output)
                self.assertFalse(supports(record, claim, "one\ntwo"))
        record = dict(
            input=dict(filePath=claim["path"]),
            output="<content>1: one\n2: two",
            output_clipped=True,
        )
        self.assertFalse(supports(record, claim, "one\ntwo"))
        self.assertTrue(supports(record, dict(claim, line_end=1), "one"))

    def test_cited_lines_must_reach_the_model_through_the_read(self):
        record = dict(
            input=dict(filePath="/a.py"),
            output="Read file /a.py, lines 1-2\n1: def f():\n2:     return 1",
        )
        claim = dict(path="/a.py", line_start=1, line_end=2)
        excerpt = "def f():\n    return 1"
        self.assertTrue(supports(record, claim, excerpt))
        legacy = dict(record, output="00001| def f():\n00002|     return 1")
        self.assertTrue(supports(legacy, claim, excerpt))
        self.assertTrue(supports(dict(record, output="1: def f():\n2:  return 1"), claim, excerpt))
        self.assertFalse(supports(dict(record, output="1: def f():"), claim, excerpt))
        self.assertFalse(supports(record, dict(claim, path="/b.py"), excerpt))

    def test_unseen_suffix_of_a_truncated_line_cannot_substantiate_a_citation(self):
        line = "x = '" + "a" * 3000 + "'"
        output = "1: " + line[:2000] + "... (line truncated to 2000 chars)"
        record = dict(input=dict(filePath="/a.py"), output=output)
        claim = dict(path="/a.py", line_start=1, line_end=1)
        self.assertFalse(supports(record, claim, line))

    def test_returned_positions_and_complete_lines_control_citations(self):
        claim = dict(path="/a.py", line_start=2, line_end=2)
        record = dict(input=dict(filePath="/a.py", offset=1, limit=2000), output="1: same")
        self.assertFalse(supports(record, claim, "same"))
        self.assertFalse(supports(dict(record, output="2: prefix same suffix"), claim, "same"))
        self.assertFalse(supports(dict(record, output="2: same\n2: same"), claim, "same"))
        self.assertFalse(supports(dict(record, output="same\nsame"), claim, "same"))
        self.assertTrue(supports(dict(record, output="2: same"), claim, "same"))
        self.assertTrue(supports(dict(record, output="00002| same"), claim, "same"))
        self.assertTrue(supports(dict(record, output="2: "), claim, ""))

    def test_executor_evidence_is_the_exact_delivered_positional_text(self):
        claim = dict(path="/snapshot.json", line_start=2, line_end=2)
        record = dict(
            tool="executor", input=dict(filePath=claim["path"]), output="header\n2: same\n"
        )
        self.assertTrue(supports(record, claim, "2: same"))
        self.assertFalse(supports(record, claim, "same"))
        clipped = dict(record, output="header\n2: same", output_clipped=True)
        self.assertFalse(supports(clipped, claim, "2: same"))


FIXTURES = Path(__file__).with_name("fixtures")


class RealStreamTests(unittest.TestCase):
    """Recorded opencode streams keep the parsers honest about real event shapes."""

    def test_recorded_read_positions_support_citations_in_both_cli_generations(self):
        fixtures = (
            (
                "opencode-1.19.3-plan.jsonl",
                "/fixture/shop/pricing.py",
                4,
                "def apply_discount(total, percent):",
            ),
            ("opencode-2.0.30-answer-plan.jsonl", "/fixture/notes/config.ini", 2, "timeout = 30"),
        )
        for filename, path, number, source in fixtures:
            translator = EventTranslator("/fixture/notes")
            for raw in (FIXTURES / filename).read_text().splitlines():
                event = json.loads(translator.translate(raw) if "2.0" in filename else raw)
                part = event.get("part", {})
                state = part.get("state", {})
                if part.get("tool") == "read" and state.get("input", {}).get("filePath") == path:
                    claim = dict(path=path, line_start=number, line_end=number)
                    self.assertTrue(supports(state, claim, source), filename)
                    self.assertFalse(supports(state, dict(claim, line_start=number + 100), source))
                    break
            else:
                self.fail(f"No recorded read for {path}")

    def test_opencode_1_plan_stream_parses_without_translation(self):
        result = parse_events(FIXTURES / "opencode-1.19.3-plan.jsonl")
        self.assertTrue(result["completed"])
        self.assertEqual((result["tool_calls"], result["errors"]), (2, []))
        self.assertGreater(result["tokens"]["total"], 0)
        self.assertIn('"status"', result["final_text"])

    def test_opencode_2_two_turn_stream_matches_the_opencode_1_shape(self):
        translator = EventTranslator("/fixture/notes")
        raw = (FIXTURES / "opencode-2.0.30-answer-plan.jsonl").read_text().splitlines()
        lines = [translator.translate(line) for line in raw]
        lines.append(translator.finish(0))
        with tempfile.TemporaryDirectory() as temp:
            events = Path(temp) / "events.jsonl"
            events.write_text("\n".join(lines) + "\n")
            result = parse_events(events)
            reads = [json.loads(line)["part"] for line in lines if '"tool": "read"' in line]
        self.assertTrue(result["completed"])
        self.assertEqual((result["tool_calls"], result["errors"]), (5, []))
        self.assertGreater(result["tokens"]["total"], 0)
        self.assertIn("PLAN_READY", result["final_text"])
        self.assertTrue(all(part["state"]["input"]["filePath"].startswith("/") for part in reads))
        self.assertTrue(any("(End of file - total" in part["state"]["output"] for part in reads))

    def test_only_quota_and_billing_errors_mark_a_provider_limit(self):
        cases = {
            "2.x quota": dict(
                type="provider.quota", message="Free usage limit reached.", status=429
            ),
            "1.x quota": dict(
                name="APIError", data=dict(message="insufficient_quota", statusCode=429)
            ),
            "billing": dict(name="APIError", data=dict(message="Payment Required", statusCode=402)),
            "rate limit": dict(
                name="APIError", data=dict(message="Rate limit reached, retry in 20s")
            ),
        }
        expected = {"2.x quota": True, "1.x quota": True, "billing": True, "rate limit": False}
        for name, error in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp:
                events = Path(temp) / "events.jsonl"
                events.write_text(json.dumps(dict(type="error", error=error)) + "\n")
                result = parse_events(events)
                self.assertEqual(result["provider_limit"], expected[name])
                self.assertEqual(len(result["errors"]), 1)

    def test_only_a_turn_the_provider_alone_broke_off_is_continued(self):
        gateway = "{'name': 'APIError', 'data': {'message': 'Retries exhausted'}}"
        broken = dict(status="TOOL_ERROR", sessions=["ses1"], errors=[gateway], tool_errors=[])
        cases = {
            "provider": (broken, {}, True),
            "failed tool": (dict(broken, tool_errors=[dict(error=gateway)]), {}, False),
            "denied": (dict(broken, permission=True), {}, False),
            "answered": (dict(broken, final_text="{}"), {}, False),
            "quota kept": (dict(broken, provider_limit=True), {}, True),
            "quota stops": (
                dict(broken, provider_limit=True),
                dict(stop_on_provider_limit=True),
                False,
            ),
            "overflow": (dict(broken, status="CONTEXT_EXCEEDED"), {}, False),
            "two sessions": (dict(broken, sessions=["ses1", "ses2"]), {}, False),
        }
        for name, (outcome, config, continued) in cases.items():
            with self.subTest(name=name):
                errors = provider_resume.interruptions(outcome, config)
                self.assertEqual(errors, [gateway] if continued else [])


class SelectionTests(unittest.TestCase):
    def version(self, output):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "cli.py"
            script.write_text(f"print({output!r})\n")
            return opencode_api.select("auto", [sys.executable, str(script)])

    def test_auto_trusts_only_an_exact_version_line(self):
        self.assertEqual(self.version("opencode v2.0.30"), "2.x")
        self.assertEqual(self.version("2.1.0"), "2.x")
        self.assertEqual(self.version("1.19.0"), "1.x")
        self.assertEqual(self.version("wrapper v2.0.30"), "2.x")
        self.assertEqual(self.version("WRAPPER 1.19.0"), "1.x")
        for ambiguous in (
            "GNU bash, version 5.2.21(1)-release",
            "wrapper build 1.0 (opencode 2.0)",
            "2.0.1\n1.0.0",
            "wrapper 1.0.0(opencode2.0.0)",
        ):
            with self.subTest(output=ambiguous), self.assertRaisesRegex(ValueError, "explicitly"):
                self.version(ambiguous)
        self.assertEqual(opencode_api.select("auto", ["/nonexistent/opencode"]), "1.x")
        self.assertEqual(opencode_api.select("2.x", ["/nonexistent/opencode"]), "2.x")
        with self.assertRaisesRegex(ValueError, "opencode_version"):
            opencode_api.select("v3", ["opencode"])

    def test_opencode_2_runs_behind_the_adapter_from_any_directory(self):
        command = opencode_api.launch_command(["opencode"], "2.x")
        self.assertEqual(command[:3], [sys.executable, "-I", "-c"])
        self.assertEqual(json.loads(command[-1]), ["opencode"])
        self.assertEqual(opencode_api.launch_command(["opencode"], "1.x"), ["opencode"])


class ProfileTests(unittest.TestCase):
    def test_rules_cover_absolute_and_base_relative_names(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "a").mkdir()
            (base / "b").mkdir()
            artifact = base / "run" / "request.md"
            artifact.parent.mkdir()
            artifact.write_text("x")
            rules = permissions([base / "a", base / "b"], [artifact], [], base / "a")
            read = list(rules["read"].items())
            whole = [("*", "allow"), ("/*", "deny"), ("..", "deny"), ("../*", "deny")]
            self.assertEqual(read[:4], whole)
            self.assertEqual(rules["read"]["../b/*"], "allow")
            self.assertEqual(rules["read"][str(artifact)], "allow")
            self.assertEqual(rules["read"]["../run/request.md"], "allow")
            self.assertNotIn(str(artifact.parent) + "/*", rules["read"])
            protected = [(pattern, "deny") for pattern in protected_paths.DEFAULT_PATTERNS]
            self.assertEqual(read[-len(protected) :], protected)
            self.assertIn(("*/.env", "deny"), protected)

    def test_subdirectory_root_never_allows_its_whole_worktree(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "sub").mkdir()
            rules = permissions([base / "sub"], [], [], base)["read"]
            self.assertEqual(next(iter(rules.items())), ("*", "deny"))
            self.assertEqual((rules["sub"], rules["sub/*"]), ("allow", "allow"))
            absolute = permissions([base / "sub"], [], [], None)["read"]
            self.assertNotIn("sub/*", absolute)


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "work"
        self.workspace.mkdir()
        fake = self.root / "fake_v2.py"
        fake.write_text(FAKE_OPENCODE_2)
        self.command = opencode_api.launch_command([sys.executable, str(fake)], "2.x")
        patcher = mock.patch.dict(os.environ, {"FAKE_STATE": str(self.root)})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)

    def test_agent_list_waits_for_configuration_and_renames_actions(self):
        expected = [
            dict(permission="*", pattern="*", action="deny"),
            dict(permission="bash", pattern="*", action="deny"),
        ]
        log = self.root / "permissions.log"
        launch = dict(command=self.command, agent_env_allow=())
        verify_launch(launch, self.workspace, "managed", expected, log)
        self.assertGreaterEqual(int((self.root / "api-calls").read_text()), 2)

    def test_a_slow_configuration_reload_is_waited_for_within_the_budget(self):
        fake = [sys.executable, str(self.root / "fake_v2.py")]
        with mock.patch.dict(os.environ, {"FAKE_SLOW_API": "1.5"}):
            with (
                mock.patch.object(opencode_server, "READY_SECONDS", 0.5),
                opencode_server.Server(fake, str(self.workspace)) as server,
                self.assertRaisesRegex(RuntimeError, "did not load agent managed"),
            ):
                server.agents("managed")
            (self.root / "api-calls").unlink()
            with opencode_server.Server(fake, str(self.workspace)) as server:
                self.assertEqual(server.agents("managed")[0]["id"], "managed")
        self.assertEqual((self.root / "api-calls").read_text(), "2")

    def test_run_translates_events_and_keeps_the_raw_stream(self):
        prompt = self.root / "request.md"
        prompt.write_text("task")
        result = run_agent(
            dict(
                command=self.command,
                workspace=self.workspace,
                agent="managed",
                model="p/m",
                prompt=prompt,
                attempt=self.root / "attempt",
                timeout=30,
            )
        )
        self.assertEqual(result["status"], "OK", result)
        self.assertEqual(result["final_text"], "done")
        self.assertEqual(result["tokens"]["total"], 17)
        seen = json.loads((self.root / "run.json").read_text())
        self.assertEqual(seen["pwd"], str(self.workspace))
        self.assertNotIn(str(self.workspace), seen["args"])
        self.assertIn("--model", seen["args"])
        raw = (self.root / "attempt" / "events.raw.jsonl").read_text()
        self.assertIn('"partID": "prt_1"', raw)
        events = (self.root / "attempt" / "events.jsonl").read_text()
        self.assertIn(f'"filePath": "{self.workspace}/a.py"', events)

    def test_turns_attach_to_the_stage_server(self):
        prompt = self.root / "request.md"
        prompt.write_text("task")
        attachment = {"TASKRAIL_OPENCODE_SERVER": "http://127.0.0.1:9", "OPENCODE_PASSWORD": "p"}
        runtime = dict(attachment=attachment)
        result = run_agent(
            dict(
                command=self.command,
                workspace=self.workspace,
                agent="managed",
                model=None,
                prompt=prompt,
                attempt=self.root / "a3",
                timeout=30,
                runtime=runtime,
            )
        )
        self.assertEqual(result["status"], "OK", result)
        self.assertFalse((self.root / "serve-started").exists())
        with opencode_api.stage_server(self.command, self.workspace, ()) as server:
            self.assertEqual(server.attachment()["TASKRAIL_OPENCODE_SERVER"], "http://127.0.0.1:9")
        self.assertTrue((self.root / "serve-started").exists())
        with opencode_api.stage_server(["opencode"], self.workspace, ()) as server:
            self.assertIsNone(server)

    def test_denied_read_stops_the_turn_for_a_decision(self):
        prompt = self.root / "request.md"
        prompt.write_text("task")
        with mock.patch.dict(os.environ, {"FAKE_DENY": "1"}):
            result = run_agent(
                dict(
                    command=self.command,
                    workspace=self.workspace,
                    agent="managed",
                    model=None,
                    prompt=prompt,
                    attempt=self.root / "a2",
                    timeout=30,
                )
            )
        self.assertEqual(result["status"], "BLOCKED_PERMISSION")
        self.assertEqual(result["tool_errors"][0]["input"]["filePath"], "/etc/hostname")


if __name__ == "__main__":
    unittest.main()
