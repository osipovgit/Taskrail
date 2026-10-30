"""Recovery views and correction budgets cannot inspect paths outside run storage."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.web import correction_state, run_files, run_view


class RecoveryPathTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name) / "runs"
        self.base.mkdir()
        self.run = self.base / "valid.run"
        self.run.mkdir()
        self.outside = self.base.with_name("runs-other")
        self.outside.mkdir()

    def test_containment_rejects_parent_absolute_and_sibling_prefix_escapes(self):
        for name in ("..", "../runs-other", str(self.outside), "."):
            with self.subTest(name=name), self.assertRaises(ValueError):
                run_files.contained(self.base, name)
        self.assertEqual(run_files.contained(self.base, self.run.name), self.run)
        self.assertEqual(run_files.contained(self.base, "not-started"), self.base / "not-started")

    def test_recovery_revalidates_run_before_inspecting_a_replaced_directory(self):
        def replace(*unused):
            self.run.rmdir()
            self.run.symlink_to(self.outside, target_is_directory=True)
            raise ValueError("Invalid saved run")

        with (
            patch.object(run_view, "readable_view", side_effect=replace),
            patch.object(run_view.run_errors, "view") as recovery,
            self.assertRaises(ValueError),
        ):
            run_view.run_view(self.base, self.run.name)
        recovery.assert_not_called()

    def test_containment_rejects_aliases_even_when_their_target_is_inside_storage(self):
        alias = self.base / "alias"
        alias.symlink_to(self.run, target_is_directory=True)
        for name in ("alias", "alias/run.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                run_files.contained(self.base, name)

    def test_correction_budget_uses_only_local_frozen_settings(self):
        self.assertEqual(correction_state.budget(self.run), 0)
        inputs = self.run / "00-input"
        inputs.mkdir()
        settings = inputs / "settings.json"
        settings.write_text(json.dumps(dict(max_repairs=2)))
        self.assertEqual(correction_state.budget(self.run), 2)
        settings.unlink()
        settings.symlink_to(self.outside / "missing.json")
        with self.assertRaises(ValueError):
            correction_state.budget(self.run)

    def test_correction_budget_rejects_intermediate_authority_aliases(self):
        settings = self.outside / "settings.json"
        settings.write_text(json.dumps(dict(max_repairs=5)))
        (self.run / "00-input").symlink_to(self.outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            correction_state.budget(self.run)

    def test_correction_budget_rejects_in_run_settings_aliases(self):
        local = self.run / "saved-inputs"
        local.mkdir()
        (local / "settings.json").write_text(json.dumps(dict(max_repairs=5)))
        (self.run / "00-input").symlink_to(local, target_is_directory=True)
        with self.assertRaises(ValueError):
            correction_state.budget(self.run)
