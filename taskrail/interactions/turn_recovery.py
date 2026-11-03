"""Resume interrupted opencode turns without replaying tools or discarding context."""

import json
import time
from pathlib import Path

from taskrail.core import control, prompt_texts
from taskrail.core.files import digest, stream_digest
from taskrail.interactions import events

MAX_STALLS = 3
WAITS = (5, 15, 30)
POLL_SECONDS = 1
INTERRUPTED = frozenset(("TURN_ERROR", "PROCESS_ERROR", "INCOMPLETE"))


def response(session, outcome):
    """Native tools recover inside opencode; only a broken turn needs another message."""
    if not eligible(outcome, session.environment.get("config", {})):
        return None
    diagnostics = details(outcome)
    count = stalled_turns(session, diagnostics)
    if count > MAX_STALLS:
        outcome.update(
            status="NO_PROGRESS",
            errors=["Repeated interrupted turn without source or diagnostic progress"],
        )
        return None
    feedback = prompt_texts.text(
        "recovery.turn", diagnostics=json.dumps(diagnostics, ensure_ascii=False)
    )
    events.correction(session, "turn", outcome.get("final_text", ""), feedback)
    if not outcome.get("tool_errors"):
        delay = WAITS[min(count - 1, len(WAITS) - 1)]
        pause(session, delay)
    return feedback


def eligible(outcome, config):
    """A unique existing session can inspect its changes; authority and budgets persist."""
    stopped = outcome.get("provider_limit") and config.get("stop_on_provider_limit")
    sessions = outcome.get("sessions", [])
    return outcome["status"] in INTERRUPTED and not stopped and len(sessions) == 1


def details(outcome):
    """Bounded diagnostics; original tool events retain complete arguments and errors."""
    tools = outcome.get("tool_errors", [])[-5:]
    errors = outcome.get("errors", [])[-5:]
    return dict(
        status=outcome["status"],
        errors=[str(error)[:1000] for error in errors],
        tools=[
            dict(
                tool=call.get("tool"),
                input=json.dumps(call.get("input", {}), sort_keys=True)[:1000],
                error=str(call.get("error", ""))[:1000],
            )
            for call in tools
        ],
    )


def pause(session, seconds):
    """Back off a broken transport while preserving cooperative Stop and stage accounting."""
    deadline = time.monotonic() + min(seconds, session.clock.remaining())
    while time.monotonic() < deadline:
        control.check_stop(session.environment["run"])
        remaining = max(0, deadline - time.monotonic())
        time.sleep(min(POLL_SECONDS, remaining))


def progress(session):
    """Source and own-artifact progress distinguish recovery from an unchanged loop."""
    snapshot = dict(session.environment["expected"])
    for name in session.launch.get("runtime", {}).get("attached_files", ()):
        path = Path(name)
        if path.is_file():
            snapshot[str(path)] = stream_digest(path)
    return snapshot


def stalled_turns(session, diagnostics):
    """Count consecutive identical interrupted states, resetting after real progress."""
    current = json.dumps((diagnostics, progress(session)), sort_keys=True)
    signature = digest(current.encode())
    previous = session.context.get("turn_recovery", {})
    repeated = previous.get("signature") == signature
    count = previous.get("count", 0) + 1 if repeated else 1
    session.context["turn_recovery"] = dict(signature=signature, count=count)
    return count
