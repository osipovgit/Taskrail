"""Actions retain authority and outcome across interruption and repeated model requests."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from taskrail.application import transitions
from taskrail.interactions import local_actions, local_journal, request_limits
from taskrail.web import delivery_steps


class LocalJournalTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.folder = self.run / "01-plan"
        self.folder.mkdir()
        self.root = self.run / "source"
        self.root.mkdir()
        self.payload = dict(cwd=str(self.root), argv=[sys.executable, "--version"], reason="Check")
        self.context = dict(run=self.run, roots={"project": self.root}, timeout=5, expected={})
        self.decision = dict(decision="allow", alternative="")

    def execute(self, decision=None):
        return local_actions.execute(
            self.run, self.folder, self.payload, self.context, decision or self.decision
        )

    def test_running_is_durable_before_command_and_completion_keeps_exact_approval(self):
        def command(payload, context):
            entry = local_journal.records(self.run)[0]
            self.assertEqual(entry["status"], "RUNNING")
            self.assertEqual(entry["approval"], self.decision)
            self.assertEqual(entry["request"], self.payload)
            self.assertEqual(entry["effective_argv"], context["effective_argv"])
            return dict(status="SUCCEEDED", exit_code=0, stdout="Python", stderr="")

        with patch("taskrail.interactions.local.execute", side_effect=command):
            outcome = self.execute()
        self.assertEqual(outcome["status"], "SUCCEEDED")
        self.assertEqual(local_journal.records(self.run)[0]["status"], "SUCCEEDED")

    def test_interrupt_is_unknown_and_never_replayed_after_reason_or_source_changes(self):
        with (
            patch("taskrail.interactions.local.execute", side_effect=KeyboardInterrupt),
            self.assertRaises(KeyboardInterrupt),
        ):
            self.execute()
        self.payload["reason"] = "A different explanation"
        self.context["expected"] = {"project/a.py": "changed"}
        with patch("taskrail.interactions.local.execute") as execute:
            outcome = self.execute()
        execute.assert_not_called()
        self.assertEqual(outcome["status"], "UNKNOWN")
        self.assertEqual(len(local_journal.records(self.run)), 1)

    def test_denied_command_does_not_run_again_under_a_new_reason(self):
        decision = dict(decision="deny", alternative="Use source evidence")
        with patch("taskrail.interactions.local.execute") as execute:
            self.execute(decision)
            self.payload["reason"] = "Please run it again"
            outcome = self.execute()
        execute.assert_not_called()
        self.assertEqual(outcome["status"], "DECLINED")
        self.assertEqual(outcome["decision"], decision)

    def test_failure_to_record_running_cannot_start_subprocess(self):
        with (
            patch("taskrail.interactions.local_journal.update", side_effect=OSError),
            patch("taskrail.interactions.local.execute") as execute,
            self.assertRaises(OSError),
        ):
            self.execute()
        execute.assert_not_called()
        self.assertEqual(local_journal.records(self.run)[0]["status"], "APPROVED")


class RequestLimitTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run = Path(self.temporary.name)
        self.session = SimpleNamespace(
            active=(self.run / "01-plan", {"stage": "planner"}),
            environment={"run": self.run, "expected": {}},
        )

    def request(self, number=0):
        payload = dict(status="LOCAL_REQUEST", argv=["ls"], cwd="/repo", reason=str(number))
        return dict(status="OK", final_text=json.dumps(payload))

    def test_repeated_requests_stop_before_execution_and_survive_session_recreation(self):
        for number in range(request_limits.MAX_DUPLICATES):
            self.assertFalse(request_limits.check(self.session, self.request(number)))
        self.session = SimpleNamespace(**vars(self.session))
        outcome = self.request(99)
        self.assertTrue(request_limits.check(self.session, outcome))
        self.assertEqual(outcome["status"], "NO_PROGRESS")

    def test_changed_source_allows_a_new_check(self):
        for _ in range(request_limits.MAX_DUPLICATES):
            request_limits.check(self.session, self.request())
        self.session.environment["expected"] = {"project/a.py": "new"}
        self.assertFalse(request_limits.check(self.session, self.request()))

    def test_final_result_is_not_counted_as_an_action(self):
        outcome = dict(status="OK", final_text='{"status":"APPROVE"}')
        self.assertFalse(request_limits.check(self.session, outcome))
        self.assertFalse((self.run / request_limits.NAME).exists())


class IntegrationAcceptanceTests(unittest.TestCase):
    def test_approved_inspection_does_not_turn_accepted_review_into_failed_delivery(self):
        verdict = dict(status="APPROVE", summary="Combined source is correct")
        flow = dict(plan={"proposed_change_files": [], "decision": "none"}, allowed=[])
        state = dict(phase="integration", execution_jobs=[{"status": "SUCCEEDED"}])
        transitions.plan_review(flow, state, verdict, 1)
        self.assertEqual(state["status"], "NO_CHANGES_REQUIRED")
        self.assertEqual(state["review_outcome"]["decision"], "APPROVE")
        delivery = dict(tasks=[{}], phases={"integration": {"status": state["status"]}})
        self.assertIsNone(delivery_steps.phase_step(delivery, "integration"))

    def test_ordinary_remote_check_keeps_its_existing_completion_status(self):
        flow = dict(plan={"proposed_change_files": [], "decision": "none"}, allowed=[])
        state = dict(phase="server", execution_jobs=[{"status": "SUCCEEDED"}])
        transitions.plan_review(flow, state, dict(status="APPROVE", summary="Checked"), 1)
        self.assertEqual(state["status"], "READY_FOR_REVIEW")
