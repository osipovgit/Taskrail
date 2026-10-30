"""Rejected combined reviews start bounded authenticated writers and fresh acceptance."""

import json
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

from test_isolated_split import IsolatedSplitFixture

from taskrail.application.live import execute_task
from taskrail.core import control
from taskrail.core.files import atomic_json
from taskrail.git import process
from taskrail.web import (
    correction_launch,
    delivery_launch,
    delivery_state,
    epic_record,
    integration_launch,
    start_controls,
)


class ImmediateLauncher:
    """Keep production submission links but execute fake-provider workers synchronously."""

    def __init__(self, fixture):
        self.fixture = fixture
        self.base = fixture.runs
        self.lock = threading.RLock()
        self.pending = []
        self.completed = []

    def submit(self, payload, before_start):
        name, mode = self.pending.pop(0)
        before_start(name)
        completed = self.fixture.execute(name, payload, mode)
        self.completed.append(completed)
        return dict(id=name, status=completed[1])


class IntegrationCorrectionTests(IsolatedSplitFixture, unittest.TestCase):
    def rejected(self, limit=1):
        self.provider = "fake_live.py"
        command = dict(cwd=str(self.root), argv=[sys.executable, "-c", "print('mandatory gate')"])
        self.split_settings = dict(
            max_repairs=limit,
            check_recipes=dict(
                health=dict(kind="local", phase="check", request=command, adapter="exit-code"),
                audit=dict(
                    kind="local",
                    phase="check",
                    request=dict(command, argv=[sys.executable, "-c", "print('corrective gate')"]),
                    adapter="exit-code",
                ),
            ),
        )
        parent, state = self.split()
        linked = {}
        for number, mode in enumerate(("ok", "new"), 1):
            _, status, finished = self.start_child(parent, state, linked, number, mode)
            self.assertEqual(status, "READY_FOR_REVIEW", finished.get("summary"))
        with epic_record.changing(parent) as epic:
            epic["auto_continue"] = True
        launcher = ImmediateLauncher(self)
        launcher.pending = [("rejected", "integration-reject")]
        integration_launch.start(launcher, parent)
        review, status, outcome = launcher.completed[-1]
        self.assertEqual(status, "CHANGES_REQUESTED", outcome.get("summary"))
        self.assertTrue(
            delivery_state.view(parent, state)["correction_available"] if limit else True
        )
        return parent, state, review, launcher

    def test_new_corrective_task_commits_then_repeats_combined_review(self):
        parent, state, _, launcher = self.rejected()
        launcher.pending = [("corrected", "integration-fix"), ("accepted", "ok")]
        delivery_launch.proceed(launcher, parent)
        correction, status, fixed = launcher.completed[-1]
        self.assertEqual(status, "READY_FOR_REVIEW", fixed.get("summary"))
        self.assertEqual(
            [entry["stage"] for entry in fixed["stages"]],
            ["planner", "plan-reviewer", "implementer", "check", "reviewer"],
        )
        self.assertEqual(len(fixed["commits"]), 1)
        self.assertEqual(fixed["required_local_checks"], ["health", "audit"])
        self.assertTrue(
            any(check.get("cwd") and check["status"] == "PASS" for check in fixed["checks"])
        )
        request = (correction / "01-plan/request.md").read_text()
        self.assertIn("Mode: integration correction", request)
        self.assertIn("Rejected integration findings", request)
        epic_record.set_auto(parent, False)
        delivery_launch.proceed(launcher, parent)
        self.assertEqual(len(launcher.completed), 2)
        self.assertEqual(delivery_state.list_fields(parent, state, "running")["group"], "attention")
        epic_record.set_auto(parent, True)
        delivery_launch.proceed(launcher, parent)
        reviewed, status, outcome = launcher.completed[-1]
        self.assertEqual(status, "NO_CHANGES_REQUIRED", outcome.get("summary"))
        self.assertEqual(outcome["required_local_checks"], ["health", "audit"])
        self.assertEqual(state["required_local_checks"], ["health"])
        self.assertTrue(
            any(
                "corrective gate" in check["file"] and check["status"] == "PASS"
                for check in outcome["checks"]
            )
        )
        combined = (reviewed / "changes.diff").read_text()
        self.assertIn("-    return 1", combined)
        self.assertIn("+# marker", combined)
        self.assertIn("new.py", combined)
        self.assertEqual(
            delivery_state.view(parent, state)["corrections"][0]["run"], correction.name
        )
        worktree = Path(state["roots"]["project"])
        self.assertEqual(process.checked(worktree, ["status", "--porcelain"]), "")
        journal = json.loads((correction / "git-execution.json").read_text())
        unsettled = [*journal, dict(stage="task-commit", status="UNKNOWN")]
        atomic_json(correction / "git-execution.json", unsettled)
        with self.assertRaisesRegex(ValueError, "Git outcome is uncertain"):
            integration_launch.repeat(launcher, parent)
        atomic_json(correction / "git-execution.json", journal)
        incomplete = dict(fixed, commits=[])
        atomic_json(correction / "run.json", incomplete)
        with self.assertRaisesRegex(ValueError, "no verified commit"):
            integration_launch.repeat(launcher, parent)
        atomic_json(correction / "run.json", fixed)

    def test_pause_budget_and_failed_writer_never_start_another_correction(self):
        parent, state, _, launcher = self.rejected()
        epic_record.set_auto(parent, False)
        delivery_launch.proceed(launcher, parent)
        self.assertEqual(len(launcher.completed), 1)
        epic_record.set_auto(parent, True)
        launcher.pending = [("failed-correction", "writer-prose-always")]
        delivery_launch.proceed(launcher, parent)
        self.assertEqual(launcher.completed[-1][1], "INVALID_RESULT")
        for _ in range(2):
            delivery_launch.proceed(launcher, parent)
        self.assertEqual(len(launcher.completed), 2)
        self.assertEqual(delivery_state.view(parent, state)["step"], "correction_failed")
        with self.assertRaisesRegex(ValueError, "No integration correction"):
            correction_launch.start(launcher, parent)
        prior = json.loads((parent / "epic.json").read_text())
        with self.assertRaisesRegex(ValueError, "Unresolved correction"):
            integration_launch.repeat(launcher, parent)
        self.assertEqual(json.loads((parent / "epic.json").read_text()), prior)

    def test_correction_budget_stops_a_second_rejected_combined_review(self):
        parent, state, _, launcher = self.rejected()
        launcher.pending = [
            ("corrected", "integration-fix"),
            ("rejected-again", "integration-reject"),
        ]
        delivery_launch.proceed(launcher, parent)
        delivery_launch.proceed(launcher, parent)
        self.assertEqual(launcher.completed[-1][1], "CHANGES_REQUESTED")
        delivery_launch.proceed(launcher, parent)
        current = delivery_state.view(parent, state)
        self.assertEqual(current["step"], "integration_failed")
        self.assertEqual(current["corrections_remaining"], 0)
        self.assertFalse(current["correction_available"])
        self.assertEqual(len(launcher.completed), 3)

    def test_continue_keeps_inherited_gates_and_self_contained_authority(self):
        parent, _, _, launcher = self.rejected()
        launcher.pending = [("paused-correction", "writer-timeout")]
        delivery_launch.proceed(launcher, parent)
        child, status, stopped = launcher.completed[-1]
        self.assertEqual(status, "TIMEOUT", stopped.get("summary"))
        self.assertEqual(stopped["required_local_checks"], ["health"])
        (parent / "run.json").unlink()
        options = json.loads(self.settings.read_text())
        options["command"][-1] = "integration-fix"
        options["timeout_seconds"] = 10
        atomic_json(self.settings, options)
        _, status = execute_task(
            child / "00-input/task.md", self.settings, run_dir=child, resume=True
        )
        finished = json.loads((child / "run.json").read_text())
        self.assertEqual(status, "READY_FOR_REVIEW", finished.get("summary"))
        self.assertEqual(finished["required_local_checks"], ["health"])
        self.assertEqual(len(finished["commits"]), 1)

    def test_unlinked_correction_cannot_run_models_or_write(self):
        parent, state, _, _ = self.rejected()
        _, status, failed = self.execute(
            "forged", correction_launch.payload(parent, state), "integration-fix"
        )
        self.assertEqual(status, "BLOCKED", failed.get("summary"))
        self.assertIn("not linked", failed["summary"])
        self.assertEqual(failed["attempts"], [])
        self.assertNotIn("marker", (Path(state["roots"]["project"]) / "hello.py").read_text())

    def test_correction_cannot_expand_into_another_task_split(self):
        for decision, steps in (("split", ["one"]), ("single", ["one", "two"])):
            with (
                self.subTest(decision=decision),
                self.assertRaisesRegex(ValueError, "one atomic task"),
            ):
                control.check_plan(dict(decision=decision, steps=steps), dict(phase="correction"))

    def test_correction_does_not_offer_an_unsupported_restart(self):
        activity = SimpleNamespace(held=False, waiting=None)
        self.assertFalse(start_controls.restart(self.base, dict(phase="correction"), activity))


if __name__ == "__main__":
    unittest.main()
