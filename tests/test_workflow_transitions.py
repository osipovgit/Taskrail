"""Every stage edge retains independent approval, bounded repairs and writer scope."""

import unittest

from taskrail.application import transitions


def flow(stage, files=None, **overrides):
    files = ["project/app.py"] if files is None else files
    return dict(
        stage=stage,
        plan=dict(proposed_change_files=files, decision="single"),
        allowed=files,
        feedback=None,
        **overrides,
    )


def verdict(status):
    return dict(
        status=status, summary="Fixture decision", findings=[], unverified=[], blocking_gaps=[]
    )


class WorkflowTransitionTests(unittest.TestCase):
    def test_blocked_verdict_in_every_model_stage_never_opens_the_next_stage(self):
        for stage in transitions.HANDLERS:
            with self.subTest(stage=stage):
                execution = flow(stage)
                state = dict(status="RUNNING", results={})
                transitions.advance(execution, state, verdict("BLOCKED"), "02-stage/result.json", 2)
                self.assertEqual(state["status"], "BLOCKED")
                self.assertEqual(execution["stage"], stage)
                self.assertNotIn("effect", execution)
                self.assertEqual(state["results"], {})

    def test_viable_alternative_to_a_blocked_plan_returns_to_the_planner(self):
        execution = flow("planner", [])
        state = dict(status="RUNNING", results={})
        plan = dict(
            verdict("BLOCKED"),
            decision="blocked",
            blocking_gaps=["Need snapshot"],
            proposed_change_files=[],
        )
        transitions.advance(execution, state, plan, "01-plan/result.json", "a")
        self.assertEqual(execution["stage"], "plan-reviewer")
        review = dict(
            verdict("REQUEST_CHANGES"),
            findings=[dict(criterion="R1", file="plan.md", evidence="Read the frozen snapshot")],
        )
        transitions.advance(execution, state, review, "02-plan-review/result.json", "a")
        self.assertEqual(execution["stage"], "planner")
        self.assertEqual(execution["feedback"]["findings"], review["findings"])
        self.assertEqual((state["status"], execution["allowed"]), ("RUNNING", []))

    def test_result_review_returns_a_verifiable_gap_only_to_an_authorized_writer(self):
        for files in ([], ["project/Main.java"]):
            execution = flow("reviewer", files)
            state = dict(status="RUNNING", results={})
            review = dict(verdict("BLOCKED"), blocking_gaps=["Missing local test result"])
            transitions.advance(execution, state, review, "05-review/result.json", "source")
            self.assertEqual(execution["stage"], "implementer" if files else "reviewer")
            self.assertEqual(state["status"], "RUNNING" if files else "BLOCKED")

    def test_repeated_gaps_follow_the_whole_plan_and_open_set(self):
        execution = flow("plan-reviewer", [])
        state = dict(status="RUNNING", results={})
        for version, gaps in [
            ("a", list("abcde")),
            ("b", list("de")),
            ("c", list("de")),
            ("c", ["e"]),
        ]:
            execution["stage"] = "plan-reviewer"
            blocked = dict(verdict("BLOCKED"), blocking_gaps=gaps)
            transitions.advance(execution, state, blocked, "02-plan-review/result.json", version)
            self.assertEqual(execution["stage"], "planner")
            self.assertEqual(execution["feedback"]["blocking_gaps"], gaps)
            self.assertEqual(state["status"], "RUNNING")

    def test_plans_with_and_without_changes_always_get_independent_plan_review(self):
        for files in ([], ["project/app.py"]):
            with self.subTest(files=files):
                execution = flow("planner", files)
                state = dict(status="RUNNING", results={})
                plan = dict(execution["plan"], **verdict("PLAN_READY"))
                transitions.advance(execution, state, plan, "01-plan/result.json", 2)
                self.assertEqual(execution["stage"], "plan-reviewer")
                self.assertNotIn("effect", execution)
                self.assertEqual(state["status"], "RUNNING")

    def test_plan_approval_selects_single_split_or_no_change_without_premature_commit(self):
        cases = (
            (["project/app.py"], "single", "RUNNING", "implementer", "capture_preimages"),
            (["project/app.py"], "split", "TASKS_READY", "plan-reviewer", None),
            ([], "none", "NO_CHANGES_REQUIRED", "plan-reviewer", None),
        )
        for files, decision, status, stage, effect in cases:
            with self.subTest(decision=decision):
                execution = flow("plan-reviewer", files)
                execution["plan"]["decision"] = decision
                execution["allowed"] = []
                state = dict(status="RUNNING", results={})
                transitions.advance(
                    execution, state, verdict("APPROVE"), "02-plan-review/result.json", 2
                )
                self.assertEqual((state["status"], execution["stage"]), (status, stage))
                self.assertEqual(execution.get("effect"), effect)
                self.assertEqual(execution["allowed"], files)

    def test_all_remaining_findings_return_after_partial_repair(self):
        execution = flow("plan-reviewer")
        state = dict(status="RUNNING", results={})
        for version, findings in [
            ("one", list("abcde")),
            ("two", list("de")),
            ("three", list("de")),
        ]:
            execution["stage"] = "plan-reviewer"
            rejected = dict(verdict("REQUEST_CHANGES"), findings=findings)
            transitions.advance(execution, state, rejected, "02-plan-review/result.json", version)
            self.assertEqual(execution["feedback"], rejected)
            self.assertEqual(execution["stage"], "planner")

    def test_implementation_requires_checks_then_independent_review_before_commit(self):
        execution = flow("implementer")
        state = dict(status="RUNNING", results={}, checks=[dict(status="PASS")])
        transitions.advance(execution, state, verdict("IMPLEMENTED"), "03-implement/result.json", 2)
        self.assertEqual(execution["stage"], "check")
        self.assertEqual(execution.pop("effect"), "write_diff")
        transitions.checked(execution, state, 2)
        self.assertEqual(execution["stage"], "reviewer")
        self.assertEqual(state["status"], "RUNNING")
        self.assertNotIn("effect", execution)
        transitions.advance(execution, state, verdict("APPROVE"), "05-review/result.json", 2)
        self.assertEqual(state["status"], "READY_FOR_REVIEW")
        self.assertEqual(execution["effect"], "commit")

    def test_result_rejection_repairs_only_an_authorized_writer(self):
        for files, expected in ((["project/Main.java"], "implementer"), ([], "reviewer")):
            execution = flow("reviewer", files)
            state = dict(status="RUNNING", results={})
            transitions.advance(
                execution, state, verdict("REQUEST_CHANGES"), "05-review/result.json", "v1"
            )
            self.assertEqual(execution["stage"], expected)
            self.assertEqual(state["status"], "RUNNING" if files else "CHANGES_REQUESTED")
            self.assertNotIn("effect", execution)

    def test_read_only_integration_and_delivery_approval_never_commit(self):
        for phase in ("integration", "validation", "server"):
            with self.subTest(phase=phase):
                execution = flow("reviewer", [])
                state = dict(status="RUNNING", results={}, phase=phase)
                transitions.advance(
                    execution, state, verdict("APPROVE"), "05-review/result.json", 2
                )
                self.assertEqual(state["status"], "NO_CHANGES_REQUIRED")
                self.assertIsNone(execution["effect"])

    def test_failed_checks_never_reach_approval_or_repair_without_authorized_files(self):
        execution = flow("check", [])
        state = dict(status="RUNNING", checks=[dict(status="FAIL")])
        transitions.checked(execution, state, 2)
        self.assertEqual(state["status"], "CHECK_FAILED")
        self.assertEqual(execution["stage"], "check")
        self.assertNotIn("effect", execution)
