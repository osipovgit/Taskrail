"""Provider context reports govern turns; large handoff notes stay bounded."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from live_fixture import LiveFixture

from taskrail.application import context_handoff, progress_archive, progress_file
from taskrail.infrastructure import artifact_access, runner


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
        self.provider = self.run / "provider.py"
        self.provider.write_text(
            "import json, sys\n"
            "from pathlib import Path\n"
            "receipt = Path('provider-inputs.json')\n"
            "turns = json.loads(receipt.read_text()) if receipt.exists() else []\n"
            "files = [Path(sys.argv[i + 1]) for i, arg in enumerate(sys.argv) "
            "if arg == '--file']\n"
            "turns.append({str(path): len(path.read_bytes()) for path in files})\n"
            "receipt.write_text(json.dumps(turns))\n"
            "identity = str(len(turns))\n"
            "events = [dict(type='text', part=dict(id='text-' + identity, "
            "messageID=identity, text='DONE')), dict(type='step_finish', "
            "part=dict(id='finish-' + identity, messageID=identity, reason='stop'))]\n"
            "if '--overflow' in sys.argv:\n"
            "    events = [dict(type='error', error='maximum context length exceeded')]\n"
            "for event in events:\n"
            "    print(json.dumps(dict(event, sessionID='same')), flush=True)\n"
        )

    def options(self, note, session=None):
        return dict(
            command=[sys.executable, str(self.provider)],
            workspace=self.run,
            agent="test",
            model=None,
            prompt=self.prompt,
            attempt=self.folder,
            timeout=10,
            runtime=dict(context_budget=86016, attached_files=[note], session_id=session),
        )

    def test_reported_context_below_boundary_continues_despite_large_history(self):
        note = self.run / "review.md"
        note.write_text("")
        for old_estimate, reported in ((262395, 76360), (147815, 43712)):
            with self.subTest(old_estimate=old_estimate, reported=reported):
                events = [
                    dict(type="text", part=dict(id="history", text="x" * (old_estimate - 4))),
                    dict(
                        type="step_finish",
                        part=dict(
                            id="usage",
                            tokens=dict(
                                input=reported - 20000,
                                cache=dict(read=20000),
                                output=1,
                                total=reported + 1,
                            ),
                        ),
                    ),
                ]
                self.folder.joinpath("events.jsonl").write_text(
                    "".join(json.dumps(event) + "\n" for event in events)
                )
                result = runner.run_agent(self.options(note, "same"))
                self.assertEqual(result["status"], "OK", result["errors"])
                self.assertEqual(result["final_text"], "DONE")
                telemetry = json.loads(self.folder.joinpath("telemetry.json").read_text())
                self.assertEqual(telemetry["last_input"], reported)
                self.assertFalse(self.folder.joinpath("turn-inputs.json").exists())

    def test_growing_attachments_reach_the_provider_on_continued_turns(self):
        note = self.run / "review.md"
        note.write_text("short")
        options = self.options(note)
        initial = runner.run_agent(options)
        self.assertEqual(initial["status"], "OK", initial["errors"])
        note.write_text("ж" * 950000, encoding="utf-8")
        options["runtime"]["session_id"] = "same"
        continued = runner.run_agent(options)
        self.assertEqual(continued["status"], "OK", continued["errors"])
        inputs = json.loads(self.run.joinpath("provider-inputs.json").read_text())
        self.assertEqual([turn[str(note)] for turn in inputs], [5, 1900000])
        self.assertFalse(self.folder.joinpath("turn-inputs.json").exists())

    def test_missing_usage_and_obsolete_ledger_do_not_block_continuations(self):
        note = self.run / "plan.md"
        note.write_text("x" * 180000)
        event = dict(
            type="tool_use",
            part=dict(
                id="read",
                tool="read",
                state=dict(status="completed", input={}, output="ж" * 210000),
            ),
        )
        self.folder.joinpath("events.jsonl").write_text(json.dumps(event) + "\n")
        ledger = self.folder / "turn-inputs.json"
        ledger.write_text("historical incomplete ledger")
        options = self.options(note, "same")
        for _ in range(2):
            result = runner.run_agent(options)
            self.assertEqual(result["status"], "OK", result["errors"])
        telemetry = json.loads(self.folder.joinpath("telemetry.json").read_text())
        self.assertIsNone(telemetry["last_input"])
        self.assertEqual(ledger.read_text(), "historical incomplete ledger")

    def test_provider_context_rejection_remains_authoritative_without_usage(self):
        note = self.run / "review.md"
        note.write_text("x" * 100000)
        options = self.options(note)
        options["command"].append("--overflow")
        result = runner.run_agent(options)
        self.assertEqual(result["status"], "CONTEXT_EXCEEDED")
        self.assertIn("maximum context length exceeded", result["errors"])
        self.assertTrue(self.run.joinpath("provider-inputs.json").exists())
        self.assertFalse(self.folder.joinpath("turn-inputs.json").exists())

    def test_progress_is_bounded_with_lossless_archive_and_exact_read_access(self):
        original = "# Done\n" + "ж" * 20000 + "\n# Remaining\nFinish the boundary check\n"
        target = self.run / "progress.md"
        target.write_text(original)
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
    def test_large_active_note_continues_after_local_result_in_the_same_writer(self):
        run, status, state = self.run_mode("large-progress-local")
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        writers = [entry for entry in state["stages"] if entry["stage"] == "implementer"]
        self.assertEqual(len(writers), 1)
        self.assertEqual(writers[0]["session_turns"], 2)
        self.assertEqual(writers[0]["session_id"], "ses1")
        self.assertGreater((run / "progress.md").stat().st_size, 1900000)
        self.assertEqual(progress_archive.paths(run), [])
        actions = json.loads((run / "local-actions.json").read_text())
        self.assertEqual(len(actions), 1)
        self.assertEqual(actions[0]["status"], "SUCCEEDED")
        self.assertEqual(actions[0]["stage"], writers[0]["directory"])

    def test_an_oversized_writer_note_is_archived_before_fresh_session_launch(self):
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
