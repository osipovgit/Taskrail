"""Execute selected local checks without model turns, sandboxed or personally approved."""

from taskrail.application import check_diagnostics, check_expectations, check_results
from taskrail.core import protected_paths
from taskrail.executor import protocol
from taskrail.interactions import approval_policy, local_actions, local_sandbox

RECIPE = "recipe"


def execute(workflow, folder, check, completed):
    """A check is bound to the unchanged source before its result is published."""
    request = request_for(check)
    context = execution_context(workflow, check)
    workflow.guard.verify("Source changed before verification")
    key = (protocol.fingerprint(check[RECIPE]["request"]), context["source_snapshot"])
    if key not in completed:
        completed[key] = run_once(workflow, folder, request, context)
    outcome = completed[key]
    workflow.guard.verify(
        "Source/Git changed during checks; verification commands must not write inside declared roots"
    )
    context["assessment"] = assessment(check[RECIPE], outcome)
    recorded = check_results.record(
        workflow.run,
        check["spec"],
        request,
        outcome,
        context,
    )
    return outcome, recorded


def run_once(workflow, folder, request, context):
    """Observe one process for all matching assertions in this check stage."""
    outcome = local_actions.previous(workflow.run, request, context)
    if outcome is None:
        decision = approve(workflow, request, context)
        workflow.guard.verify("Source changed while waiting for verification approval")
        outcome = local_actions.execute(workflow.run, folder, request, context, decision)
    return outcome


def assessment(recipe, outcome):
    """Assess a reviewed executable check or an operator-configured adapter."""
    expect = recipe.get("expect")
    if expect is not None:
        return check_expectations.assess(expect, outcome)
    return check_diagnostics.assess(recipe["adapter"], outcome)


def approve(workflow, request, context):
    """A check runs in the sandbox without a decision, else it is approved.

    It may write build output inside the roots; the guard still stops changed source.
    """
    if local_sandbox.sandboxed(request):
        context[local_sandbox.WRITES] = True
        return approval_policy.automatic(workflow.run, request, approval_policy.SANDBOX)
    return approval_policy.decision(
        workflow.run, request, workflow.state, read_scope(workflow.config)
    )


def read_scope(config):
    """The roots and protected patterns of the automatic read-only route."""
    return config["roots"], protected_paths.patterns(config)


def request_for(check):
    """Render the exact local command before the operator sees its approval."""
    command = check[RECIPE]["request"]
    return dict(
        status="LOCAL_REQUEST",
        schema_version=1,
        cwd=command["cwd"],
        argv=command["argv"],
        reason="Configured verification check: {}".format(check["spec"]["id"]),
    )


def execution_context(workflow, check):
    """Bind journal execution to current source and the recipe's finite deadline."""
    roots = workflow.config["roots"]
    return dict(
        roots=roots,
        config=workflow.config,
        run=workflow.run,
        timeout=check[RECIPE]["request"]["timeout_seconds"],
        expected=workflow.guard.expected,
        source_snapshot=check_results.source_identity(roots),
    )
