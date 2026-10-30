"""The keys of plan.md: their synonyms, which hold lists and how a value is kept."""

import re
from types import MappingProxyType

KEY = re.compile(r"^[A-Za-z][A-Za-z ]*$")
BACKTICK = "`"
MARKERS = ("**", "__", BACKTICK)
DEPENDS = "depends"
NOTES = "notes"
VERIFY = "verify"
READ = "read"
KEYS = MappingProxyType(
    {
        "decision": "decision",
        "summary": "summary",
        "reason": "summary",
        "depends on": DEPENDS,
        "dependencies": DEPENDS,
        "after": DEPENDS,
        "files": "files",
        "done when": "done",
        "acceptance": "done",
        VERIFY: VERIFY,
        "verification": VERIFY,
        "checks": VERIFY,
        NOTES: NOTES,
        READ: READ,
        "read first": READ,
        "not todo": "not_todo",
        "not to do": "not_todo",
        "required checks": "required_checks",
    }
)
LISTS = frozenset(("files", "done", VERIFY, DEPENDS, READ, "not_todo", "required_checks"))
CONTINUED = LISTS | {"notes"}


def key_line(line):
    """(known key, text) of a `Key: value` line, or (None, "")."""
    name, separator, text = line.partition(":")
    if not separator:
        return None, ""
    name, text = name.strip(), text.strip()
    for marker in MARKERS:
        if name.startswith(marker):
            name = name.removeprefix(marker)
            if name.endswith(marker):
                name = name.removesuffix(marker)
            else:
                text = text.removeprefix(marker).strip()
    selected = KEYS.get(name.casefold()) if KEY.fullmatch(name) else None
    return selected, text


def uncode(text):
    """Remove one complete Markdown code wrapper, preserving the literal contents."""
    wrapped = text.startswith(BACKTICK) and text.endswith(BACKTICK)
    if wrapped and text.count(BACKTICK) == 2:
        return text[1:-1]
    return text


def stored(key, text, number):
    """A list key keeps its items, any other key its text; both keep the line."""
    if key not in LISTS:
        return text, number
    return ([text] if text else []), number
