"""Summarize one opencode turn from its JSON event stream."""

import json
import os
import re
from collections import defaultdict

from taskrail.infrastructure import (
    opencode_cli,
    provider_limits,
    read_warnings,
    turn_io,
    write_warnings,
)

END_OF_FILE = re.compile(r"\(End of file - total (\d+) lines\)")
LINE_NUMBER = re.compile(r"^\s*(\d+):", re.MULTILINE)
OFFSET_ERROR = re.compile(r"Error: Offset \d+ is out of range for this file \(\d+ lines\)")
TOKEN_FIELDS = ("input", "output", "reasoning", "total")
RECOVERY_KEYS = ("event_line", "call_id", "part_id")
STATUS = "status"
ERROR = "error"
ERRORS = "errors"
TOOL = "tool"
PART = "part"
INPUT = "input"
FILE_PATH = "filePath"


def parse_events(path, start=0, plan_file=None, writable_files=(), notes=()):
    """Usage, sessions, errors and the final text of events after line `start`.

    notes: the orchestrator's run files attached to the turn. The plan file among them
    is the planner's result, not a note, so its rejected overwrite still needs a proof.
    """
    summary = EventSummary()
    writes = write_warnings.FileWrites(
        (*writable_files, plan_file) if plan_file else writable_files,
        [note for note in notes if note != plan_file],
    )
    for event_line, line in turn_io.event_lines(path, start):
        event = decoded(line)
        if event is not None:
            summary.observe(event_line, event)
            writes.observe(event_line, event)
    return writes.recover(
        read_warnings.classify_missing_reads(summary.outcome()), summary.identity["final_line"]
    )


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
        self.full_reads = []

    def observe(self, event_line, event):
        """Dispatch one new event by type."""
        if not self.fresh(event):
            return
        part = event.get(PART, {})
        kind = event.get("type")
        if kind == "text" and isinstance(part.get("text"), str):
            message = self.texts[part.get("messageID")]
            message.append(part["text"])
        elif kind == "tool_use":
            self.tool(event_line, part, event.get("sessionID"))
        elif kind == ERROR:
            error = str(event.get(ERROR, event))
            self.fail(error)
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
        """Count a call; record failures and complete first-line reads."""
        self.counts["tool_calls"] += 1
        state = part.get("state", {})
        call = dict(event_line=event_line, call_id=part.get("callID"))
        call["part_id"] = part.get("id")
        if state.get(STATUS) == ERROR:
            error = str(state.get(ERROR, "unknown tool error"))
            self.fail(error)
            failure = dict(tool=part.get(TOOL), call_id=call["call_id"])
            failure.update(input=state.get(INPUT, {}), error=error, event_line=event_line)
            failure["session_id"] = session_id
            self.failures["tool_errors"].append(failure)
        elif part.get(TOOL) == "read" and full_read(state):
            call["source"] = state.get(INPUT, {}).get(FILE_PATH)
            self.full_reads.append(call)

    def fail(self, error):
        """Every error is kept; a permission denial is also flagged."""
        self.failures[ERRORS].append(error)
        self.failures["permission"] |= opencode_cli.permission_error(error)

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
        """The turn summary; recovered errors and later-fixed offset errors become warnings."""
        final = self.identity["final"]
        text = "\n".join(self.texts[final]) if final else ""
        summary = dict(
            tokens=self.tokens,
            steps=self.counts["steps"],
            tool_calls=self.counts["tool_calls"],
            warnings=offset_warnings(self.failures, self.full_reads),
            sessions=sorted(self.identity["sessions"]),
            errors=self.failures[ERRORS],
            tool_errors=self.failures["tool_errors"],
            permission=self.failures["permission"],
            provider_limit=provider_limits.reached(self.failures[ERRORS]),
            completed=final is not None,
            final_text=text,
        )
        session = self.failures["session"]
        read_warnings.recover_session_errors(summary, session, self.identity["final_line"])
        return summary


def full_read(state):
    """A completed, untruncated read from line 1."""
    output = state.get("output", "")
    metadata = state.get("metadata") or {}
    if not isinstance(output, str) or metadata.get("truncated"):
        return False
    if state.get(INPUT, {}).get("offset", 1) != 1:
        return False
    return complete_listing(output)


def complete_listing(output):
    """The numbered lines run from 1 to the reported end of file."""
    end = END_OF_FILE.search(output)
    if not end:
        return False
    body = output.split("<content>", 1)[-1]
    body = body.split("</content>", 1)[0]
    numbers = [int(number) for number in LINE_NUMBER.findall(body)]
    total = int(end.group(1))
    return numbers == list(range(1, total + 1))


def offset_warnings(failures, full_reads):
    """An out-of-range read later followed by a full read of the same file is recovered."""
    warnings = []
    for failure in failures["tool_errors"]:
        read = recovering_read(failure, full_reads)
        if read is not None:
            failure["recovered_by"] = {key: read[key] for key in RECOVERY_KEYS}
            warnings.append(dict(failure))
            failures["errors"].remove(failure[ERROR])
    return warnings


def recovering_read(failure, full_reads):
    """The first later full read of the absolute file an offset error named."""
    source = failure[INPUT].get(FILE_PATH)
    if failure[TOOL] != "read" or not OFFSET_ERROR.fullmatch(failure[ERROR]):
        return None
    if not isinstance(source, str) or not os.path.isabs(source):
        return None
    later = [read for read in full_reads if read["event_line"] > failure["event_line"]]
    return next((read for read in later if read["source"] == source), None)
