"""A temporary report crosses native tools and local commands within one attempt."""

import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from taskrail.application import evidence_scope
from taskrail.infrastructure import command_status, sandbox, stage_scratch
from taskrail.interactions import local_route
from taskrail.interactions.actions import Actions


class StageScratchTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.project = Path(temporary.name) / "project"
        self.project.mkdir()
        self.run = self.project.parent / "runs" / "test"
        self.stage = self.run / "01-plan"
        self.stage.mkdir(parents=True)
        self.scratch = stage_scratch.prepare(self.stage)
        (self.stage / "events.jsonl").touch()
        record = dict(role="planner", scratch_directory=str(self.scratch))
        self.actions = Actions(
            SimpleNamespace(
                active=(self.stage, record),
                environment=dict(
                    roots={"project": self.project},
                    run=self.run,
                    scan=dict,
                    expected={},
                    git_before={},
                    git_metadata=lambda roots: {},
                ),
                clock=Mock(remaining=lambda: 20),
                check_sources=Mock(),
            )
        )

    def execute(self, rule, *argv):
        request = dict(
            schema_version=1,
            status="LOCAL_REQUEST",
            cwd=str(self.project),
            argv=list(argv),
            reason="Inspect the fixture",
        )
        return local_route.executed(self.actions, request, dict(rule=rule, decision="allow"))

    def check_report(self, rule):
        # A native write supplies the helper and a placeholder, but no command receipt.
        report = self.scratch / "details.json"
        report.write_text("placeholder")
        helper = self.scratch / "lint.sh"
        helper.write_text(
            'printf \'{"issues":1}\\n\' > "$TMPDIR/details.json"\n'
            'cat "$TMPDIR/details.json"\nexit 2\n'
        )
        receipts = self.run / "00-input/local"
        self.assertFalse(receipts.exists())
        delivered = self.execute(rule, "sh", str(helper))
        first = receipts / "01-plan-0.json"
        outcome = json.loads(first.read_text())["result"]
        self.assertEqual((outcome["status"], outcome.get("exit_code")), ("FAILED", 2), outcome)
        self.assertEqual(outcome["stdout"], report.read_text())
        self.assertIn(str(first), delivered)
        self.execute(rule, "cat", str(report))
        observed = json.loads((receipts / "01-plan-1.json").read_text())["result"]
        self.assertEqual((observed["status"], observed["stdout"]), ("SUCCEEDED", outcome["stdout"]))
        self.assertEqual(list(self.project.iterdir()), [])
        allowed = evidence_scope.roots(self.run, report, {"project": self.project})
        self.assertFalse(any(report.is_relative_to(root) for root in allowed.values()))
        stage_scratch.discard(self.run, self.stage)
        self.assertFalse(report.exists())
        self.assertEqual(json.loads(outcome["stdout"]), {"issues": 1})
        self.assertTrue(first.exists())

    def test_shell_receipt_identifies_the_shell_when_a_later_command_succeeds(self):
        response = self.execute("host", "sh", "-c", 'sh -c "exit 2"; echo EXIT:$?')
        self.assertIn('"exit_code": 0', response)
        receipt = self.run / "00-input/local/01-plan-0.json"
        result = json.loads(receipt.read_text())["result"]
        self.assertEqual((result["stdout"].strip(), result["exit_code_of"]), ("EXIT:2", "sh"))

    def test_sandbox_setup_and_interruption_have_no_checked_program_exit(self):
        signaled = command_status.process_outcome("lint", -15, None)
        self.assertEqual(signaled, dict(status="FAILED", signal=15, process_started=True))
        for events, launcher, status in (
            (b"", 1, "FAILED"),
            (b"", -15, "UNKNOWN"),
            (b'{"child-pid":42}\n', 1, "UNKNOWN"),
        ):
            with self.subTest(events=events, launcher=launcher):
                result = command_status.process_outcome("lint", launcher, io.BytesIO(events))
                self.assertEqual(result, dict(status=status, launcher_exit_code=launcher))

    def test_host_command_uses_the_native_stage_directory(self):
        self.check_report("host")

    @unittest.skipUnless(sandbox.mode(), "needs a working bubblewrap")
    def test_sandbox_keeps_the_temporary_report_across_commands(self):
        self.check_report("sandbox")

    @unittest.skipUnless(sandbox.mode(), "needs a working bubblewrap")
    def test_sandbox_only_mounts_the_current_attempt(self):
        neighbor = self.run / "other-stage"
        neighbor.touch()
        response = self.execute("sandbox", "test", "!", "-e", str(neighbor))
        self.assertIn('"exit_code": 0', response)

    def test_only_regular_independent_files_return_to_native_tools(self):
        target = self.project / "original"
        target.write_text("original")
        with stage_scratch.command_files(self.scratch):
            (self.scratch / "directory").symlink_to(self.project, target_is_directory=True)
            (self.scratch / "linked").symlink_to(target)
            os.link(target, self.scratch / "hardlinked")
            os.mkfifo(self.scratch / "pipe")
        self.assertEqual(list(self.scratch.iterdir()), [])
        self.assertEqual(target.read_text(), "original")

    def test_interruption_restores_the_scratch_directory_without_following_its_replacement(self):
        with self.assertRaises(KeyboardInterrupt), stage_scratch.command_files(self.scratch):
            self.scratch.rmdir()
            self.scratch.symlink_to(self.project, target_is_directory=True)
            raise KeyboardInterrupt
        self.assertEqual(self.scratch.resolve(), self.scratch)
        self.assertTrue(self.scratch.is_dir())
        self.assertTrue(self.project.is_dir())

    def test_failed_inspection_cannot_resume_with_unchecked_native_access(self):
        with (
            patch.object(stage_scratch, "sanitize", side_effect=PermissionError),
            self.assertRaisesRegex(RuntimeError, "secure stage scratch"),
        ):
            self.execute("host", "true")
