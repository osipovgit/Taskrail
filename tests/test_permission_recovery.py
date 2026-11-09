"""A failed permission transport may retry; an unsafe policy never starts a model."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.infrastructure import permission_check, permission_probe

LISTING = """import json, sys, time
from pathlib import Path
assert sys.argv[1:] == ['--profile', 'work', 'agent', 'list'], sys.argv
counter = Path('calls.txt')
number = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(number))
mode = Path('mode.txt').read_text()
if mode == 'fail' or (number == 1 and mode in {'exit', 'timeout'}):
    print('Temporary cli failure', flush=True)
    if mode == 'timeout':
        time.sleep(30)
    sys.exit(7)
print('managed (primary)')
if mode == 'malformed':
    print('not JSON')
else:
    print(json.dumps([dict(permission='*', pattern='*', action=mode if mode == 'allow' else 'deny')]))
"""


class PermissionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        script = self.root / "cli.py"
        script.write_text(LISTING)
        self.launch = dict(
            command=[sys.executable, str(script), "--profile", "work"],
            agent_env_allow=(),
            transport_retries=2,
            stop_run=self.root,
        )
        self.expected = [dict(permission="*", pattern="*", action="deny")]
        self.log = self.root / "permissions.log"

    def verify(self, mode):
        (self.root / "mode.txt").write_text(mode)
        return permission_check.verify_launch(
            self.launch, self.root, "managed", self.expected, self.log
        )

    def test_failed_cli_and_timeout_recover_without_changing_the_policy(self):
        for mode in ("exit", "timeout"):
            with self.subTest(mode=mode):
                (self.root / "calls.txt").unlink(missing_ok=True)
                with patch.object(permission_probe, "LISTING_SECONDS", 0.3):
                    self.assertEqual(self.verify(mode), self.expected)
                self.assertEqual((self.root / "calls.txt").read_text(), "2")
                failed = self.root / "permissions-failed-1.log"
                self.assertIn("Temporary cli failure", failed.read_text())
                self.assertIn(json.dumps(self.expected), self.log.read_text())

    def test_persistent_failure_uses_existing_retry_setting_and_keeps_all_logs(self):
        with self.assertRaisesRegex(ValueError, "exited with code 7"):
            self.verify("fail")
        self.assertEqual((self.root / "calls.txt").read_text(), "3")
        for number in range(1, 4):
            failure = self.root / f"permissions-failed-{number}.log"
            self.assertIn("Temporary cli failure", failure.read_text())
        self.launch["transport_retries"] = 0
        with self.assertRaises(permission_probe.Unavailable):
            self.verify("fail")
        self.assertEqual((self.root / "calls.txt").read_text(), "4")

    def test_unsafe_and_malformed_successful_listings_are_not_retried(self):
        for mode, error in (("allow", "default-deny"), ("malformed", "Cannot parse")):
            with self.subTest(mode=mode):
                (self.root / "calls.txt").unlink(missing_ok=True)
                with self.assertRaisesRegex(ValueError, error):
                    self.verify(mode)
                self.assertEqual((self.root / "calls.txt").read_text(), "1")
                self.assertEqual(list(self.root.glob("permissions-failed-*.log")), [])

    def test_stop_after_a_failed_probe_prevents_another_process(self):
        def stop(message):
            (self.root / "stop.request").touch()

        with (
            patch.object(permission_probe, "say", side_effect=stop),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.verify("fail")
        self.assertEqual((self.root / "calls.txt").read_text(), "1")

    def test_missing_executable_is_not_a_retryable_probe(self):
        self.launch["command"] = [str(self.root / "missing-cli")]
        with self.assertRaises(FileNotFoundError):
            self.verify("exit")
        self.assertEqual(list(self.root.glob("permissions-failed-*.log")), [])
