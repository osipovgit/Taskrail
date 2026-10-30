"""Synthetic credentials never survive runtime, custom prefix or project mounts."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.core import protected_paths
from taskrail.infrastructure import sandbox_mounts, sandbox_paths, sandbox_secrets

SECRETS = (
    ".m2/settings.xml",
    ".m2/settings-security.xml",
    ".gradle/gradle.properties",
    ".cargo/credentials.toml",
    ".cargo/config.toml",
    ".gem/credentials",
    ".npmrc",
    ".netrc",
    ".local/share/opencode/auth.json",
    "visible/secrets.env",
    ".m2/repository/auth.json",
    ".gradle/caches/gradle.properties",
    ".cargo/registry/.npmrc",
)


class SandboxMountTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        home_patch = patch.dict(os.environ, HOME=str(self.home))
        home_patch.start()
        self.addCleanup(home_patch.stop)
        for name in SECRETS:
            secret = self.home / name
            secret.parent.mkdir(parents=True, exist_ok=True)
            secret.write_text("DUMMY_ONLY")

    def test_home_mounts_only_runtime_cache_components(self):
        mounts = sandbox_paths.home()
        self.assertIn(self.home / ".m2/repository", mounts)
        self.assertIn(self.home / ".gradle/caches", mounts)
        for name in SECRETS[:10]:
            self.assertFalse(any((self.home / name).is_relative_to(root) for root in mounts))
        masks = sandbox_mounts.credentials("/usr/bin/true", ())
        for name in SECRETS[10:]:
            self.assertIn(str(self.home / name), masks)

    def test_declaring_home_as_a_root_does_not_restore_known_credentials(self):
        options = sandbox_mounts.project(
            {"p": self.home}, True, protected_paths.read_patterns(["secrets.env"]), False
        )
        for name in SECRETS:
            self.assertIn(str(self.home / name), options)
        self.assertIn("/dev/null", options)

    def test_private_directory_aliases_cannot_become_runtime_mounts(self):
        private = self.home / ".ssh"
        private.mkdir()
        (private / "id_ed25519").write_text("DUMMY_ONLY")
        link = self.home / ".local/bin"
        link.parent.mkdir(exist_ok=True)
        link.symlink_to(private, target_is_directory=True)
        self.assertNotIn(link, sandbox_paths.home())
        self.assertEqual(sandbox_paths.installation(str(link / "id_ed25519")), [])

    def test_custom_virtualenv_components_are_available_but_prefix_secrets_are_hidden(self):
        prefix = self.home / "envs/linter"
        for name in ("bin", "lib", "share"):
            (prefix / name).mkdir(parents=True)
        (prefix / "pyvenv.cfg").write_text("home = /usr/bin\n")
        (prefix / "bin/ansible-lint").write_text("#!/usr/bin/python3\n")
        secret = prefix / "lib/.npmrc"
        secret.write_text("DUMMY_ONLY")
        paths = sandbox_paths.installation(str(prefix / "bin/ansible-lint"))
        self.assertEqual(
            set(paths), {prefix / name for name in ("bin", "lib", "share", "pyvenv.cfg")}
        )
        self.assertNotIn(prefix, paths)
        self.assertIn(str(secret), sandbox_mounts.credentials(str(prefix / "bin/ansible-lint"), ()))

    def test_a_local_bin_tool_cannot_reopen_provider_credentials(self):
        (self.home / ".local/bin").mkdir()
        paths = sandbox_paths.installation(str(self.home / ".local/bin/ansible-lint"))
        self.assertNotIn(self.home / ".local/share", paths)

    def test_runtime_alias_masks_both_the_visible_binding_and_original_location(self):
        original = self.home / "original"
        original.mkdir()
        secret = original / "credentials.toml"
        secret.write_text("DUMMY_ONLY")
        alias = self.home / "alias"
        alias.symlink_to(original, target_is_directory=True)
        masks = sandbox_secrets.masks((alias, original), ())
        self.assertIn(str(alias / secret.name), masks)
        self.assertIn(str(secret), masks)

    def test_scan_resolves_directories_once_and_discovers_new_credentials(self):
        runtime = self.home / "runtime"
        runtime.mkdir()
        for number in range(100):
            (runtime / f"module_{number}.py").touch()
        resolved = Path.resolve
        with patch.object(Path, "resolve", autospec=True, side_effect=resolved) as calls:
            self.assertEqual(sandbox_secrets.masks((runtime, runtime), ()), [])
        self.assertEqual(calls.call_count, 1)
        secret = runtime / "auth.json"
        secret.write_text("DUMMY_ONLY")
        self.assertIn(str(secret), sandbox_secrets.masks((runtime,), ()))

    def test_ordinary_alias_to_a_credential_file_is_masked_after_resolution(self):
        runtime = self.home / "runtime"
        runtime.mkdir()
        secret = self.home / ".netrc"
        alias = runtime / "module.py"
        alias.symlink_to(secret)
        masks = sandbox_secrets.masks((runtime,), ())
        self.assertNotIn(str(alias), masks)
        self.assertIn(str(secret), masks)
