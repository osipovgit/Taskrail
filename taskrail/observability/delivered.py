"""Characters a session received: text and finished tool calls.

With the latest reported input they approximate the session's current context while
a step is still running, or when the provider reports no usage at all. A step that
reports its input restarts the unreported count.
"""

import json

from taskrail.observability.telemetry_parts import number

TEXT = "text"
FINISHED = frozenset(("completed", "error"))
OBSERVED = "observed_characters"
UNREPORTED = "unreported_characters"
BYTES = "observed_bytes"
CACHE = ("read", "write")


class Delivered:
    """Characters since the session started and since its last reported input."""

    def __init__(self):
        """Nothing delivered yet."""
        self.counts = {OBSERVED: 0, UNREPORTED: 0, BYTES: 0}

    def observe(self, kind, part):
        """Count one fresh event."""
        if reports_input(kind, part):
            self.counts[UNREPORTED] = 0
            return
        received = delivered_text(kind, part)
        size = len(received)
        self.counts[OBSERVED] += size
        self.counts[UNREPORTED] += size
        self.counts[BYTES] += len(received.encode("utf-8"))

    def summary(self):
        """Both counts."""
        return dict(self.counts)


def reports_input(kind, part):
    """A finished step with a reported input or cache count."""
    if kind != "step_finish":
        return False
    usage = part.get("tokens") or {}
    cache = usage.get("cache") or {}
    if number(usage.get("input")) is not None:
        return True
    counted = [number(cache.get(name)) for name in CACHE]
    return counted != [None, None]


def delivered_text(kind, part):
    """Text a model response or a finished tool call adds to the session."""
    if kind == TEXT:
        return str(part.get(TEXT, ""))
    state = part.get("state") or {}
    if kind != "tool_use" or state.get("status") not in FINISHED:
        return ""
    arguments = json.dumps(state.get("input") or {}, ensure_ascii=False)
    output = state.get("output") or state.get("error") or ""
    return arguments + str(output)
