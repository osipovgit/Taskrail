"""Small model decisions retain semantic review and exact delivered evidence."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import evidence, result_validation, session_budget, source_packet
from taskrail.core import schema
from taskrail.core.files import atomic_json
from taskrail.interactions import transcripts


class DecisionContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.path = self.root / "sample.py"
        self.path.write_text("value = 2\nother = 3\n")
        self.run = self.base / "run"
        self.folder = self.run / "03-reviewer"
        self.folder.mkdir(parents=True)
        self.context = dict(
            role="reviewer",
            stage="reviewer",
            roots=dict(repo=self.root),
            run=self.run,
            folder=self.folder,
            changed=[str(self.path)],
            requirements=[dict(id="R-stable", kind="task", text="Return two")],
            plan=dict(steps=[dict(id="T1")], proposed_change_files=[str(self.path)]),
        )
        self.observe()

    def observe(self):
        record = dict(
            tool="read",
            input=dict(filePath=str(self.path)),
            output="1: value = 2\n",
            source_sha256=evidence.fingerprint(self.path),
            source_event="prior/events.jsonl",
            event_line=1,
        )
        atomic_json(self.run / evidence.OBSERVATIONS, dict(records=[record], omitted=0))

    def decision(self, **updates):
        payload = dict(
            schema_version=2,
            outcomes=[dict(requirement="R1", result="satisfied", evidence=[f"{self.path}:1"])],
            findings=[],
            missing_inputs=[],
        )
        return dict(payload, **updates)

    def validate(self, payload):
        return result_validation.validate(json.dumps(payload), self.context)

    def test_implementation_derives_files_steps_and_status_from_its_final_word(self):
        self.context.update(role="implementer", stage="implementer")
        done = result_validation.validate(
            "Edited hello.py.\n**DONE:** hello() returns 2", self.context
        )
        self.assertEqual(done["status"], "IMPLEMENTED")
        self.assertEqual(done["summary"], "hello() returns 2")
        self.assertEqual(done["changed_files"], [str(self.path)])
        self.assertEqual(done["completed_steps"], ["T1"])
        self.assertEqual((done["coverage"], done["evidence"]), ([], []))
        blocked = result_validation.validate("BLOCKED: the inventory is missing", self.context)
        self.assertEqual(blocked["status"], "BLOCKED")
        self.assertEqual(blocked["blocking_gaps"], ["the inventory is missing"])
        self.assertEqual(blocked["completed_steps"], [])
        with self.assertRaisesRegex(ValueError, "End your final message with DONE"):
            result_validation.validate(json.dumps(self.decision()), self.context)

    def test_stored_records_and_other_versions_are_not_authored_decisions(self):
        result = self.validate(self.decision())
        self.assertEqual(result["schema_version"], 1)
        with self.assertRaisesRegex(ValueError, "FIELD_KEYS"):
            self.validate(result)
        with self.assertRaisesRegex(ValueError, "Invalid enum"):
            self.validate(dict(self.decision(), schema_version=99))

    def test_handles_only_cover_current_delivered_lines_of_this_stage(self):
        packet = source_packet.prepare(self.run, "reviewer", self.context["roots"])
        self.assertEqual(packet[0]["lines"], {"1": "value = 2"})
        payload = self.decision()
        payload["outcomes"][0]["evidence"] = ["S1:1"]
        self.assertEqual(self.validate(payload)["status"], "APPROVE")
        payload["outcomes"][0]["evidence"] = ["S1:1-2"]
        with self.assertRaisesRegex(ValueError, "complete range"):
            self.validate(payload)
        payload["outcomes"][0]["evidence"] = ["S1:1"]
        self.path.write_text("value = 3\n")
        with self.assertRaisesRegex(ValueError, "Stale source handle"):
            self.validate(payload)

    def test_handles_are_not_available_to_a_different_stage(self):
        source_packet.prepare(self.run, "planner", self.context["roots"])
        payload = self.decision()
        payload["outcomes"][0]["evidence"] = ["S1:1"]
        with self.assertRaisesRegex(ValueError, "Unknown delivered"):
            self.validate(payload)

    def test_findings_need_real_observed_references(self):
        defect = dict(requirement="R1", evidence=[f"{self.path}:1"], problem="Returns wrong value")
        result = self.validate(self.decision(findings=[defect]))
        self.assertEqual(result["status"], "REQUEST_CHANGES")
        self.assertEqual(result["findings"][0]["file"], str(self.path))
        defect["evidence"] = []
        with self.assertRaisesRegex(ValueError, "Finding needs"):
            self.validate(self.decision(findings=[defect]))

    def test_missing_inputs_reduce_to_a_safe_stop(self):
        result = self.validate(self.decision(outcomes=[], missing_inputs=["Missing API contract"]))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["coverage"][0]["outcome"], "not_evaluated")
        self.assertEqual(result["evidence"], [])

    def test_malformed_references_are_addressed_without_guessing_ranges(self):
        references = (
            f"{self.path}:1-1 the file is fixed",
            f"{self.path}: command exited 0",
            f"{self.path}:0-1",
            f"{self.path}:2-1",
            "request.md:1-1",
            "S99:1-1",
        )
        for reference in references:
            with self.subTest(reference=reference):
                payload = self.decision()
                payload["outcomes"][0]["evidence"] = [reference]
                with self.assertRaises(schema.ContractError) as rejected:
                    self.validate(payload)
                self.assertEqual(rejected.exception.code, "EVIDENCE_REFERENCE")
                self.assertEqual(rejected.exception.path, "/outcomes/0/evidence/0")
                draft = json.loads((self.folder / "decision-draft.json").read_text())
                self.assertEqual(draft, payload)
                correction = dict(
                    schema_version=2,
                    corrections=[dict(path=rejected.exception.path, value=f"{self.path}:1-1")],
                )
                self.assertEqual(self.validate(correction)["status"], "APPROVE")
        defect = dict(requirement="R1", evidence=[references[0]], problem="Wrong value")
        with self.assertRaises(schema.ContractError) as rejected:
            self.validate(self.decision(findings=[defect]))
        self.assertEqual(rejected.exception.path, "/findings/0/evidence/0")

    def test_executor_summary_needs_observed_snapshot_lines_not_commentary(self):
        (self.folder / "events.jsonl").write_text("")
        request = dict(cwd=str(self.root), argv=["ansible-lint", "roles/"], reason="Verify")
        outcome = dict(status="SUCCEEDED", exit_code=0, stdout="0 failure(s), 2 warning(s).")
        delivered = transcripts.local_snapshot(self.run, self.folder, request, outcome)
        snapshot = self.run / "00-input/local" / f"{self.folder.name}-0.json"
        payload = self.decision()
        payload["outcomes"][0]["evidence"] = [f"{snapshot}: ansible-lint exit_code 0"]
        with self.assertRaisesRegex(ValueError, "EVIDENCE_REFERENCE"):
            self.validate(payload)
        number = next(
            index
            for index, line in enumerate(snapshot.read_text().splitlines(), 1)
            if '"exit_code": 0' in line
        )
        payload["outcomes"][0]["evidence"] = [f"{snapshot}:{number}-{number}"]
        self.assertIn(str(snapshot), delivered)
        self.assertEqual(self.validate(payload)["status"], "APPROVE")

    def test_missing_input_prose_is_never_silently_discarded(self):
        note = (
            "No optional source was unavailable during this task; all required files were present."
        )
        result = self.validate(self.decision(missing_inputs=[note]))
        self.assertEqual(result["status"], "BLOCKED")
        self.assertEqual(result["blocking_gaps"], [note])
        self.assertEqual(self.validate(self.decision(missing_inputs=[]))["status"], "APPROVE")

    def test_missing_coverage_cannot_be_inferred_from_no_findings(self):
        with self.assertRaisesRegex(ValueError, "Incomplete requirement coverage"):
            self.validate(self.decision(outcomes=[]))

    def test_typed_validation_error_points_to_the_exact_outcome(self):
        payload = self.decision()
        payload["outcomes"][0]["result"] = "probably"
        with self.assertRaises(schema.ContractError) as captured:
            self.validate(payload)
        self.assertEqual(captured.exception.code, "FIELD_ENUM")
        self.assertEqual(captured.exception.path, "/outcomes/0/result")

    def test_addressed_correction_reuses_only_the_unvalidated_draft(self):
        payload = self.decision()
        payload["outcomes"][0]["result"] = "probably"
        with self.assertRaises(schema.ContractError):
            self.validate(payload)
        correction = dict(
            schema_version=2,
            corrections=[dict(path="/outcomes/0/result", value="satisfied")],
        )
        result = self.validate(correction)
        self.assertEqual(result["status"], "APPROVE")
        self.assertEqual(result["evidence"][0]["path"], str(self.path))
        correction["corrections"][0]["path"] = "/changed_files"
        with self.assertRaisesRegex(ValueError, "semantic decision field"):
            self.validate(correction)

    def test_correction_cannot_invent_a_prior_draft_or_unseen_evidence(self):
        correction = dict(schema_version=2, corrections=[dict(path="/outcomes", value=[])])
        with self.assertRaisesRegex(ValueError, "No V2 draft"):
            self.validate(correction)
        self.validate(self.decision())
        correction["corrections"] = [dict(path="/outcomes/0/evidence", value=[f"{self.path}:2"])]
        with self.assertRaisesRegex(ValueError, "matching observed read"):
            self.validate(correction)

    def test_packet_and_admission_are_bounded_by_delivered_bytes(self):
        self.path.write_text("x = 1\n" * 10000)
        self.observe()
        source_packet.prepare(self.run, "reviewer", self.context["roots"])
        self.folder.joinpath("agent.md").write_text("Review source")
        self.folder.joinpath("request.md").write_text("A small request and its exact source range")
        record = dict(role="reviewer")
        self.assertIsNone(session_budget.admission({}, (self.folder, record), []))
        self.assertEqual(record["context_budget"]["planned_input_bytes"], 0)
        self.folder.joinpath("request.md").write_text("large" * 20000)
        outcome = session_budget.admission({}, (self.folder, record), [])
        self.assertTrue(outcome["admission_blocked"])
        self.assertEqual(outcome["status"], "CONTEXT_EXCEEDED")


if __name__ == "__main__":
    unittest.main()
