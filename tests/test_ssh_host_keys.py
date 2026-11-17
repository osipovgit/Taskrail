"""First-use SSH trust, independent of the lifetime of a ticket or executor process."""

import subprocess
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from taskrail.executor import host_keys, transport


class FirstUseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.pinned = self.root / "known_hosts"
        self.pinned.touch()
        for field, path in (("PINNED", self.pinned), ("LEARNED", self.root / "learned")):
            substitute = patch.object(host_keys, field, path)
            substitute.start()
            self.addCleanup(substitute.stop)
        self.host = dict(hostname="Node.Example", port=2222)

    def test_reconnect_uses_the_first_keys_for_the_same_address_and_port(self):
        with patch.object(host_keys, "scan", return_value=b"first keys\n") as scan:
            path = host_keys.trust_file(self.host)
            self.assertEqual(path.read_bytes(), b"first keys\n")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            changed_login = dict(hostname="node.example", port=2222, username="another")
            self.assertEqual(host_keys.trust_file(changed_login), path)
            scan.assert_called_once_with("node.example", 2222)
            self.assertNotEqual(host_keys.trust_file(dict(self.host, port=22)), path)

    def test_an_administrator_pin_overrides_previous_first_use_and_skips_discovery(self):
        key = self.root / "example"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        with patch.object(host_keys, "scan", return_value=b"old keys\n") as scan:
            host_keys.trust_file(self.host)
            self.pinned.write_text("[node.example]:2222 " + key.with_suffix(".pub").read_text())
            self.assertEqual(host_keys.trust_file(self.host), Path("/dev/null"))
            scan.assert_called_once()

    def test_concurrent_enrollment_never_combines_or_overwrites_competing_identities(self):
        overlap = Barrier(2)

        def scan(hostname, port):
            return f"candidate {overlap.wait(timeout=5)}\n".encode()

        with patch.object(host_keys, "scan", side_effect=scan), ThreadPoolExecutor(2) as pool:
            selected = list(pool.map(host_keys.trust_file, [self.host, self.host]))
        self.assertEqual(selected[0], selected[1])
        self.assertIn(selected[0].read_bytes(), (b"candidate 0\n", b"candidate 1\n"))
        self.assertEqual(list(host_keys.LEARNED.iterdir()), [selected[0]])

    def test_no_authentication_or_action_when_learning_or_saving_fails(self):
        action = dict(script="uptime", files={})
        failures = (
            patch.object(host_keys, "scan", side_effect=host_keys.HostKeyError("unreachable")),
            patch.object(host_keys, "publish", side_effect=OSError("disk full")),
        )
        with patch.object(transport.streams, "execute") as execute:
            for failure in failures:
                with patch.object(host_keys, "scan", return_value=b"candidate\n"), failure:
                    self.assertEqual(transport.execute(self.host, action)["status"], "FAILED")
            self.pinned.unlink()
            with patch.object(host_keys, "scan") as scan:
                self.assertEqual(transport.execute(self.host, action)["status"], "FAILED")
                scan.assert_not_called()
            execute.assert_not_called()
