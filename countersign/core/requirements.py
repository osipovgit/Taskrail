"""Assign stable identities to complete task blocks without model summarization."""

import hashlib

from countersign.core import legacy_task
from countersign.core.input_header import HEADER, typed_metadata

HASH_PREFIX_LENGTH = 12
HISTORY = "\n## Conversation history"
SERVER_TITLES = ("Workflow rules", "Turn control", "Current turn", "Task split context")


def task_requirements(task, deferred):
    """Retain every current task block; old conversation remains reference data."""
    entries = typed_metadata(task)
    if entries is not None:
        from countersign.core.task_spec import resolve

        return resolve(task, dict(entries, verification=deferred))["requirements"]
    task = task.split(HISTORY, 1)[0]
    entries = legacy_task.entries(HEADER.sub("", task).strip())
    requirements = [requirement(entry, "task") for entry in entries]
    requirements.extend(requirement(entry, "runtime") for entry in deferred)
    return list({entry["id"]: entry for entry in requirements}.values())


def labelled_task(text, entries):
    """Show task text once, adding server labels before its verbatim requirement blocks."""
    labelled = RequirementLabels(text)
    for number, entry in enumerate(entries, 1):
        labelled.add(number, entry)
    return labelled.render()


class RequirementLabels:
    """Insert labels without copying or changing the source requirement blocks."""

    def __init__(self, text):
        self.text = text
        self.current = text.split(HISTORY, 1)[0]
        self.insertions = {}
        self.additional = []

    def add(self, number, entry):
        """Reference an existing task block, or append a separate runtime requirement."""
        label = "[R{0}; {1}; kind={2}]".format(number, entry["id"], entry["kind"])
        offset = -1
        if entry["kind"] == "task":
            offset = self.current.find(entry["text"])
        if offset < 0:
            self.additional.append(f"{label}\n{entry['text']}")
        else:
            self.insertions.setdefault(offset, []).append(label)

    def render(self):
        """Apply insertions from the end so every original offset stays valid."""
        text = self.text
        for offset in sorted(self.insertions, reverse=True):
            labels = "\n".join(self.insertions[offset])
            text = "{0}{1}\n{2}".format(text[:offset], labels, text[offset:])
        return "\n".join([text, *self.additional])


def requirement(description, kind):
    """Bind identity to verbatim content and verification kind, not list position."""
    encoded = (kind + description).encode()
    fingerprint = hashlib.sha256(encoded).hexdigest()[:HASH_PREFIX_LENGTH]
    return {"id": f"R-{fingerprint}", "text": description, "kind": kind}
