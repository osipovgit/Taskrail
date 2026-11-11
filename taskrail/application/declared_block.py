"""Turn a plan's explicit blockers into a safe stop, never a validated work proposal."""

from taskrail.core.files import atomic_json

GAPS = "blocking_gaps"


def present(payload):
    """Only explicit structured blockers can trigger the conservative stop."""
    if payload[GAPS]:
        return True
    return any(entry["outcome"] == "gap" for entry in payload["coverage"])


def stop_result(payload, context):
    """Preserve the draft; generate no source claims or authorization to proceed."""
    atomic_json(context["folder"] / "blocked-draft.json", payload)
    gaps = payload[GAPS] or ["Agent reported incomplete required evidence."]
    stopped = {key: [] for key in payload}
    stopped.update(
        schema_version=1,
        status="BLOCKED",
        decision="blocked",
        summary="Agent reported blocking gaps. Draft claims and proposed changes were not validated. "
        + " ".join(gaps),
        blocking_gaps=gaps,
        unverified=[
            "Source claims, completion claims and proposed work in blocked-draft.json are unvalidated."
        ],
        coverage=[blocked_requirement(entry) for entry in context["requirements"]],
    )
    responses = payload.get("finding_responses")
    if responses:
        stopped["finding_responses"] = responses
    return stopped


def blocked_requirement(requirement):
    """Account for each requirement without claiming it was checked or satisfied."""
    outcome = "not_evaluated"
    return dict(
        id=requirement["id"],
        outcome=outcome,
        evidence_ids=[],
        explanation="Not evaluated: the stage stopped on a shared blocker before validating this requirement.",
    )


def confirmed(flow, state, verdict, reference):
    """Keep a confirmed blocker and resume the planner when the requested input arrives."""
    if flow["plan"].get("decision") != "blocked" or verdict["findings"]:
        return False
    state["results"]["plan-review"] = reference
    summary = " ".join(verdict[GAPS])
    state.update(status="BLOCKED", plan_review=verdict, summary=summary)
    flow.update(stage="planner", feedback=verdict, effect="blocked_checkpoint")
    return True


def stops(flow, state, verdict, reference):
    """Route actionable gaps through normal stage handlers; keep terminal gaps read-only."""
    stage = flow["stage"]
    if verdict[GAPS]:
        if stage == "plan-reviewer":
            return confirmed(flow, state, verdict, reference)
        if stage == "planner" or (stage == "reviewer" and flow["allowed"]):
            return False
    state.update(status="BLOCKED", summary=verdict["summary"])
    return True
