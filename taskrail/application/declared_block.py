"""Turn a plan's explicit blockers into a safe stop, never a validated work proposal."""

from taskrail.core.files import atomic_json


def present(payload):
    """Only explicit structured blockers can trigger the conservative stop."""
    return (
        bool(payload["blocking_gaps"])
        or any(entry["outcome"] == "gap" for entry in payload["coverage"])
        or payload.get("input_complete") is False
    )


def stop_result(payload, context):
    """Preserve the draft; generate no source claims or authorization to proceed."""
    atomic_json(context["folder"] / "blocked-draft.json", payload)
    gaps = payload["blocking_gaps"] or ["Agent reported incomplete required evidence."]
    stopped = {key: [] for key in payload}
    stopped.update(
        schema_version=1,
        status="BLOCKED",
        summary="Agent reported blocking gaps. Draft claims and proposed changes were not validated. "
        + " ".join(gaps),
        blocking_gaps=gaps,
        unverified=[
            "Source claims, completion claims and proposed work in blocked-draft.json are unvalidated."
        ],
        coverage=[blocked_requirement(entry) for entry in context["requirements"]],
    )
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
