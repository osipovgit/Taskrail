"""Resume resolves typed check IDs against sealed settings before live configuration."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from countersign.application import check_configuration, check_recipes, run_setup
from countersign.core.files import atomic_json
from countersign.core.requirements import requirement

BASE = Path(__file__).resolve().parents[1]


class ResumeCheckConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.run = self.base / "run"
        (self.run / "00-input").mkdir(parents=True)
        self.task = self.run / "00-input/task.md"
        self.settings = self.base / "settings.json"
        command = dict(cwd=str(self.root), argv=[sys.executable, "--version"], timeout_seconds=5)
        recipe = dict(kind="local", phase="check", request=command, adapter="exit-code")
        self.spec = dict(
            id="C-health",
            recipe_id="health",
            criteria=[requirement("Health check passes", "runtime")["id"]],
            phase="check",
            parameters={},
        )
        catalog = check_recipes.parse_catalog(
            dict(check_recipes={"health": recipe}, verify_commands=[command])
        )
        self.frozen = dict(
            check_recipes=catalog, verify_commands=[command], check_specs=[self.spec]
        )
        state = dict(roots={"project": str(self.root)}, status="TIMEOUT", check_specs=[self.spec])
        check_configuration.capture(self.frozen, state)
        atomic_json(self.run / "run.json", state)
        atomic_json(self.run / "00-input/settings.json", self.frozen)
        header = dict(
            roots=state["roots"], verification=["Health check passes"], check_specs=[self.spec]
        )
        self.task.write_text("```countersign-task\n" + json.dumps(header) + "\n```\nVerify health")
        atomic_json(
            self.settings,
            dict(
                command=[
                    sys.executable,
                    str(BASE / "tests/fake_live.py"),
                    "--profiles",
                    str(self.base / "profiles"),
                    "--mode",
                    "ok",
                ],
                check_recipes={},
                verify_commands=[],
            ),
        )
        self.request = dict(task=self.task, settings=self.settings, run_dir=self.run, resume=True)

    def test_resume_uses_sealed_recipe_removed_from_current_settings(self):
        config, run = run_setup.configure(self.request)
        self.assertEqual(run, self.run)
        self.assertEqual(config["check_recipes"], self.frozen["check_recipes"])
        self.assertEqual(config["verify_commands"], self.frozen["verify_commands"])
        self.assertEqual(config["check_specs"], [self.spec])
        with self.assertRaisesRegex(ValueError, "Unknown check recipe"):
            run_setup.configure(dict(self.request, resume=False))

    def test_tampered_frozen_catalog_fails_before_loading_agent_settings(self):
        atomic_json(self.run / "00-input/settings.json", dict(self.frozen, check_recipes={}))
        with (
            patch("countersign.application.task_config.launch_settings") as launch,
            self.assertRaisesRegex(ValueError, "Frozen check settings changed"),
        ):
            run_setup.configure(self.request)
        launch.assert_not_called()


if __name__ == "__main__":
    unittest.main()
