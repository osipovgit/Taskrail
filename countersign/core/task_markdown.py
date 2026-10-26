"""Read a Markdown task file into the typed fields the browser form submits.

The file holds an optional `countersign-task` header, an optional `# title` and either
plain text, which is the Goal, or known `##` sections. With sections, any other heading
or text outside a section is an error with its line number. Headings in code fences
are text. A server-written conversation history ends the task; it is reference data.
"""

import re
from types import MappingProxyType

from countersign.core import input_blocks, task_spec
from countersign.core.input_header import HEADER
from countersign.core.requirements import HISTORY

HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
BULLET = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
VERIFICATION = "verification"
TITLE = "title"
GOAL = "goal"
SECTIONS = MappingProxyType(
    {
        GOAL: GOAL,
        "acceptance criteria": "criteria",
        "current behavior": "current_behavior",
        "known entry points": "entry_points",
        "constraints": "constraints",
        "additional constraints": "constraints",
        VERIFICATION: VERIFICATION,
    }
)
KNOWN = "Goal, Acceptance criteria, Current behavior, Known entry points, Constraints, Verification"
OUTSIDE = "line {0}: text outside a section; known sections: {1}"


def typed_input(text, meta):
    """Header metadata with typed fields; a Markdown task file's sections become them.

    Its `## Verification` lines join the header's deferred runtime checks.
    """
    if task_spec.TASK_SPEC in meta:
        return meta
    fields, deferred = read(text)
    deferred = [*meta.get(VERIFICATION, []), *deferred]
    spec = task_spec.from_fields(fields)
    return dict(meta, task_spec=spec, verification=list(dict.fromkeys(deferred)))


def read(text):
    """({field: text}, deferred runtime checks) of a task file."""
    reader = Reader()
    for number, line in numbered(text.split(HISTORY, 1)[0]):
        reader.line(number, line)
    fields = reader.fields()
    if not fields.get(GOAL):
        raise ValueError("A task file needs a Goal: plain text or a ## Goal section")
    return fields, checks(fields.pop(VERIFICATION, ""))


def numbered(text):
    """(line number, line with its ending) after the header, which nothing may precede."""
    header = HEADER.search(text)
    if header is None:
        return enumerate(text.splitlines(keepends=True), 1)
    if text[: header.start()].strip():
        raise ValueError("line 1: text before the countersign-task header")
    first = text.count("\n", 0, header.end()) + 1
    return enumerate(text[header.end() :].splitlines(keepends=True), first)


def checks(section):
    """One deferred runtime check per line, without its list marker."""
    lines = (BULLET.sub("", line).strip() for line in section.splitlines())
    return [line for line in lines if line]


class Reader:
    """Assign every line after the header to the title, a known section or the Goal."""

    def __init__(self):
        """Nothing is read yet."""
        self.fence = ""
        self.current = None
        self.lines = {}
        self.loose = []

    def line(self, number, line):
        """A heading opens a section; other lines, with their endings, belong to it."""
        fenced = self.fence
        self.fence = input_blocks.next_fence(fenced, line)
        heading = None if fenced else HEADING.fullmatch(line.rstrip("\r\n"))
        if heading is not None and len(heading[1]) <= 2:
            self.heading(number, heading)
        elif self.current is None:
            self.loose.append((number, line))
        else:
            self.lines[self.current].append(line)

    def heading(self, number, heading):
        """The single `#` title, or a known `##` section that appears once."""
        title = heading[2]
        if len(heading[1]) == 1:
            self.open(number, TITLE, "# title")
            self.lines[TITLE].append(title)
            self.current = None
            return
        name = SECTIONS.get(title.casefold())
        if name is None:
            raise ValueError(f"line {number}: unknown section '{title}'; known sections: {KNOWN}")
        self.open(number, name, f"section '{title}'")

    def open(self, number, name, label):
        """Start a field that has not appeared before."""
        if name in self.lines:
            raise ValueError(f"line {number}: repeated {label}")
        self.lines[name] = []
        self.current = name

    def fields(self):
        """Section texts; without sections, the text outside the title is the Goal."""
        if set(self.lines) - {TITLE}:
            self.check_loose()
        else:
            self.lines[GOAL] = [line for _, line in self.loose]
        return {name: trimmed(lines) for name, lines in self.lines.items()}

    def check_loose(self):
        """With sections, every line outside them is blank."""
        for number, line in self.loose:
            if line.strip():
                raise ValueError(OUTSIDE.format(number, KNOWN))


def trimmed(lines):
    """The text without blank lines around it; inner lines and their endings stay verbatim."""
    filled = [index for index, line in enumerate(lines) if line.strip()]
    if not filled:
        return ""
    kept = lines[filled[0] : filled[-1] + 1]
    return "".join(kept).rstrip("\r\n")
