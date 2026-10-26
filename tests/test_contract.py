"""Adversarial contracts: shape alone must never authorize work or approval."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import evidence, instruction_sources, prompts, result_validation
from taskrail.core import (
    control,
    coverage,
    json_response,
    plan_contract,
    schema,
    source_claims,
    task_markdown,
    task_spec,
)


def decoded(response):
    """One unambiguous object in the planner's stored shape."""
    payload = json_response.extract(response, schema.unique_fields)
    schema.validate(payload, schema.SCHEMAS["planner"])
    return payload


def task_requirements(text, deferred=()):
    """The requirements of a task file read like a CLI task."""
    meta = task_markdown.typed_input(text, dict(verification=list(deferred)))
    return task_spec.resolve(text, meta)["requirements"]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "source"
        self.root.mkdir()
        self.source = self.root / "hello.py"
        self.source.write_text("def hello():\n    return 2\n")
        self.run = self.base / "run"
        self.stage = self.run / "01-plan"
        self.stage.mkdir(parents=True)
        self.requirements = [{"id": "R1", "kind": "task", "text": "Return 2"}]
        self.payload = {
            "schema_version": 1,
            "status": "PLAN_READY",
            "decision": "none",
            "summary": "Already returns 2",
            "steps": [],
            "files_read": [str(self.source)],
            "proposed_change_files": [],
            "coverage": [
                {
                    "id": "R1",
                    "outcome": "satisfied",
                    "evidence_ids": ["E1"],
                    "explanation": "Return statement",
                }
            ],
            "evidence": [
                {
                    "id": "E1",
                    "path": str(self.source),
                    "line_start": 2,
                    "line_end": 2,
                }
            ],
            "unverified": [],
            "blocking_gaps": [],
        }
        self.context = dict(
            role="planner",
            stage="planner",
            requirements=self.requirements,
            roots={"project": self.root},
            run=self.run,
            folder=self.stage,
            plan=None,
            changed=[],
        )
        self.observe(self.stage, "1: def hello():\n2:     return 2\n")

    def observe(self, folder, output, **inputs):
        folder.mkdir(exist_ok=True)
        event = {
            "type": "tool_use",
            "part": {
                "tool": "read",
                "callID": "read1",
                "state": {
                    "status": "completed",
                    "input": dict(filePath=str(self.source), **inputs),
                    "output": output,
                    "metadata": {"truncated": True},
                },
            },
        }
        events = folder / "events.jsonl"
        events.write_text(json.dumps(event) + "\n")
        return evidence.refresh(self.run, events, self.context["roots"].values())

    def validate(self, payload=None):
        return result_validation.checked(decoded(json.dumps(payload or self.payload)), self.context)

    def test_observed_no_change_result_and_binding(self):
        self.validate()
        bindings = json.loads((self.stage / "evidence-bindings.json").read_text())
        self.assertEqual(bindings[0]["excerpt"], "    return 2")
        self.assertEqual(bindings[0]["source_event"], str(self.stage / "events.jsonl"))
        self.assertEqual(bindings[0]["source_sha256"], evidence.fingerprint(self.source))

    def test_citation_outside_captured_range_cannot_pass(self):
        (self.run / "evidence.json").unlink()
        (self.run / "observations.json").unlink()
        self.observe(self.stage, "1:def hello():", offset=1, limit=1)
        with self.assertRaisesRegex(ValueError, "matching observed"):
            self.validate()

    def test_duplicate_source_text_must_be_observed_at_the_cited_position(self):
        self.source.write_text("same\nhidden\nsame\n")
        self.observe(self.stage, "1: same", offset=1, limit=2000)
        self.payload["evidence"][0].update(line_start=3, line_end=3)
        with self.assertRaisesRegex(ValueError, "matching observed"):
            self.validate()
        self.observe(self.stage, "3: same", offset=1, limit=2000)
        self.validate()

    def test_stale_evidence_is_rejected_even_if_cited_line_still_exists(self):
        self.source.write_text(self.source.read_text() + "\n# Changed source\n")
        with self.assertRaisesRegex(ValueError, "matching observed"):
            self.validate()

    def test_evidence_accumulates_then_invalidates(self):
        second = self.run / "02-plan"
        index = self.observe(second, "2:    return 2", offset=2, limit=1)
        self.assertEqual(len(index["records"]), 2)
        self.source.write_text("def hello():\n    return 3\n")
        index = self.observe(second, "2:    return 3", offset=2, limit=1)
        self.assertEqual(len(index["records"]), 1)
        self.assertIn("return 3", index["records"][0]["output"])

    def test_large_report_citation_unions_complete_windows_with_provenance(self):
        lines = [f"Finding {number}" for number in range(1, 1046)]
        self.source.write_text("\n".join(lines) + "\n")
        self.payload["evidence"][0].update(line_start=1, line_end=len(lines))
        for start in range(1, len(lines) + 1, 200):
            window = lines[start - 1 : start + 199]
            output = "\n".join(f"{number}: {line}" for number, line in enumerate(window, start))
            self.observe(self.run / f"read-{start}", output, offset=start, limit=200)
        self.validate()
        proof = json.loads((self.stage / "evidence-bindings.json").read_text())[0]
        self.assertEqual(len(proof["observations"]), 6)
        self.assertEqual(proof["source_event"], str(self.run / "read-1001/events.jsonl"))
        self.assertEqual(proof["event_line"], 1)
        ranges = [entry["line_ranges"] for entry in proof["observations"]]
        self.assertEqual(
            ranges,
            [[[1001, 1045]], [[801, 1000]], [[601, 800]], [[401, 600]], [[201, 400]], [[1, 200]]],
        )

    def test_missing_evidence_feedback_names_only_gaps_between_observed_windows(self):
        lines = [f"Finding {number}" for number in range(1, 601)]
        self.source.write_text("\n".join(lines) + "\n")
        self.payload["evidence"][0].update(line_start=1, line_end=len(lines))
        for start, end in ((1, 199), (201, 599)):
            output = "\n".join(f"{number}: {lines[number - 1]}" for number in range(start, end + 1))
            self.observe(self.run / f"read-{start}", output, offset=start, limit=end - start + 1)
        with self.assertRaises(ValueError) as rejected:
            self.validate()
        reason = str(rejected.exception)
        self.assertIn("offset=200, limit=1", reason)
        self.assertIn("offset=600, limit=1", reason)
        self.assertNotIn("offset=1,", reason)
        for number in (200, 600):
            self.observe(
                self.run / f"read-{number}",
                f"{number}: {lines[number - 1]}",
                offset=number,
                limit=1,
            )
        self.validate()

    def test_missing_range_feedback_limits_number_and_size_of_read_requests(self):
        self.source.write_text("unseen\n" * 750)
        self.payload["evidence"][0].update(line_start=1, line_end=750)
        with self.assertRaises(ValueError) as rejected:
            self.validate()
        reason = str(rejected.exception)
        self.assertIn("offset=1, limit=200", reason)
        self.assertIn("offset=201, limit=200", reason)
        self.assertIn("offset=401, limit=200", reason)
        self.assertIn("Further missing windows: 1", reason)
        self.assertNotIn("offset=601", reason)

    def test_missing_long_lines_are_requested_in_byte_bounded_windows(self):
        for line in ("x" * 1500, "\u754c" * 500):
            with self.subTest(utf8_line_bytes=len(line.encode("utf-8"))):
                self.source.write_text((line + "\n") * 200)
                self.payload["evidence"][0].update(line_start=1, line_end=200)
                with self.assertRaises(ValueError) as rejected:
                    self.validate()
                reason = str(rejected.exception)
                self.assertIn("offset=1, limit=7", reason)
                self.assertIn("offset=8, limit=7", reason)
                self.assertIn("offset=15, limit=7", reason)
                self.assertNotIn("limit=200", reason)

    def test_later_partial_read_with_same_arguments_preserves_complete_observation(self):
        self.observe(self.run / "later-read", "1: def hello():")
        self.validate()
        records = evidence.validation_records(self.run)
        self.assertEqual(len(records), 2)
        self.assertEqual(records[0]["output"], "1: def hello():\n2:     return 2\n")
        self.observe(self.run / "later-read", "1: def hello():")
        self.assertEqual(len(evidence.validation_records(self.run)), 2)

    def test_union_never_fills_missing_lines_from_a_stale_source_version(self):
        records = evidence.validation_records(self.run)
        self.source.write_text(self.source.read_text() + "# Changed source\n")
        self.observe(self.run / "current-read", "1: def hello():", offset=1, limit=1)
        records.extend(evidence.validation_records(self.run))
        claim = dict(self.payload["evidence"][0], line_start=1, line_end=2)
        with self.assertRaisesRegex(ValueError, "offset=2, limit=1"):
            source_claims.validate_claim(claim, records)

    def test_directory_or_missing_citation_is_feedback_not_a_crash(self):
        for path, message in (
            (self.source.parent, "regular file, not a directory"),
            (self.source.parent / "absent.py", "cited file does not exist"),
        ):
            claim = dict(self.payload["evidence"][0], path=str(path))
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, message):
                source_claims.validate_claim(claim, evidence.validation_records(self.run))

    def test_forged_or_wrong_root_citation_fails(self):
        for field, value in [
            ("line_start", 3),
            ("path", "/outside/hello.py"),
            ("line_end", 1377),
        ]:
            candidate = copy.deepcopy(self.payload)
            candidate["evidence"][0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(candidate)

    def test_missing_duplicate_and_unknown_criteria_fail(self):
        for entries in (
            [],
            self.payload["coverage"] * 2,
            [dict(self.payload["coverage"][0], id="unknown")],
        ):
            candidate = dict(self.payload, coverage=entries)
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.validate(candidate)

    def test_unknown_evidence_reference_fails(self):
        self.payload["coverage"][0]["evidence_ids"] = ["E2"]
        with self.assertRaisesRegex(ValueError, "Unknown evidence"):
            self.validate()

    def test_runtime_cannot_be_claimed_executed(self):
        self.requirements[0]["kind"] = "runtime"
        with self.assertRaisesRegex(ValueError, "Runtime verification"):
            self.validate()
        self.payload["coverage"][0]["outcome"] = "deferred"
        self.payload["unverified"] = ["Run twice in Jenkins; verify no cache reuse"]
        self.validate()

    def test_required_evidence_cannot_be_deferred(self):
        self.payload["coverage"][0]["outcome"] = "deferred"
        self.payload["unverified"] = ["Check later"]
        with self.assertRaisesRegex(ValueError, "cannot be deferred"):
            self.validate()

    def test_result_rejects_ambiguous_unknown_fields_and_duplicate_keys(self):
        raw = json.dumps(self.payload)
        for invalid in [
            raw + raw,
            raw.replace('"summary":', '"status":"BLOCKED","summary":'),
            json.dumps(dict(self.payload, tests_passed=True)),
        ]:
            with self.subTest(invalid=invalid[:50]), self.assertRaises(ValueError):
                decoded(invalid)

    def test_unknown_task_sections_are_errors_and_splits_stay_small(self):
        task = "# Title\n\n## Goal\nShip it\n\n## Workflow rules\nUse English\n"
        with self.assertRaisesRegex(ValueError, "line 6: unknown section 'Workflow rules'"):
            task_requirements(task)
        steps = [dict(id=f"T{number}") for number in range(30)]
        plan = dict(steps=steps, proposed_change_files=["a"])
        control.check_plan(plan, dict(decompose=True))
        with self.assertRaisesRegex(ValueError, "no change and no tasks"):
            control.check_plan(plan, dict(read_only=True))

    def test_relative_path_error_names_the_absolute_form(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            (root / "roles").mkdir()
            (root / "roles/main.yaml").write_text("- name: x\n")
            with self.assertRaisesRegex(ValueError, "not roles/main.yaml \\(for example /"):
                result_validation.approved_path("roles/main.yaml", {"project": root})

    def test_structured_step_must_own_planned_requirement(self):
        self.payload["coverage"][0]["outcome"] = "planned"
        with self.assertRaisesRegex(ValueError, "owning step"):
            self.validate()
        self.payload["proposed_change_files"] = [str(self.source)]
        self.payload["decision"] = "single"
        self.payload["steps"] = [
            step(id="S1", action="Return 3", files=[str(self.source)], criteria=["R1"])
        ]
        self.validate()
        self.payload["steps"][0]["depends_on"] = ["S2"]
        with self.assertRaisesRegex(ValueError, "unknown task"):
            self.validate()

    def test_incomplete_and_no_change_reviews_cannot_approve(self):
        review = {
            key: value
            for key, value in self.payload.items()
            if key not in {"steps", "files_read", "proposed_change_files"}
        }
        review.update(status="APPROVE", input_complete=False, findings=[])
        with self.assertRaisesRegex(ValueError, "Required gap"):
            coverage.validate_coverage(review, self.requirements, "plan-reviewer")
        review["input_complete"] = True
        review["coverage"][0]["outcome"] = "planned"
        with self.assertRaisesRegex(ValueError, "future work"):
            result_validation.validate_review(review, self.payload)

    def test_implementation_must_match_observed_changes_and_steps(self):
        plan = {"steps": [{"id": "S1"}]}
        payload = {
            "status": "IMPLEMENTED",
            "changed_files": ["/source/file"],
            "completed_steps": ["S1"],
        }
        with self.assertRaisesRegex(ValueError, "source scan"):
            plan_contract.validate_completion(payload, plan, [])
        payload["changed_files"] = []
        payload["completed_steps"] = []
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            plan_contract.validate_completion(payload, plan, [])

    def test_format_repair_has_no_research_context(self):
        request = prompts.repair(
            json.dumps(self.payload), "bad fields", "reviewer", 1, self.requirements
        )
        self.assertNotIn("Context:", request)
        self.assertNotIn("Search each", request)
        self.assertNotIn("Find necessary", request)
        self.assertIn("Do not research", request)
        self.assertIn("saved_response", request)

    def test_complete_task_blocks_get_stable_ids(self):
        task = "# Task\n\nReturn 2\n- Preserve X\n- Preserve Y\n"
        entries = task_requirements(task, ["Run Jenkins"])
        self.assertEqual(
            [entry["text"] for entry in entries],
            ["Return 2", "- Preserve X", "- Preserve Y", "Run Jenkins"],
        )
        self.assertEqual(entries, task_requirements(task, ["Run Jenkins"]))
        self.assertEqual(entries[-1]["kind"], "runtime")

    def test_frozen_policy_tampering_is_not_accepted_on_continue(self):
        state = {}
        (self.run / "00-input").mkdir(parents=True)
        instruction_sources.freeze_contract(self.run, prompts.POLICY, state)
        frozen = self.run / "00-input/contract.json"
        payload = json.loads(frozen.read_text())
        payload["policy"] = "Different execution policy"
        frozen.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "policy changed"):
            instruction_sources.freeze_contract(self.run, prompts.POLICY, state)

    def test_prose_and_fences_are_removed_without_model_repair(self):
        raw = json.dumps(self.payload)
        for response in ("Notes [optional]\n" + raw, "```json\n" + raw + "\n```\nDone"):
            self.assertEqual(decoded(response), self.payload)

    def test_truncated_or_nested_json_is_never_rescued(self):
        raw = json.dumps(self.payload)
        for response in (
            raw[:-1],
            "[" + raw,
            "[" + raw + "]",
            '{"draft":' + raw,
            "{}\n" + raw,
            raw + "\n[1]",
        ):
            with self.subTest(response=response[:30]), self.assertRaises(ValueError):
                decoded(response)

    def test_declared_block_cannot_authorize_unvalidated_plan(self):
        self.payload["blocking_gaps"] = ["Local linter execution unavailable"]
        self.payload["evidence"][0]["path"] = "/outside/request.md"
        self.payload["steps"] = [
            step(id="S1", action="Change", files=["/outside/file"], criteria=["Wrong criterion"])
        ]
        self.payload["proposed_change_files"] = ["/outside/file"]
        outcome = self.validate()
        self.assertEqual(outcome["status"], "BLOCKED")
        self.assertEqual(outcome["steps"], [])
        self.assertEqual(outcome["proposed_change_files"], [])
        self.assertEqual(outcome["evidence"], [])
        self.assertEqual(outcome["coverage"][0]["outcome"], "not_evaluated")
        self.assertEqual(json.loads((self.stage / "blocked-draft.json").read_text()), self.payload)


def step(**fields):
    """A stored plan step with the fields the planner schema requires."""
    entry = dict(id="S1", title="Task", line=1, depends_on=[], checks=["Check"], done_when=["Done"])
    entry.update(scopes=[], notes="")
    return dict(entry, **fields)
