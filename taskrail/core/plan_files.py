"""Fields of a plan task that weak planners get wrong: Files and stray lines.

A planner that cannot know every file yet writes `roles/*/tasks/*.yaml` or a sentence
under Files. That names no file the server can protect or diff, so the line and the
entry are reported with what to write instead. Lines that are no key at all, such as an
invented `Facts:` key, are kept as more notes instead of rejecting the plan.
"""

import re

from taskrail.core.plan_keys import ENTRY_LINES, EXTRA, NOTES, uncode
from taskrail.core.prompt_texts import text

# Wildcards of a pattern; a trailing slash marks a directory.
PATTERN = re.compile(r"[*?\[\]{}]|/$")
PREVIEW = 80
NEW_FILE = re.compile(r"\s*\((?:new|new file)\)\s*$", re.IGNORECASE)


def of_task(fields):
    """The Files problems of one task's fields."""
    entries = fields.get("files", ([], 0))[0]
    numbers = fields.get(ENTRY_LINES, {}).get("files", [])
    return [
        error
        for entry, line in zip(entries, numbers, strict=True)
        for error in problems(entry, line)
    ]


def notes(fields):
    """The task's Notes followed by its lines that were no key."""
    stated = fields.get(NOTES, ("", 0))[0]
    extra = fields.get(EXTRA, ())
    return " ".join(filter(None, (stated, *extra)))


def problems(entry, line):
    """One line-numbered problem for each Files entry that is not a file path."""
    found = []
    names = [name.strip() for name in entry.split(",")]
    for name in names:
        clean = uncode(NEW_FILE.sub("", name))
        key = "validation.files_prose" if "`" in clean else "validation.files_pattern"
        if PATTERN.search(clean) or "`" in clean:
            found.append(text(key, line=line, entry=name[:PREVIEW]))
    return found
