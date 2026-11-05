"""Every stage edge retains independent approval, bounded repairs and writer scope."""

import unittest

from taskrail.application import transitions


def flow(stage, files=None, **overrides):
    files = ["project/app.py"] if files is None else files
    return dict(
        stage=stage,
        plan=dict(proposed_change_files=files, decision="single"),
        allowed=files,
        plan_repairs=0,
        repair_count=0,
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

    def test_a_disputed_plan_review_gap_returns_to_planning_once_within_budget(self):
        blocked = dict(verdict("BLOCKED"), blocking_gaps=["Original changes need inspection"])
        execution = flow("plan-reviewer", [])
        state = dict(status="RUNNING", results={})
        transitions.advance(execution, state, blocked, "02-plan-review/result.json", 3)
        self.assertEqual((execution["stage"], execution["plan_repairs"]), ("planner", 1))
        self.assertEqual(execution["feedback"], blocked)
        self.assertFalse(execution["allowed"])
        plan = dict(execution["plan"], **verdict("PLAN_READY"))
        transitions.advance(execution, state, plan, "03-plan/result.json", 3)
        self.assertEqual(execution["stage"], "plan-reviewer")
        transitions.advance(execution, state, blocked, "04-plan-review/result.json", 3)
        self.assertEqual(state["status"], "BLOCKED")
        self.assertNotIn("effect", execution)
        exhausted = dict(status="RUNNING", results={})
        transitions.advance(
            flow("plan-reviewer", []), exhausted, blocked, "02-plan-review/result.json", 0
        )
        self.assertEqual(exhausted["status"], "BLOCKED")

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

    def test_plan_rejection_returns_to_planning_until_its_separate_repair_limit(self):
        for used, status, next_stage in (
            (0, "RUNNING", "planner"),
            (2, "PLAN_REJECTED", "plan-reviewer"),
        ):
            with self.subTest(used=used):
                execution = flow("plan-reviewer", [])
                execution["plan_repairs"] = used
                state = dict(status="RUNNING", results={})
                rejected = verdict("REQUEST_CHANGES")
                transitions.advance(execution, state, rejected, "02-plan-review/result.json", 2)
                self.assertEqual((state["status"], execution["stage"]), (status, next_stage))
                self.assertEqual(execution["repair_count"], 0)
                self.assertNotIn("effect", execution)
                if used == 0:
                    self.assertEqual(execution["feedback"], rejected)

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

    def test_result_rejection_repairs_only_an_authorized_writer_with_budget(self):
        for files, used, status, stage in (
            (["project/app.py"], 0, "RUNNING", "implementer"),
            (["project/app.py"], 2, "CHANGES_REQUESTED", "reviewer"),
            ([], 0, "CHANGES_REQUESTED", "reviewer"),
        ):
            with self.subTest(files=files, used=used):
                execution = flow("reviewer", files)
                execution["repair_count"] = used
                state = dict(status="RUNNING", results={})
                transitions.advance(
                    execution, state, verdict("REQUEST_CHANGES"), "05-review/result.json", 2
                )
                self.assertEqual((state["status"], execution["stage"]), (status, stage))
                self.assertNotIn("effect", execution)
                self.assertEqual(execution["plan_repairs"], 0)

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
        for files, used in (([], 0), (["project/app.py"], 2)):
            with self.subTest(files=files, used=used):
                execution = flow("check", files)
                execution["repair_count"] = used
                state = dict(status="RUNNING", checks=[dict(status="FAIL")])
                transitions.checked(execution, state, 2)
                self.assertEqual(state["status"], "CHECK_FAILED")
                self.assertEqual(execution["stage"], "check")
                self.assertNotIn("effect", execution)
