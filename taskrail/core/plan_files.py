"""Fields of a plan task that weak planners get wrong: Files and stray lines.

A planner that cannot know every file yet writes `roles/*/tasks/*.yaml` or a sentence
under Files. That names no file the server can protect or diff, so the line and the
entry are reported with what to write instead. Lines that are no key at all, such as an
invented `Facts:` key, are kept as more notes instead of rejecting the plan.
"""

import re

from taskrail.core.paths import absolute
from taskrail.core.plan_keys import EXTRA, NOTES, numbered, uncode
from taskrail.core.prompt_texts import text

# Wildcards of a pattern; a trailing slash marks a directory.
LITERAL = re.compile(r"[*?]|/$")
PATTERN = re.compile(r"[*?\[\]{}]|/$")
PREVIEW = 80
NEW_FILE = re.compile(r"\s*\((?:new|new file)\)\s*$", re.IGNORECASE)


def names(fields, coverage):
    """Parse each literal once for both validation and the stored Files array."""
    found = []
    for entry, line in numbered(fields, "files"):
        for candidate in split_names(entry):
            literal = checked_name(candidate, line, coverage.problems)
            if literal:
                found.append(str(absolute(literal, coverage.roots)))
    return found


def split_names(entry):
    """Split comma lists only outside Markdown code spans."""
    parts = re.split(r"(`[^`]*`|,)", entry)
    current = []
    for part in parts:
        if part == ",":
            yield "".join(current).strip()
            current.clear()
        else:
            current.append(part)
    yield "".join(current).strip()


def checked_name(candidate, line, issues):
    """A quoted literal can name files containing spaces, commas and brackets."""
    raw = NEW_FILE.sub("", candidate)
    if raw.startswith("<") and raw.endswith(">"):
        return None
    name = uncode(raw)
    pattern = PATTERN if raw == name else LITERAL
    if "`" in name:
        key = "validation.files_prose"
    elif pattern.search(name):
        key = "validation.files_pattern"
    elif raw == name and any(map(str.isspace, name)):
        key = "validation.files_prose"
    else:
        return name
    issues.append(text(key, line=line, entry=candidate[:PREVIEW]))
    return None


def notes(fields, hints):
    """The task's Notes followed by its lines that were no key."""
    stated = fields.get(NOTES, ("", 0))[0]
    extra = fields.get(EXTRA, ())
    return " ".join(filter(None, (stated, *extra, *hints)))
