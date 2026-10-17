import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from countersign.core.source_claims import supports
from countersign.infrastructure import environment, opencode_api, opencode_cli
from countersign.infrastructure.agent_sync import launch_settings, make_profile, verify_permissions
from countersign.infrastructure.opencode_events import EventTranslator
from countersign.infrastructure.profile_rules import permissions
from countersign.infrastructure.runner import run_agent

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
        with tempfile.TemporaryDirectory() as temp:
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
                profile, _ = make_profile(
                    role, root / "profiles", mode, [root], [], [target], format_only=mode
                )
                rules = json.loads(profile.read_text().split("---")[1])["permission"]
                self.assertEqual(rules["edit"], "deny")
                self.assertEqual(rules["glob"], read)
            self.assertEqual(launch_settings({}, root)["format_repair_tools"], "none")
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
                [sys.executable, str(script)], root, "agent", model, prompt, root / "attempt", 10
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
                run_agent(command, root, "a", None, prompt, root / "t", 10, runtime=runtime)
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
            script.write_text("print({0!r})\n".format(json.dumps(event)))
            prompt = root / "request.md"
            prompt.write_text("task")
            result = run_agent(
                [sys.executable, str(script)], root, "a", None, prompt, root / "t", 10
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
                expected + [guard], indent=2
            )
            script = root / "cli.py"
            script.write_text(
                "import sys\nassert sys.argv[1:] == ['agent', 'list'], sys.argv\nprint("
                + repr(listing)
                + ")\n"
            )
            with mock.patch.dict(os.environ, {"XDG_DATA_HOME": str(root / "data")}):
                actual = verify_permissions(
                    [sys.executable, str(script)], root, "managed", expected, root / "log"
                )
            self.assertEqual(actual, expected + [guard])


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


class QuoteTests(unittest.TestCase):
    def test_indented_multiline_quote_matches_numbered_read_output(self):
        record = dict(
            input=dict(filePath="/a.py"),
            output="Read file /a.py, lines 1-2\n1: def f():\n2:     return 1",
        )
        claim = dict(path="/a.py", line_start=1, line_end=2, quote="def f():\n    return 1")
        self.assertTrue(supports(record, claim))
        legacy = dict(record, output="00001| def f():\n00002|     return 1")
        self.assertTrue(supports(legacy, claim))
        self.assertFalse(supports(dict(record, output="1: def f():\n2:  return 1"), claim))


class SelectionTests(unittest.TestCase):
    def version(self, output):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "cli.py"
            script.write_text("print({0!r})\n".format(output))
            return opencode_api.select("auto", [sys.executable, str(script)])

    def test_auto_trusts_only_an_exact_version_line(self):
        self.assertEqual(self.version("opencode v2.0.30"), "2.x")
        self.assertEqual(self.version("2.1.0"), "2.x")
        self.assertEqual(self.version("1.19.0"), "1.x")
        self.assertEqual(self.version("GNU bash, version 5.2.21(1)-release"), "1.x")
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
            self.assertEqual(read[-2:], [(".env", "deny"), (".env.*", "deny")])

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
        verify_permissions(self.command, self.workspace, "managed", expected, log)
        self.assertGreaterEqual(int((self.root / "api-calls").read_text()), 2)

    def test_run_translates_events_and_keeps_the_raw_stream(self):
        prompt = self.root / "request.md"
        prompt.write_text("task")
        result = run_agent(
            self.command, self.workspace, "managed", "p/m", prompt, self.root / "attempt", 30
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
        self.assertIn('"filePath": "{0}/a.py"'.format(self.workspace), events)

    def test_turns_attach_to_the_stage_server(self):
        prompt = self.root / "request.md"
        prompt.write_text("task")
        attachment = {"COUNTERSIGN_OPENCODE_SERVER": "http://127.0.0.1:9", "OPENCODE_PASSWORD": "p"}
        runtime = dict(attachment=attachment)
        result = run_agent(
            self.command,
            self.workspace,
            "managed",
            None,
            prompt,
            self.root / "a3",
            30,
            runtime=runtime,
        )
        self.assertEqual(result["status"], "OK", result)
        self.assertFalse((self.root / "serve-started").exists())
        with opencode_api.stage_server(self.command, self.workspace, ()) as server:
            self.assertEqual(
                server.attachment()["COUNTERSIGN_OPENCODE_SERVER"], "http://127.0.0.1:9"
            )
        self.assertTrue((self.root / "serve-started").exists())
        with opencode_api.stage_server(["opencode"], self.workspace, ()) as server:
            self.assertIsNone(server)

    def test_denied_read_stops_the_turn_for_a_decision(self):
        prompt = self.root / "request.md"
        prompt.write_text("task")
        with mock.patch.dict(os.environ, {"FAKE_DENY": "1"}):
            result = run_agent(
                self.command, self.workspace, "managed", None, prompt, self.root / "a2", 30
            )
        self.assertEqual(result["status"], "BLOCKED_PERMISSION")
        self.assertEqual(result["tool_errors"][0]["input"]["filePath"], "/etc/hostname")


if __name__ == "__main__":
    unittest.main()
