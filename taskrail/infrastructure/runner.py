"""Run one opencode turn and summarize its JSON event stream."""

import re
import time
from types import MappingProxyType

from taskrail.infrastructure import context_overflow, turn_io, usage_limits
from taskrail.infrastructure.event_summary import parse_events
from taskrail.infrastructure.process_watch import SUCCESS, TurnWatch

AUTO_REJECT = "auto-rejecting"
PROMPT_ARGUMENT = "Execute_the_task_in_the_attached_file"
OPTIONAL = MappingProxyType(dict(debug=False, progress=False, format_only=False, runtime=None))
UNAVAILABLE_TOOL = re.compile(
    r"Model tried to call unavailable tool '[^']+'. Available tools:\s*\.?"
)
UNAVAILABLE_RESOLUTION = "Rejected unavailable tool in a tool-free format pass; nothing executed. Final JSON still requires validation."


def run_agent(launch):
    """Launch, watch and classify one turn; the raw response is saved unchanged.

    launch: command, workspace, agent, model, prompt, attempt and timeout, plus the
    optional debug, progress, format_only and runtime.
    """
    options = dict(OPTIONAL, **launch)
    attempt = options["attempt"]
    attempt.mkdir(exist_ok=True)
    turn = turn_io.TurnIO(attempt, options["runtime"])
    watch = TurnWatch(turn, attempt, options["progress"])
    outcome = summarize(watch, start(watch, options), options)
    outcome.update(model=options["model"], agent=options["agent"])
    attempt.joinpath("response.raw.txt").write_text(outcome["final_text"], encoding="utf-8")
    return outcome


def start(watch, options):
    """Freeze the request and run opencode under the watch."""
    watch.turn.prepare(options["prompt"])
    argv, env = watch.turn.launch(options["command"], options["model"])
    target = (options["workspace"], options["agent"], options["prompt"])
    argv += arguments(target, options["debug"])
    return watch.launch(argv, env, options["workspace"], options["timeout"])


def summarize(watch, process, options):
    """Parse the turn's events and decide its status."""
    status, code = process
    watch.drain()
    turn = watch.turn
    if status == SUCCESS:
        status = usage_limits.exceeded(watch.telemetry, **turn.budgets)
    outcome = parse_events(
        turn.path,
        len(turn.previous.splitlines()),
        plan_file=(options["runtime"] or {}).get("plan_file"),
        writable_files=(options["runtime"] or {}).get("writable_files", ()),
    )
    usage_limits.explain(outcome, watch.telemetry, turn.budgets["context_budget"])
    stderr = turn.error_text()
    if options["format_only"] and status == SUCCESS and code == 0 and AUTO_REJECT not in stderr:
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
    errors = outcome["errors"]
    failures = (
        (outcome["permission"] or AUTO_REJECT in stderr, "BLOCKED_PERMISSION"),
        (context_overflow.exceeded(errors), context_overflow.STATUS),
        (code != 0, "PROCESS_ERROR"),
        (bool(errors), "TOOL_ERROR"),
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
