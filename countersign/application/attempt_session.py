"""Launch inputs of one attempt and validation of its final response."""

from countersign.application import result_context, session_budget
from countersign.application.attempt_launch import agent_name
from countersign.application.git_state import git_metadata
from countersign.application.plan_validation import canonical_plan, validate_plan
from countersign.observability.progress import clock, say
from countersign.observability.telemetry import inspect_events

ROOTS = "roots"
INVALID = "INVALID_RESULT"


def announce(record):
    """One progress line per attempt."""
    now = clock()
    model = record.get("model", "CLI default")
    say("[{0}] [{1:02d}] {2} model={3}".format(now, record["number"], record["directory"], model))


def token_allowance(workflow):
    """Remaining observed tokens, or None without a configured budget."""
    budget = workflow.config["max_observed_tokens"]
    if not budget:
        return None
    logs = [
        workflow.run / stage["directory"] / "events.jsonl" for stage in workflow.state["stages"]
    ]
    observed = sum(inspect_events(log)["tokens"]["total"] for log in logs)
    return budget - observed


def session_environment(workflow, profile, files, format_only, check_result):
    """What the stage session needs to keep scope and integrity guards between turns."""
    guard = workflow.guard
    return dict(
        format_only=format_only,
        check_result=check_result,
        run=workflow.run,
        config=workflow.config,
        roots=workflow.config[ROOTS],
        profile=profile,
        allowed=workflow.flow["allowed"],
        allowed_paths=files,
        expected=guard.expected,
        git_before=guard.git_before,
        scan=guard.scan,
        git_metadata=git_metadata,
    )


def launch_options(workflow, active, allowance, format_only):
    """The opencode invocation of one attempt."""
    folder, record = active
    config = workflow.config
    return dict(
        command=config["command"],
        workspace=next(iter(config[ROOTS].values())),
        agent=agent_name(workflow, record),
        model=config["models"].get(record["role"]),
        prompt=folder / "request.md",
        attempt=folder,
        debug=workflow.runtime["debug"],
        progress=True,
        format_only=format_only,
        runtime=dict(
            token_budget=allowance,
            context_budget=session_budget.capacity(config),
            env_allow=config["agent_env_allow"],
            autocompact=False,
        ),
    )


def validated(workflow, record, outcome):
    """Parse the final response; a plan must also pass path and scope checks."""
    roots = workflow.config[ROOTS]
    environment = dict(
        roots=roots, run=workflow.run, plan=workflow.flow["plan"], check_config=workflow.config
    )
    verdict = result_context.parse(outcome, record, workflow.state, environment)
    if record["stage"] == "planner":
        verdict = canonical_plan(verdict, roots)
        validate_plan(verdict, roots, workflow.config["task"], workflow.config)
    return verdict


def invalid(workflow, outcome, error):
    """Record a contract violation on the attempt and its stage record."""
    reason = str(error)
    outcome.update(status=INVALID, contract_error=reason)
    workflow.state["attempts"][-1].update(status=INVALID, contract_error=reason)
    say(f"  {INVALID}: {reason}")
    workflow.finish_active(INVALID, diagnostics=outcome)
