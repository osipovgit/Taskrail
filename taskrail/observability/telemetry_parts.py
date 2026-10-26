"""Tool calls, model steps and the public timeline of one event stream."""

import json
import math
from collections import Counter

TEXT_PREVIEW_LIMIT = 30000
TOOL_PREVIEW_LIMIT = 8000
TIMELINE_LIMIT = 300
MILLISECONDS_PER_SECOND = 1000
FIELDS = ("input", "output", "reasoning", "cache_read", "cache_write", "total")
INPUT = "input"
STATUS = "status"
TOOL = "tool"


def number(candidate):
    """A finite, non-negative int or float (not bool); anything else is None."""
    if isinstance(candidate, bool) or not isinstance(candidate, (int, float)):
        return None
    if not math.isfinite(candidate) or candidate < 0:
        return None
    return candidate


class ToolCalls:
    """Distinct calls by ID and repeated identical reads."""

    def __init__(self):
        """No calls yet."""
        self.calls = {}
        self.reads = Counter()
        self.read_calls = set()

    def observe(self, part, stamp):
        """Record the call's latest status and return its timeline entry."""
        state = part.get("state") or {}
        call = part.get("callID") or part.get("id")
        if not call:
            call = str(len(self.calls))
        arguments = state.get(INPUT) or {}
        status = state.get(STATUS)
        self.calls[call] = dict(tool=part.get(TOOL), status=status)
        if part.get(TOOL) == "read" and call not in self.read_calls:
            self.count_read(call, arguments)
        return tool_entry(part, call, stamp)

    def count_read(self, call, arguments):
        """Identical read arguments of distinct calls are repeated reads."""
        if isinstance(arguments, dict) and arguments.get("filePath"):
            self.reads[json.dumps(arguments, sort_keys=True)] += 1
            self.read_calls.add(call)

    def summary(self):
        """Call counts by tool and status."""
        records = self.calls.values()
        return dict(
            tool_calls=len(self.calls),
            tool_errors=sum(record[STATUS] == "error" for record in records),
            tools=dict(Counter(record[TOOL] for record in records)),
            repeated_reads=sum(count - 1 for count in self.reads.values()),
        )


class Steps:
    """Reported usage and cost of model steps; missing values are not zero usage."""

    def __init__(self):
        """No steps yet."""
        self.tokens = dict.fromkeys(FIELDS, 0)
        self.counts = dict(steps=0, usage_steps=0, cost_steps=0)
        self.inputs = dict(last=None, peak=None)
        self.cost = 0

    def observe(self, part):
        """Add one finished step."""
        self.counts["steps"] += 1
        usage = part.get("tokens") or {}
        if number(usage.get("total")) is not None:
            self.counts["usage_steps"] += 1
        self.add_usage(usage)
        incoming = self.context_input(usage)
        if incoming is not None:
            peak = max(self.inputs["peak"] or 0, incoming)
            self.inputs.update(last=incoming, peak=peak)
        if number(part.get("cost")) is not None:
            self.cost += part["cost"]
            self.counts["cost_steps"] += 1

    def add_usage(self, usage):
        """Only reported numeric values are added."""
        cache = usage.get("cache") or {}
        reported = {name: usage.get(name) for name in FIELDS}
        reported.update(cache_read=cache.get("read"), cache_write=cache.get("write"))
        for name, amount in reported.items():
            self.tokens[name] += number(amount) or 0

    def context_input(self, usage):
        """Reported input includes uncached tokens and both provider cache categories."""
        cache = usage.get("cache") or {}
        reported = [number(usage.get(INPUT))]
        for name in ("read", "write"):
            reported.append(number(cache.get(name)))
        if all(amount is None for amount in reported):
            return None
        return sum(amount or 0 for amount in reported)

    def summary(self):
        """Usage totals with their coverage."""
        usage_steps = self.counts["usage_steps"]
        return dict(
            tokens=self.tokens,
            model_steps=self.counts["steps"],
            usage_steps=usage_steps,
            usage_coverage="reported_steps_only" if usage_steps else "unavailable",
            last_input=self.inputs["last"],
            peak_input=self.inputs["peak"],
            reported_cost=self.cost if self.counts["cost_steps"] else None,
            cost_coverage_steps=self.counts["cost_steps"],
        )


class Timeline:
    """The latest public entries; explicit compaction markers are counted separately."""

    def __init__(self):
        """An empty timeline."""
        self.entries = []
        self.compactions = []
        self.omitted = 0

    def add(self, entry):
        """Keep at most TIMELINE_LIMIT entries."""
        if entry is None:
            return
        self.entries.append(entry)
        if len(self.entries) > TIMELINE_LIMIT:
            self.entries.pop(0)
            self.omitted += 1

    def compaction(self, kind, stamp):
        """Only explicit structured markers count; prose never proves compaction."""
        completed = kind == "session.compacted"
        text = "Compaction marker observed; completion not confirmed"
        if completed:
            text = "Compaction completed (explicit event)"
        entry = dict(kind="compaction", timestamp=stamp, completed=completed, text=text)
        self.compactions.append(entry)
        return entry

    def summary(self):
        """Entries and compaction counts."""
        return dict(
            compaction_completed=sum(entry["completed"] for entry in self.compactions),
            compaction_markers=len(self.compactions),
            compaction_coverage="unknown",
            timeline=self.entries,
            timeline_omitted=self.omitted,
        )


def tool_entry(part, call, stamp):
    """A bounded public trace of one tool call."""
    state = part.get("state") or {}
    start, end = bounds(state.get("time") or {})
    output = str(state.get("output", ""))
    arguments = json.dumps(state.get(INPUT) or {}, ensure_ascii=False)
    return dict(
        kind=TOOL,
        tool=part.get(TOOL),
        call_id=call,
        status=state.get(STATUS),
        input=arguments[:TOOL_PREVIEW_LIMIT],
        timestamp=stamp or end or start,
        duration_seconds=duration(start, end),
        error=str(state.get("error", ""))[:TOOL_PREVIEW_LIMIT],
        output=output[:TOOL_PREVIEW_LIMIT],
        output_truncated=len(output) > TOOL_PREVIEW_LIMIT,
    )


def bounds(times):
    """Valid start and end timestamps of a tool call."""
    return number(times.get("start")), number(times.get("end"))


def duration(start, end):
    """Seconds between millisecond timestamps, when both are valid and ordered."""
    if start is None or end is None or end < start:
        return None
    return (end - start) / MILLISECONDS_PER_SECOND
