"""On-request corpus transport, root boundaries and syntax checks."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from corpus import CORPUS, fields, materialize, snapshot, submission

from taskrail.application import builtin_checks, project_map
from taskrail.core import task_spec
from taskrail.web import task_form


class ScenarioInputs(unittest.TestCase):
    def test_exported_independent_tasks_preserve_literal_fields_and_flags(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "export"
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("export.py")), str(destination)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            for case in CORPUS["tasks"]:
                with self.subTest(task=case["id"]):
                    text = (destination / case["id"] / "task.md").read_text()
                    meta = json.loads(text.split("\n", 1)[1].split("\n```", 1)[0])
                    spec = task_spec.resolve(text, meta)
                    actual = {field["name"]: field["text"] for field in spec["fields"]}
                    for name in ("goal", "criteria", "constraints"):
                        self.assertEqual(actual[name], case[name])
                    for alias, root in meta["roots"].items():
                        self.assertIn(case["id"], Path(root).parts)
                        self.assertTrue(Path(root).is_dir())
                        if alias == "service":
                            self.assertTrue(os.access(Path(root) / "scripts/start.sh", os.X_OK))
                    if case["mode"] in {"answer", "design"}:
                        self.assertIs(meta["read_only"], True)
                    if case["mode"] == "design":
                        self.assertIs(meta["design"], True)
                    if case["mode"] == "split":
                        self.assertIs(meta["decompose"], True)
            repeated = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("export.py")), str(destination)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertNotEqual(repeated.returncode, 0)

    def test_project_map_does_not_expose_protected_inputs_or_change_sources(self):
        for case in CORPUS["tasks"]:
            with self.subTest(task=case["id"]), tempfile.TemporaryDirectory() as directory:
                base = Path(directory)
                roots = materialize(base, case)
                before = snapshot(roots)
                text, _ = submission(fields(case, roots), base / "runs")
                meta = json.loads(text.split("\n", 1)[1].split("\n```", 1)[0])
                resolved = task_spec.resolve(text, meta)
                shown = project_map.render(roots, resolved["requirements"])
                self.assertNotIn("FIXTURE_ONLY", shown)
                self.assertNotIn("/.env", shown)
                for alias in roots:
                    self.assertIn(f"## {alias}:", shown)
                self.assertEqual(snapshot(roots), before)

    def test_syntax_outcomes_distinguish_failure_from_unchecked_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            for case in CORPUS["syntax_cases"]:
                with self.subTest(file=case["name"]):
                    path = Path(directory) / case["name"]
                    path.write_text(case["text"])
                    outcome = builtin_checks.file_check(str(path), path)
                    self.assertEqual(outcome["status"], case["expected"], outcome)

    def test_eight_roots_with_alias_collisions_are_unambiguous(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            entries = []
            for number in range(8):
                path = base / str(number) / "same name"
                path.mkdir(parents=True)
                entries.append(dict(path=str(path)))
            text, _ = task_form.build_task(dict(roots=entries, goal="Inspect."), base / "runs")
            meta = json.loads(text.split("\n", 1)[1].split("\n```", 1)[0])
            self.assertEqual(len(meta["roots"]), 8)
            with self.assertRaisesRegex(ValueError, "between one and eight"):
                task_form.build_task(dict(roots=[*entries, entries[0]], goal="Inspect."), base)
            with self.assertRaisesRegex(ValueError, "overlap"):
                task_form.build_task(dict(roots=[entries[0], entries[0]], goal="Inspect."), base)
