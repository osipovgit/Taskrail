"""Run a corpus task through the application using a disposable scripted CLI."""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from corpus import fields, materialize, snapshot, submission

from taskrail.application.live import execute_task
from taskrail.core.files import atomic_json
from taskrail.web import parent_context

BASE = Path(__file__).resolve().parents[2]


class ScenarioFixture:
    def prepare(self, case):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.case = case
        self.roots = materialize(self.base, case)
        self.originals = snapshot(self.roots)
        self.runs = self.base / "runs"
        self.runs.mkdir()
        scenario = self.base / "scenario.json"
        atomic_json(scenario, case)
        self.settings = self.base / "settings.json"
        atomic_json(
            self.settings,
            dict(
                command=[
                    sys.executable,
                    str(BASE / "tests/fake_live.py"),
                    "--profiles",
                    str(self.base / "profiles"),
                    "--mode",
                    "scenario",
                    "--scenario",
                    str(scenario),
                ],
                agent_directory=str(self.base / "profiles"),
                timeout_seconds=10,
                max_repairs=0,
            ),
        )

    def execute(self, name="task", payload=None):
        folder = self.base / "submitted" / name
        folder.mkdir(parents=True)
        text, context = submission(payload or fields(self.case, self.roots), self.runs)
        task = folder / "task.md"
        task.write_text(text)
        parent_context.write(folder, context)
        with (
            patch("taskrail.executor.client.request", side_effect=AssertionError("Remote call")),
            patch("taskrail.interactions.approvals.wait", return_value=dict(decision="deny")),
        ):
            run, status = execute_task(task, self.settings, run_dir=self.runs / name)
        state = json.loads((run / "run.json").read_text())
        return run, status, state

    def assert_preserved(self, changed):
        actual = snapshot(self.roots)
        expected = dict(self.originals)
        expected.update({name: content.encode() for name, content in changed.items()})
        self.assertEqual(actual, expected)
