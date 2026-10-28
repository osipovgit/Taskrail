"""First-install settings, imported roles, bundled-role switching and the service PATH."""

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from taskrail.deployment.settings_init import main
from taskrail.infrastructure.opencode_cli import COMMAND_ERROR

BASE = Path(__file__).resolve().parents[1]


class SettingsInitTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config = self.home / "config"
        self.config.mkdir()
        self.app = self.home / "app"
        self.binaries = self.home / "bin"
        self.binaries.mkdir()
        for name in ("opencode", "wrapper"):
            executable = self.binaries / name
            executable.write_text("#!/bin/sh\nexit 0\n")
            executable.chmod(0o755)
        path = patch.dict(os.environ, PATH=f'{self.binaries}:/usr/bin:/x"y\\z')
        path.start()
        self.addCleanup(path.stop)

    def initialize(self, supplied="", agents="keep"):
        arguments = [str(BASE), str(self.config), supplied, str(self.app), agents]
        with redirect_stdout(io.StringIO()) as output:
            main(arguments)
        return output.getvalue()

    def settings(self):
        return json.loads((self.config / "settings.json").read_text())

    def test_bundled_defaults_resolve_the_cli_and_point_at_release_roles(self):
        self.initialize()
        settings = self.settings()
        self.assertEqual(settings["command"], [str(self.binaries / "opencode")])
        self.assertEqual(settings["timeout_seconds"], 3600)
        self.assertEqual(settings["agent_source"], str(self.app / "current/taskrail/agents"))
        self.assertEqual((self.config / "settings.json").stat().st_mode & 0o777, 0o600)
        environment = self.config / "service.env"
        self.assertEqual(
            environment.read_text(),
            f'PATH="{self.binaries}:/usr/bin:/x\\"y\\\\z"\nTASKRAIL_WEB_PORT=8787\n',
        )
        self.assertEqual(environment.stat().st_mode & 0o777, 0o600)

    def test_imported_settings_copy_roles_once_and_keep_relative_folders_meaningful(self):
        imported = self.home / "imported"
        (imported / "roles").mkdir(parents=True)
        (imported / "roles/planner.md").write_text("Imported planner")
        supplied = imported / "settings.json"
        supplied.write_text(
            json.dumps(
                dict(
                    command=["wrapper", "--flag"],
                    agent_source="roles",
                    run_base="runs",
                    agent_directory="/absolute/profiles",
                    timeout_seconds=5,
                )
            )
        )
        self.initialize(str(supplied))
        settings = self.settings()
        self.assertEqual(settings["command"], [str(self.binaries / "wrapper"), "--flag"])
        self.assertEqual(settings["timeout_seconds"], 3600)
        self.assertEqual(settings["agent_source"], str(self.config / "agents"))
        self.assertEqual(settings["run_base"], str(imported / "runs"))
        self.assertEqual(settings["agent_directory"], "/absolute/profiles")
        self.assertEqual((self.config / "agents/planner.md").read_text(), "Imported planner")
        (self.config / "settings.json").unlink()
        (imported / "roles/planner.md").write_text("Changed planner")
        self.initialize(str(supplied))
        self.assertEqual((self.config / "agents/planner.md").read_text(), "Imported planner")

    def test_exported_bundled_settings_import_without_an_adjacent_roles_folder(self):
        supplied = self.home / "exported.json"
        supplied.write_text(json.dumps(dict(command=["wrapper"], run_base="runs")))
        self.initialize(str(supplied))
        settings = self.settings()
        self.assertEqual(settings["agent_source"], str(self.app / "current/taskrail/agents"))
        self.assertEqual(settings["run_base"], str(self.home / "runs"))
        self.assertFalse((self.config / "agents").exists())

    def test_fresh_preflight_validates_an_import_without_copying_or_writing(self):
        roles = self.home / "roles"
        roles.mkdir()
        supplied = self.home / "exported.json"
        supplied.write_text(json.dumps(dict(command=["wrapper"], agent_source="roles")))
        arguments = [str(BASE), str(self.config), str(supplied), str(self.app), "keep"]
        main([*arguments, "--check", "--fresh"])
        self.assertEqual(list(self.config.iterdir()), [])
        roles.rmdir()
        (self.config / "agents").mkdir()
        with self.assertRaisesRegex(ValueError, "Imported role directory"):
            main([*arguments, "--check", "--fresh"])
        self.assertFalse((self.config / "settings.json").exists())

    def test_updates_preserve_existing_settings_and_service_environment(self):
        target = self.config / "settings.json"
        target.write_text('{"command": ["custom"], "max_repairs": 1}')
        environment = self.config / "service.env"
        environment.write_text("PATH=/kept\n")
        self.initialize(str(self.home / "missing.json"))
        self.assertEqual(target.read_text(), '{"command": ["custom"], "max_repairs": 1}')
        self.assertEqual(environment.read_text(), "PATH=/kept\n")
        target.write_text("{")
        with self.assertRaises(json.JSONDecodeError):
            self.initialize()

    def test_bundled_roles_back_up_each_distinct_previous_file_once(self):
        target = self.config / "settings.json"
        target.write_text('{"agent_source": "/custom/roles"}')
        output = self.initialize(agents="bundled")
        backups = list(self.config.glob("settings.json.backup-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), '{"agent_source": "/custom/roles"}')
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        self.assertIn(str(backups[0]), output)
        self.assertEqual(self.settings()["agent_source"], str(self.app / "current/taskrail/agents"))
        self.assertFalse((self.config / "settings.json.next").exists())
        for _ in range(2):
            self.initialize(agents="bundled")
        self.assertEqual(len(list(self.config.glob("settings.json.backup-*"))), 2)

    def test_invalid_commands_and_multiline_path_are_rejected_before_writing(self):
        supplied = self.home / "settings.json"
        for command, message in (([], COMMAND_ERROR), (["absent-cli"], "absent-cli")):
            supplied.write_text(json.dumps(dict(command=command)))
            with self.assertRaisesRegex(ValueError, message):
                self.initialize(str(supplied))
            self.assertFalse((self.config / "settings.json").exists())
        (self.config / "settings.json").write_text("{}")
        with (
            patch.dict(os.environ, PATH=f"{self.binaries}\n/injected"),
            self.assertRaisesRegex(ValueError, "newlines"),
        ):
            self.initialize()
        self.assertFalse((self.config / "service.env").exists())


if __name__ == "__main__":
    unittest.main()
