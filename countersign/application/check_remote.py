"""Fixed remote checks use the existing isolated executor and exact root approval."""

from countersign.application import (
    check_diagnostics,
    check_results,
    execution_requests,
    execution_wait,
)
from countersign.core.schema import require
from countersign.executor import protocol

STATUS = "status"


def execute(workflow, folder, spec, recipe):
    """Observe the same durable ticket on resume; never submit a replacement for UNKNOWN."""
    workflow.guard.verify("Source changed before remote verification")
    authorize(workflow, recipe)
    context = binding(workflow, spec, recipe)
    ticket = followed(workflow, folder, recipe["request"], recipe["kind"], context)
    workflow.guard.verify("Source changed during remote verification")
    context["assessment"] = assess(recipe["adapter"], ticket)
    return check_results.record(workflow.run, spec, recipe["request"], outcome(ticket), context)


def authorize(workflow, recipe):
    """The server verifies confirmation independently of the selected recipe."""
    if recipe["kind"] == "ssh":
        mode = execution_requests.remote_mode(workflow.run, workflow.config, "reviewer")
        require(mode == execution_requests.SERVER, "Server checks require confirmed changes")


def binding(workflow, spec, recipe):
    """A ticket belongs to a criterion check on this source snapshot."""
    return dict(
        check_id=spec["id"],
        request_sha256=protocol.fingerprint(recipe["request"]),
        source_snapshot=check_results.source_identity(workflow.config["roots"]),
    )


def outcome(ticket):
    """The check links to the full executor evidence without copying its logs."""
    targets = [
        {key: entry[key] for key in ("target", STATUS, "exit_code") if key in entry}
        for entry in ticket.get("results", [])
    ]
    return dict(status=ticket[STATUS], ticket_id=ticket.get("id"), targets=targets)


def followed(workflow, folder, request, kind, binding):
    """A prior check ticket retains authority only for its exact source and request."""
    entries = execution_wait.read(workflow.run)
    prior = [
        entry
        for entry in entries
        if (entry.get("binding") or {}).get("check_id") == binding["check_id"]
    ]
    if prior:
        pending = prior[-1]
        require(
            pending["binding"] == binding,
            "Remote check inputs changed; inspect the existing ticket",
        )
        if pending[STATUS] in execution_wait.TERMINAL:
            return pending
        require(pending == entries[-1], "Another executor ticket follows an unfinished check")
    else:
        execution_wait.submit(
            workflow.run, folder, request, "jenkins" if kind == "jenkins" else "action", binding
        )
    try:
        execution_wait.resume(workflow.run, workflow.state)
    except ValueError:
        pending = execution_wait.read(workflow.run)[-1]
        if pending[STATUS] != "UNKNOWN":
            raise
    return execution_wait.read(workflow.run)[-1]


def assess(adapter, ticket):
    """All targets must pass; missing targets and unknown effects remain unknown."""
    outcomes = ticket.get("results", [])
    if ticket[STATUS] not in {"SUCCEEDED", "FAILED"} or not outcomes:
        return check_diagnostics.unknown(adapter, "Remote check did not complete")
    assessed = [check_diagnostics.assess(adapter, entry) for entry in outcomes]
    statuses = {entry[STATUS] for entry in assessed}
    status = "unknown" if "unknown" in statuses or ticket[STATUS] != "SUCCEEDED" else "passed"
    if "failed" in statuses:
        status = "failed"
    return dict(status=status, adapter=adapter, targets=assessed)
