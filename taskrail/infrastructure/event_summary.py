"""Summarize one opencode turn from its JSON event stream."""

import json
from collections import defaultdict

from taskrail.infrastructure import (
    context_overflow,
    native_tools,
    opencode_cli,
    turn_io,
)

TOKEN_FIELDS = ("input", "output", "reasoning", "total")
ERROR = "error"
ERRORS = "errors"
TOOL = "tool"
PART = "part"
INPUT = "input"
NATIVE_FAILURE = "Native tool failure returned to the agent. No successful operation or evidence is inferred; source integrity and final result validation still apply."
SESSION_RECOVERY = (
    "opencode continued after this session error; the final result still requires validation."
)


def parse_events(path, start=0):
    """Keep native diagnostics without overriding opencode's tool recovery loop."""
    summary = EventSummary()
    for event_line, line in turn_io.event_lines(path, start):
        event = decoded(line)
        if event is not None:
            summary.observe(event_line, event)
    return summary.outcome()


def decoded(line):
    """A JSON object event with an object part, or None."""
    try:
        event = json.loads(line)
    except ValueError:
        return None
    if not isinstance(event, dict):
        return None
    part = event.get(PART, {})
    return event if isinstance(part, dict) else None


class EventSummary:
    """Duplicate parts are counted once; only the final stopping message is the answer."""

    def __init__(self):
        """Empty usage, messages and failures."""
        self.tokens = dict.fromkeys((*TOKEN_FIELDS, "cache_read", "cache_write"), 0)
        self.texts = defaultdict(list)
        self.identity = dict(final=None, final_line=None, sessions=set())
        self.identity["seen"] = set()
        self.counts = dict(tool_calls=0, steps=0)
        self.failures = dict(errors=[], tool_errors=[], session=[], permission=False)

    def observe(self, event_line, event):
        """Dispatch one new event by type."""
        if not self.fresh(event):
            return
        kind = event.get("type")
        if kind in {"step_start", "tool_use"}:
            self.identity.update(final=None, final_line=None)
        self.dispatch(event_line, event, kind)

    def dispatch(self, event_line, event, kind):
        """Aggregate one normalized event after updating its lifecycle."""
        part = event.get(PART, {})
        if kind == "text" and isinstance(part.get("text"), str):
            message = self.texts[part.get("messageID")]
            message.append(part["text"])
        elif kind == "tool_use":
            self.tool(event_line, part, event.get("sessionID"))
        elif kind == ERROR:
            error = str(event.get(ERROR, event))
            self.failures[ERRORS].append(error)
            self.failures["permission"] |= opencode_cli.permission_error(error)
            self.failures["session"].append(dict(error=error, event_line=event_line))
        elif kind == "step_finish":
            self.step(event_line, part)

    def fresh(self, event):
        """Skip repeated parts; remember the sessions that produced events."""
        part = event.get(PART, {})
        key = (event.get("type"), part.get("id"))
        if key[1] and key in self.identity["seen"]:
            return False
        self.identity["seen"].add(key)
        if event.get("sessionID"):
            self.identity["sessions"].add(event["sessionID"])
        return True

    def tool(self, event_line, part, session_id):
        """Count a call and retain native failures for the agent and operator."""
        self.counts["tool_calls"] += 1
        state = part.get("state", {})
        error = native_tools.failure(part)
        if error:
            self.failures[ERRORS].append(error)
            self.failures["permission"] |= opencode_cli.permission_error(error)
            failure = dict(tool=part.get(TOOL), call_id=part.get("callID"))
            failure.update(input=state.get(INPUT, {}), error=error, event_line=event_line)
            failure["session_id"] = session_id
            self.failures["tool_errors"].append(failure)

    def step(self, event_line, part):
        """Add reported usage; a stopping step marks the final message."""
        self.counts["steps"] += 1
        tokens = part.get("tokens", {})
        cache = tokens.get("cache", {})
        reported = {field: tokens.get(field, 0) for field in TOKEN_FIELDS}
        reported["cache_read"] = cache.get("read", 0)
        reported["cache_write"] = cache.get("write", 0)
        for field, amount in reported.items():
            self.tokens[field] += amount if isinstance(amount, (int, float)) else 0
        if part.get("reason") == "stop":
            self.identity.update(final=part.get("messageID"), final_line=event_line)

    def outcome(self):
        """Native tool diagnostics do not override a completed, independently checked result."""
        final = self.identity["final"]
        text = "\n".join(self.texts[final]) if final else ""
        summary = dict(
            tokens=self.tokens,
            steps=self.counts["steps"],
            tool_calls=self.counts["tool_calls"],
            warnings=[],
            sessions=sorted(self.identity["sessions"]),
            errors=self.failures[ERRORS],
            tool_errors=self.failures["tool_errors"],
            permission=self.failures["permission"],
            provider_context_exceeded=context_overflow.exceeded(
                [entry[ERROR] for entry in self.failures["session"]]
            ),
            completed=final is not None,
            final_text=text,
        )
        for failure in summary["tool_errors"]:
            summary[ERRORS].remove(failure[ERROR])
            summary["warnings"].append(dict(failure, resolution=NATIVE_FAILURE))
        last = self.identity["final_line"]
        for failure in self.failures["session"]:
            if text.strip() and last is not None and failure["event_line"] < last:
                summary[ERRORS].remove(failure[ERROR])
                summary["warnings"].append(dict(failure, resolution=SESSION_RECOVERY))
        summary["provider_context_exceeded"] = context_overflow.exceeded(summary[ERRORS])
        return summary
