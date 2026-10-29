"""Context remains complete, bounded and consistent across executor turns."""

import json
import tempfile
import unittest
from pathlib import Path

from taskrail.application import execution_wait, prompts, response_format
from taskrail.core import prompt_texts, task_markdown, task_spec
from taskrail.core.files import atomic_json
from taskrail.core.plan_document import payload
from taskrail.infrastructure import artifact_access
from taskrail.interactions import transcripts

PLAN = """**Decision:** split
Summary: Keep __name__ and `shell` literal.
## Requirements
- R1 → T1 [first], T2 [second]
## T1: First
Depends on: none
Files: `project/__init__.py`
Done when: __name__ stays unchanged
Verify: bash -c 'echo `pwd` && echo __name__'
Notes: Keep <!-- literal --> in the generated text.
## Task 2: Second
Depends on:
- Task 1
Files: project/__main__.py
Done when: The second part works
Verify: python -m project
"""


class ContextContractTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.run = Path(temporary.name)
        (self.run / "00-input").mkdir()
        self.stage = self.run / "01-plan"
        self.stage.mkdir()
        (self.stage / "events.jsonl").touch()

    def test_plan_values_are_lossless_and_dependencies_are_complete(self):
        requirements = [dict(id="R-a", kind="task", text="Implement both parts")]
        plan = payload(PLAN, requirements, {"project": "/repo"})
        first, second = plan["steps"]
        self.assertEqual(first["files"], ["/repo/__init__.py"])
        self.assertEqual(first["checks"], ["bash -c 'echo `pwd` && echo __name__'"])
        self.assertEqual(first["notes"], "Keep <!-- literal --> in the generated text.")
        self.assertEqual(second["depends_on"], ["T1"])
        self.assertIn("__name__", plan["summary"])
        for invalid in ("Task 1 later", "T1, typo", "nonsense"):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "Depends on"):
                payload(
                    PLAN.replace("- Task 1", f"- {invalid}"), requirements, {"project": "/repo"}
                )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            payload(
                PLAN.replace("Depends on: none", "Depends on: none\nAfter: none"), requirements, {}
            )

    def test_plan_and_parent_snapshot_are_explicit_readable_inputs(self):
        inputs = (self.run / "plan.md", self.run / "00-input/parent-task.md")
        for path in inputs:
            path.write_text("input")
        manifest = artifact_access.manifest(self.run, self.stage, {})
        for path in inputs:
            self.assertIn(str(path), manifest["readable_artifacts"])
        inputs[-1].unlink()
        inputs[-1].symlink_to(inputs[0])
        self.assertNotIn(inputs[-1], artifact_access.model_inputs(self.run, self.stage))

    def test_planner_continuations_keep_the_plan_file_contract(self):
        for text in (
            response_format.continuation("planner", "/run/request.md"),
            response_format.correction("planner", "missing R1"),
        ):
            self.assertNotIn("corrected final JSON", text)
        continuation = response_format.continuation("planner", "/run/request.md")
        self.assertIn("plan.md", continuation)
        self.assertIn("reply DONE", continuation)
        self.assertIn("only the windows named in the feedback", continuation)
        self.assertIn("formatted source view", continuation)
        self.assertNotIn("attached JSON contract", prompt_texts.text("profile.runtime_rules"))
        self.assertIn("review.md", response_format.finish("reviewer"))
        feedback = response_format.correction("planner", "no matching observed read")
        self.assertIn("no matching observed read", feedback)
        self.assertNotIn("corrections", feedback)
        self.assertNotIn('"corrections"', response_format.correction("reviewer", "bad"))

    def test_requirements_exclude_navigation_but_task_keeps_all_context(self):
        text = (
            "# API\n\n## Goal\n\nReject invalid names.\n\n## Acceptance criteria\n"
            "- Return 400.\n\n## Current behavior\nReturns 500.\n\n"
            "## Known entry points\nsrc/api.py\n\n## Additional constraints\nKeep Unicode.\n"
        )
        meta = task_markdown.typed_input(text, dict(verification=["Run the integration check"]))
        spec = task_spec.resolve(text, meta)
        entries = spec["requirements"]
        self.assertEqual(
            [entry["text"] for entry in entries],
            [
                "Reject invalid names.",
                "- Return 400.",
                "Keep Unicode.",
                "Run the integration check",
            ],
        )
        shown = task_spec.prompt_text(spec, entries)
        for expected in (
            "Returns 500.",
            "src/api.py",
            "## Title\nAPI",
            "Run the integration check",
        ):
            self.assertIn(expected, shown)
        root = self.run / "source"
        root.mkdir()
        state = dict(
            contract_version=1,
            requirements=entries,
            roots={"project": str(root)},
            checks=[],
            preimages={},
        )
        config = dict(task_text=text, task_spec=spec, roots={"project": root})
        request = prompts.make_request(config, ("planner", None, [], None), state, self.run)
        self.assertEqual(request.count("Reject invalid names."), 1)
        self.assertEqual(request.count("Run the integration check"), 1)

    def test_local_progress_cannot_hide_short_stderr_or_status(self):
        outcome = dict(
            exit_code=1,
            stdout="progress\n" * 10000,
            stderr="FATAL missing executable",
            status="FAILED",
        )
        response = transcripts.local_snapshot(self.run, self.stage, {"argv": ["check"]}, outcome)
        self.assertIn("status: FAILED", response)
        self.assertIn("exit_code: 1", response)
        self.assertIn("FATAL missing executable", response)
        self.assertLess(len(response), 6000)

    def test_large_local_request_cannot_hide_short_result(self):
        response = transcripts.local_snapshot(
            self.run,
            self.stage,
            {"argv": ["check", "argument" * 10000]},
            dict(status="FAILED", exit_code=2, stderr="FATAL invalid arguments", stdout=""),
        )
        self.assertIn("status: FAILED", response)
        self.assertIn("exit_code: 2", response)
        self.assertIn("FATAL invalid arguments", response)
        self.assertLess(len(response), 6000)

    def test_labels_preserve_multiline_requirement_bytes(self):
        block = "Preserve __name__ identifiers\r\nand `shell` quotes."
        text = f"## Goal\r\n\r\n{block}\r\n"
        spec = task_spec.resolve(text, task_markdown.typed_input(text, {}))
        requirements = spec["requirements"]
        self.assertEqual(requirements[0]["text"], block)
        shown = task_spec.prompt_text(spec, requirements)
        self.assertEqual(shown.count(block), 1)
        self.assertTrue(shown.endswith(f"[R1]\n{block}"))

    def test_remote_delivery_is_delta_only_and_snapshots_are_immutable(self):
        entries = [
            dict(
                id=f"ticket-{number}",
                status="SUCCEEDED",
                results=[dict(output=f"output-{number}\r\n" * 4000)],
            )
            for number in range(10)
        ]
        atomic_json(self.run / "execution.json", entries)
        response = execution_wait.resume(self.run, {"attempts": []})
        snapshot = self.run / "00-input/ssh/ticket-9.json"
        saved = snapshot.read_bytes()
        self.assertEqual(json.loads(saved), [entries[-1]])
        self.assertNotIn("output-0", response)
        self.assertIn("output-9", response)
        self.assertLess(len(response), 6000)
        output = snapshot.with_suffix(".1-output.txt")
        execution_wait.resume(self.run, {"attempts": []})
        self.assertEqual(snapshot.read_bytes(), saved)
        output.write_text("changed")
        with self.assertRaisesRegex(ValueError, "snapshot changed"):
            execution_wait.resume(self.run, {"attempts": []})

    def test_legacy_remote_snapshot_is_not_rewritten(self):
        entries = [
            dict(id="old", status="SUCCEEDED", results=[dict(console="older output")]),
            dict(id="latest", status="SUCCEEDED", results=[dict(console="latest output")]),
        ]
        atomic_json(self.run / "execution.json", entries)
        snapshot = self.run / "00-input/ssh/latest.json"
        snapshot.parent.mkdir()
        atomic_json(snapshot, entries)
        saved = snapshot.read_bytes()
        response = execution_wait.resume(self.run, {"attempts": []})
        self.assertEqual(snapshot.read_bytes(), saved)
        self.assertNotIn("older output", response)
        self.assertIn("latest output", response)

    def test_many_remote_targets_have_a_bounded_preview(self):
        entries = [
            dict(
                id="targets",
                status="FAILED",
                results=[
                    dict(target=f"host-{number}", status="FAILED", output="failure\n" * 3000)
                    for number in range(40)
                ],
            )
        ]
        atomic_json(self.run / "execution.json", entries)
        response = execution_wait.resume(self.run, {"attempts": []})
        self.assertIn("Ticket targets: FAILED", response)
        self.assertLess(len(response), 24500)
        snapshot = self.run / "00-input/ssh/targets.json"
        self.assertEqual(json.loads(snapshot.read_bytes()), entries)


if __name__ == "__main__":
    unittest.main()
