"""Lossless requirement blocks with positions in their original input field."""

import re

BULLET = re.compile(r"^(?:[-*+] |\d+[.)] )")
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def spans(text):
    """Split paragraphs and top-level list items, never the contents of a code fence."""
    block = Blocks(text)
    for line in text.splitlines(keepends=True):
        yield from block.feed(line)
    yield from trimmed(text, block.start, len(text))


class Blocks:
    """Track field offsets and fence boundaries without interpreting user headings."""

    def __init__(self, text):
        self.text = text
        self.start = 0
        self.offset = 0
        self.fence = ""

    def feed(self, line):
        """A new paragraph or list item ends the preceding block outside code fences."""
        boundary = not line.strip() or BULLET.match(line)
        if not self.fence and boundary:
            yield from trimmed(self.text, self.start, self.offset)
            self.start = self.offset
        self.fence = next_fence(self.fence, line)
        self.offset += len(line)


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


def trimmed(text, start, end):
    """Whitespace does not belong to a block; its interior remains byte-for-byte text."""
    block = text[start:end]
    first = start + len(block) - len(block.lstrip())
    last = end - len(block) + len(block.rstrip())
    if first < last:
        yield first, last
