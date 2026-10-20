"""Stage decisions without model calls, filesystem writes or permission changes."""

from types import MappingProxyType

PLAN_REVIEW = "plan-reviewer"
STATUS = "status"
SUMMARY = "summary"
PLANNER = "planner"
ALLOWED = "allowed"
IMPLEMENTER = "implementer"
REPAIRS = "repair_count"
REVIEWER = "reviewer"


def planning(flow, state, verdict, limit):
    """Send every plan, including no-change plans, to independent review."""
    flow.update(plan=verdict, stage=PLAN_REVIEW)


def plan_review(flow, state, verdict, limit):
    """Approve scope or return bounded feedback to planning."""
    state["plan_review"] = verdict
    if verdict[STATUS] == "REQUEST_CHANGES":
        if flow["plan_repairs"] >= limit:
            state.update(status="PLAN_REJECTED", summary=verdict[SUMMARY])
        else:
            flow.update(feedback=verdict, stage=PLANNER)
            flow["plan_repairs"] += 1
        return
    flow[ALLOWED] = flow["plan"]["proposed_change_files"]
    state["no_changes_needed"] = not bool(flow[ALLOWED])
    if flow[ALLOWED] and state.get("decompose"):
        state.update(status="TASKS_READY", summary=verdict[SUMMARY])
    elif flow[ALLOWED]:
        flow.update(stage=IMPLEMENTER, feedback=None, effect="capture_preimages")
    else:
        terminal = "READY_FOR_REVIEW" if state.get("execution_jobs") else "NO_CHANGES_REQUIRED"
        state.update(status=terminal, summary=verdict[SUMMARY])


def implementation(flow, state, verdict, limit):
    """Check actual edits before independent result review."""
    flow.update(stage="check", effect="write_diff")


def result_review(flow, state, verdict, limit):
    """Stop on approval or request only the missing approved work."""
    if verdict[STATUS] == "APPROVE":
        state.update(status="READY_FOR_REVIEW", summary=verdict[SUMMARY])
    elif flow[REPAIRS] >= limit:
        state.update(status="CHANGES_REQUESTED", summary=verdict[SUMMARY])
    else:
        flow.update(feedback=verdict, stage=IMPLEMENTER if flow[ALLOWED] else PLANNER)
        flow[REPAIRS] += 1


HANDLERS = MappingProxyType(
    {
        PLANNER: planning,
        PLAN_REVIEW: plan_review,
        IMPLEMENTER: implementation,
        REVIEWER: result_review,
    }
)
RESULT_KEYS = MappingProxyType(
    {
        PLANNER: "plan",
        PLAN_REVIEW: "plan-review",
        IMPLEMENTER: "implementation",
        REVIEWER: "review",
    }
)


def advance(flow, state, verdict, reference, limit):
    """Choose a transition; the engine retains source integrity and write effects."""
    stage = flow["stage"]
    if stage in {PLAN_REVIEW, REVIEWER}:
        state.setdefault("review_limits", []).append(
            dict(
                stage=reference.split("/")[0],
                unverified=verdict["unverified"],
                blocking_gaps=verdict["blocking_gaps"],
            )
        )
    if verdict[STATUS] == "BLOCKED":
        state.update(status="BLOCKED", summary=verdict[SUMMARY])
        return
    state["results"][RESULT_KEYS[stage]] = reference
    HANDLERS[stage](flow, state, verdict, limit)


def checked(flow, state, limit):
    """Route failed built-in checks to bounded repair, never to approval."""
    failed = any(check[STATUS] == "FAIL" for check in state["checks"])
    if failed:
        if flow[REPAIRS] >= limit:
            state.update(status="CHECK_FAILED", summary="Checks failed after the last repair")
        else:
            flow.update(stage=IMPLEMENTER, feedback={"checks": state["checks"]})
            flow[REPAIRS] += 1
    else:
        flow["stage"] = REVIEWER
