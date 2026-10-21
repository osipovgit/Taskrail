"""Bounded local messages and immutable action validation."""

import hashlib
import json
import re

from countersign.core.schema import unique_fields

MAX_MESSAGE = 2 * 1024 * 1024
MAX_SCRIPT = 524288
SOCKET = "/run/countersign-executor/control.sock"
# Present while an update or reset runs: no new submissions or approvals.
MAINTENANCE_MARKER = "/etc/countersign-executor/maintenance"
MAINTENANCE = "maintenance"


class MaintenanceError(OSError):
    """The executor is being updated or reset; like an outage, ask again later."""


def encode(payload):
    """Encode one bounded message without ambiguous JSON fields."""
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
    if len(raw) > MAX_MESSAGE:
        raise ValueError("Executor message exceeds the size limit")
    return b"%s\n" % raw


def receive(stream):
    """Read exactly one bounded newline-delimited object."""
    raw = stream.readline(MAX_MESSAGE + 2)
    if len(raw) > MAX_MESSAGE + 1 or not raw.endswith(b"\n"):
        raise ValueError("Incomplete or oversized executor message")
    payload = json.loads(raw, object_pairs_hook=unique_fields)
    if not isinstance(payload, dict):
        raise ValueError("Executor message must be an object")
    return payload


def fingerprint(payload):
    """Bind authorization to the complete canonical payload."""
    return hashlib.sha256(encode(payload)).hexdigest()


def label(entry):
    """Accept only non-option identifiers."""
    if not isinstance(entry, str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,63}", entry):
        raise ValueError("Invalid executor identifier")
    return entry


def text(entry):
    """Bound text submitted for human review."""
    if not isinstance(entry, str) or not entry.strip() or "\x00" in entry:
        raise ValueError("Expected nonempty text without NUL bytes")
    if len(entry.encode("utf-8")) > MAX_SCRIPT:
        raise ValueError("Executor text exceeds the size limit")
    return entry
