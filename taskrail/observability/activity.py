"""Public event activity; never infer or expose private model reasoning."""

import json
import re
from datetime import datetime
from types import MappingProxyType

from taskrail.core.files import atomic_json
from taskrail.observability.progress import clock

DETAIL_LIMIT = 220
UNKNOWN = "unknown"
FIXED_DETAILS = MappingProxyType(
    {
        "step_start": "Model step started; waiting for public output",
        "error": "opencode reported an error",
    }
)


def clean(text, limit=DETAIL_LIMIT):
    """One line of bounded length."""
    return re.sub(r"\s+", " ", str(text)).strip()[:limit]


def event_activity(line):
    """The public activity of one raw event line, or None."""
    event = decoded_event(line)
    if event is None:
        return None
    detail = activity_detail(event.get("type"), event.get("part", {}))
    if detail is None:
        return None
    return dict(
        kind=event.get("type"),
        detail=clean(detail),
        event_timestamp=event.get("timestamp"),
        observed_at=clock(),
    )


def decoded_event(line):
    """A JSON object event with an object part, or None."""
    try:
        event = json.loads(line)
    except (ValueError, TypeError):
        return None
    if not isinstance(event, dict):
        return None
    return event if isinstance(event.get("part", {}), dict) else None


def activity_detail(kind, part):
    """Tool calls, messages and step boundaries; other events are not shown."""
    if kind == "tool_use":
        return tool_detail(part)
    if kind == "text" and isinstance(part.get("text"), str):
        return "Message: {}".format(part["text"])
    if kind == "step_finish":
        return "Model step finished: {!s}".format(part.get("reason", UNKNOWN))
    return FIXED_DETAILS.get(kind)


def tool_detail(part):
    """Tool name, status and target path."""
    state = part.get("state", {})
    if not isinstance(state, dict):
        return None
    arguments = state.get("input") or {}
    if not isinstance(arguments, dict):
        return None
    target = arguments.get("filePath") or arguments.get("path") or ""
    tool = part.get("tool", UNKNOWN)
    return "Tool {}: {} {}".format(tool, state.get("status", UNKNOWN), target)


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
            detail = self.last["detail"]
            activity = f"waiting for next public opencode event; last: {detail} ({int(age)}s ago)"
        else:
            activity = "waiting for the first public opencode event"
        return f"  [{clock()}] waiting {elapsed:.0f}s; events={size} bytes; {activity}"
