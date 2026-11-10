"""Identify an explicit stage submission before considering executor requests in its prose."""

import re

# A quote or heading marker and emphasis may precede the word; a list bullet may not.
FINAL = re.compile(
    r"^\s*(?:[>#]+\s*)?[*_`]*(DONE|BLOCKED)(?=[\s:*_`]|$)[*_`]*(:?)[\s*_`]*(.*)$", re.I
)
BLOCKED = "BLOCKED"
# "Blocked: none" in a closing summary reports the absence of a blocker.
NOT_BLOCKED = frozenset(("none", "nothing", "n/a", "no", "-"))


def submitted(text):
    """A submitted artifact or implementation may quote previous requests in its report."""
    for line in text.splitlines():
        marker = line.strip(" .*_`").casefold()
        if marker in {"ready for server plan checks", "done"} or final_line(line):
            return True
    return False


def final_line(line):
    """(word, text) of a closing line, or None.

    The word counts in capitals, or in any case when a colon follows it, so prose such as
    "Done when: ..." is not mistaken for the final word.
    """
    found = FINAL.match(line)
    if found is None:
        return None
    word, colon, text = found.groups()
    if not (word.isupper() or colon):
        return None
    word = word.upper()
    if word == BLOCKED and text.strip(" .*_`").casefold() in NOT_BLOCKED:
        return None
    return word, text
