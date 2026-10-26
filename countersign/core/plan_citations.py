"""Explicit Markdown citation lists, with optional parenthesized explanations.

Only the leading list declares evidence. A comma can introduce another range of
the same path; prose never creates implicit source paths or line claims.
"""

import re

from countersign.core import prompt_texts

SPAN = r"(\d+)(?:\s*-\s*(\d+))?"
CITATION = re.compile(rf"(?:`([^`\n]+):{SPAN}`|([^`\s,;()]+):{SPAN})")
RANGE = re.compile(rf"{SPAN}(?=\s*(?:[,;()]|$))")
SEPARATOR = re.compile(r"\s*([,;])\s*")


def parse(text, explanation=True):
    """Consume a citation list; reject malformed suffixes instead of dropping claims."""
    found, remaining = citation(text.strip())
    while remaining.strip():
        if explanation and explained(remaining):
            return found
        entries, remaining = following(remaining, found[-1][0])
        found.extend(entries)
    return found


def explained(text):
    """One balanced outer pair ends the list; text after its close cannot hide citations."""
    if not text[:1].isspace():
        return False
    text = text.strip()
    if not text.startswith("("):
        return False
    depth = 0
    for position, character in enumerate(text):
        depth += (character == "(") - (character == ")")
        if depth == 0:
            return position == len(text) - 1
    return False


def following(text, previous):
    """A separator introduces a complete path citation or another range of that path."""
    separator = SEPARATOR.match(text)
    if separator is None:
        raise invalid()
    remaining = text[separator.end() :]
    shorthand = RANGE.match(remaining) if separator[1] == "," else None
    if shorthand:
        span = (previous, *shorthand.groups())
        return [span], remaining[shorthand.end() :]
    return citation(remaining)


def citation(text):
    """Read one complete citation, including paths with spaces when backtick-quoted."""
    match = CITATION.match(text)
    if match is None:
        raise invalid()
    groups = match.groups()
    span = groups[:3] if groups[0] else groups[3:]
    return [span], text[match.end() :]


def invalid():
    """Validation diagnostics follow the parser version, independently of frozen prompts."""
    return ValueError(prompt_texts.diagnostic("validation.plan_citations"))
