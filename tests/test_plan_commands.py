"""Reviewed executable checks produce evidence for the exact program on the submitted source."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from run_fixture import current_run

from taskrail.application import (
    check_expectations,
    check_results,
    plan_commands,
    reviewed_artifacts,
)
from taskrail.application.source_guard import SourceGuard
from taskrail.application.verify_commands import run_commands
from taskrail.core.files import atomic_json
from taskrail.interactions import local_journal


def directive(argv, **fields):
    return "run: " + json.dumps(dict(root="project", argv=argv, **fields))


class ReviewedCommandTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        self.run = base / "run"
        self.stage = self.run / "03-check"
        self.stage.mkdir(parents=True)
        self.root = base / "project"
        self.app = self.root / "app"
        self.app.mkdir(parents=True)
        self.program = self.app / "check"
        self.program.write_text(
            '#!/bin/sh\nprintf \'[{"rule":"expected"}]\\n\'\nprintf "EXIT:0\\n" >&2\nexit 2\n'
        )
        self.program.chmod(0o755)
        self.roots = dict(project=self.root)
        self.state = dict(
            roots={"project": str(self.root)},
            requirements=[],
            results=dict(plan="result.json"),
            plan_review=dict(status="APPROVE"),
            auto_approve=True,
        )
        atomic_json(self.run / "run.json", current_run(self.state))
        guard = SourceGuard(self.roots)
        guard.capture()
        self.workflow = SimpleNamespace(
            config=dict(roots=self.roots, check_specs=[], verify_commands=[]),
            run=self.run,
            state=self.state,
            guard=guard,
        )

    def plan(self, *instructions):
        atomic_json(self.run / "result.json", dict(steps=[dict(checks=instructions)]))
        reviewed_artifacts.seal(self.workflow)

    def test_reviewed_command_records_true_exit_and_checks_the_full_report_once(self):
        counts = dict(field="rule", equals={"expected": 1})
        criterion = directive(["./check"], cwd="app", expect=dict(exit_code=2, json_counts=counts))
        other = directive(["./check"], cwd="app")
        self.plan(criterion, other, criterion, "Review the message manually")
        checks = run_commands(self.workflow, self.stage)
        self.assertEqual([row["status"] for row in checks], ["PASS", "FAIL"], checks)
        self.assertIn("Expected exit 0, observed 2", checks[1]["detail"])
        self.assertTrue(all(row["started"] for row in checks))
        receipts = check_results.read(self.run)
        self.assertEqual(len(local_journal.records(self.run)), 1)
        self.assertEqual(
            receipts[0]["execution"]["action_id"], receipts[1]["execution"]["action_id"]
        )
        self.assertEqual(receipts[0]["command"], dict(cwd=str(self.app), argv=["./check"]))
        self.assertEqual(receipts[0]["execution"]["exit_code_of"], "./check")
        self.assertEqual(receipts[0]["assessment"]["json_counts"], counts["equals"])
        self.assertEqual(len(check_results.trusted(self.run)), 2)
        self.program.write_text("#!/bin/sh\nexit 0\n")
        self.assertFalse(check_results.trusted(self.run))

    def test_prerequisite_failure_never_executes_a_check_or_establishes_an_exit(self):
        self.plan(directive(["./check"], cwd="app"))
        rows = run_commands(self.workflow, self.stage, prerequisite_failed=True)
        self.assertEqual(
            [(row["status"], row["started"]) for row in rows], [("NOT_STARTED", False)]
        )
        self.assertEqual(check_results.read(self.run), [])

    def test_changed_or_unapproved_command_cannot_run(self):
        self.plan(directive(["true"]))
        atomic_json(self.run / "result.json", dict(steps=[]))
        with self.assertRaisesRegex(ValueError, "changed"):
            run_commands(self.workflow, self.stage)
        self.plan(directive(["true"]))
        del self.state[reviewed_artifacts.SEAL]
        with self.assertRaisesRegex(ValueError, "Unsealed"):
            run_commands(self.workflow, self.stage)
        self.assertEqual(local_journal.records(self.run), [])

    def test_invalid_commands_are_returned_before_plan_approval(self):
        for instruction in (
            directive(["bash", "-c", "false; echo done"]),
            directive(["tool", "--fix"]),
            directive(["true"], cwd="../outside"),
            directive(["true"], expect=dict(exit_code=False)),
            directive(["true"], expect=dict(exit_code=256)),
            directive(["true"], expect=dict(json_counts={"field": "rule", "equals": {"rule": -1}})),
            'run: {"root":"project","argv":["true"],"argv":["false"]}',
        ):
            with self.subTest(instruction=instruction), self.assertRaises(ValueError):
                plan_commands.entries(dict(steps=[dict(checks=[instruction])]), self.roots)

    def test_missing_codes_and_incomplete_or_unexpected_categories_cannot_pass(self):
        expectation = dict(exit_code=0, json_counts=dict(field="rule", equals={"known": 1}))
        for outcome, status in (
            (dict(status="UNKNOWN", stdout="[]"), "unknown"),
            (dict(status="FAILED", launcher_exit_code=0), "unknown"),
            (dict(status="SUCCEEDED", exit_code=0, stdout="partial"), "unknown"),
            (dict(status="SUCCEEDED", exit_code=0, stdout="[{}]"), "unknown"),
            (dict(status="SUCCEEDED", exit_code=0, stdout='[{"rule":"new"}]'), "failed"),
        ):
            with self.subTest(outcome=outcome):
                self.assertEqual(check_expectations.assess(expectation, outcome)["status"], status)
