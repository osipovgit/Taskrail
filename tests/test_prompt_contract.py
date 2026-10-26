"""What a model reads: field-placed labels, stage-specific instructions within a budget."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from live_fixture import LiveFixture

from taskrail.application import instruction_sources, prompts
from taskrail.core import prompt_texts, task_spec
from taskrail.web.task_form import build_task

# Bytes of the instructions of one stage, paths shortened; the task and Context excluded.
BUDGETS = {"01-plan": 10500, "02-plan-review": 10500, "03-implement": 9000, "05-review": 9000}
STABLE_ID = re.compile(r"R-[0-9a-f]{12}")


class LabelTests(unittest.TestCase):
    def test_a_label_stays_with_its_field_when_the_title_repeats_the_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            goal = "Fix the lint findings in roles/ntp.\n\nKeep variable names stable."
            payload = dict(goal=goal, criteria="ansible-lint roles/ntp passes")
            payload.update(constraints="Do not disable rules.")
            payload["roots"] = [dict(alias="project", path=str(root))]
            text, _ = build_task(payload, Path(directory) / "runs")
        meta = json.loads(text.split("```taskrail-task\n", 1)[1].split("\n```", 1)[0])
        spec = task_spec.resolve(text, dict(meta, verification=["The play runs twice"]))
        shown = task_spec.prompt_text(spec, spec["requirements"])
        self.assertNotIn("## Title", shown)
        self.assertTrue(shown.startswith("## Goal\n[R1]\nFix the lint findings"))
        self.assertIn("\n\n[R2]\nKeep variable names stable.", shown)
        self.assertIn("## Acceptance criteria\n[R3]\nansible-lint", shown)
        self.assertIn("## Constraints\n[R4 constraint]\nDo not disable rules.", shown)
        self.assertIn("## Runtime checks\n[R5 runtime]\nThe play runs twice", shown)


class FrozenTextTests(unittest.TestCase):
    def test_a_continued_run_keeps_the_texts_it_started_with(self):
        self.addCleanup(prompt_texts.ACTIVE.adopt, prompt_texts.release())
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "00-input").mkdir()
            instruction_sources.freeze_contract(run, prompts.POLICY, {})
            contract = run / "00-input/contract.json"
            saved = json.loads(contract.read_text())
            saved["texts"]["stage.planner"] = "Stage: planning (frozen)."
            contract.write_text(json.dumps(saved))
            instruction_sources.freeze_contract(run, prompts.POLICY, {})
            self.assertEqual(prompt_texts.text("stage.planner"), "Stage: planning (frozen).")
            del saved["texts"]
            contract.write_text(json.dumps(saved))
            with self.assertRaisesRegex(ValueError, "differs from this release"):
                instruction_sources.freeze_contract(run, prompts.POLICY, {})


class RequestBudgetTests(LiveFixture, unittest.TestCase):
    def test_each_stage_reads_only_its_own_instructions_within_budget(self):
        run, status, state = self.run_mode()
        self.assertEqual(status, "READY_FOR_REVIEW", state.get("summary"))
        requests = {}
        for stage, budget in BUDGETS.items():
            request = (run / stage / "request.md").read_text()
            short = request.replace(str(self.base), "/B")
            instructions = short.split("# Orchestrator instructions\n", 1)[1]
            instructions = instructions.split("\nContext:\n", 1)[0]
            self.assertLess(len(instructions.encode()), budget, stage)
            self.assertIsNone(STABLE_ID.search(request), stage)
            self.assertNotIn("{'", request)
            requests[stage] = request
        self.assertIn("Your only writable file is the plan file", requests["01-plan"])
        self.assertNotIn("Your only writable file", requests["03-implement"])
        self.assertIn("Edit only the allowed files", requests["03-implement"])
        self.assertNotIn("Edit only the allowed files", requests["05-review"])
        self.assertIn("A push waits for the operator's approval", requests["03-implement"])
        self.assertNotIn("push", requests["05-review"].split("Local commands:")[0])
        self.assertNotIn('"findings"', requests["03-implement"])
        self.assertEqual(requests["01-plan"].count("as your entire message"), 3)


if __name__ == "__main__":
    unittest.main()
