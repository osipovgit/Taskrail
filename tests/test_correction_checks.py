"""Later acceptance repeats runtime bindings from authenticated corrective plans."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import check_configuration, check_specs, correction_checks, planned_checks
from taskrail.application.reviewed_artifacts import SEAL
from taskrail.core.files import atomic_json, digest


class CorrectionCheckTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.parent = self.base / "parent"
        self.child = self.base / "correction"
        for run in (self.parent, self.child):
            (run / "00-input").mkdir(parents=True)
        command = dict(cwd="/project", argv=["python3", "--version"], timeout_seconds=5)
        recipe = dict(kind="local", phase="check", adapter="exit-code", request=command)
        self.settings = dict(check_recipes=dict(health=recipe, audit=recipe), verify_commands=[])
        self.requirements = [dict(id="runtime-1", kind="runtime", text="The runtime passes")]
        self.original = check_specs.from_selections(
            [dict(recipe_id="health", criteria=["runtime-1"])],
            self.settings["check_recipes"],
            self.requirements,
        )
        self.state = dict(requirements=self.requirements, check_specs=self.original)
        check_configuration.capture(self.settings, self.state)
        self.corrected = dict(
            status="NO_CHANGES_REQUIRED",
            phase="correction",
            check_parent="parent",
            results=dict(plan="plan.json"),
            required_local_checks=[],
            check_specs=[dict(recipe_id="untrusted-state-only")],
        )
        check_configuration.capture(self.settings, self.corrected)
        for run in (self.parent, self.child):
            atomic_json(run / "00-input/settings.json", self.settings)
        atomic_json(
            self.parent / "epic.json", dict(corrections=[dict(run="correction", review="rejected")])
        )
        self.plan = dict(
            steps=[], check_selections=[dict(recipe_id="audit", criteria=["runtime-1"])]
        )
        self.save_plan()

    def save_plan(self):
        atomic_json(self.child / "plan.json", self.plan)
        self.corrected[SEAL] = digest((self.child / "plan.json").read_bytes())
        atomic_json(self.child / "run.json", self.corrected)

    def test_fresh_integration_and_next_correction_keep_sealed_runtime_additions(self):
        expected = ["health", "audit"]
        for excluded in (None, "next-correction"):
            selected = correction_checks.selected(self.parent, self.state, excluded)
            self.assertEqual([entry["recipe_id"] for entry in selected], expected)
            self.assertTrue(all(entry["criteria"] == ["runtime-1"] for entry in selected))
        self.assertEqual(self.state["check_specs"], self.original)
        self.assertEqual(
            correction_checks.selected(self.parent, self.state, "correction"), self.original
        )

    def test_correction_cannot_add_unknown_criteria_commands_or_recipes(self):
        for selection in (
            dict(recipe_id="audit", criteria=["unknown"]),
            dict(recipe_id="unknown", criteria=["runtime-1"]),
            dict(recipe_id="audit", criteria=["runtime-1"], argv=["arbitrary"]),
        ):
            with self.subTest(selection=selection):
                self.plan["check_selections"] = [selection]
                self.save_plan()
                with self.assertRaises(ValueError):
                    correction_checks.selected(self.parent, self.state)

    def test_changed_plan_or_frozen_catalog_cannot_replace_inherited_commands(self):
        (self.child / "plan.json").write_text(json.dumps(dict(self.plan, check_selections=[])))
        with self.assertRaisesRegex(ValueError, "reviewed plan changed"):
            correction_checks.selected(self.parent, self.state)
        self.save_plan()
        changed = json.loads(json.dumps(self.settings))
        changed["check_recipes"]["audit"]["request"]["argv"] = ["other-command"]
        check_configuration.capture(changed, self.corrected)
        atomic_json(self.child / "run.json", self.corrected)
        atomic_json(self.child / "00-input/settings.json", changed)
        with self.assertRaisesRegex(ValueError, "catalog changed"):
            correction_checks.selected(self.parent, self.state)

    def test_legacy_delivery_without_corrections_needs_no_new_frozen_artifacts(self):
        parent = self.base / "legacy"
        parent.mkdir()
        self.assertEqual(correction_checks.selected(parent, self.state), self.original)

    def test_new_correction_plan_cannot_add_or_replace_remote_bindings(self):
        catalog = dict(self.settings["check_recipes"])
        config = dict(phase="correction", check_recipes=catalog, task_spec=self.state)
        for phase in ("validation", "server"):
            with self.subTest(phase=phase):
                catalog["remote"] = dict(kind="jenkins", phase=phase)
                plan = dict(check_selections=[dict(recipe_id="remote", criteria=["runtime-1"])])
                with self.assertRaisesRegex(ValueError, "only local check recipes"):
                    planned_checks.validate(plan, config)
                planned_checks.validate(plan, dict(config, phase=None))
        planned_checks.validate(self.plan, config)
