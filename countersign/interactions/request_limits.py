"""Bound intermediate requests without treating model narration as progress."""

import json

from countersign.core import json_response, schema
from countersign.core.files import atomic_json, digest

NAME = "request-counts.json"
STATUS = "status"
MAX_ACTIONS = 64
MAX_DUPLICATES = 3
REQUESTS = frozenset(("LOCAL_REQUEST", "GIT_REQUEST", "ACTION_REQUEST", "JENKINS_REQUEST"))


def check(session, outcome):
    """Return a typed stop before routing the request that would exceed its limit."""
    if outcome[STATUS] != "OK":
        return False
    payload = extract(outcome["final_text"])
    if payload is None:
        return False
    total, duplicates = record(session, payload)
    exceeded = total > MAX_ACTIONS or repeated(payload, duplicates)
    if exceeded:
        outcome.update(
            status="NO_PROGRESS",
            errors=[
                "Intermediate request limit reached; inspect completed actions before continuing."
            ],
        )
    return exceeded


def record(session, payload):
    """Keep counters across retries and continuations of the same workflow stage."""
    run = session.environment["run"]
    path = run / NAME
    counts = json.loads(path.read_text()) if path.exists() else {}
    entries = counts.setdefault(session.active[1]["stage"], {})
    identity = fingerprint(payload, session.environment.get("expected", {}))
    entries[identity] = 1 + entries.get(identity, 0)
    atomic_json(path, counts)
    return sum(entries.values()), entries[identity]


def extract(text):
    """Recognize only advertised executable requests; final results retain their validator."""
    try:
        payload = json_response.extract(text, schema.unique_fields)
    except ValueError:
        return None
    if isinstance(payload, dict) and payload.get(STATUS) in REQUESTS:
        return payload
    return None


def fingerprint(payload, snapshot):
    """New source permits another check; wording alone does not create progress."""
    operation = {key: entry for key, entry in payload.items() if key != "reason"}
    encoded = json.dumps([operation, snapshot], sort_keys=True).encode()
    return digest(encoded)


def repeated(payload, count):
    """Live remote observations can change independently of local source files."""
    live = payload[STATUS] in {"JENKINS_REQUEST", "ACTION_REQUEST"}
    return not live and count > MAX_DUPLICATES
