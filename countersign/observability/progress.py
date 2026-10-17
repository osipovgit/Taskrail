"""Public event activity; never infer or expose private model reasoning."""

import json
import re
import sys
from datetime import datetime

from countersign.core.files import atomic_json


def say(text):
    """Write one progress line for the CLI or the worker log."""
    sys.stdout.write(f"{text}\n")
    sys.stdout.flush()


def clock():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def clean(value, limit=220):
    return re.sub(r"\s+", " ", str(value)).strip()[:limit]


def event_activity(line):
    try:
        event = json.loads(line)
        part = event.get("part", {})
        kind = event.get("type")
        if kind == "tool_use":
            state = part.get("state", {})
            arguments = state.get("input") or {}
            target = arguments.get("filePath") or arguments.get("path") or ""
            detail = "Tool %s: %s %s" % (
                part.get("tool", "unknown"),
                state.get("status", "unknown"),
                target,
            )
        elif kind == "text" and isinstance(part.get("text"), str):
            detail = "Message: {text}".format(text=part["text"])
        elif kind == "step_start":
            detail = "Model step started; waiting for public output"
        elif kind == "step_finish":
            detail = "Model step finished: {reason!s}".format(reason=part.get("reason", "unknown"))
        elif kind == "error":
            detail = "opencode reported an error"
        else:
            return None
        return dict(
            kind=kind,
            detail=clean(detail),
            event_timestamp=event.get("timestamp"),
            observed_at=clock(),
        )
    except (ValueError, AttributeError, TypeError):
        return None


class Progress:
    def __init__(self, path):
        self.path = path
        self.last = None

    def observe(self, lines):
        for line in lines:
            activity = event_activity(line)
            if activity:
                self.last = activity
        if self.last:
            atomic_json(self.path, self.last)

    def line(self, elapsed, size):
        if self.last:
            observed = datetime.fromisoformat(self.last["observed_at"])
            age = max(0, (datetime.now().astimezone() - observed).total_seconds())
            activity = "waiting for next public opencode event; last: %s (%ds ago)" % (
                self.last["detail"],
                age,
            )
        else:
            activity = "waiting for the first public opencode event"
        return "  [%s] waiting %.0fs; events=%d bytes; %s" % (clock(), elapsed, size, activity)
