"""Fields of a plan task that weak planners get wrong: Files and stray lines.

A planner that cannot know every file yet writes `roles/*/tasks/*.yaml` or a sentence
under Files. That names no file the server can protect or diff, so the line and the
entry are reported with what to write instead. Lines that are no key at all, such as an
invented `Facts:` key, are kept as more notes instead of rejecting the plan.
"""

import re

from taskrail.core.plan_keys import EXTRA, NOTES
from taskrail.core.prompt_texts import text

# Wildcards of a pattern; a trailing slash marks a directory.
PATTERN = re.compile(r"[*?\[\]{}]|/$")
PREVIEW = 80


def of_task(fields, line):
    """The Files problems of one task's fields."""
    entries, number = fields.get("files", ([], line))
    return problems(entries, number)


def notes(fields):
    """The task's Notes followed by its lines that were no key."""
    stated = fields.get(NOTES, ("", 0))[0]
    extra = fields.get(EXTRA, ())
    return " ".join(filter(None, (stated, *extra)))


def problems(entries, line):
    """One line-numbered problem for each Files entry that is not a file path."""
    found = []
    names = [name.strip() for entry in entries for name in entry.split(",")]
    for entry in names:
        if PATTERN.search(entry):
            shown = entry[:PREVIEW]
            found.append(text("validation.files_pattern", line=line, entry=shown))
    return found
