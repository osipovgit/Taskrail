"""Mandatory checks gate no-change engineering results without turning research into execution."""

import json
import sys
import unittest

from live_fixture import LiveFixture


class CheckSchedulingTests(LiveFixture, unittest.TestCase):
    def execute(self, read_only=False, design=False, code="raise SystemExit(7)"):
        header = dict(
            roots={"project": str(self.root)},
            auto_approve=True,
            read_only=read_only,
            design=design,
        )
        self.task.write_text(f"```taskrail-task\n{json.dumps(header)}\n```\nReturn 2")
        command = dict(cwd=str(self.root), argv=[sys.executable, "-c", code])
        return self.run_mode("no-change", verify_commands=[command], max_repairs=0)

    def test_no_change_engineering_result_cannot_skip_a_failed_mandatory_gate(self):
        _, status, state = self.execute()
        self.assertEqual(status, "CHECK_FAILED", state.get("summary"))
        self.assertEqual(state["checks"][0]["status"], "FAIL")
        self.assertNotIn("implementer", [entry["stage"] for entry in state["stages"]])
        self.assertNotIn("commits", state)

    def test_passed_no_change_checks_are_followed_by_independent_result_review(self):
        _, status, state = self.execute(code="print('verified')")
        self.assertEqual(status, "NO_CHANGES_REQUIRED", state.get("summary"))
        self.assertEqual(
            [entry["stage"] for entry in state["stages"]],
            ["planner", "plan-reviewer", "check", "reviewer"],
        )
        self.assertEqual(state["checks"][0]["status"], "PASS")

    def test_plain_answer_and_design_do_not_execute_unrequested_project_gates(self):
        for design in (False, True):
            with self.subTest(design=design):
                self.base = self.base / ("design" if design else "answer")
                self.base.mkdir()
                _, status, state = self.execute(read_only=True, design=design)
                self.assertEqual(status, "NO_CHANGES_REQUIRED", state.get("summary"))
                self.assertEqual(
                    [entry["stage"] for entry in state["stages"]], ["planner", "plan-reviewer"]
                )
                self.assertEqual(state["checks"], [])


if __name__ == "__main__":
    unittest.main()
