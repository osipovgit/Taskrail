"""Stable runtime identities and global constraint classification."""

import hashlib

HASH_PREFIX_LENGTH = 12
HISTORY = "\n## Conversation history"


def requirement(description, kind):
    """Bind identity to verbatim content and verification kind, not list position."""
    encoded = (kind + description).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()[:HASH_PREFIX_LENGTH]
    return {"id": f"R-{fingerprint}", "text": description, "kind": kind}


def constraint(entry):
    """Explicit model classification or a constraint supplied to an assigned child."""
    source = entry.get("source", {})
    return entry["kind"] == "constraint" or source.get("field") == "constraints"
