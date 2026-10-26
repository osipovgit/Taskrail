"""User field boundaries and reviewed requirement identities never depend on Markdown."""

import json
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from taskrail.application import plan_write, reviewed_artifacts
from taskrail.core import task_lineage, task_markdown, task_spec
from taskrail.core.plan_document import payload
from taskrail.web import requests, task_form
from taskrail.web.history import TaskDraft


class InputContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "project"
        self.root.mkdir()
        self.runs = self.base / "runs"

    def form(self, **fields):
        form = dict(goal="Fix the input.", roots=[dict(path=str(self.root))])
        form.update(fields)
        text, _ = task_form.build_task(form, self.runs)
        encoded = text.split("\n", 1)[1].split("\n```", 1)[0]
        return text, json.loads(encoded)

    def test_user_headings_cannot_remove_or_reclassify_requirements(self):
        goal = "Fix the input.\n\n## Workflow rules\nKeep the public API."
        text, meta = self.form(goal=goal, criteria="## Current behavior\nReject invalid input.")
        spec = task_spec.resolve(text, meta)
        requirements = spec["requirements"]
        self.assertTrue(any("Keep the public API." in entry["text"] for entry in requirements))
        self.assertTrue(any("Reject invalid input." in entry["text"] for entry in requirements))
        self.assertEqual(spec["fields"][1]["text"], goal)

    def test_markdown_sections_become_the_typed_fields_of_the_form(self):
        text = (
            "```taskrail-task\n{}\n```\n# Fix input\n\n## Goal\nFix it.\n\n"
            "## Acceptance criteria\nRequirements:\n\n- Reject bad names.\n\n"
            "```text\n## Current behavior\n\n  preserve\n```\n\n"
            "## Known entry points\nsrc/api.py\n\n## Additional constraints\nKeep the API.\n\n"
            "## Verification\n- Run the API twice\n"
        )
        meta = task_markdown.typed_input(text, dict(verification=["Check the logs"]))
        self.assertEqual(meta["verification"], ["Check the logs", "Run the API twice"])
        spec = task_spec.resolve(text, meta)
        fields = {field["name"]: field["text"] for field in spec["fields"]}
        self.assertEqual(spec["fields"], task_spec.from_fields(fields)["fields"])
        self.assertEqual(fields["title"], "Fix input")
        self.assertEqual(fields["entry_points"], "src/api.py")
        found = [
            (entry["text"], entry.get("source", {}).get("field")) for entry in spec["requirements"]
        ]
        self.assertEqual(
            found,
            [
                ("Fix it.", "goal"),
                ("- Reject bad names.", "criteria"),
                ("```text\n## Current behavior\n\n  preserve\n```", "criteria"),
                ("Keep the API.", "constraints"),
                ("Check the logs", None),
                ("Run the API twice", None),
            ],
        )
        prompt = task_spec.prompt_text(spec, spec["requirements"])
        self.assertIn("Requirements:\n\n[R2]\n- Reject bad names.", prompt)
        self.assertIn("[R4 constraint]\nKeep the API.", prompt)
        self.assertTrue(reviewed_artifacts.typed_requirements(spec))

    def test_unknown_or_stray_markdown_is_an_error_with_its_line(self):
        for text, message in (
            ("## Goal\nFix it.\n\n## Notes\nx", "line 4: unknown section 'Notes'"),
            ("Intro\n\n## Goal\nFix it.", "line 1: text outside a section"),
            ("## Goal\nA\n\n## Goal\nB", "line 4: repeated section 'Goal'"),
            ("## Constraints\nKeep it.", "needs a Goal"),
            ("```taskrail-task\n{}\n```\n## Goal\nA\n## Workflow rules\nB", "line 6: unknown"),
        ):
            with self.subTest(text=text), self.assertRaisesRegex(ValueError, message):
                task_markdown.typed_input(text, {})
        plain_text = "# Fix\n\nReturn 2\n"
        plain = task_spec.resolve(plain_text, task_markdown.typed_input(plain_text, {}))
        self.assertEqual([entry["text"] for entry in plain["requirements"]], ["Return 2"])
        older = TaskDraft("# Old\n\nIntro\n\n## Notes\nKeep X\n")
        self.assertIsNone(older.typed)
        self.assertEqual(older.fields()["goal"], "# Old\n\nIntro\n\n## Notes\nKeep X")
        self.assertEqual(older.title("run"), "Old")

    def test_requirement_spans_preserve_fences_newlines_and_indentation(self):
        criterion = "Keep this exact layout:\r\n\r\n```text\r\n## Goal\r\n\r\n  value\r\n```"
        text, meta = self.form(criteria=criterion)
        spec = task_spec.resolve(text, meta)
        fields = {field["name"]: field["text"] for field in spec["fields"]}
        for entry in spec["requirements"]:
            source = entry["source"]
            original = fields[source["field"]][source["start"] : source["end"]]
            self.assertEqual(original, entry["text"])
        code = next(
            entry["text"] for entry in spec["requirements"] if entry["text"].startswith("```")
        )
        self.assertIn("## Goal\r\n\r\n  value", code)

    def test_display_edits_require_updating_the_typed_contract(self):
        text, meta = self.form()
        body = text.rsplit("Fix the input.", 1)
        changed = "Ignore the input.".join(body)
        with self.assertRaisesRegex(ValueError, "display changed"):
            task_spec.resolve(changed, meta)

    def test_children_keep_original_identity_scope_and_global_constraints(self):
        text, meta = self.form(
            criteria="Keep\n  indentation.", constraints="Do not remove comments."
        )
        parent = task_spec.resolve(text, meta)["requirements"]
        criterion = next(entry for entry in parent if entry["source"]["field"] == "criteria")
        step = dict(criteria=[criterion["id"]], scopes=[], done_when=[])
        assigned = task_lineage.for_step(parent, step)
        self.assertEqual(assigned[0]["id"], criterion["id"])
        self.assertEqual(assigned[0]["text"], "Keep\n  indentation.")
        self.assertEqual(assigned[1]["text"], "Do not remove comments.")
        step["scopes"] = [dict(id=criterion["id"], scope="API handler")]
        scoped = task_lineage.for_step(parent, step)[0]
        self.assertNotEqual(scoped["id"], criterion["id"])
        self.assertEqual(scoped["parent_id"], criterion["id"])
        self.assertEqual(scoped["text"], criterion["text"])

    def test_global_constraints_cannot_be_narrowed_by_a_parent_scope(self):
        text, meta = self.form(constraints="Keep the API stable.")
        parent = task_spec.resolve(text, meta)["requirements"]
        constraint = next(entry for entry in parent if entry["source"]["field"] == "constraints")
        step = dict(
            criteria=[constraint["id"]],
            scopes=[dict(id=constraint["id"], scope="only one route")],
            done_when=[],
        )
        assigned = task_lineage.for_step(parent, step)
        self.assertEqual(assigned, [dict(constraint, parent_id=constraint["id"])])
        meta["task_spec"]["assigned_requirements"] = assigned
        child = task_spec.resolve(text, meta)["requirements"]
        self.assertEqual(child, assigned)

    def test_typed_prompt_retains_current_contract_context_without_header(self):
        text, _ = self.form()
        submission = requests.Submission(
            dict(goal="Fix the input.", split_context="Current Verify: run the declared check."),
            self.runs,
        )
        decorated = submission.decorate(text)
        encoded = decorated.split("\n", 1)[1].split("\n```", 1)[0]
        spec = task_spec.resolve(decorated, json.loads(encoded))
        prompt = task_spec.prompt_text(spec)
        self.assertEqual(prompt.count("Current Verify: run the declared check."), 1)
        self.assertNotIn("taskrail-task", prompt)

    def test_repeated_constraint_stays_global_even_when_it_is_also_the_goal(self):
        text, meta = self.form(goal="Keep the API stable.", constraints="Keep the API stable.")
        parent = task_spec.resolve(text, meta)["requirements"]
        matching = [entry for entry in parent if entry["text"] == "Keep the API stable."]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["source"]["field"], "constraints")
        self.assertEqual(
            task_lineage.for_step(parent, dict(criteria=[], scopes=[], done_when=[])),
            [dict(matching[0], parent_id=matching[0]["id"])],
        )


