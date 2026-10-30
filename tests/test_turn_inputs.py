"""Actual attachments and repeated turns cannot evade context admission."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from live_fixture import LiveFixture

from taskrail.application import context_handoff, progress_archive, progress_file, session_budget
from taskrail.infrastructure import artifact_access, runner, turn_budget
from taskrail.observability.telemetry import Telemetry


class TurnInputTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name)
        self.folder = self.run / "01-implement"
        self.folder.mkdir()
        self.prompt = self.folder / "request.md"
        self.prompt.write_text("task")
        (self.folder / "agent.md").write_text("role")

    def options(self, note, session=None):
        return dict(
            command=["must-not-start"],
            workspace=self.run,
            agent="test",
            model=None,
            prompt=self.prompt,
            attempt=self.folder,
            timeout=10,
            runtime=dict(context_budget=5000, attached_files=[note], session_id=session),
        )

    def test_each_stage_counts_the_actual_attached_result_or_progress(self):
        for role, name in (
            ("planner", "plan.md"),
            ("reviewer", "review.md"),
            ("implementer", "progress.md"),
        ):
            with self.subTest(role=role):
                note = self.run / name
                note.write_text("ж" * 950000)
                record = dict(role=role, attached_files=[str(note)])
                result = session_budget.admission({}, (self.folder, record), [])
                self.assertEqual(result["status"], "CONTEXT_EXCEEDED")
                self.assertEqual(record["context_budget"]["attached_bytes"], 1900000)

    def test_growth_between_turns_is_remeasured_before_spawning(self):
        note = self.run / "review.md"
        note.write_text("short")
        options = self.options(note)
        self.assertIsNone(turn_budget.admission(options, Telemetry()))
        note.write_text("x" * 5000)
        options["runtime"]["session_id"] = "same"
        (self.folder / "events.jsonl").write_text("")
        with patch("taskrail.infrastructure.process_watch.subprocess.Popen") as launch:
            result = runner.run_agent(options)
        launch.assert_not_called()
        self.assertEqual(result["status"], "CONTEXT_EXCEEDED")
        self.assertTrue(result["admission_blocked"])

    def test_continuations_accumulate_actual_bytes_without_provider_usage(self):
        note = self.run / "plan.md"
        note.write_text("x" * 1800)
        options = self.options(note)
        telemetry = Telemetry()
        self.assertIsNone(turn_budget.admission(options, telemetry))
        options["runtime"]["session_id"] = "same"
        self.assertIsNone(turn_budget.admission(options, telemetry))
        result = turn_budget.admission(options, telemetry)
        self.assertEqual(result["status"], "CONTEXT_EXCEEDED")
        self.assertFalse(result["admission_blocked"])
        self.assertEqual(result["turn_admission"]["previous_tokens"], 3608)
        options["runtime"]["session_id"] = None
        self.assertIsNone(turn_budget.admission(options, telemetry))

    def test_reported_context_and_multibyte_tool_output_are_counted(self):
        note = self.run / "review.md"
        note.write_text("x" * 1000)
        telemetry = Telemetry()
        telemetry.observe(json.dumps(dict(type="text", part=dict(text="ж" * 2100))))
        options = self.options(note, "session")
        result = turn_budget.admission(options, telemetry)
        self.assertEqual(result["turn_admission"]["previous_tokens"], 4200)

    def test_progress_is_bounded_with_lossless_archive_and_exact_read_access(self):
        original = "# Done\n" + "ж" * 20000 + "\n# Remaining\nFinish the boundary check\n"
        target = self.run / "progress.md"
        target.write_text(original)
        self.assertEqual(
            progress_file.overflow(self.run, "implementer")["status"], "CONTEXT_EXCEEDED"
        )
        progress_file.prepare(self.run)
        self.assertLessEqual(target.stat().st_size, progress_archive.MAX_BYTES)
        archives = progress_archive.paths(self.run)
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0].read_text(), original)
        self.assertIn("Finish the boundary check", target.read_text())
        inputs = artifact_access.model_inputs(self.run, self.folder)
        self.assertIn(archives[0], inputs)
        self.assertNotIn(archives[0].parent, inputs)
        self.assertNotIn(self.run / "run.json", inputs)
        access = dict(writable=[], readable=[])
        progress_file.grant(access, self.run)
        self.assertIn(archives[0], access["readable"])
        self.assertEqual(access["writable"], [target])

    def test_large_changed_file_inventory_has_a_bounded_handoff(self):
        workflow = SimpleNamespace(run=self.run, config=dict(roots={"repo": self.run}))
        paths = [f"repo/long-file-{index:05d}.py" for index in range(10000)]
        note = context_handoff.changed_paths(workflow, paths)
        self.assertLess(len(note.encode()), 4500)
        self.assertIn("changes.diff", note)
        self.assertNotIn("run.json", note)


class ProgressHandoffTests(LiveFixture, unittest.TestCase):
    def test_an_oversized_writer_note_is_archived_before_fresh_session_admission(self):
        run, status, state = self.run_mode("large-progress-context")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        writers = [entry for entry in state["stages"] if entry["stage"] == "implementer"]
        self.assertEqual(len(writers), 2)
        self.assertEqual(writers[0]["status"], "CONTEXT_EXCEEDED")
        self.assertLessEqual(writers[1]["context_budget"]["attached_bytes"], 8192)
        archives = progress_archive.paths(run)
        self.assertEqual(len(archives), 1)
        self.assertGreater(archives[0].stat().st_size, 1900000)
        profile = json.loads(
            (run / writers[1]["directory"] / "agent.md").read_text().split("---")[1]
        )
        self.assertEqual(profile["permission"]["read"][str(archives[0])], "allow")
        self.assertNotIn(str(archives[0].parent) + "/*", profile["permission"]["read"])


if __name__ == "__main__":
    unittest.main()
