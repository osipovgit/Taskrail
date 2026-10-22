"""Behavioral checks for deterministic, criterion-bound execution and report parsing."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from countersign.application import (
    check_batches,
    check_configuration,
    check_diagnostics,
    check_parents,
    check_recipes,
    check_remote,
    check_results,
    check_specs,
    execution_evidence,
    execution_wait,
    verify_commands,
)
from countersign.application.source_guard import SourceGuard
from countersign.application.workflow_state import Workflow
from countersign.core import coverage
from countersign.core.files import atomic_json
from countersign.executor import protocol
from countersign.web import delivery_payload, integration_review, requests


class CheckRecipesTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.base = Path(self.directory.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.source = self.root / "source.txt"
        self.source.write_text("unchanged\n")
        self.run = self.base / "run"
        self.folder = self.run / "01-check"
        self.folder.mkdir(parents=True)
        self.roots = {"project": self.root}
        self.requirement = dict(id="R-health", kind="runtime", text="Health check passes")
        self.spec = dict(
            id="C-health", recipe_id="health", criteria=["R-health"], phase="check", parameters={}
        )
        self.command = dict(
            cwd=str(self.root), argv=[sys.executable, "-c", "print('healthy')"], timeout_seconds=30
        )
        self.recipe = dict(kind="local", phase="check", request=self.command, adapter="exit-code")
        self.guard = SourceGuard(self.roots)
        self.guard.capture()
        self.state = dict(roots={"project": str(self.root)}, requirements=[self.requirement])
        atomic_json(self.run / "run.json", self.state)

    def workflow(self, commands=()):
        config = dict(
            roots=self.roots,
            worktrees={},
            verify_commands=list(commands),
            check_specs=[self.spec],
            check_recipes={"health": self.recipe},
        )
        return SimpleNamespace(config=config, state=self.state, run=self.run, guard=self.guard)

    def completed(self, status="SUCCEEDED", code=0):
        assessment = check_diagnostics.assess("exit-code", dict(status=status, exit_code=code))
        context = dict(
            source_snapshot=check_results.source_identity(self.roots), assessment=assessment
        )
        outcome = dict(status=status, exit_code=code, stdout="healthy\n", stderr="")
        return check_results.record(self.run, self.spec, self.command, outcome, context)

    def test_existing_verify_command_is_bound_once_without_a_second_model_command(self):
        with patch(
            "countersign.interactions.approval_policy.decision",
            return_value=dict(decision="allow", alternative=""),
        ) as approval:
            checks = verify_commands.run_commands(self.workflow([self.command]), self.folder)
        approval.assert_called_once()
        self.assertEqual([entry["status"] for entry in checks], ["PASS"])
        records = check_results.read(self.run)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["criteria"], ["R-health"])
        self.assertEqual(records[0]["execution"]["exit_code"], 0)
        self.assertEqual(len(json.loads((self.run / "local-actions.json").read_text())), 1)

    def test_new_recipe_keeps_personal_approval_and_decline_cannot_become_success(self):
        decision = dict(decision="deny", alternative="")
        with patch(
            "countersign.interactions.approval_policy.decision", return_value=decision
        ) as approval:
            checks = verify_commands.run_commands(self.workflow(), self.folder)
        approval.assert_called_once()
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertEqual(check_results.read(self.run)[0]["assessment"]["status"], "unknown")
        self.assertEqual(check_results.trusted(self.run), {})

    def test_configured_verify_command_cannot_bypass_denial_or_spawn_a_process(self):
        with (
            patch(
                "countersign.interactions.approval_policy.decision",
                return_value=dict(decision="deny", alternative=""),
            ) as approval,
            patch("countersign.interactions.local.execute") as execute,
        ):
            checks = verify_commands.run_commands(self.workflow([self.command]), self.folder)
        approval.assert_called_once()
        execute.assert_not_called()
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertEqual(check_results.trusted(self.run), {})

    def test_source_change_while_waiting_for_check_approval_prevents_execution(self):
        def changed_while_approving(*_args):
            self.source.write_text("changed during approval\n")
            return dict(decision="allow", alternative="")

        with (
            patch(
                "countersign.interactions.approval_policy.decision",
                side_effect=changed_while_approving,
            ),
            patch("countersign.interactions.local.execute") as execute,
        ):
            checks = verify_commands.run_commands(self.workflow([self.command]), self.folder)
        execute.assert_not_called()
        self.assertEqual(checks[0]["status"], "FAIL")
        self.assertIn("while waiting", checks[0]["detail"])
        self.assertEqual(check_results.read(self.run), [])

    def test_runtime_acceptance_rejects_unrelated_stale_and_tampered_check_results(self):
        record = self.completed()
        claims = [dict(id="E1", path=record["path"])]
        trusted = execution_evidence.claim_ids(self.run, claims)
        outcome = dict(outcome="satisfied", evidence_ids=["E1"])
        coverage.validate_outcome(outcome, self.requirement, {"E1": {}}, trusted)
        with self.assertRaisesRegex(ValueError, "matching current"):
            coverage.validate_outcome(
                outcome, dict(self.requirement, id="R-other"), {"E1": {}}, trusted
            )
        self.source.write_text("changed\n")
        self.assertEqual(execution_evidence.claim_ids(self.run, claims), {})
        self.source.write_text("unchanged\n")
        stream = record["execution"]["artifacts"]["stdout"]["path"]
        Path(stream).write_text("forged\n")
        self.assertEqual(execution_evidence.claim_ids(self.run, claims), {})

    def test_failed_check_proves_contradiction_but_never_satisfaction(self):
        record = self.completed("FAILED", 2)
        trusted = execution_evidence.claim_ids(self.run, [dict(id="E1", path=record["path"])])
        outcome = dict(outcome="contradicted", evidence_ids=["E1"])
        coverage.validate_outcome(outcome, self.requirement, {"E1": {}}, trusted)
        with self.assertRaises(ValueError):
            coverage.validate_outcome(
                dict(outcome, outcome="satisfied"), self.requirement, {"E1": {}}, trusted
            )

    def test_catalog_and_specs_cannot_invent_shell_commands_or_criterion_bindings(self):
        catalog = check_recipes.parse_catalog(dict(check_recipes={"health": self.recipe}))
        self.assertEqual(
            check_specs.validate_specs([self.spec], catalog, [self.requirement]), [self.spec]
        )
        for change in (
            dict(recipe_id="invented"),
            dict(parameters={"argv": ["rm"]}),
            dict(phase="server"),
            dict(criteria=["R-other"]),
        ):
            with self.subTest(change=change), self.assertRaises(ValueError):
                check_specs.validate_specs([dict(self.spec, **change)], catalog, [self.requirement])

    def test_remote_unknown_ticket_is_observed_without_resubmission(self):
        binding = dict(
            check_id="C-server",
            request_sha256=protocol.fingerprint(self.command),
            source_snapshot="snapshot",
        )
        pending = dict(id="ticket", status="UNKNOWN", binding=binding, results=[])
        atomic_json(self.run / execution_wait.LEDGER, [pending])
        with (
            patch.object(execution_wait, "submit") as submit,
            patch.object(execution_wait, "resume") as resume,
        ):
            observed = check_remote.followed(
                self.workflow(), self.folder, self.command, "ssh", binding
            )
        self.assertEqual(observed, pending)
        submit.assert_not_called()
        resume.assert_not_called()

    def test_server_recipe_cannot_bypass_parent_confirmation(self):
        with patch(
            "countersign.application.execution_requests.remote_mode", return_value="inspect"
        ):
            with self.assertRaisesRegex(ValueError, "confirmed changes"):
                check_remote.authorize(self.workflow(), dict(kind="ssh"))

    def test_report_adapters_reject_invalid_empty_or_incomplete_reports(self):
        base = dict(status="SUCCEEDED", exit_code=0)
        for adapter, text in (
            ("ruff-json", "0 errors"),
            ("junit", "<testsuite/>"),
            ("junit", '<!DOCTYPE x [<!ENTITY y "x">]><testsuite/>'),
        ):
            with self.subTest(adapter=adapter, text=text):
                self.assertEqual(
                    check_diagnostics.assess(adapter, dict(base, stdout=text))["status"], "unknown"
                )
        report = dict(base, build=dict(building=False, number=7), tests_status="unavailable")
        self.assertEqual(check_diagnostics.assess("jenkins", report)["status"], "unknown")

    def test_structured_diagnostics_are_stable_bounded_and_not_keyword_counts(self):
        entries = [
            dict(filename="file.py", location=dict(row=n, column=1), code="F401", message="unused")
            for n in range(150)
        ]
        outcome = dict(status="FAILED", exit_code=1, stdout=json.dumps(entries))
        assessment = check_diagnostics.assess("ruff-json", outcome)
        self.assertEqual(assessment["status"], "failed")
        self.assertEqual(assessment["counts"]["failed"], 150)
        self.assertEqual(len(assessment["diagnostics"]), 100)
        self.assertEqual(assessment["omitted"], 50)
        no_errors = dict(status="SUCCEEDED", exit_code=0, stdout="[]", stderr="0 errors, 0 failed")
        self.assertEqual(check_diagnostics.assess("ruff-json", no_errors)["status"], "passed")

    def test_junit_counts_real_cases_and_records_failures(self):
        text = '<testsuite tests="999"><testcase name="pass"/><testcase name="fail"><failure>boom</failure></testcase><testcase name="skip"><skipped/></testcase></testsuite>'
        assessment = check_diagnostics.assess(
            "junit", dict(status="FAILED", exit_code=1, stdout=text)
        )
        self.assertEqual(assessment["counts"], dict(passed=1, failed=1, skipped=1))
        self.assertEqual(assessment["diagnostics"][0]["test"], "fail")

    def test_later_failed_check_invalidates_an_earlier_pass_on_the_same_source(self):
        first = self.completed()
        latest = self.completed("FAILED", 1)
        trusted = check_results.trusted(self.run)
        self.assertNotIn(first["path"], trusted)
        self.assertIn(latest["path"], trusted)

    def test_resume_uses_frozen_recipes_and_rejects_tampering(self):
        config = self.workflow().config
        saved = {name: config[name] for name in ("check_recipes", "check_specs", "verify_commands")}
        directory = self.run / "00-input"
        directory.mkdir(exist_ok=True)
        atomic_json(directory / "settings.json", saved)
        check_configuration.capture(config, self.state)
        modified = dict(config, check_recipes={})
        self.state["check_specs"] = [self.spec]
        check_configuration.restore(modified, self.run, self.state)
        self.assertEqual(modified["check_recipes"], config["check_recipes"])
        atomic_json(directory / "settings.json", dict(saved, check_recipes={}))
        with self.assertRaisesRegex(ValueError, "Frozen check settings changed"):
            check_configuration.restore(modified, self.run, self.state)

    def remote_workflow(self):
        self.folder.rmdir()
        request = dict(
            server="ci",
            job="tests",
            operation="build",
            build="new",
            parameters={},
            reason="Test the change",
            timeout_seconds=30,
        )
        recipe = dict(kind="jenkins", phase="validation", request=request, adapter="jenkins")
        config = dict(
            self.workflow().config,
            phase="validation",
            task_text="Verify",
            check_specs=[dict(self.spec, phase="validation")],
            check_recipes={"health": recipe},
        )
        state = dict(self.state, attempts=[], stages=[], results={}, checks=[], status="RUNNING")
        workflow = Workflow(config, self.run, state, dict(debug=False, resume=False))
        workflow.guard = self.guard
        return workflow

    def test_remote_batch_waits_in_code_and_reuses_the_same_completed_check(self):
        workflow = self.remote_workflow()
        completed = dict(
            status="SUCCEEDED",
            build=dict(number=8, result="SUCCESS", building=False),
            tests_status="available",
            tests=dict(passCount=3, failCount=0, skipCount=0, failed_cases=[]),
            console="passed",
        )
        responses = [
            dict(id="ticket", status="PENDING_APPROVAL", results=[]),
            dict(id="ticket", status="SUCCEEDED", results=[completed]),
        ]
        with (
            patch("countersign.executor.client.request", side_effect=responses) as client,
            patch("countersign.application.execution_wait.time.sleep"),
        ):
            check_batches.run_configured(workflow)
            check_batches.run_configured(workflow)
        self.assertEqual(client.call_count, 2)
        self.assertEqual(
            [call.args[0]["operation"] for call in client.call_args_list], ["submit", "status"]
        )
        self.assertEqual(len(check_results.read(self.run)), 1)
        self.assertEqual(workflow.state["checks"][0]["status"], "PASS")
        self.assertEqual(workflow.state["attempts"], [])
        self.assertEqual(workflow.flow["stage"], "reviewer")

    def test_failed_fixed_batch_blocks_acceptance_without_an_extra_model_turn(self):
        workflow = self.remote_workflow()
        failed = dict(
            status="FAILED",
            build=dict(number=8, result="FAILURE", building=False),
            tests_status="available",
            tests=dict(passCount=0, failCount=1, skipCount=0, failed_cases=[]),
        )
        with patch(
            "countersign.executor.client.request",
            return_value=dict(id="ticket", status="FAILED", results=[failed]),
        ):
            check_batches.run_configured(workflow)
        self.assertEqual(workflow.state["status"], "BLOCKED")
        self.assertEqual(workflow.state["checks"][0]["assessment"], "failed")
        self.assertEqual(workflow.state["attempts"], [])

    def test_partial_fixed_batch_keeps_planning_for_unbound_legacy_checks(self):
        workflow = self.remote_workflow()
        workflow.state["requirements"].append(dict(self.requirement, id="R-legacy"))
        record = dict(criteria=["R-health"], assessment=dict(status="passed"))
        check_batches.review_completed(workflow, [record])
        self.assertEqual(workflow.flow["stage"], "planner")

    def test_delivery_inherits_exact_frozen_recipes_and_refreezes_its_own_settings(self):
        workflow = self.workflow()
        workflow.config.update(phase="integration", check_parent="parent")
        parent = self.base / "parent"
        (parent / "00-input").mkdir(parents=True)
        (self.run / "00-input").mkdir()
        parent_state = dict(self.state, status="TASKS_READY", check_specs=[self.spec])
        original = {name: workflow.config[name] for name in ("check_recipes", "verify_commands")}
        check_configuration.capture(original, parent_state)
        atomic_json(parent / "00-input/settings.json", original)
        atomic_json(parent / "run.json", parent_state)
        atomic_json(parent / "epic.json", dict(phases=dict(integration=self.run.name)))
        changed = dict(self.recipe, request=dict(self.command, argv=["changed-command"]))
        workflow.config["check_recipes"] = {"health": changed}
        atomic_json(
            self.run / "00-input/settings.json",
            {name: workflow.config[name] for name in original},
        )
        check_configuration.capture(workflow.config, workflow.state)
        check_parents.adopt(workflow)
        self.assertEqual(workflow.config["check_recipes"], original["check_recipes"])
        self.assertEqual(workflow.config["check_specs"], [self.spec])
        frozen = check_configuration.frozen(self.run, workflow.state)
        self.assertEqual(frozen["check_recipes"], original["check_recipes"])
        (parent / "run.json").unlink()
        check_parents.adopt(workflow, resume=True)
        self.assertEqual(workflow.config["check_recipes"], original["check_recipes"])
        workflow.config["check_specs"] = []
        with self.assertRaisesRegex(ValueError, "Inherited check phase inputs changed"):
            check_parents.adopt(workflow, resume=True)

    def test_delivery_parent_metadata_cannot_replace_lineage_roots_or_criteria(self):
        workflow = self.workflow()
        workflow.config.update(phase="integration", check_parent="parent")
        parent = self.base / "parent"
        parent.mkdir()
        parent_state = dict(self.state, status="TASKS_READY", check_specs=[self.spec])
        atomic_json(parent / "epic.json", dict(phases=dict(integration=self.run.name)))
        for change, message in (
            (dict(status="RUNNING"), "not complete"),
            (dict(roots={"project": str(self.base)}), "roots differ"),
            (dict(check_specs=[]), "bindings changed"),
            (dict(requirements=[dict(self.requirement, text="Changed")]), "requirements changed"),
        ):
            with self.subTest(change=change), self.assertRaisesRegex(ValueError, message):
                check_parents.verify(workflow, parent, dict(parent_state, **change))
        atomic_json(parent / "epic.json", dict(phases=dict(integration="another-run")))
        with self.assertRaisesRegex(ValueError, "does not link"):
            check_parents.verify(workflow, parent, parent_state)
        with self.assertRaisesRegex(ValueError, "delivery check phase"):
            requests.Submission(dict(check_parent="parent", phase="task"), self.base)

    def test_typed_delivery_labels_do_not_create_new_legacy_runtime_requirements(self):
        spec = dict(self.spec, phase="validation")
        state = dict(self.state, check_specs=[spec])
        checks = dict(jenkins=["C-health: health", "Legacy check still needs a plan"])
        selected = delivery_payload.typed_checks(self.run, state, "validation")
        self.assertEqual(selected["assigned_requirements"], [self.requirement])
        self.assertEqual(selected["check_parent"], self.run.name)
        self.assertEqual(
            delivery_payload.legacy_verification(self.run, state, "validation", checks),
            ["Legacy check still needs a plan"],
        )

    def test_integration_preserves_recorded_requirements_and_accepts_legacy_parents(self):
        state = dict(self.state, check_specs=[self.spec])
        with (
            patch("countersign.web.history.task_draft", return_value=dict(title="Goal")),
            patch("countersign.web.epic_tasks.tasks", return_value=[]),
            patch("countersign.web.parent_context.snapshot", return_value="Parent goal"),
        ):
            typed = integration_review.payload(self.run, state)
            legacy = integration_review.payload(self.run, dict(roots=self.state["roots"]))
        self.assertEqual(typed["assigned_requirements"], [self.requirement])
        self.assertEqual(typed["check_specs"], [self.spec])
        self.assertEqual(typed["check_parent"], self.run.name)
        self.assertEqual(legacy["assigned_requirements"], [])
        self.assertEqual(legacy["check_specs"], [])
        self.assertIsNone(legacy["check_parent"])

    def test_exit_status_and_stylelint_reports_are_explicit_contracts(self):
        self.assertEqual(
            check_diagnostics.assess("exit-code", dict(status="SUCCEEDED"))["status"], "unknown"
        )
        report = [
            dict(
                source="style.css",
                warnings=[
                    dict(
                        line=2,
                        column=3,
                        rule="unknown-property",
                        severity="error",
                        text="Bad property",
                    )
                ],
            )
        ]
        outcome = dict(status="FAILED", exit_code=2, stdout=json.dumps(report))
        assessed = check_diagnostics.assess("stylelint-json", outcome)
        self.assertEqual(assessed["status"], "failed")
        self.assertEqual(assessed["diagnostics"][0]["file"], "style.css")
        with self.assertRaisesRegex(ValueError, "reserved"):
            check_recipes.parse_catalog(dict(check_recipes={"verify-forged": self.recipe}))


if __name__ == "__main__":
    unittest.main()
