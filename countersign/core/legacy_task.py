"""Conservative Markdown import: unknown user sections and code blocks remain obligations."""

import re

from countersign.core import input_blocks

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
STRUCTURE = frozenset(("goal", "acceptance criteria", "additional constraints"))
CONTEXT = frozenset(("current behavior", "known entry points"))


def entries(text):
    """Remove only standard navigation/context, never a section merely named like policy."""
    reader = Reader()
    lines = text.splitlines(keepends=True)
    rendered = "".join(map(reader.line, lines))
    return blocks(rendered)


def blocks(rendered):
    """Standalone headings are navigation; their accompanying content is retained."""
    for start, end in input_blocks.spans(rendered):
        block = rendered[start:end]
        if not HEADING.fullmatch(block):
            yield block


class Reader:
    """A code fence prevents its headings from changing the enclosing input field."""

    def __init__(self):
        self.fence = ""
        self.contextual = False

    def line(self, line):
        """Keep every non-context source line verbatim, including code fence contents."""
        previous = self.fence
        self.fence = input_blocks.next_fence(self.fence, line)
        if previous or self.fence:
            return "\n" if self.contextual else line
        heading = HEADING.fullmatch(line.rstrip("\r\n"))
        if heading and len(heading[1]) <= 2:
            self.contextual = heading[2].casefold() in CONTEXT
        return "\n" if self.contextual or structural(heading) else line


def structural(heading):
    """A standard heading is navigation, while an unknown section's text is retained."""
    if heading is None:
        return False
    title = len(heading[1]) == 1
    return title or heading[2].casefold() in STRUCTURE
