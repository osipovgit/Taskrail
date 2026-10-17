"""Run one opencode turn and summarize its JSON event stream."""

import re
import time

from countersign.infrastructure import turn_io, usage_limits
from countersign.infrastructure.event_summary import parse_events
from countersign.infrastructure.process_watch import SUCCESS, TurnWatch

AUTO_REJECT = "auto-rejecting"
PROMPT_ARGUMENT = "Execute_the_task_in_the_attached_file"
UNAVAILABLE_TOOL = re.compile(
    r"Model tried to call unavailable tool '[^']+'. Available tools:\s*\.?"
)
UNAVAILABLE_RESOLUTION = "Rejected unavailable tool in a tool-free format pass; nothing executed. Final JSON still requires validation."


def run_agent(
    command,
    workspace,
    agent,
    model,
    prompt,
    attempt,
    timeout,
    debug=False,
    progress=False,
    format_only=False,
    runtime=None,
):
    """Launch, watch and classify one turn; the raw response is saved unchanged."""
    attempt.mkdir(exist_ok=True)
    watch = TurnWatch(turn_io.TurnIO(attempt, runtime), attempt, progress)
    watch.turn.prepare(prompt)
    argv, env = watch.turn.launch(command, model)
    argv += arguments((workspace, agent, prompt), debug)
    process = watch.launch(argv, env, workspace, timeout)
    outcome = summarize(watch, process, format_only)
    outcome.update(model=model, agent=agent)
    (attempt / "response.raw.txt").write_text(outcome["final_text"], encoding="utf-8")
    return outcome


def summarize(watch, process, format_only):
    """Parse the turn's events and decide its status."""
    status, code = process
    watch.drain()
    turn = watch.turn
    if status == SUCCESS:
        status = usage_limits.exceeded(watch.telemetry, turn.token_budget)
    outcome = parse_events(turn.path, len(turn.previous.splitlines()))
    stderr = turn.error_text()
    if format_only and status == SUCCESS and code == 0 and AUTO_REJECT not in stderr:
        recover_unavailable_format_tools(outcome)
    status = final_status(status, code, outcome, stderr)
    outcome.update(
        status=status,
        exit_code=code,
        elapsed_seconds=round(time.monotonic() - watch.clock["started"], 3),
        usage_complete=status == SUCCESS,
    )
    return outcome


def arguments(target, debug):
    """The opencode run arguments after the launch prefix."""
    workspace, agent, prompt = target
    logs = ["--print-logs", "--log-level", "DEBUG"] if debug else []
    return [
        *logs,
        "--dir",
        str(workspace),
        "--agent",
        agent,
        "--format",
        "json",
        "--file",
        str(prompt),
        "--",
        PROMPT_ARGUMENT,
    ]


def final_status(status, code, outcome, stderr):
    """A clean exit still fails on denials, tool errors or a missing final answer."""
    if status != SUCCESS:
        return status
    failures = (
        (outcome["permission"] or AUTO_REJECT in stderr, "BLOCKED_PERMISSION"),
        (code != 0, "PROCESS_ERROR"),
        (bool(outcome["errors"]), "TOOL_ERROR"),
        (not outcome["completed"] or not outcome["final_text"].strip(), "INCOMPLETE"),
    )
    return next((name for failed, name in failures if failed), SUCCESS)


def recover_unavailable_format_tools(outcome):
    """Retain rejected calls as warnings only for a completed, tool-free format pass.

    The caller still validates the final JSON and source integrity. Any permission
    denial, available tool, successful call or other transport error stays fatal.
    """
    failures = outcome.get("tool_errors", [])
    if not only_unavailable_tools(outcome, failures):
        return
    for failure in failures:
        failure["resolution"] = UNAVAILABLE_RESOLUTION
        outcome["warnings"].append(dict(failure))
    outcome["errors"] = []


def only_unavailable_tools(outcome, failures):
    """Every call failed only because the format pass offers no tools."""
    answered = outcome.get("completed") and outcome.get("final_text", "").strip()
    if not answered or outcome.get("permission") or not failures:
        return False
    messages = [failure["error"] for failure in failures]
    if outcome.get("errors") != messages:
        return False
    if outcome.get("tool_calls") != len(failures):
        return False
    return all(UNAVAILABLE_TOOL.fullmatch(message) for message in messages)
