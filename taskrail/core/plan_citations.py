"""Explicit Markdown citation lists, with optional parenthesized explanations.

Only the leading list declares evidence. A comma can introduce another range of
the same path; prose never creates implicit source paths or line claims.
"""

import re

from taskrail.core import prompt_texts

SPAN = r"(\d+)(?:\s*-\s*(\d+))?"
CITATION = re.compile(rf"(?:`([^`\n]+)`:{SPAN}|`([^`\n]+):{SPAN}`|([^`\s,;()]+):{SPAN})")
RANGE = re.compile(rf"{SPAN}(?=\s*(?:[,;().]|$))")
SEPARATOR = re.compile(r"\s*([,;])\s*")


def parts(text, explanation=True, syntax=CITATION):
    """Keep every explicit citation and explanation, including notes between citations."""
    found, remaining = citation(text.strip(), syntax)
    details = []
    while remaining.strip() and not (explanation and remaining.strip() == "."):
        note = explanation_prefix(remaining.removeprefix(",")) if explanation else None
        if note is not None:
            details.append(note[0])
            remaining = note[1]
            continue
        entries, remaining = following(remaining, found[-1][0], syntax)
        found.extend(entries)
    return found, "; ".join(filter(None, details))


def explained(text):
    """A complete parenthesized reason, with no following outcomes or citations."""
    note = explanation_prefix(text)
    return note is not None and note[1] in {"", "."}


def explanation_prefix(text):
    """Consume one balanced explanation; leave subsequent citations for the list parser."""
    if not text[:1].isspace():
        return None
    text = text.strip()
    if not text.startswith("("):
        return None
    depth = 0
    for position, character in enumerate(text):
        depth += (character == "(") - (character == ")")
        if depth == 0:
            detail = text[1:position].strip()
            return detail, text[position + 1 :].strip()
    return None


def following(text, previous, syntax):
    """A separator introduces a complete path citation or another range of that path."""
    separator = SEPARATOR.match(text)
    if separator is None:
        raise ValueError(prompt_texts.diagnostic("validation.plan_citations"))
    remaining = text[separator.end() :]
    shorthand = RANGE.match(remaining) if separator[1] == "," else None
    if shorthand:
        span = (previous, *shorthand.groups())
        return [span], remaining[shorthand.end() :]
    return citation(remaining, syntax)


def citation(text, syntax):
    """Only the future-read grammar permits a file without an evidence span."""
    text = re.sub(r"^` ([^`\n]+) `", r"`\1`", text)
    match = syntax.match(text)
    if match is None:
        raise ValueError(prompt_texts.diagnostic("validation.plan_citations"))
    groups = match.groups()
    tail = text[match.end() :]
    for index in (0, 3, 6):
        if groups[index]:
            return [groups[index : index + 3]], tail
    return [(match[0].strip("`"), None, None)], tail
