"""Plan review cites the exact proposal without turning its claims into completed work."""

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from taskrail.application import evidence, evidence_delivery, result_validation
from taskrail.application.stage_attempts import evidence_roots
from taskrail.core.files import atomic_json
from taskrail.infrastructure import artifact_access


class PlanReviewEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "repo"
        self.root.mkdir()
        self.source = self.root / "config (local).yaml"
        self.source.write_text("skip_list: []\n")
        self.run = self.base / "run"
        self.folder = self.run / "02-plan-review"
        self.folder.mkdir(parents=True)
        saved = self.run / "01-plan"
        saved.mkdir()
        self.plan = dict(proposed_change_files=[str(self.source)], steps=[])
        atomic_json(saved / "result.json", self.plan)
        self.plan_file = self.run / "plan.md"
        self.plan_file.write_text("Verify: skip required check\n")
        (saved / "plan.md").write_bytes(self.plan_file.read_bytes())
        self.context = dict(
            run=self.run,
            folder=self.folder,
            role="reviewer",
            stage="plan-reviewer",
            roots=dict(repo=self.root),
            plan=self.plan,
            plan_reference="01-plan/result.json",
            session_id="review",
            deliver_lines=True,
            requirements=[dict(id="R-check", kind="task", text="Run the check")],
        )

    def observe(self, path, session="review"):
        records = evidence.validation_records(self.run)
        records.append(
            dict(
                tool="read",
                input=dict(filePath=str(path)),
                output="\n".join(
                    f"{number}: {line}"
                    for number, line in enumerate(path.read_text().splitlines(), 1)
                ),
                source_sha256=evidence.fingerprint(path),
                source_event=str(self.folder / "events.jsonl"),
                session_id=session,
                event_line=1,
            )
        )
        atomic_json(self.run / evidence.OBSERVATIONS, dict(records=records, omitted=0))

    def review(self, decision):
        (self.run / "review.md").write_text(f"Summary: Inspect proposal\n- R1: {decision}\n")
        return result_validation.validate("DONE", self.context)

    def test_observed_proposal_defect_with_sentence_period_requests_replanning(self):
        self.observe(self.plan_file)
        self.observe(self.source)
        result = self.review(
            f"fails: {self.plan_file}:1-1; `{self.source}:1` (skips the check (required))."
        )
        self.assertEqual(result["status"], "REQUEST_CHANGES")
        self.assertEqual(result["findings"][0]["evidence"], "skips the check (required) (E1, E2)")
        self.assertEqual(result["evidence"][0]["line_end"], 1)
        bindings = json.loads((self.folder / "evidence-bindings.json").read_text())
        self.assertEqual(bindings[0]["excerpt"], "Verify: skip required check")

    def test_readable_current_proposal_can_prove_planned_work_only_in_plan_review(self):
        for path in (
            self.plan_file,
            self.run / "01-plan/result.json",
        ):
            with self.subTest(path=path):
                self.assertIn(path, artifact_access.model_inputs(self.run, self.folder))
                self.observe(path)
                self.assertEqual(self.review(f"planned: {path}:1.")["status"], "APPROVE")
                with self.assertRaisesRegex(ValueError, "only planned work or a plan defect"):
                    self.review(f"done: {path}:1.")
        self.context["stage"] = "reviewer"
        with self.assertRaisesRegex(ValueError, "Path outside"):
            self.review(f"fails: {self.plan_file}:1 (bad implementation).")

    def test_missing_read_requires_actual_delivery_to_the_current_session(self):
        self.observe(self.plan_file, session="earlier")
        with self.assertRaises(ValueError) as rejected:
            self.review(f"fails: {self.plan_file}:1 (skips check).")
        feedback = str(rejected.exception)
        self.assertIn("now recorded as read", feedback)
        evidence_delivery.confirm(
            self.run,
            self.folder,
            feedback,
            dict(status="OK", completed=True, sessions=["review"]),
            "review",
        )
        self.assertEqual(
            self.review(f"fails: {self.plan_file}:1 (skips check).")["status"], "REQUEST_CHANGES"
        )

    def test_mutated_or_old_proposals_and_other_run_artifacts_are_rejected(self):
        self.observe(self.plan_file)
        self.plan_file.write_text("Verify: something else\n")
        with self.assertRaisesRegex(ValueError, "plan under review changed"):
            self.review(f"fails: {self.plan_file}:1 (wrong proposal).")
        for relative in (
            "old-plan/result.json",
            "01-plan/plan.md",
            "02-plan-review/request.md",
            "review.md",
        ):
            path = self.run / relative
            path.parent.mkdir(exist_ok=True)
            path.write_text("untrusted note\n")
            self.observe(path)
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "Path outside"):
                self.review(f"fails: {path}:1 (wrong source).")

    def test_runtime_plan_defect_needs_no_execution_but_cannot_claim_runtime_success(self):
        self.context["requirements"][0]["kind"] = "runtime"
        self.observe(self.plan_file)
        self.assertEqual(
            self.review(f"fails: {self.plan_file}:1 (required check is skipped).")["status"],
            "REQUEST_CHANGES",
        )
        with self.assertRaisesRegex(ValueError, "only planned work or a plan defect"):
            self.review(f"done: {self.plan_file}:1.")
        self.context["stage"] = "reviewer"
        self.observe(self.source)
        with self.assertRaisesRegex(ValueError, "matching current CheckResult"):
            self.review(f"fails: `{self.source}:1` (runtime failed).")

    def test_native_check_snapshot_read_reaches_result_review_without_a_repair_turn(self):
        self.context.update(stage="reviewer", deliver_lines=False)
        snapshot = self.run / "00-input/checks/output.txt"
        snapshot.parent.mkdir(parents=True)
        snapshot.write_text("Verification completed\n")
        event = dict(
            type="tool_use",
            sessionID="review",
            part=dict(
                tool="read",
                id="check-read",
                state=dict(
                    status="completed",
                    input=dict(filePath=str(snapshot)),
                    output="1: Verification completed",
                ),
            ),
        )
        events = self.folder / "events.jsonl"
        events.write_text(json.dumps(event) + "\n")
        workflow = SimpleNamespace(
            run=self.run,
            config=dict(roots=self.context["roots"]),
            state=dict(results={}),
            flow=dict(stage="reviewer"),
        )
        evidence.refresh(self.run, events, evidence_roots(workflow))
        self.assertEqual(self.review(f"done: {snapshot}:1.")["status"], "APPROVE")

    def test_symlink_and_changed_stored_plan_cannot_replace_the_reviewed_proposal(self):
        snapshot = self.run / "01-plan/result.json"
        self.observe(self.plan_file)
        original = snapshot.read_bytes()
        snapshot.write_text(json.dumps(dict(self.plan, proposed_change_files=[])))
        with self.assertRaisesRegex(ValueError, "plan under review changed"):
            self.review(f"fails: {self.plan_file}:1 (wrong proposal).")
        snapshot.write_bytes(original)
        self.plan_file.unlink()
        self.plan_file.symlink_to(self.run / "01-plan/plan.md")
        with self.assertRaisesRegex(ValueError, "plan under review changed"):
            self.review(f"fails: {self.plan_file}:1 (wrong proposal).")
