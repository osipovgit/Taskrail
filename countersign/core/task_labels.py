"""Requirement labels in the task a model reads: [R1], [R2 runtime], [R3 constraint].

A typed task is rendered field by field, and each label is placed at its requirement's
own field and offset, so it never lands in the title or in another field that repeats
the same words. Labels are numbered in the server's requirement order.
"""

from types import MappingProxyType

HEADINGS = MappingProxyType(
    {
        "goal": "Goal",
        "current_behavior": "Current behavior",
        "criteria": "Acceptance criteria",
        "entry_points": "Known entry points",
        "constraints": "Constraints",
    }
)
CONSTRAINTS = "constraints"
SEARCHED = ("criteria", "goal")
SOURCE = "source"
FIELD = "field"
TEXT = "text"
RUNTIME = "runtime"
TASK = "task"


def label(number, entry):
    """The label of the requirement numbered `number`."""
    kind = kind_of(entry)
    suffix = "" if kind == TASK else f" {kind}"
    return f"[R{number}{suffix}]"


def kind_of(entry):
    """runtime, constraint (an obligation of every task) or task."""
    if entry["kind"] == RUNTIME:
        return RUNTIME
    if (entry.get(SOURCE) or {}).get(FIELD) == CONSTRAINTS:
        return "constraint"
    return TASK


class Labels:
    """Labels collected per field offset, and the requirements no field holds."""

    def __init__(self, fields):
        """Nothing is placed yet."""
        self.fields = fields
        self.marks = {name: {} for name in fields}
        self.unplaced = {RUNTIME: [], TASK: []}

    def add(self, number, entry):
        """Place one requirement's label before its block, or keep it apart."""
        tag = label(number, entry)
        place = self.place(entry)
        if place is None:
            group = RUNTIME if entry["kind"] == RUNTIME else TASK
            self.unplaced[group].append(f"{tag}\n{entry[TEXT]}")
            return
        field, offset = place
        self.marks[field].setdefault(offset, []).append(tag)

    def place(self, entry):
        """(field, offset) of a requirement block, or None when no field holds its text."""
        source = entry.get(SOURCE) or {}
        if self.at_source(entry[TEXT], source):
            return source[FIELD], source["start"]
        candidates = (CONSTRAINTS,) if source.get(FIELD) == CONSTRAINTS else SEARCHED
        for name in candidates:
            offset = self.fields.get(name, "").find(entry[TEXT])
            if offset >= 0:
                return name, offset
        return None

    def at_source(self, text, source):
        """The requirement's own field still holds its text at the recorded offset."""
        field = self.fields.get(source.get(FIELD))
        start = source.get("start")
        if field is None or start is None:
            return False
        return field[start : start + len(text)] == text

    def sections(self):
        """The title when it adds something, then the labelled fields under headings."""
        shown = self.title()
        for name, heading in HEADINGS.items():
            if self.fields.get(name):
                marked = labelled(self.fields[name], self.marks[name])
                shown.append(f"## {heading}\n{marked}")
        return shown

    def title(self):
        """The title section, unless the goal starts with the title anyway."""
        title = self.fields.get("title", "")
        if not title or self.fields.get("goal", "").startswith(title):
            return []
        return [f"## Title\n{title}"]

    def extras(self):
        """Sections for labelled requirements that no field holds, if there are any."""
        groups = (("Other requirements", TASK), ("Runtime checks", RUNTIME))
        return [
            "## {}\n{}".format(heading, "\n\n".join(self.unplaced[group]))
            for heading, group in groups
            if self.unplaced[group]
        ]


def typed(spec, entries=()):
    """The typed fields under readable headings, each requirement labelled in place."""
    fields = {field["name"]: field[TEXT] for field in spec["fields"]}
    labels = Labels(fields)
    for number, entry in enumerate(entries, 1):
        labels.add(number, entry)
    sections = labels.sections()
    if spec.get("context"):
        sections.append("## Task split context\n{}".format(spec["context"]))
    return "\n\n".join([*sections, *labels.extras()])


def labelled(text, marks):
    """Insert labels before their blocks, from the end so earlier offsets stay valid."""
    for offset in sorted(marks, reverse=True):
        labels = "\n".join(marks[offset])
        head, tail = text[:offset], text[offset:]
        text = f"{head}{labels}\n{tail}"
    return text
