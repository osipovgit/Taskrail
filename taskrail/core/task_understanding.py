"""Bind model-extracted obligations to exact spans of the unchanged user input."""

import hashlib
import json
from operator import itemgetter

from taskrail.core import schema, task_lineage

STAGE = "understanding"
REQUIREMENTS = "requirements"
SOURCES = "sources"
TEXT = "text"
HASH_LENGTH = 12


def resolve(payload, spec):
    """Validate references; interpretation remains a model and independent-review duty."""
    schema.validate(payload, schema.SCHEMAS[STAGE])
    schema.require(bool(payload[REQUIREMENTS]), "Task understanding needs at least one obligation")
    fields = {field["name"]: field[TEXT] for field in spec["fields"]}
    entries = [obligation(entry, fields) for entry in payload[REQUIREMENTS]]
    identities = [entry["id"] for entry in entries]
    schema.require(len(set(identities)) == len(entries), "Repeated extracted requirement")
    preserved = [entry for entry in spec[REQUIREMENTS] if entry["kind"] == "runtime"]
    return dict(payload, requirements=task_lineage.distinct([*entries, *preserved]))


def obligation(entry, fields):
    """The server owns identities and offsets; a model supplies text and verbatim quotes."""
    schema.require(bool(entry[SOURCES]), "An extracted requirement needs original source quotes")
    sources = [reference(source, fields) for source in entry[SOURCES]]
    explicit_constraint = any(source["field"] == "constraints" for source in sources)
    schema.require(
        not explicit_constraint or entry["kind"] == "constraint",
        "Constraints-field obligations must stay global constraints",
    )
    ordered = sorted(sources, key=itemgetter("field", "start", "end"))
    identity = [entry["kind"], entry[TEXT], ordered]
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
