"""Launch inputs of one attempt and validation of its final response."""

from functools import partial

from taskrail.application import context_windows, result_context, stage_artifacts
from taskrail.application.attempt_launch import agent_name
from taskrail.application.git_state import git_metadata
from taskrail.application.plan_validation import canonical_plan, validate_plan
from taskrail.application.task_branch import KEY as TASK_BRANCH
from taskrail.application.task_branch import extend as extend_beyond_plan
from taskrail.observability.progress import clock, say
from taskrail.observability.telemetry import inspect_events

ROOTS = "roots"
INVALID = "INVALID_RESULT"


def announce(record):
    """One progress line per attempt."""
    now = clock()
    model = record.get("model", "CLI default")
    say("[{}] [{:02d}] {} model={}".format(now, record["number"], record["directory"], model))


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


def session_environment(workflow, profile, files, check_result):
    """What the stage session needs to keep scope and integrity guards between turns.

    On a task branch the writer's changes beyond the plan are adopted before each check.
    """
    guard = workflow.guard
    on_branch = workflow.config.get(TASK_BRANCH) is True
    adopts = on_branch and bool(workflow.writable())
    return dict(
        check_result=check_result,
        run=workflow.run,
        config=workflow.config,
        roots=workflow.config[ROOTS],
        profile=profile,
        allowed=workflow.flow["allowed"],
        allowed_paths=files,
        expected=guard.expected,
        original_sources=guard.before,
        git_before=guard.git_before,
        scan=guard.scan,
        git_metadata=git_metadata,
        beyond_plan=partial(extend_beyond_plan, workflow) if adopts else None,
    )


def launch_options(workflow, active, allowance):
    """The opencode invocation of one attempt."""
    folder, record = active
    config = workflow.config
    return dict(
        command=config["command"],
        server=config.get("opencode_server", True),
        workspace=next(iter(config[ROOTS].values())),
        agent=agent_name(workflow, record),
        model=config["models"].get(record["role"]),
        prompt=folder / "request.md",
        attempt=folder,
        debug=workflow.runtime["debug"],
        progress=True,
        runtime=dict(
            token_budget=allowance,
            context_budget=context_windows.role_capacity(config, record["role"]),
            env_allow=config["agent_env_allow"],
            autocompact=False,
            writable_files=record.get("writable_files", ())
            if record["stage"] == "implementer"
            else (),
            plan_file=str(workflow.run / "plan.md") if record["stage"] == "planner" else None,
            attached_files=record.get(stage_artifacts.ATTACHED, ()),
            input_overhead=sum(
                record.get("context_budget", {}).get(key, 0)
                for key in ("role_bytes", "framing_tokens")
            ),
        ),
    )


def validated(workflow, record, outcome, deliver_lines=False):
    """Parse the final response; a plan must also pass path and scope checks.

    deliver_lines: only while a correction turn of the same session follows.
    """
    roots = workflow.config[ROOTS]
    environment = dict(
        roots=roots, run=workflow.run, plan=workflow.flow["plan"], check_config=workflow.config
    )
    environment["deliver_lines"] = deliver_lines
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
