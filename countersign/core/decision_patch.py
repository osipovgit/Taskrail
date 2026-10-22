"""Addressed corrections of one unvalidated V2 draft, never execution authority."""

import copy
import re

from countersign.core import schema

FIELDS = frozenset(("outcomes", "findings", "missing_inputs", "summary"))
ESCAPE = re.compile(r"~(?![01])")
MAX_CORRECTIONS = 20
MAX_POINTER = 300


def apply(payload, previous):
    """Merge bounded replacements and let the full decision validator run again."""
    schema.require(set(payload) == {"schema_version", "corrections"}, "Invalid correction envelope")
    version = payload["schema_version"]
    schema.require(isinstance(version, int) and version == 2, "Unsupported correction version")
    schema.require(previous.get("schema_version") == 2, "No V2 draft; return a complete decision")
    replacements = payload["corrections"]
    schema.require(isinstance(replacements, list), "Corrections must be a list")
    schema.require(0 < len(replacements) <= MAX_CORRECTIONS, "Invalid correction count")
    draft = copy.deepcopy(previous)
    for replacement in replacements:
        replace(draft, replacement)
    return draft


def replace(draft, replacement):
    """Replace a field or existing array element; object fields may be supplied if missing."""
    schema.require(isinstance(replacement, dict), "Correction must be an object")
    schema.require(set(replacement) == {"path", "value"}, "Correction needs path and value")
    segments = pointer(replacement["path"])
    schema.require(segments[0] in FIELDS, "Correction must address a semantic decision field")
    parent = draft
    for segment in segments[:-1]:
        parent = member(parent, segment)
    if isinstance(parent, list):
        parent[index(segments[-1], parent)] = replacement["value"]
    else:
        schema.require(isinstance(parent, dict), "Correction parent must be an object or array")
        parent[segments[-1]] = replacement["value"]


def pointer(path):
    """Decode a canonical JSON pointer; malformed escapes never guess a field."""
    schema.require(
        isinstance(path, str) and path.startswith("/"), "Correction needs a JSON pointer"
    )
    valid = len(path) <= MAX_POINTER and not ESCAPE.search(path)
    schema.require(valid, "Invalid correction pointer")
    return list(map(unescaped, path[1:].split("/")))


def unescaped(segment):
    """Decode only the two JSON pointer escapes after their grammar was checked."""
    return segment.replace("~1", "/").replace("~0", "~")


def index(segment, entries):
    """Only existing array slots are addressable; insertion and deletion are explicit arrays."""
    schema.require(segment.isdecimal(), "Correction array index must be a number")
    number = int(segment)
    schema.require(
        str(number) == segment and number < len(entries), "Correction array index is absent"
    )
    return number


def member(parent, segment):
    """Walk only an existing object or array boundary."""
    if isinstance(parent, list):
        return parent[index(segment, parent)]
    schema.require(isinstance(parent, dict) and segment in parent, "Correction parent is absent")
    return parent[segment]
