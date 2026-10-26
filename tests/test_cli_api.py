"""The CLI as an automation API: submit, answer approvals, control and follow a run."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from taskrail import cli
from taskrail.application import run_locks
from taskrail.core.files import atomic_json


class CliApiTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.runs = self.base / "runs"
        self.runs.mkdir()
        self.repo = self.base / "repo"
        self.repo.mkdir()
        self.run = self.runs / "20260101-000000-abcd1234"
        self.run.mkdir()
        home = patch.dict("os.environ", {"HOME": str(self.base)})
        home.start()
        self.addCleanup(home.stop)

    def call(self, *argv):
        output, errors = io.StringIO(), io.StringIO()
        arguments = [*argv, "--runs-dir", str(self.runs)]
        with (
            patch("sys.argv", ["taskrail", *arguments]),
            contextlib.redirect_stdout(output),
            contextlib.redirect_stderr(errors),
        ):
            code = cli.main()
        return code, json.loads(output.getvalue()) if output.getvalue() else errors.getvalue()

    def test_submit_starts_a_detached_worker_with_the_form_fields(self):
        goal = self.base / "goal.md"
        goal.write_text("Explain why the pipeline failed.")
        with patch("taskrail.web.submissions.start_worker", return_value=None) as start:
            code, answer = self.call(
                "submit",
                "--root",
                f"project={self.repo}",
                "--goal",
                f"@{goal}",
                "--mode",
                "answer",
                "--allow-all",
            )
        self.assertEqual(code, 0, answer)
        self.assertEqual(answer["status"], "STARTING")
        folder = start.call_args.args[0]
        task = (folder / "task.md").read_text()
        self.assertIn("Explain why the pipeline failed.", task)
        self.assertIn('"read_only": true', task)
        self.assertIn('"auto_approve": true', task)
        code, error = self.call("submit", "--root", "project", "--goal", "x")
        self.assertEqual(code, 2)
        self.assertIn("Expected --root ALIAS=PATH", error)

    def test_decide_answers_the_pending_ticket_and_status_shows_it(self):
        atomic_json(self.run / "run.json", dict(status="RUNNING", summary="Planning"))
        request = dict(status="LOCAL_REQUEST", argv=["pytest"], cwd=str(self.repo))
        atomic_json(self.run / "pending-approval.json", dict(ticket="t-1", request=request))
        code, status = self.call("status", self.run.name)
        self.assertEqual(code, 0, status)
        self.assertEqual((status["status"], status["approval"]["argv"]), ("RUNNING", ["pytest"]))
        code, answer = self.call("decide", str(self.run), "alternative", "--text", "Use tox")
        self.assertEqual((code, answer["status"]), (0, "DECISION_RECORDED"))
        decision = json.loads((self.run / "approval-decision.json").read_text())
        self.assertEqual((decision["ticket"], decision["alternative"]), ("t-1", "Use tox"))
        (self.run / "pending-approval.json").unlink()
        code, error = self.call("decide", self.run.name, "allow")
        self.assertEqual(code, 2)
        self.assertIn("not waiting for an approval", error)

    def test_status_of_a_finished_question_carries_the_answer(self):
        state = dict(status="NO_CHANGES_REQUIRED", summary="Approved", answer="It returns 'ab'.")
        atomic_json(self.run / "run.json", state)
        code, status = self.call("status", self.run.name)
        self.assertEqual(code, 0, status)
        self.assertEqual((status["summary"], status["answer"]), ("Approved", "It returns 'ab'."))
        self.assertNotIn("approval", status)

    def test_status_tells_whether_a_worker_still_holds_the_run(self):
        atomic_json(self.run / "run.json", dict(status="RUNNING"))
        code, status = self.call("status", self.run.name)
        self.assertEqual((code, status["status"], status["active"]), (0, "RUNNING", False))
        with run_locks.lock_file(run_locks.lock_path(run_locks.RUN, self.run)) as stream:
            self.assertTrue(run_locks.locked(stream, run_locks.EXCLUSIVE))
            code, status = self.call("status", self.run.name)
        self.assertEqual((code, status["active"]), (0, True))

    def test_action_controls_a_run_like_the_browser(self):
        atomic_json(self.run / "run.json", dict(status="RUNNING"))
        code, answer = self.call("action", self.run.name, "stop")
        self.assertEqual((code, answer["status"]), (0, "STOP_REQUESTED"))
        self.assertTrue((self.run / "stop.request").is_file())
        code, error = self.call("action", self.run.name, "explode")
        self.assertEqual(code, 2)
        self.assertIn("supported task action", error)


if __name__ == "__main__":
    unittest.main()