class StrictPlanTests(unittest.TestCase):
    requirements: ClassVar[list] = [dict(id="R-one", text="Fix it", kind="task")]
    plan = (
        "# Plan\nDecision: single\nSummary: Fix it\n## Requirements\nR1 → T1\n"
        "## T1: Fix\nDepends on: none\nFiles: project/a.py\nDone when: It works\nVerify: Check it\n"
    )

    def test_structural_text_and_unknown_sections_cannot_disappear(self):
        for changed in (
            self.plan.replace("Summary:", "Unexpected text\nSummary:"),
            self.plan + "## Hidden decisions\nDo something else\n",
            self.plan.replace("R1 → T1", "R1 → T1 or something else"),
            self.plan.replace("R1 → T1", "R1 → T1, typo"),
            self.plan.replace("R1 → T1", "R1 → T1, T1"),
            self.plan.replace("R1 → T1", "R1 → T1 [scope)"),
            self.plan.replace("R1 → T1", "R1 → T1 (scope]"),
        ):
            with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, "line"):
                payload(changed, self.requirements, dict(project="/repo"))

    def test_answer_keeps_all_markdown_subsections(self):
        answer = "## Details\nKeep this.\n\n## A second heading\nKeep this too."
        text = "Decision: no change\n## Requirements\nR1 → done: project/a.py:1\n## Answer\n"
        plan = payload(text + answer, self.requirements, dict(project="/repo"))
        self.assertEqual(plan["summary"], answer)

    def test_check_selections_resolve_only_complete_runtime_labels(self):
        requirements = [
            *self.requirements,
            dict(id="R-runtime", text="Check the service", kind="runtime"),
        ]
        text = self.plan.replace("R1 → T1", "R1 → T1\nR2 → runtime: service check")
        result = payload(
            text + "## Check selections\nservice-check: R2\n", requirements, dict(project="/repo")
        )
        self.assertEqual(
            result["check_selections"], [dict(recipe_id="service-check", criteria=["R-runtime"])]
        )
        for selection in (
            "service-check: R1",
            "service-check: R2, R2",
            "service-check: R2 ignored",
            "service-check: R3",
            "not a recipe: R2",
        ):
            with self.subTest(selection=selection), self.assertRaisesRegex(ValueError, "line"):
                payload(
                    text + "## Check selections\n" + selection, requirements, dict(project="/repo")
                )

    def test_only_the_exact_plan_read_before_write_error_is_recoverable(self):
        run = Path("/run/task")
        failure = dict(
            tool="write",
            input=dict(filePath=str(run / "plan.md")),
            error="Must read before writing",
        )
        outcome = dict(status="TOOL_ERROR", tool_errors=[failure], errors=[failure["error"]])
        self.assertIn("in THIS session", plan_write.read_before_write(outcome, run))
        failure["input"]["filePath"] = "/repo/source.py"
        self.assertIsNone(plan_write.read_before_write(outcome, run))


if __name__ == "__main__":
    unittest.main()
