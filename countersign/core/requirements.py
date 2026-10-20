"""Assign stable identities to complete task blocks without model summarization."""

import hashlib
import re

HEADER = re.compile(r"(?ms)^```countersign-task\s*\n.*?^```\s*$")
# Server-generated instructions are followed as policy, not covered as requirements.
SERVER_TITLES = ("Workflow rules", "Turn control", "Current turn", "Task split context")
SERVER_SECTIONS = re.compile(r"(?ms)^## (?:{0})\n.*?(?=^## |\Z)".format("|".join(SERVER_TITLES)))
HASH_PREFIX_LENGTH = 12
HISTORY = "\n## Conversation history"


def task_requirements(task, deferred):
    """Retain every current task block; old conversation remains reference data."""
    task = task.split(HISTORY, 1)[0]
    current = SERVER_SECTIONS.sub("", HEADER.sub("", task)).strip()
    blocks = re.split(r"\n\s*\n|\n(?=\s*(?:[-*] |\d+[.)] ))", current)
    entries = [entry.strip() for entry in blocks if entry.strip()]
    requirements = [requirement(entry, "task") for entry in entries]
    requirements.extend(requirement(entry, "runtime") for entry in deferred)
    return list({entry["id"]: entry for entry in requirements}.values())


def requirement(description, kind):
    """Bind identity to verbatim content and verification kind, not list position."""
    encoded = (kind + description).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()[:HASH_PREFIX_LENGTH]
    return {"id": f"R-{fingerprint}", "text": description, "kind": kind}
