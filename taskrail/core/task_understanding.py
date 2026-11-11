"""Bind model-extracted obligations to exact spans of the unchanged user input."""

import hashlib
import json
from operator import itemgetter

from taskrail.core import schema, task_lineage

STAGE = "understanding"
NEEDS_GOAL = "NEEDS_GOAL"
REQUIREMENTS = "requirements"
SOURCES = "sources"
TEXT = "text"
KIND = "kind"
HASH_LENGTH = 12


def resolve(payload, spec):
    """Validate references; interpretation remains a model and independent-review duty."""
    schema.validate(payload, schema.SCHEMAS[STAGE])
    entries = extracted(payload[REQUIREMENTS], spec["fields"])
    preserved = [entry for entry in spec[REQUIREMENTS] if entry[KIND] == "runtime"]
    kinds = {entry[KIND] for entry in entries}
    status = "UNDERSTOOD" if "task" in kinds else NEEDS_GOAL
    combined = task_lineage.distinct([*entries, *preserved])
    return dict(payload, requirements=combined, status=status)


def extracted(requirements, fields):
    """Bind the model's obligations to user input and reject duplicate identities."""
    original = {field["name"]: field[TEXT] for field in fields}
    entries = [obligation(entry, original) for entry in requirements]
    identities = {entry["id"] for entry in entries}
    schema.require(len(identities) == len(entries), "Repeated extracted requirement")
    return entries


def obligation(entry, fields):
    """The server owns identities and offsets; a model supplies text and verbatim quotes."""
    schema.require(bool(entry[SOURCES]), "An extracted requirement needs original source quotes")
    sources = [reference(source, fields) for source in entry[SOURCES]]
    explicit_constraint = any(source["field"] == "constraints" for source in sources)
    schema.require(
        not explicit_constraint or entry[KIND] == "constraint",
        "Constraints-field obligations must stay global constraints",
    )
    ordered = sorted(sources, key=itemgetter("field", "start", "end"))
    identity = [entry[KIND], entry[TEXT], ordered]
    identity = json.dumps(identity, sort_keys=True).encode()
    fingerprint = hashlib.sha256(identity).hexdigest()[:HASH_LENGTH]
    return dict(entry, id=f"R-{fingerprint}", sources=sources)


def reference(source, fields):
    """Resolve a quote only in its named field, disambiguating repeated occurrences."""
    field = source["field"]
    schema.require(field in fields, f"Unknown input field: {field}")
    quote = source["quote"]
    positions = occurrences(fields[field], quote)
    selected = source.get("occurrence")
    if selected is None:
        schema.require(len(positions) == 1, f"Quote in {field} needs one exact match or occurrence")
        selected = 1
    schema.require(selected <= len(positions), f"Quote occurrence is missing in {field}")
    start = positions[selected - 1]
    return dict(field=field, start=start, end=start + len(quote))


def occurrences(text, quote):
    """Character positions, including overlapping matches; quoted text is never normalized."""
    positions = []
    offset = text.find(quote)
    while offset >= 0:
        positions.append(offset)
        offset = text.find(quote, offset + 1)
    return positions
