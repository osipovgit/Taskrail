"""Track Markdown code fences without interpreting their contents."""

import re

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def next_fence(current, line):
    """Opening and closing markers must use the same fence character."""
    match = FENCE.match(line)
    if not match:
        return current
    marker = match[1]
    if not current:
        return marker
    closes = marker[0] == current[0]
    closes = closes and len(marker) >= len(current)
    return "" if closes else current
