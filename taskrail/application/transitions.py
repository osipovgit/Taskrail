"""Stage decisions without model calls, filesystem writes or permission changes."""

from types import MappingProxyType

from taskrail.application import (
    check_outcomes,
    declared_block,
    input_revision,
    plan_feedback,
    repair_feedback,
    review_outcome,
)
from taskrail.core import plan_contract, prompt_texts

PLAN_REVIEW = "plan-reviewer"
STATUS = "status"
SUMMARY = "summary"
PLANNER = "planner"
ALLOWED = "allowed"
IMPLEMENTER = "implementer"
REVIEWER = "reviewer"
CHECKS = "checks"
BLOCKED = "BLOCKED"


def understood(flow, state, verdict, version):
    """Planning uses the accepted interpretation and rechecks any existing draft."""
    state["requirements"] = verdict["requirements"]
    feedback = (
        dict(summary=prompt_texts.text("understanding.replanned")) if flow["feedback"] else None
    )
    prior = plan_feedback.packet(flow["feedback"])
    if prior:
        feedback.update(prior)
    flow.update(
        stage=PLANNER,
        plan=None,
        feedback=feedback,
        effect="understood",
    )


def planning(flow, state, verdict, version):
    """Send every plan, including no-change plans, to independent review."""
    flow.update(plan=verdict, stage=PLAN_REVIEW)


def plan_review(flow, state, verdict, version):
    """Approve scope or return bounded feedback to planning."""
    state["plan_review"] = verdict
    if verdict[STATUS] in {"REQUEST_CHANGES", BLOCKED}:
        repair_feedback.route(flow, state, PLANNER, verdict, version)
        return
    flow[ALLOWED] = list(flow["plan"]["proposed_change_files"])
    state["review_outcome"] = review_outcome.describe(verdict, state.get("changed_files", []))
    if plan_contract.splits(flow["plan"], state.get("decompose")):
        state.update(status="TASKS_READY", summary=verdict[SUMMARY])
    elif flow[ALLOWED]:
        flow.update(stage=IMPLEMENTER, feedback=None, effect="capture_preimages")
    else:
        state.update(status=review_outcome.accepted_status(flow, state), summary=verdict[SUMMARY])


def implementation(flow, state, verdict, version):
    """Check actual edits before independent result review."""
    flow.update(stage="check", effect="write_diff")


def result_review(flow, state, verdict, version):
    """Stop on approval, or return the findings to the implementer while repairs remain.

    A run without approved files (an integration review or a delivery check) has no
    writer to repair anything, so its findings end the run for the operator.
    """
    state["review_outcome"] = review_outcome.describe(verdict, state.get("changed_files", []))
    if verdict[STATUS] == "APPROVE":
        state.update(status=review_outcome.accepted_status(flow, state), summary=verdict[SUMMARY])
        flow["effect"] = "commit" if flow[ALLOWED] else None
    elif flow[ALLOWED]:
        repair_feedback.route(flow, state, IMPLEMENTER, verdict, version)
    else:
        state.update(status="CHANGES_REQUESTED", summary=verdict[SUMMARY])


HANDLERS = MappingProxyType(
    {
        "understanding": understood,
        PLANNER: planning,
        PLAN_REVIEW: plan_review,
        IMPLEMENTER: implementation,
        REVIEWER: result_review,
    }
)
RESULT_KEYS = MappingProxyType(
    {
        "understanding": "understanding",
        PLANNER: "plan",
        PLAN_REVIEW: "plan-review",
        IMPLEMENTER: "implementation",
        REVIEWER: "review",
    }
)


def advance(flow, state, verdict, reference, version):
    """Choose a transition; the engine retains source integrity and write effects."""
    stage = flow["stage"]
    if verdict[STATUS] == input_revision.STATUS:
        input_revision.route(flow, state, verdict, version)
        return
    if stage in {PLAN_REVIEW, REVIEWER}:
        state.setdefault("review_limits", []).append(
            dict(
                stage=reference.split("/")[0],
                unverified=verdict["unverified"],
                blocking_gaps=verdict["blocking_gaps"],
            )
        )
    if verdict[STATUS] == BLOCKED and declared_block.stops(flow, state, verdict, reference):
        return
    state["results"][RESULT_KEYS[stage]] = reference
    HANDLERS[stage](flow, state, verdict, version)
    if stage == PLAN_REVIEW and verdict[STATUS] == BLOCKED:
        limits = state["review_limits"][-1]
        limits["returned_to_planning"] = flow["stage"] == PLANNER


def checked(flow, state, version):
    """Route failed built-in checks to bounded repair, never to approval."""
    checks = state[CHECKS]
    failed = any(map(check_outcomes.blocks, checks))
    if failed:
        if flow[ALLOWED]:
            repair_feedback.route(flow, state, IMPLEMENTER, {CHECKS: checks}, version)
        else:
            state.update(status="CHECK_FAILED", summary="Checks failed with no approved writer")
    else:
        flow["stage"] = REVIEWER
