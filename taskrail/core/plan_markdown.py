"""Read the plan a planner writes as Markdown, keeping the line number of every part.

The format is forgiving: key case, emphasis, backticks, bullet styles and a few key
synonyms are accepted. What cannot be read is reported with its line number, so the
session can fix that line instead of writing the plan again.
"""

import re

from taskrail.core.finding_decisions import RESPONSES
from taskrail.core.plan_checks import SELECTIONS
from taskrail.core.plan_keys import CONTINUED, ENTRY_LINES, EXTRA, LISTS, NOTES, key_line, stored
from taskrail.core.prompt_texts import text

BULLET = re.compile(r"^(?:[-*+]|\d+[.)])\s+(.*)$")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*#*$")
# Separators accept hyphens, en dashes (U+2013) and em dashes (U+2014).
TASK = re.compile(r"^(?:T|Task\s*)(\d+)\s*[:.)\-\u2013\u2014]\s*(.+)$", re.IGNORECASE)
REQUIREMENT = re.compile(r"^R(\d+)\s*(?:→|->|=>|:|\u2014|\u2013)\s*(.*)$", re.IGNORECASE)
TOP = "top"
TASKS = "tasks"
AFTER = "after"
ANSWER = "answer"
REQUIREMENTS = "requirements"
PROBLEMS = "problems"
LINE = "line"
FIELDS = "fields"
# "## T2: After the change" is the after-change section written as a task.
AFTER_TITLE = re.compile(r"after the change\b", re.IGNORECASE)
NAME_PREVIEW = 40


def read_plan_text(text):
    """The plan's parts: top keys, requirement lines, tasks and after-change checks."""
    reader = Reader()
    for number, line in enumerate(text.splitlines(), 1):
        reader.feed(number, line)
    return reader.document


class Reader:
    """A line-by-line state machine over the sections of the plan."""

    def __init__(self):
        """Start in the top section, before any heading."""
        self.document = {TOP: {}, REQUIREMENTS: [], TASKS: [], AFTER: [], PROBLEMS: []}
        self.document[ANSWER] = []
        self.document[SELECTIONS] = []
        self.document[RESPONSES] = []
        self.section = TOP
        self.key = None
        self.comment = False

    def feed(self, number, raw):
        """Route one line to its section; an answer keeps its lines as written."""
        comment_start = self.section == TOP and raw.lstrip().startswith("<!--")
        if self.comment or comment_start:
            self.comment = "-->" not in raw
            return
        if self.section == ANSWER and raw.strip().casefold() != "## finding responses":
            self.document[ANSWER].append(raw)
            return
        line = raw.strip()
        heading = HEADING.match(line)
        if heading:
            self.open(number, heading.group(1))
        elif line:
            self.route(number, line)

    def open(self, number, title):
        """A task heading starts a task; known titles start their sections."""
        self.key = None
        task = TASK.match(title)
        if task and AFTER_TITLE.match(task.group(2)):
            self.section = AFTER
        elif task:
            self.document[TASKS].append(task_entry(task, number))
            self.section = TASKS
        else:
            self.section = section_of(title, self.section)
            if self.section == "invalid":
                self.document[PROBLEMS].append(f"line {number}: unknown section '{title}'")

    def route(self, number, line):
        """A requirement line, an after-change check or a field."""
        if self.section == REQUIREMENTS:
            entry = requirement_entry(number, line)
            target = self.document[REQUIREMENTS] if entry else self.document[PROBLEMS]
            target.append(entry or f"line {number}: expected 'R<n> → <outcome>'")
        elif self.section in {AFTER, SELECTIONS, RESPONSES}:
            self.document[self.section].append((unbullet(line), number))
        elif self.section in {TOP, TASKS}:
            self.field(number, line)

    def field(self, number, line):
        """A `Key: value` line, or a bullet or continuation of the key above."""
        key, text = key_line(unbullet(line))
        if key is None:
            self.extend(number, line)
            return
        allowed = {"decision", "summary"} if self.section == TOP else CONTINUED
        if key not in allowed:
            self.document[PROBLEMS].append(f"line {number}: unexpected {key} field")
            return
        if key in self.target():
            self.document[PROBLEMS].append(f"line {number}: duplicate {key} field")
            return
        self.target()[key] = stored(key, text, number)
        if key in LISTS:
            entry_lines = self.target().setdefault(ENTRY_LINES, {})
            entry_lines[key] = [number] if text else []
        self.key = key if key in CONTINUED else None

    def extend(self, number, line):
        """A bullet of a list key, or more notes.

        Inside a task any other line, such as an invented `Facts:` key or prose, is kept
        in the task's Notes; weak models add such lines, and rejecting the whole plan for
        them only costs a correction. At the top it names what is not a plan key.
        """
        if self.key in LISTS and BULLET.match(line):
            bullets = self.target()[self.key][0]
            bullets.append(unbullet(line))
            self.target()[ENTRY_LINES][self.key].append(number)
        elif self.key == NOTES:
            note, start = self.target()[NOTES]
            self.target()[NOTES] = (f"{note} {line}".strip(), start)
        elif self.section == TASKS:
            self.target().setdefault(EXTRA, []).append(line)
        else:
            name = line.partition(":")[0][:NAME_PREVIEW]
            message = text("validation.unknown_key", line=number, name=name)
            self.document[PROBLEMS].append(message)

    def target(self):
        """The fields of the current task, or the top-level keys."""
        if self.section == TOP:
            return self.document[TOP]
        return self.document[TASKS][-1][FIELDS]


def task_entry(found, number):
    """A new task from its heading."""
    identifier = f"T{found.group(1)}"
    entry = dict(id=identifier, title=found.group(2).strip())
    return dict(entry, line=number, fields={})


def section_of(title, current):
    """The section a non-task heading opens; text before any heading is the top."""
    sections = {
        "requirements": REQUIREMENTS,
        "after the change": AFTER,
        "checks": AFTER,
        "answer": ANSWER,
        "design": ANSWER,
        "finding responses": RESPONSES,
        "check selections": SELECTIONS,
    }
    name = title.casefold()
    fallback = TOP if current == TOP and name == "plan" else "invalid"
    return sections.get(name, fallback)


def requirement_entry(number, line):
    """One `R<n> → outcome` line as an entry, or None."""
    found = REQUIREMENT.match(unbullet(line))
    if not found:
        return None
    label = f"R{found.group(1)}"
    return dict(label=label, text=found.group(2).strip(), line=number)


def unbullet(line):
    """The text of a bullet line, or the line itself."""
    found = BULLET.match(line)
    return found.group(1).strip() if found else line
