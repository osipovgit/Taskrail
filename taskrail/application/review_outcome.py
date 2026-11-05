"""Keep semantic acceptance independent of diagnostic side effects."""


def accepted_status(flow, state):
    """A read-only integration review never becomes a code-delivery phase."""
    changed = flow["allowed"] or state.get("execution_jobs")
    if state.get("phase") == "integration" or not changed:
        return "NO_CHANGES_REQUIRED"
    return "READY_FOR_REVIEW"


def describe(verdict, changed):
    """Store source effects and unresolved acceptance separately from execution history."""
    return dict(
        decision=verdict["status"],
        source_effect="changed" if changed else "unchanged",
        unverified=verdict.get("unverified", []),
        blocking_gaps=verdict.get("blocking_gaps", []),
    )


def unresolved_limits(state):
    """An approved revision supersedes the gap that prompted its replan."""
    limits = state.get("review_limits", [])
    if state.get("plan_review", {}).get("status") == "APPROVE":
        return [entry for entry in limits if not entry.get("returned_to_planning")]
    return limits
