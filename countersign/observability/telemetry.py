"""Observed opencode usage and public tool traces. Missing telemetry is not zero usage."""

import json
import math
from collections import Counter
from datetime import datetime

TEXT_PREVIEW_LIMIT = 30000
TOOL_PREVIEW_LIMIT = 8000
TIMELINE_LIMIT = 300
MILLISECONDS_PER_SECOND = 1000

FIELDS = ("input", "output", "reasoning", "cache_read", "cache_write", "total")


def number(value):
    return (
        value
        if isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
        else None
    )


class Telemetry:
    def __init__(self):
        self.tokens = dict.fromkeys(FIELDS, 0)
        self.seen = set()
        self.calls = {}
        self.reads = Counter()
        self.read_calls = set()
        self.usage_steps = 0
        self.steps = 0
        self.last_input = None
        self.peak_input = None
        self.compactions = []
        self.timeline = []
        self.cost = 0
        self.cost_steps = 0
        self.first_event = None
        self.first_text = None
        self.last_event = None
        self.omitted = 0

    def observe(self, line):
        try:
            event = json.loads(line)
            part = event.get("part") or event.get("properties", {}).get("part") or {}
            kind = event.get("type")
            state = part.get("state") or {}
            stamp = event.get("timestamp")
            identity = part.get("id") or part.get("callID")
            key = (kind, identity, state.get("status")) if identity else ("raw", line)
            if key in self.seen:
                return
            self.seen.add(key)
            if number(stamp) is not None:
                if self.first_event is None:
                    self.first_event = stamp
                self.last_event = stamp
            entry = None
            if kind == "text" and isinstance(part.get("text"), str):
                if self.first_text is None:
                    self.first_text = stamp
                entry = dict(kind="text", text=part["text"][:TEXT_PREVIEW_LIMIT], timestamp=stamp)
            if kind == "tool_use":
                call = part.get("callID") or identity or str(len(self.calls))
                arguments = state.get("input") or {}
                self.calls[call] = dict(tool=part.get("tool"), status=state.get("status"))
                if (
                    call not in self.read_calls
                    and part.get("tool") == "read"
                    and isinstance(arguments, dict)
                    and arguments.get("filePath")
                ):
                    self.reads[json.dumps(arguments, sort_keys=True)] += 1
                    self.read_calls.add(call)
                times = state.get("time") or {}
                start, end = number(times.get("start")), number(times.get("end"))
                entry = dict(
                    kind="tool",
                    tool=part.get("tool"),
                    call_id=call,
                    status=state.get("status"),
                    input=json.dumps(arguments, ensure_ascii=False)[:TOOL_PREVIEW_LIMIT],
                    timestamp=stamp or end or start,
                    duration_seconds=(end - start) / MILLISECONDS_PER_SECOND
                    if start is not None and end is not None and end >= start
                    else None,
                    error=str(state.get("error", ""))[:TOOL_PREVIEW_LIMIT],
                    output=str(state.get("output", ""))[:TOOL_PREVIEW_LIMIT],
                    output_truncated=len(str(state.get("output", ""))) > TOOL_PREVIEW_LIMIT,
                )
            if kind == "step_finish":
                self.steps += 1
                usage = part.get("tokens") or {}
                if number(usage.get("total")) is not None:
                    self.usage_steps += 1
                for name in FIELDS:
                    value = (
                        (usage.get("cache") or {}).get(name[6:])
                        if name.startswith("cache_")
                        else usage.get(name)
                    )
                    if number(value) is not None:
                        self.tokens[name] += value
                incoming = number(usage.get("input"))
                if incoming is not None:
                    self.last_input = incoming
                    self.peak_input = max(self.peak_input or 0, incoming)
                if number(part.get("cost")) is not None:
                    self.cost += part["cost"]
                    self.cost_steps += 1
            # Explicit structured markers only; prose/token drops never prove compaction.
            if (
                kind == "session.compacted"
                or kind == "compaction"
                or part.get("type") == "compaction"
            ):
                completed = kind == "session.compacted"
                entry = dict(
                    kind="compaction",
                    timestamp=stamp,
                    completed=completed,
                    text="Compaction completed (explicit event)"
                    if completed
                    else "Compaction marker observed; completion not confirmed",
                )
                self.compactions.append(entry)
            if entry:
                self.timeline.append(entry)
                if len(self.timeline) > TIMELINE_LIMIT:
                    self.timeline.pop(0)
                    self.omitted += 1
        except (ValueError, TypeError, AttributeError):
            pass

    def value(self):
        return dict(
            tokens=self.tokens,
            model_steps=self.steps,
            usage_steps=self.usage_steps,
            usage_coverage="reported_steps_only" if self.usage_steps else "unavailable",
            tool_calls=len(self.calls),
            tool_errors=sum(record["status"] == "error" for record in self.calls.values()),
            tools=dict(Counter(record["tool"] for record in self.calls.values())),
            repeated_reads=sum(count - 1 for count in self.reads.values()),
            last_input=self.last_input,
            peak_input=self.peak_input,
            reported_cost=self.cost if self.cost_steps else None,
            cost_coverage_steps=self.cost_steps,
            first_event=self.first_event,
            first_text=self.first_text,
            last_event=self.last_event,
            compaction_completed=sum(record["completed"] for record in self.compactions),
            compaction_markers=len(self.compactions),
            compaction_coverage="unknown",
            timeline=self.timeline,
            timeline_omitted=self.omitted,
        )


def inspect_events(path):
    collector = Telemetry()
    if path.is_file():
        with path.open(encoding="utf-8", errors="replace") as stream:
            for line in stream:
                collector.observe(line)
    return collector.value()


def seconds(start, end):
    try:
        return max(0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except (ValueError, TypeError):
        return None
