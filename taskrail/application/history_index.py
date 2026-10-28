"""history.md: an index of the earlier turns of a follow-up, then each turn.

A model reads the index first and then only the sections it needs, because the whole
history can be larger than its context.
"""

import json

from taskrail.core import prompt_texts

LINE_LIMIT = 800
CHUNK_SIZE = 500
GOAL_PREVIEW = 120
SECTIONS = (
    ("goal", "Goal"),
    ("summary", "Summary"),
    ("task", "Task"),
    ("conclusions", "Conclusions"),
    ("diff", "Diff"),
)
ENTRY = "{0}. Run {1}: {2}. Goal: {3}"


class HistoryFile:
    """The lines of history.md, built turn by turn after an index of known length."""

    def __init__(self, turns):
        """One index entry and one block per turn, oldest first."""
        self.entries = prompt_texts.text("history.header").splitlines()
        self.index_end = len(self.entries) + len(turns)
        self.body = []
        for number, turn in enumerate(turns, 1):
            self.add(number, turn)

    def lines(self):
        """The whole file, ending with a newline."""
        return [*self.entries, *self.body, ""]

    def add(self, number, turn):
        """A turn's block, and its index entry with the line range of each section."""
        start = self.line() + 2
        heading = "## Run {}".format(turn.get("run", ""))
        self.body.extend(["", heading])
        ranges = []
        for key, title in SECTIONS:
            ranges.append(self.section(title, turn.get(key)))
        self.entries.append(self.entry(number, turn, start, ranges))

    def entry(self, number, turn, start, ranges):
        """Run, the line range of the turn and of each section, and the goal's first line."""
        where = "lines {}-{} ({})".format(start, self.line(), ", ".join(ranges))
        return ENTRY.format(number, turn.get("run", ""), where, preview(turn))

    def section(self, title, field):
        """Append one section; returns its name and line range for the index."""
        first = self.line() + 2
        self.body.extend(section_lines(title, field))
        return f"{title.lower()} {first}-{self.line()}"

    def line(self):
        """The number of the last line written so far."""
        return self.index_end + len(self.body)


def section_lines(title, field):
    """A blank line, a heading, then the text split into lines a read returns whole."""
    lines = ["", f"### {title}"]
    for line in (text_of(field).rstrip("\n") or "(none)").split("\n"):
        lines.extend(bounded(line))
    return lines


def bounded(line):
    """Long lines in 500-character pieces, like long strings in the prompt context."""
    if len(line) <= LINE_LIMIT:
        return [line]
    offsets = range(0, len(line), CHUNK_SIZE)
    return [line[offset : offset + CHUNK_SIZE] for offset in offsets]


def preview(turn):
    """The first line of the goal, shortened."""
    goal = text_of(turn.get("goal")).strip()
    return goal.split("\n", 1)[0][:GOAL_PREVIEW]


def text_of(field):
    """Strings as they are, anything else as indented JSON."""
    if field is None:
        return ""
    if isinstance(field, str):
        return field
    return json.dumps(field, ensure_ascii=False, indent=2)
