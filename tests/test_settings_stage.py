"""First-install settings, imported roles, bundled-role switching and the service PATH."""

import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from taskrail.deployment.settings_stage import main
from taskrail.infrastructure.opencode_cli import COMMAND_ERROR

BASE = Path(__file__).resolve().parents[1]


class SettingsStageTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.config = self.home / "config"
        self.config.mkdir()
        self.app = self.home / "app"
        self.binaries = self.home / "bin"
        self.binaries.mkdir()
        for name in ("opencode", "example"):
            executable = self.binaries / name
            executable.write_text("#!/bin/sh\nprintf '1.19.3\\n'\n")
            executable.chmod(0o755)
        path = patch.dict(os.environ, PATH=f'{self.binaries}:/usr/bin:/x"y\\z')
        path.start()
        self.addCleanup(path.stop)

    def initialize(self, supplied="", agents="keep", *flags):
        arguments = [str(BASE), str(self.config), supplied, str(self.app), agents]
        with tempfile.TemporaryDirectory() as stage, redirect_stdout(io.StringIO()) as output:
            prepared = Path(stage) / "settings"
            main([*arguments, str(prepared), *flags])
            shutil.copytree(prepared, self.config, dirs_exist_ok=True)
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

    def test_select_executable_on_install_and_update(self):
        selected = self.binaries / "opencode-myfork"
        shutil.copy(self.binaries / "opencode", selected)
        supplied = self.home / "input.json"
        supplied.write_text('{"command":["missing","--old"],"timeout_seconds":7}')
        self.initialize(str(supplied), "keep", "--opencode=opencode-myfork")
        self.assertEqual(self.settings()["command"], [str(selected)])
        self.initialize("", "keep", "--opencode=opencode")
        self.assertEqual(self.settings()["command"], [str(self.binaries / "opencode")])
        with self.assertRaisesRegex(ValueError, "not found"):
            self.initialize("", "keep", "--opencode=absent-cli")
        self.assertEqual(self.settings()["timeout_seconds"], 7)
        self.assertEqual(self.settings()["command"], [str(self.binaries / "opencode")])
        supplied.write_text('{"command":["opencode"],"timeout_seconds":9,"run_base":"runs"}')
        self.initialize(str(supplied), "keep", "--apply-settings")
        self.assertEqual(self.settings()["timeout_seconds"], 9)
        self.assertEqual(self.settings()["run_base"], "runs")

    def test_imported_settings_copy_roles_once_and_keep_relative_folders_meaningful(self):
        imported = self.home / "imported"
        shutil.copytree(BASE / "taskrail/agents", imported / "roles")
        custom = "Instruction contract: 1.\nImported planner"
        (imported / "roles/planner.md").write_text(custom)
        supplied = imported / "settings.json"
        supplied.write_text(
            json.dumps(
                dict(
                    command=["example", "--flag"],
                    agent_source="roles",
                    run_base="runs",
                    agent_directory="/absolute/profiles",
                    timeout_seconds=5,
                )
            )
        )
        (imported / "roles/unrelated.env").write_text("local-only configuration")
        (imported / "roles/unreadable").symlink_to(self.home / "missing")
        self.initialize(str(supplied))
        self.assertEqual(
            {path.name for path in (self.config / "agents").iterdir()},
            {path.name for path in (BASE / "taskrail/agents").glob("*.md")},
        )
        settings = self.settings()
        self.assertEqual(settings["command"], [str(self.binaries / "example"), "--flag"])
        self.assertEqual(settings["timeout_seconds"], 5)
        self.assertEqual(settings["agent_source"], str(self.config / "agents"))
        self.assertEqual(settings["run_base"], str(imported / "runs"))
        self.assertEqual(settings["agent_directory"], "/absolute/profiles")
        self.assertEqual((self.config / "agents/planner.md").read_text(), custom)
        (self.config / "settings.json").unlink()
        (imported / "roles/planner.md").write_text("Changed planner")
        self.initialize(str(supplied))
        self.assertEqual((self.config / "agents/planner.md").read_text(), custom)

    def test_exported_bundled_settings_import_without_an_adjacent_roles_folder(self):
        supplied = self.home / "exported.json"
        supplied.write_text(json.dumps(dict(command=["example"], run_base="runs")))
        self.initialize(str(supplied))
        settings = self.settings()
        self.assertEqual(settings["agent_source"], str(self.app / "current/taskrail/agents"))
        self.assertEqual(settings["run_base"], str(self.home / "runs"))
        self.assertFalse((self.config / "agents").exists())

    def test_fresh_stages_import_without_touching_installed_files(self):
        roles = self.home / "roles"
        shutil.copytree(BASE / "taskrail/agents", roles)
        supplied = self.home / "exported.json"
        supplied.write_text(json.dumps(dict(command=["example"], agent_source="roles")))
        arguments = [str(BASE), str(self.config), str(supplied), str(self.app), "keep"]
        main([*arguments, str(self.home / "prepared"), "--fresh"])
        self.assertEqual(list(self.config.iterdir()), [])
        shutil.rmtree(roles)
        (self.config / "agents").mkdir()
        with self.assertRaisesRegex(ValueError, "Missing source agent"):
            main([*arguments, str(self.home / "rejected"), "--fresh"])
        self.assertFalse((self.config / "settings.json").exists())

    def test_updates_preserve_existing_settings_and_service_environment(self):
        target = self.config / "settings.json"
        target.write_text('{"command": ["example"], "max_integration_corrections": 1}')
        environment = self.config / "service.env"
        environment.write_text("PATH=/kept\n")
        self.initialize(str(self.home / "missing.json"))
        self.assertEqual(
            target.read_text(), '{"command": ["example"], "max_integration_corrections": 1}'
        )
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
        self.assertEqual(len(list(self.config.glob("settings.json.backup-*"))), 1)

    def test_updates_remove_retired_keys_without_retaining_or_overwriting_extensions(self):
        path = self.config / "settings.json"
        path.write_text(json.dumps(dict(command=["example"], extension={"foo": 1}, max_repairs=2)))
        output = self.initialize()
        self.assertIn("max_repairs", output)
        self.assertEqual(self.settings(), dict(command=["example"], extension={"foo": 1}))
        self.assertFalse(list(self.config.glob("settings.json.backup-*")))
        self.assertEqual(self.initialize(), "")

    def test_first_install_selecting_bundled_roles_does_not_copy_custom_files(self):
        supplied = self.home / "import.json"
        supplied.write_text(json.dumps(dict(command=["example"], agent_source="unused")))
        self.initialize(str(supplied), agents="bundled")
        self.assertEqual(self.settings()["agent_source"], str(self.app / "current/taskrail/agents"))
        self.assertFalse((self.config / "agents").exists())
        self.assertFalse(list(self.config.glob("settings.json.backup-*")))

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
