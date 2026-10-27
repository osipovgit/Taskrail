"""Observed opencode usage and public tool traces. Missing telemetry is not zero usage."""

import json

from taskrail.observability.delivered import Delivered
from taskrail.observability.telemetry_parts import (
    TEXT_PREVIEW_LIMIT,
    Steps,
    Timeline,
    ToolCalls,
    number,
)

COMPACTION = "compaction"
TEXT = "text"
FIRST_EVENT = "first_event"
FIRST_TEXT = "first_text"


class Telemetry:
    """Each part is counted once per status, however often the stream repeats it."""

    def __init__(self):
        """No events yet."""
        self.seen = set()
        self.times = dict(first_event=None, first_text=None, last_event=None)
        self.tool_calls = ToolCalls()
        self.steps = Steps()
        self.timeline = Timeline()
        self.delivered = Delivered()

    @property
    def tokens(self):
        """Reported token totals."""
        return self.steps.tokens

    def observe(self, line):
        """Malformed lines are ignored; raw JSONL stays the authoritative record."""
        try:
            self.record(json.loads(line), line)
        except (ValueError, TypeError, AttributeError):
            return

    def record(self, event, line):
        """Update counters and the timeline from one decoded event."""
        properties = event.get("properties", {})
        part = event.get("part") or properties.get("part") or {}
        kind = event.get("type")
        if not self.fresh(kind, part, line):
            return
        stamp = event.get("timestamp")
        if number(stamp) is not None:
            keep_first(self.times, FIRST_EVENT, stamp)
            self.times["last_event"] = stamp
        self.delivered.observe(kind, part)
        self.timeline.add(self.entry(kind, part, stamp))

    def fresh(self, kind, part, line):
        """A part identity and status, or the raw line without an identity, is seen once."""
        identity = part.get("id") or part.get("callID")
        state = part.get("state") or {}
        key = (kind, identity, state.get("status")) if identity else ("raw", line)
        if key in self.seen:
            return False
        self.seen.add(key)
        return True

    def entry(self, kind, part, stamp):
        """Record the event and return its public timeline entry, if any."""
        if kind == "step_finish":
            self.steps.observe(part)
        if kind in {"session.compacted", COMPACTION} or part.get("type") == COMPACTION:
            return self.timeline.compaction(kind, stamp)
        if kind == "tool_use":
            return self.tool_calls.observe(part, stamp)
        if kind == TEXT and isinstance(part.get(TEXT), str):
            keep_first(self.times, FIRST_TEXT, stamp)
            return dict(kind=TEXT, text=part[TEXT][:TEXT_PREVIEW_LIMIT], timestamp=stamp)
        return None

    def summary(self):
        """The telemetry record stored as telemetry.json."""
        return dict(
            **self.steps.summary(),
            **self.tool_calls.summary(),
            **self.times,
            **self.delivered.summary(),
            **self.timeline.summary(),
        )


def keep_first(times, name, stamp):
    """Keep the first timestamp of its kind."""
    if times[name] is None:
        times[name] = stamp


def inspect_events(path):
    """Telemetry of a complete event file; a missing file has no observations."""
    collector = Telemetry()
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                collector.observe(line)
    return collector.summary()
