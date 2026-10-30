"""Historical byte-admission stops continue under the unchanged frozen contract."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail.application.attempt_retries import final
from taskrail.application.checkpoints import resume_available
from taskrail.application.live import execute_task
from taskrail.application.stage_attempts import StageAttempts

BASE = Path(__file__).resolve().parents[1]


def legacy_admission(attempts, active):
    """Persist the old admission result without launching a model or editing sources."""
    folder, record = active
    record["context_budget"] = dict(estimated_input_tokens=262395, input_capacity_tokens=86016)
    outcome = dict(
        status="CONTEXT_EXCEEDED",
        admission_blocked=True,
        errors=["Estimated context exceeds the configured boundary"],
        elapsed_seconds=0,
        exit_code=None,
        tokens={},
        sessions=[],
        final_text="",
        completed=False,
        usage_complete=False,
    )
    (folder / "events.jsonl").touch()
    attempts.settle(active, outcome)
    return outcome


class ContextResumeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "project"
        (self.root / ".git").mkdir(parents=True)
        (self.root / ".git/HEAD").write_text("ref: refs/heads/main\n")
        self.source = self.root / "hello.py"
        self.source.write_text("def hello():\n    return 1\n")
        self.task = self.base / "task.md"
        header = json.dumps(dict(roots=dict(project=str(self.root))))
        self.task.write_text(f"```taskrail-task\n{header}\n```\nReturn 2.")
        self.settings = self.base / "settings.json"
        profiles = self.base / "profiles"
        self.settings.write_text(
            json.dumps(
                dict(
                    command=[
                        sys.executable,
                        str(BASE / "tests/fake_live.py"),
                        "--profiles",
                        str(profiles),
                        "--mode",
                        "ok",
                    ],
                    agent_source=str(BASE / "taskrail/agents"),
                    agent_directory=str(profiles),
                    timeout_seconds=5,
                    read_retries=0,
                )
            )
        )

    def blocked_run(self):
        with patch.object(StageAttempts, "launch", legacy_admission):
            run, status = execute_task(self.task, self.settings, run_dir=self.base / "run")
        state = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "CONTEXT_EXCEEDED", state.get("summary"))
        self.assertTrue(resume_available(run, state)[0])
        self.assertEqual(len(state["attempts"]), 1)
        return run, state

    def test_continue_ignores_old_estimates_and_preserves_original_diagnostics(self):
        run, before = self.blocked_run()
        contract = (run / "00-input/contract.json").read_bytes()
        stage = run / before["stages"][0]["directory"] / "stage.json"
        historical = stage.read_bytes()
        continued, status = execute_task(
            run / "00-input/task.md", self.settings, run_dir=run, resume=True
        )
        after = json.loads((run / "run.json").read_text())
        self.assertEqual(continued, run)
        self.assertEqual(status, "READY_FOR_REVIEW", after.get("summary"))
        self.assertIn("return 2", self.source.read_text())
        self.assertEqual((run / "00-input/contract.json").read_bytes(), contract)
        self.assertEqual(stage.read_bytes(), historical)
        self.assertEqual(after["attempts"][0], before["attempts"][0])
        self.assertEqual(after["stages"][0], before["stages"][0])
        self.assertNotIn("estimated_input_tokens", after["stages"][1]["context_budget"])

    def test_continue_after_old_admission_still_checks_source_integrity(self):
        run, before = self.blocked_run()
        self.source.write_text("user changes\n")
        _, status = execute_task(run / "00-input/task.md", self.settings, run_dir=run, resume=True)
        after = json.loads((run / "run.json").read_text())
        self.assertEqual(status, "BLOCKED")
        self.assertIn("Source/Git changed since checkpoint", after["summary"])
        self.assertEqual(after["stages"], before["stages"])
        self.assertEqual(self.source.read_text(), "user changes\n")

    def test_legacy_admission_flag_is_not_an_independent_retry_stop(self):
        outcome = dict(status="CONTEXT_EXCEEDED", admission_blocked=True)
        self.assertFalse(final("planner", outcome, {}))


if __name__ == "__main__":
    unittest.main()
