import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from taskrail.onboarding import check, init

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
        with mock.patch("taskrail.onboarding.permission_result") as permission:
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

    def test_init_writes_private_settings_once(self):
        fake = self.root / "opencode"
        fake.write_text(f"#!{sys.executable}\nprint('1.19.3')\n")
        fake.chmod(0o755)
        target = init(str(fake), ["planner=p/a", "reviewer=p/b"], "read")
        written = json.loads(target.read_text())
        self.assertEqual(written["command"], [str(fake)])
        self.assertEqual(written["models"], {"planner": "p/a", "reviewer": "p/b"})
        self.assertEqual(written["format_repair_tools"], "read")
        self.assertNotIn("agent_source", written)
        self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
        with self.assertRaisesRegex(ValueError, "--force"):
            init(str(fake))
        self.assertEqual(init(str(fake), force=True), target)


if __name__ == "__main__":
    unittest.main()
