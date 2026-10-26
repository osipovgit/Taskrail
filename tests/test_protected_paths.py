"""Protected paths stay unreadable and uneditable on every route that reaches a model."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import (
    check_configuration,
    planned_paths,
    project_map,
    source_windows,
    task_config,
)
from taskrail.core import protected_paths
from taskrail.infrastructure.profile_rules import permissions
from taskrail.interactions import access, read_only

DENY = "deny"


class ProtectedPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project"
        (self.root / ".git").mkdir(parents=True)
        (self.root / ".git/config").write_text("url = https://token@example.com/x.git\n")
        (self.root / "certs").mkdir()
        (self.root / "certs/server.pem").write_text("-----BEGIN PRIVATE KEY-----\n")
        (self.root / "id_ed25519").write_text("private\n")
        (self.root / ".npmrc").write_text("//registry/:_authToken=secret\n")
        (self.root / "app.py").write_text("def main():\n    return 1\n")
        self.roots = {"project": self.root}

    def configure(self, **settings):
        """The run configuration of a task on the project root with these settings."""
        source = self.base / "settings.json"
        source.write_text(json.dumps(dict(opencode_version="1.x", **settings)))
        header = json.dumps(dict(roots={"project": str(self.root)}))
        task = self.base / "task.md"
        task.write_text(f"```taskrail-task\n{header}\n```\n# Goal\nChange app.py\n")
        return task_config.configuration(task, source)

    def listing(self, argv, protected=protected_paths.DEFAULT_PATTERNS):
        request = dict(status="LOCAL_REQUEST", cwd=str(self.root), argv=argv)
        return read_only.request(request, self.roots, protected)

    def test_defaults_protect_credentials_and_keep_env_files_fixed(self):
        config = self.configure()
        self.assertEqual(config["protected_paths"], list(protected_paths.DEFAULTS))
        patterns = protected_paths.read_patterns([])
        self.assertTrue(protected_paths.matches(self.root / ".env.local", patterns))
        for name in (".git/config", "certs/server.pem", "id_ed25519", ".npmrc"):
            with self.subTest(name=name):
                self.assertTrue(protected_paths.matches(self.root / name, config_patterns(config)))
        self.assertFalse(protected_paths.matches(self.root / "app.py", config_patterns(config)))

    def test_invalid_settings_are_refused(self):
        for entries in ("*.pem", ["/etc/shadow"], ["../x"], ["a/./b"], ["[ab].key"], [3], [""]):
            with self.subTest(entries=entries), self.assertRaisesRegex(ValueError, "protected"):
                self.configure(protected_paths=entries)
        self.assertEqual(self.configure(protected_paths=["*.p12"])["protected_paths"], ["*.p12"])

    def test_profiles_deny_protected_reads_and_edits_after_every_allowance(self):
        writable = [self.root / "certs/server.pem", self.root / "app.py"]
        rules = permissions([self.root], [], writable, self.root, protected_paths.DEFAULT_PATTERNS)
        for permission in ("read", "edit"):
            names = list(rules[permission])
            tail = names[-len(protected_paths.DEFAULT_PATTERNS) :]
            self.assertEqual(tail, list(protected_paths.DEFAULT_PATTERNS), permission)
            self.assertEqual(rules[permission]["*/*.pem"], DENY)
        self.assertEqual(rules["edit"][str(self.root / "app.py")], "allow")

    def test_automatic_reads_and_grants_refuse_protected_files(self):
        self.assertTrue(self.listing(["cat", "app.py"]))
        for name in (".git/config", "certs/server.pem", "id_ed25519", ".npmrc"):
            with self.subTest(name=name):
                self.assertFalse(self.listing(["cat", name]))
                call = dict(tool="read", input=dict(filePath=str(self.root / name)))
                with self.assertRaisesRegex(ValueError, "Protected"):
                    access.target(call, self.roots)
        custom = protected_paths.read_patterns(["app.py"])
        self.assertFalse(self.listing(["cat", "app.py"], custom))
        self.assertTrue(self.listing(["cat", "certs/server.pem"], custom))

    def test_project_map_and_source_windows_leave_protected_files_out(self):
        text = project_map.render(self.roots, [], protected_paths.DEFAULT_PATTERNS)
        self.assertIn("project/app.py", text)
        for name in ("server.pem", "id_ed25519", ".npmrc"):
            self.assertNotIn(name, text)
        config = self.configure()
        spec = dict(fields=[dict(name="entry_points", text="certs/server.pem\napp.py:1-2")])
        config["task_spec"] = spec
        observed = source_windows.observations(config, None)
        self.assertEqual(
            [entry["input"]["filePath"] for entry in observed], [str(self.root / "app.py")]
        )

    def test_plans_cannot_edit_protected_files_or_configured_tool_state(self):
        protected = protected_paths.read_patterns([*protected_paths.DEFAULTS, ".private-tool/*"])
        for name in (
            "project/certs/server.pem",
            "project/.npmrc",
            "project/.private-tool/config.json",
        ):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, "Protected"):
                planned_paths.safe_file(name, self.roots, protected)
        self.assertEqual(
            planned_paths.safe_file("project/app.py", self.roots, protected).name, "app.py"
        )
        released = protected_paths.read_patterns([])
        self.assertTrue(planned_paths.safe_file("project/certs/server.pem", self.roots, released))

    def test_a_resumed_run_keeps_its_frozen_entries(self):
        run = self.base / "run"
        (run / "00-input").mkdir(parents=True)
        frozen = dict(check_recipes={}, verify_commands=[], protected_paths=["*.p12"])
        (run / "00-input/settings.json").write_text(json.dumps(frozen))
        config = dict(protected_paths=["*.pem"])
        check_configuration.restore(config, run, {})
        self.assertEqual(config["protected_paths"], ["*.p12", "*.pem"])


def config_patterns(config):
    return protected_paths.patterns(config)


if __name__ == "__main__":
    unittest.main()
