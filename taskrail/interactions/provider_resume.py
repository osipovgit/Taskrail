"""Continue a turn the provider broke off in the same session instead of ending the stage.

A provider or gateway that gives up mid-turn leaves the opencode session with its
context and the files the model already changed, which the source guard has just
checked. After a pause the same session continues, a bounded number of times per
stage; no new session replays the work. A failed tool, a permission denial, an
answered turn or, under stop_on_provider_limit, an exhausted quota is not continued.
"""

import time

from taskrail.core import control, prompt_texts
from taskrail.interactions import events
from taskrail.observability.progress import say

# Pause before each continuation; its length bounds the continuations per stage.
WAITS = (60, 180, 300)
POLL_SECONDS = 1
ERROR_CHARACTERS = 500
RESUMES = "provider_resumes"
INTERRUPTED = frozenset(("TOOL_ERROR", "PROCESS_ERROR", "INCOMPLETE"))


def response(session, outcome):
    """The continuation after a pause, or None when the turn stays as it ended."""
    errors = interruptions(outcome, session.environment.get("config", {}))
    count = session.context.get(RESUMES, 0)
    if not errors or count >= len(WAITS):
        return None
    session.context[RESUMES] = count + 1
    wait = WAITS[count]
    note = prompt_texts.diagnostic("provider.resumed", error=errors[-1][:ERROR_CHARACTERS])
    arguments = dict(continuation=count + 1, wait_seconds=wait)
    events.append(session.active[0], "provider_resume", arguments, note)
    say(f"  Provider interrupted the turn; the same session continues in {wait} s")
    pause(session, wait)
    return note


def interruptions(outcome, config):
    """Errors that only the provider raised before the turn had an answer, else []."""
    errors = outcome.get("errors", [])
    failed_tools = {failure["error"] for failure in outcome.get("tool_errors", [])}
    stopped = outcome.get("provider_limit") and config.get("stop_on_provider_limit")
    eligible = outcome["status"] in INTERRUPTED and not stopped
    eligible = eligible and len(outcome.get("sessions", [])) == 1
    eligible = eligible and not outcome.get("permission")
    eligible = eligible and not outcome.get("final_text", "").strip()
    return errors if eligible and not failed_tools.intersection(errors) else []


def pause(session, seconds):
    """Wait without charging active stage time; cooperative Stop still works."""
    remaining = seconds
    while remaining > 0:
        control.check_stop(session.environment["run"])
        started = time.monotonic()
        time.sleep(min(POLL_SECONDS, remaining))
        waited = time.monotonic() - started
        session.clock.paused += waited
        remaining -= waited
