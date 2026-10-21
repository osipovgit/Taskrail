"""The keys of plan.md: their synonyms, which hold lists and how a value is kept."""

import re
from types import MappingProxyType

KEY = re.compile(r"^([A-Za-z][A-Za-z ]*?)\s*:\s*(.*)$")
NOTES = "notes"
VERIFY = "verify"
KEYS = MappingProxyType(
    {
        "decision": "decision",
        "summary": "summary",
        "reason": "summary",
        "depends on": "depends",
        "dependencies": "depends",
        "after": "depends",
        "files": "files",
        "done when": "done",
        "acceptance": "done",
        VERIFY: VERIFY,
        "verification": VERIFY,
        "checks": VERIFY,
        NOTES: NOTES,
    }
)
LISTS = frozenset(("files", "done", VERIFY))
CONTINUED = LISTS | {"notes"}


def key_line(line):
    """(known key, text) of a `Key: value` line, or (None, "")."""
    found = KEY.match(line)
    if not found:
        return None, ""
    name = found.group(1).strip().casefold()
    return KEYS.get(name), found.group(2).strip()


def stored(key, text, number):
    """A list key keeps its items, any other key its text; both keep the line."""
    if key not in LISTS:
        return text, number
    return ([text] if text else []), number
