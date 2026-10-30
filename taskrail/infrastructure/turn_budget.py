"""Count every transmitted prompt and attachment before initial and continued turns."""

import json
from pathlib import Path

from taskrail.core.files import atomic_json
from taskrail.infrastructure.context_overflow import STATUS

LEDGER = "turn-inputs.json"
TOTAL = "input_bytes"


def admission(options, telemetry):
    """Bound observed input even when a wrapper provides no token usage."""
    runtime = options.get("runtime") or {}
    if runtime.get("context_budget") is None:
        return None
    location = options["attempt"] / LEDGER
    previous = history(location, runtime.get("session_id"))
    measured = measure(options, previous, telemetry)
    if measured[TOTAL] + measured["previous_tokens"] >= measured["capacity"]:
        return blocked(measured, runtime.get("session_id"))
    atomic_json(location, [*previous, measured])
    return None


def measure(options, previous, telemetry):
    """Count actual current file sizes, never stale sizes from the initial request."""
    runtime = options.get("runtime") or {}
    files = (options["prompt"], *runtime.get("attached_files", ()))
    incoming = sum(Path(path).stat().st_size for path in files)
    incoming += runtime.get("input_overhead", 0)
    consumed = occupied(previous, telemetry) if runtime.get("session_id") else 0
    return dict(input_bytes=incoming, previous_tokens=consumed, capacity=runtime["context_budget"])


def history(location, session):
    """A fresh session never inherits the previous session's admitted turns."""
    return json.loads(location.read_text()) if session and location.exists() else []


def occupied(previous, telemetry):
    """Use the greater of reported context and a byte estimate of admitted conversation."""
    summary = telemetry.summary()
    sent = sum(entry[TOTAL] for entry in previous)
    observed = summary.get("observed_bytes", 0)
    return max(summary.get("last_input") or 0, sent + observed)


def blocked(measured, session):
    """A large continuation may roll over; input too large on its own must stop."""
    total = measured[TOTAL] + measured["previous_tokens"]
    reason = (
        f"Turn admission exceeds the reserved context boundary: {total} estimated tokens, "
        f"{measured['capacity']} available; prompt and attachments use {measured[TOTAL]} bytes."
    )
    return dict(
        status=STATUS,
        errors=[reason],
        final_text="",
        completed=False,
        sessions=[session] if session else [],
        tokens={},
        elapsed_seconds=0,
        usage_complete=False,
        admission_blocked=measured[TOTAL] >= measured["capacity"] or not session,
        turn_admission=measured,
    )
