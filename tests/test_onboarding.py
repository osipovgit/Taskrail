import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taskrail.onboarding import CHECK_MARKER, check, check_connection, init

BASE = Path(__file__).resolve().parents[1]


class OnboardingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.root / "home")})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.temp.cleanup)
        self.profiles = self.root / "profiles"

    def settings(self, **options):
        path = self.root / "settings.json"
        values = dict(
            command=[
                sys.executable,
                str(BASE / "tests/fake_live.py"),
                "--profiles",
                str(self.profiles),
                "--mode",
                "ok",
            ],
            agent_directory=str(self.profiles),
            run_base=str(self.root / "runs"),
        )
        values.update(options)
        path.write_text(json.dumps(values))
        return str(path)

    def test_check_verifies_cli_permissions_and_storage(self):
        report = check(self.settings())
        self.assertTrue(all(passed for passed, _ in report), report)
        self.assertTrue(any("1.0.0" in message for _, message in report), report)
        self.assertEqual(list(self.profiles.glob("*.md")), [])
        self.assertTrue((self.root / "runs").is_dir())

    def test_check_reports_missing_cli_and_invalid_settings(self):
        with mock.patch("taskrail.cli_health.permission_result") as permission:
            report = check(self.settings(command=[str(self.root / "missing-opencode")]))
        permission.assert_not_called()
        failures = [message for passed, message in report if not passed]
        self.assertTrue(any("Cannot detect opencode interface" in message for message in failures))
        for options, expected in (
            (dict(models=[]), "settings.models"),
            (dict(agent_directory=[]), "Settings are invalid"),
        ):
            with self.subTest(options=options):
                report = check(self.settings(**options))
                failures = [message for passed, message in report if not passed]
                self.assertTrue(any(expected in message for message in failures), report)
        broken = self.root / "broken.json"
        for content, expected in (("{", "unreadable"), ("[]", "JSON object")):
            with self.subTest(content=content):
                broken.write_text(content)
                report = check(str(broken))
                failures = [message for passed, message in report if not passed]
                self.assertTrue(any(expected in message for message in failures), report)

    def test_installation_checks_effective_paths_and_keeps_existing_probe_profile(self):
        options = json.loads(
            Path(self.settings(agent_directory="profiles", run_base="runs")).read_text()
        )
        self.profiles.mkdir()
        existing = self.profiles / "taskrail-check.md"
        original = '---\n{"permission": {}}\n---\nMy own agent.\n'
        existing.write_text(original)

        current = check_connection(options, self.root)
        self.assertTrue((self.root / "runs").is_dir())
        self.assertEqual(existing.read_text(), original)
        self.assertEqual(list(self.profiles.iterdir()), [existing])
        marker = self.root / CHECK_MARKER
        self.assertFalse(marker.exists())
        marker.write_text(current + "\n")
        with mock.patch("taskrail.cli_health.Connection.diagnostics") as diagnostics:
            self.assertIsNone(check_connection(dict(options, stage_timeout=55), self.root))
            diagnostics.assert_not_called()
            diagnostics.return_value = [(False, "Permission enforcement failed")]
            for change in (
                {"models": {"planner": "provider/research"}},
                {"agent_env_allow": ["CUSTOM_CLI_TOKEN"]},
                {"agent_directory": "new-profiles"},
                {"run_base": "other-runs"},
            ):
                with (
                    self.subTest(change=change),
                    self.assertRaisesRegex(ValueError, "Permission enforcement failed"),
                ):
                    check_connection(dict(options, **change), self.root)
            with self.assertRaisesRegex(ValueError, "Permission enforcement failed"):
                check_connection(options, self.root, force=True)
        self.assertEqual(marker.read_text(), current + "\n")

    def test_checked_cli_file_replacement_invalidates_success_marker(self):
        script = self.root / "runner.py"
        script.write_text("pass")
        options = {"command": [sys.executable, str(script)]}
        marker = self.root / CHECK_MARKER
        with mock.patch(
            "taskrail.cli_health.Connection.diagnostics", return_value=[(True, "OK")]
        ) as checks:
            first = check_connection(options, self.root)
            marker.write_text(first)
            self.assertIsNone(check_connection(options, self.root))
            script.chmod(0o700)
            changed = check_connection(options, self.root)
            self.assertNotEqual(changed, first)
            marker.write_text(changed)
            script.unlink()
            self.assertNotEqual(check_connection(options, self.root), changed)
            self.assertEqual(checks.call_count, 3)

    def test_cli_environment_changes_trigger_a_new_probe(self):
        options = json.loads(Path(self.settings(agent_env_allow=["CUSTOM_CLI_TOKEN"])).read_text())
        config = self.root / "cli.json"
        config.write_text("{}")
        with (
            mock.patch.dict(os.environ, {"OPENCODE_CONFIG": str(config)}),
            mock.patch("taskrail.cli_health.Connection.diagnostics", return_value=[(True, "OK")]),
        ):
            saved = check_connection(options, self.root)
            (self.root / CHECK_MARKER).write_text(saved)
            for name in ("OPENCODE_CONFIG_CONTENT", "OPENCODE_CONFIG_DIR", "CUSTOM_CLI_TOKEN"):
                with (
                    self.subTest(name=name),
                    mock.patch.dict(os.environ, {name: "another-selection"}),
                ):
                    self.assertNotEqual(check_connection(options, self.root), saved)
            config.write_text('{"agent": {}}')
            self.assertNotEqual(check_connection(options, self.root), saved)

    def test_installation_rejects_unsafe_effective_rules(self):
        options = json.loads(Path(self.settings()).read_text())
        options["command"][-1] = "unsafe"
        with self.assertRaisesRegex(ValueError, "Effective opencode permissions differ"):
            check_connection(options, self.root)
        self.assertFalse((self.root / CHECK_MARKER).exists())
        self.assertEqual(list(self.profiles.glob("*.md")), [])

    def test_init_writes_private_settings_once(self):
        fake = self.root / "opencode"
        fake.write_text(f"#!{sys.executable}\nprint('1.19.3')\n")
        fake.chmod(0o755)
        target = init(str(fake), ["planner=p/a", "reviewer=p/b"])
        written = json.loads(target.read_text())
        self.assertEqual(written["command"], [str(fake)])
        self.assertEqual(written["models"], {"planner": "p/a", "reviewer": "p/b"})
        self.assertNotIn("format_repair_tools", written)
        self.assertNotIn("agent_source", written)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.assertRaisesRegex(ValueError, "--force"):
            init(str(fake))
        self.assertEqual(init(str(fake), force=True), target)


if __name__ == "__main__":
    unittest.main()
