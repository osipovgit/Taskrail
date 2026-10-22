"""Stable requirement ownership between reviewed plans and their child runs."""

import hashlib
import json

from countersign.core import requirements, schema

IDENTIFIER = "id"
REQUIRED = frozenset((IDENTIFIER, "kind", "text"))
OPTIONAL = frozenset(("parent_id", "scope", "source", "derived_from"))
HASH_LENGTH = 12


def checked_assignments(entries):
    """Lineage is data; only the workflow can authenticate a reviewed parent contract."""
    schema.require(isinstance(entries, list), "assigned_requirements must be a list")
    for entry in entries:
        check_entry(entry)
    names = {record[IDENTIFIER] for record in entries}
    schema.require(len(names) == len(entries), "Duplicate assigned requirement")
    return entries


def check_entry(entry):
    """Requirement transport cannot add arbitrary untyped metadata."""
    schema.require(isinstance(entry, dict), "Invalid assigned requirement")
    fields = set(entry)
    schema.require(REQUIRED <= fields <= REQUIRED | OPTIONAL, "Invalid assigned requirement fields")
    texts = [entry[key] for key in REQUIRED]
    schema.require(
        all(isinstance(text, str) for text in texts), "Invalid assigned requirement text"
    )
    valid = entry["kind"] in {"task", "runtime"}
    valid = valid and bool(entry["text"].strip())
    schema.require(valid, "Invalid assigned requirement kind or text")


def assigned(entry, scope):
    """Preserve the parent's text and identity, deriving an ID only for a scoped part."""
    kind = entry.get("kind", "task")
    record = dict(entry, kind=kind, parent_id=entry[IDENTIFIER])
    if scope:
        encoded = json.dumps([entry[IDENTIFIER], scope]).encode()
        fingerprint = hashlib.sha256(encoded).hexdigest()[:HASH_LENGTH]
        record.update(id=f"R-{fingerprint}", scope=scope)
    return record


def distinct(entries):
    """Retain global constraint scope and authenticated lineage when text repeats."""
    kept = {}
    for entry in entries:
        previous = kept.setdefault(entry[IDENTIFIER], entry)
        global_constraint = entry.get("source", {}).get("field") == "constraints"
        if global_constraint and "parent_id" not in previous:
            kept[entry[IDENTIFIER]] = entry
    return list(kept.values())


def for_step(parent_requirements, step):
    """A child's exact obligations: owned parts, global constraints and its acceptance."""
    entries = inherited(parent_requirements, step)
    for text in step.get("done_when", []):
        record = requirements.requirement(text, "task")
        entries.append(dict(record, derived_from=list(step["criteria"])))
    return distinct(entries)


def inherited(parent_requirements, step):
    """Global constraints are obligations of every child, not model-owned optional context."""
    scope_records = step.get("scopes", [])
    scopes = {entry[IDENTIFIER]: entry["scope"] for entry in scope_records}
    entries = []
    for entry in parent_requirements:
        global_constraint = entry.get("source", {}).get("field") == "constraints"
        if entry[IDENTIFIER] in step["criteria"] or global_constraint:
            entries.append(
                assigned(entry, None if global_constraint else scopes.get(entry[IDENTIFIER]))
            )
    return entries
