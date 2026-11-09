"""Bound intermediate requests without treating model narration as progress."""

import json

from taskrail.core.files import atomic_json, digest
from taskrail.interactions import turn_recovery

NAME = "request-counts.json"
MAX_DUPLICATES = 3


def check(session, outcome, payload):
    """Return a typed stop before routing the request that would exceed its limit."""
    exceeded = record(session, payload) > MAX_DUPLICATES
    if exceeded:
        outcome.update(
            status="NO_PROGRESS",
            errors=[
                "Repeated unchanged executor request; inspect its previous result and use a different approach."
            ],
        )
    return exceeded


def reset(run, stage):
    """A stage round starts counting afresh: a new entry after feedback, or a Continue."""
    path = run / NAME
    if not path.exists():
        return
    counts = json.loads(path.read_text())
    if counts.pop(stage, None) is not None:
        atomic_json(path, counts)


def record(session, payload):
    """Keep counters across the retries of one stage round."""
    path = session.environment["run"] / NAME
    counts = json.loads(path.read_text()) if path.exists() else {}
    entries = counts.setdefault(session.active[1]["stage"], {})
    identity = fingerprint(payload, turn_recovery.work_state(session))
    count = 1 + entries.get(identity, 0)
    entries[identity] = count
    atomic_json(path, counts)
    return count


def fingerprint(payload, snapshot):
    """New source permits another check; wording alone does not create progress."""
    operation = {key: entry for key, entry in payload.items() if key != "reason"}
    encoded = json.dumps([operation, snapshot], sort_keys=True).encode()
    return digest(encoded)
