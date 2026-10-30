"""Run one opencode turn and summarize its JSON event stream."""

import time
from types import MappingProxyType

from taskrail.infrastructure import context_overflow, turn_io, usage_limits
from taskrail.infrastructure.event_summary import parse_events
from taskrail.infrastructure.opencode_serve import ATTACH
from taskrail.infrastructure.process_watch import SUCCESS, TurnWatch

AUTO_REJECT = "auto-rejecting"
PROMPT_ARGUMENT = "Execute_the_task_in_the_attached_file"
ATTACHED = "attached_files"
RUNTIME = "runtime"
DEBUG_LOGS = ("--print-logs", "--log-level", "DEBUG")
OPTIONAL = MappingProxyType(dict(debug=False, progress=False, runtime=None))


def run_agent(launch):
    """Launch, watch and classify one turn; the raw response is saved unchanged.

    launch: command, workspace, agent, model, prompt, attempt and timeout, plus the
    optional debug, progress and runtime.
    """
    options = dict(OPTIONAL, **launch)
    attempt = options["attempt"]
    attempt.mkdir(exist_ok=True)
    turn = turn_io.TurnIO(attempt, options[RUNTIME])
    watch = TurnWatch(turn, attempt, options["progress"])
    outcome = summarize(watch, start(watch, options), options)
    outcome.update(model=options["model"], agent=options["agent"])
    attempt.joinpath("response.raw.txt").write_text(outcome["final_text"], encoding="utf-8")
    return outcome


def start(watch, options):
    """Freeze the request and run opencode under the watch."""
    watch.turn.prepare(options["prompt"])
    argv, env = watch.turn.launch(options["command"], options["model"])
    runtime = options[RUNTIME] or {}
    files = (options["prompt"], *runtime.get(ATTACHED, ()))
    target = (options["workspace"], options["agent"], files)
    argv += arguments(target, options["debug"], env.get(ATTACH))
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
        plan_file=(options[RUNTIME] or {}).get("plan_file"),
        writable_files=(options[RUNTIME] or {}).get("writable_files", ()),
        notes=(options[RUNTIME] or {}).get(ATTACHED, ()),
    )
    usage_limits.explain(outcome, watch.telemetry, turn.budgets["context_budget"])
    stderr = turn.error_text()
    status = final_status(status, code, outcome, stderr)
    outcome.update(
        status=status,
        exit_code=code,
        elapsed_seconds=round(time.monotonic() - watch.clock["started"], 3),
        usage_complete=status == SUCCESS,
    )
    return outcome


def arguments(target, debug, server=None):
    """The opencode run arguments after the launch prefix; the prompt is the first file.

    A turn on the stage's 1.x server attaches to it. Every attached file is read by
    opencode itself when the turn starts, so a fresh session knows it as read too.
    """
    workspace, agent, files = target
    attached = [argument for path in files for argument in ("--file", str(path))]
    options = ["--dir", str(workspace), "--agent", agent, "--format", "json"]
    if server:
        options = ["--attach", server, *options]
    return [*(DEBUG_LOGS if debug else ()), *options, *attached, "--", PROMPT_ARGUMENT]


def final_status(status, code, outcome, stderr):
    """A clean exit still fails on denials, tool errors or a missing final answer."""
    if status != SUCCESS:
        return status
    errors = outcome["errors"]
    failures = (
        (outcome["permission"] or AUTO_REJECT in stderr, "BLOCKED_PERMISSION"),
        (outcome.get("provider_context_exceeded"), context_overflow.STATUS),
        (code != 0, "PROCESS_ERROR"),
        (bool(errors), "TOOL_ERROR"),
        (not outcome["completed"] or not outcome["final_text"].strip(), "INCOMPLETE"),
    )
    return next((name for failed, name in failures if failed), SUCCESS)
