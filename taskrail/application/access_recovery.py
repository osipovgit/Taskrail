"""Continue read-only work with permitted evidence after an access rejection."""

import json

from taskrail.core import prompt_texts
from taskrail.infrastructure.opencode_cli import permission_error

READ_TOOLS = frozenset(("read", "grep", "glob", "list"))
MAX_RECOVERIES = 2


def denied_calls(outcome):
    """Keep tool arguments, never turn an error message into authorization."""
    if any(
        not (permission_error(message) or "Tool execution aborted" in message)
        for message in outcome.get("errors", [])
    ):
        return []
    calls = []
    for error in outcome.get("tool_errors", []):
        if not permission_error(error.get("error", "")):
            continue
        if error.get("tool") not in READ_TOOLS:
            return []
        calls.append({key: error.get(key) for key in ("tool", "input")})
    return calls


def previous_correction(state, stage, roots):
    """Restore denied-call feedback when explicitly resuming a read-only stage."""
    if stage == "implementer":
        return ""
    for record in reversed(state["stages"]):
        if record.get("stage") == stage:
            calls = denied_calls(record)
            return correction(calls, roots) if calls else ""
    return ""


def correction(calls, roots):
    """Supply declared alternatives without guessing or opening a denied location."""
    text = prompt_texts.text(
        "recovery.access",
        calls=json.dumps(calls, ensure_ascii=False),
        roots=json.dumps(list(map(str, roots.values()))),
    )
    return f"\n{text}\n"


class AccessRecovery:
    """Bound retries; an identical denied call is never retried automatically."""

    def __init__(self):
        self.seen = set()
        self.count = 0
        self.spent = 0

    def accept(self, outcome, timeout):
        """Count time already spent and refuse repeated or unclassified failures."""
        self.spent += outcome.get("elapsed_seconds", 0)
        calls = denied_calls(outcome)
        signatures = {json.dumps(call, sort_keys=True) for call in calls}
        if not calls or signatures & self.seen:
            return False
        if self.count >= MAX_RECOVERIES or self.spent >= timeout:
            return False
        self.seen.update(signatures)
        self.count += 1
        return True


def restore(state, stage):
    """Explicit continuation retains denied signatures and recovery count."""
    recovery = AccessRecovery()
    for record in state["stages"]:
        if record.get("stage") == stage and record.get("mode") == "access-recovery":
            recovery.count += 1
        if record.get("stage") == stage:
            calls = denied_calls(record)
            recovery.seen.update(json.dumps(call, sort_keys=True) for call in calls)
    return recovery
