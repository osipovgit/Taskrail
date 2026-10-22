"""Execute selected local checks without model turns, preserving personal approval."""

from countersign.application import check_diagnostics, check_results
from countersign.application.check_selection import selected as selected
from countersign.interactions import approval_policy, local_actions


def execute(workflow, folder, check):
    """A check is bound to the unchanged source before its result is published."""
    request = request_for(check)
    context = execution_context(workflow, check)
    workflow.guard.verify("Source changed before verification")
    outcome = local_actions.previous(workflow.run, request, context)
    if outcome is None:
        decision = approval_policy.decision(
            workflow.run, request, workflow.state, workflow.config["roots"]
        )
        workflow.guard.verify("Source changed while waiting for verification approval")
        outcome = local_actions.execute(workflow.run, folder, request, context, decision)
    workflow.guard.verify(
        "Source/Git changed during checks; verification commands must not write inside declared roots"
    )
    context["assessment"] = check_diagnostics.assess(check["recipe"]["adapter"], outcome)
    recorded = check_results.record(
        workflow.run,
        check["spec"],
        request,
        outcome,
        context,
    )
    return outcome, recorded


def request_for(check):
    """Render the exact local command before the operator sees its approval."""
    command = check["recipe"]["request"]
    return dict(
        status="LOCAL_REQUEST",
        schema_version=1,
        cwd=command["cwd"],
        argv=command["argv"],
        reason="Configured verification check: {0}".format(check["spec"]["id"]),
    )


def execution_context(workflow, check):
    """Bind journal execution to current source and the recipe's finite deadline."""
    roots = workflow.config["roots"]
    return dict(
        roots=roots,
        run=workflow.run,
        timeout=check["recipe"]["request"]["timeout_seconds"],
        expected=workflow.guard.expected,
        source_snapshot=check_results.source_identity(roots),
    )
