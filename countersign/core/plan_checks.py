"""Strict recipe selections use requirement labels, never model-authored commands."""

import re

from countersign.core.schema import require

SELECTIONS = "check_selections"
RECIPE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
LABEL = re.compile(r"R[1-9]\d*", re.IGNORECASE)


def selections(lines, requirements):
    """Translate every selected runtime label to its frozen requirement identity."""
    labels = requirement_labels(requirements)
    selected = [selection(text, number, labels) for text, number in lines]
    names = [entry["recipe_id"] for entry in selected]
    require(
        len(names) == len(set(names)), "Check selections: duplicate recipe; combine its criteria"
    )
    return selected


def selection(text, number, labels):
    """One `recipe-id: R1, R2` line, consumed completely."""
    name, separator, raw = text.partition(":")
    valid = separator and RECIPE.fullmatch(name.strip())
    require(bool(valid), f"line {number}: invalid recipe ID")
    entries = [runtime(label, labels, number) for label in requested_labels(raw, number)]
    return dict(recipe_id=name.strip(), criteria=entries)


def requested_labels(raw, number):
    """Reject partial labels and duplicated selections before resolving identities."""
    requested = [label.strip().upper() for label in raw.split(",")]
    valid = all(LABEL.fullmatch(label) for label in requested)
    require(valid, f"line {number}: invalid criterion labels")
    unique = len(requested) == len(set(requested))
    require(unique, f"line {number}: duplicate criterion label")
    return requested


def requirement_labels(requirements):
    """Resolve display labels in the frozen, server-owned requirement order."""
    return {f"R{number}": entry for number, entry in enumerate(requirements, 1)}


def runtime(label, labels, number):
    """Only a declared runtime criterion can be proven by an executed recipe."""
    require(label in labels, f"line {number}: unknown requirement {label}")
    entry = labels[label]
    require(entry["kind"] == "runtime", f"line {number}: {label} is not a runtime requirement")
    return entry["id"]
