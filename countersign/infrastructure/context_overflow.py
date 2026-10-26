"""Recognize a provider refusing a turn because the session outgrew the model context.

opencode compacts a session only when the model's context limit is configured; with
an unknown limit the session grows until the provider rejects the next call.
"""

import json
import re
from pathlib import Path

STATUS = "CONTEXT_EXCEEDED"
CALL_CHARS = 300
STATE = "state"
MARKERS = re.compile(
    r"context[ _]?window[ _]?exceeded|context_length_exceeded|maximum context length"
    + r"|prompt is too long|context ?overflow|input is too long",
    re.IGNORECASE,
)


def exceeded(errors):
    """True when any recorded error reports an exceeded context window."""
    return any(MARKERS.search(str(error)) for error in errors)


def tool_outputs(events):
    """(characters, call) for every tool output a session received; [] without events."""
    try:
        with Path(events).open(encoding="utf-8", errors="replace") as stream:
            return [entry for line in stream for entry in output_entry(line)]
    except OSError:
        return []


def output_entry(line):
    """[(characters, call)] for an event that returned tool output to the model, else []."""
    try:
        part = json.loads(line).get("part")
    except (ValueError, AttributeError):
        return []
    state = part.get(STATE) if isinstance(part, dict) else None
    output = state.get("output") if isinstance(state, dict) else None
    if not isinstance(output, str):
        return []
    arguments = json.dumps(state.get("input"), ensure_ascii=False)
    call = "{} {}".format(part.get("tool"), arguments)
    return [(len(output), call[:CALL_CHARS])]
