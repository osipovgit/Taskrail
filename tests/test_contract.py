"""Adversarial contracts: shape alone must never authorize work or approval."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

from countersign.application import evidence, instruction_sources, prompts, result_validation
from countersign.core import control, coverage, plan_contract, schema
from countersign.core.requirements import task_requirements


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
                    "quote": "    return 2",
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
        self.observe(self.stage, "def hello():\n    return 2\n")

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
        return result_validation.validate(json.dumps(payload or self.payload), self.context)

    def test_observed_no_change_result_and_binding(self):
        self.validate()
        bindings = json.loads((self.stage / "evidence-bindings.json").read_text())
        self.assertEqual(bindings[0]["source_event"], str(self.stage / "events.jsonl"))
        self.assertEqual(bindings[0]["source_sha256"], evidence.fingerprint(self.source))

    def test_quote_outside_captured_range_cannot_pass(self):
        (self.run / "evidence.json").unlink()
        (self.run / "observations.json").unlink()
        self.observe(self.stage, "1:def hello():", offset=1, limit=1)
        with self.assertRaisesRegex(ValueError, "matching observed"):
            self.validate()

    def test_stale_evidence_is_rejected_even_if_quoted_line_still_exists(self):
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

    def test_forged_or_wrong_root_quote_fails(self):
        for field, value in [
            ("quote", "return 999"),
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
                schema.decode(invalid, "planner")

    def test_server_sections_are_instructions_and_splits_stay_small(self):
        task = "# Title\n\n## Goal\nShip it\n\n## Workflow rules\nUse English\n\n## Turn control\nSplit\n"
        self.assertEqual(
            [entry["text"] for entry in task_requirements(task, [])],
            ["# Title", "## Goal\nShip it"],
        )
        steps = [dict(id=f"S{number}") for number in range(9)]
        plan = dict(steps=steps, proposed_change_files=["a"])
        with self.assertRaisesRegex(ValueError, "at most 8 tasks"):
            control.check_plan(plan, dict(decompose=True))
        control.check_plan(dict(plan, steps=steps[:8]), dict(decompose=True))

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
        self.payload["steps"] = [
            dict(
                id="S1",
                action="Return 3",
                files=[str(self.source)],
                criteria=["R1"],
                depends_on=[],
                checks=["Static read"],
            )
        ]
        self.validate()
        self.payload["steps"][0]["depends_on"] = ["S2"]
        with self.assertRaisesRegex(ValueError, "dependency"):
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
            json.dumps(self.payload), "bad fields", "planner", 1, self.requirements
        )
        self.assertNotIn("Context:", request)
        self.assertNotIn("Search each", request)
        self.assertNotIn("Find necessary", request)
        self.assertIn("Do not research", request)
        self.assertIn("saved_response", request)

    def test_complete_task_blocks_get_stable_ids_without_history(self):
        task = "# Task\n\nReturn 2\n- Preserve X\n- Preserve Y\n\n## Conversation history\nOld goal"
        entries = task_requirements(task, ["Run Jenkins"])
        text = " ".join(entry["text"] for entry in entries)
        self.assertNotIn("Old goal", text)
        self.assertIn("Preserve Y", text)
        self.assertEqual(entries, task_requirements(task, ["Run Jenkins"]))
        self.assertEqual(entries[-1]["kind"], "runtime")

    def test_frozen_policy_tampering_is_not_accepted_on_continue(self):
        state = {}
        (self.run / "00-input").mkdir(parents=True)
        instruction_sources.freeze_contract(self.run, prompts.POLICY, prompts.INSTRUCTIONS, state)
        frozen = self.run / "00-input/contract.json"
        payload = json.loads(frozen.read_text())
        payload["policy"] = "Different execution policy"
        frozen.write_text(json.dumps(payload))
        with self.assertRaisesRegex(ValueError, "policy changed"):
            instruction_sources.freeze_contract(
                self.run, prompts.POLICY, prompts.INSTRUCTIONS, state
            )

    def test_prose_and_fences_are_removed_without_model_repair(self):
        raw = json.dumps(self.payload)
        for response in ("Notes [optional]\n" + raw, "```json\n" + raw + "\n```\nDone"):
            self.assertEqual(schema.decode(response, "planner"), self.payload)

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
                schema.decode(response, "planner")

    def test_declared_block_cannot_authorize_unvalidated_plan(self):
        self.payload["blocking_gaps"] = ["Local linter execution unavailable"]
        self.payload["evidence"][0]["path"] = "/outside/request.md"
        self.payload["steps"] = [
            dict(
                id="S1",
                action="Change",
                files=["/outside/file"],
                criteria=["Wrong criterion"],
                depends_on=[],
                checks=["Check"],
            )
        ]
        self.payload["proposed_change_files"] = ["/outside/file"]
        outcome = self.validate()
        self.assertEqual(outcome["status"], "BLOCKED")
        self.assertEqual(outcome["steps"], [])
        self.assertEqual(outcome["proposed_change_files"], [])
        self.assertEqual(outcome["evidence"], [])
        self.assertEqual(outcome["coverage"][0]["outcome"], "not_evaluated")
        self.assertEqual(json.loads((self.stage / "blocked-draft.json").read_text()), self.payload)
