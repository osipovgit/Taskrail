"""Canonical user inputs, independent of Markdown headings and runtime policy."""

from countersign.core import input_rendering, requirements
from countersign.core.input_blocks import spans
from countersign.core.task_lineage import checked_assignments, distinct

VERSION = 1
FIELDS = ("title", "goal", "criteria", "current_behavior", "entry_points", "constraints")
OBLIGATIONS = frozenset(("goal", "criteria", "constraints"))
ASSIGNED = "assigned_requirements"
IDENTIFIER = "id"
NAME = "name"
TEXT = "text"
FIELD_LIST = "fields"
BODY = "body"
CONTEXT = "context"
SPEC_KEYS = frozenset(("version", FIELD_LIST, ASSIGNED, BODY, CONTEXT))


def from_fields(form):
    """Use the form's existing boundaries instead of parsing its rendered Markdown."""
    fields = [{NAME: name, TEXT: form.get(name, "")} for name in FIELDS]
    return {"version": VERSION, FIELD_LIST: fields}


def resolve(text, meta):
    """Validate a typed input or import legacy Markdown without changing its source."""
    supplied = meta.get("task_spec")
    if supplied is None:
        entries = requirements.task_requirements(text, meta.get("verification", []))
        return dict(version=VERSION, raw_input=text, fields=[], requirements=entries)
    spec = checked(supplied)
    input_rendering.verify(spec, text)
    entries = entries_for(spec)
    deferred = meta.get("verification", [])
    entries.extend(requirements.requirement(check, "runtime") for check in deferred)
    return dict(spec, raw_input=text, requirements=distinct(entries))


def checked(spec):
    """Reject unknown typed input fields, duplicates and untyped field values."""
    if not isinstance(spec, dict) or set(spec) - SPEC_KEYS:
        raise ValueError("Invalid task_spec fields")
    supported = spec.get("version") == VERSION
    supported = supported and isinstance(spec.get(CONTEXT, ""), str)
    if not supported or not isinstance(spec.get(FIELD_LIST), list):
        raise ValueError("Unsupported task_spec version or fields")
    fields = spec[FIELD_LIST]
    names = [checked_field(field) for field in fields]
    if len(set(names)) != len(names):
        raise ValueError("Duplicate task_spec field")
    assigned = checked_assignments(spec.get(ASSIGNED, []))
    validated = dict(version=VERSION, fields=fields, assigned_requirements=assigned)
    if spec.get(BODY) is not None:
        validated[BODY] = spec[BODY]
    if spec.get(CONTEXT):
        validated[CONTEXT] = spec[CONTEXT]
    return validated


def checked_field(field):
    """A field keeps its text literally, including headings and code fences."""
    if not isinstance(field, dict) or set(field) != {NAME, TEXT}:
        raise ValueError("Invalid task_spec field")
    if field[NAME] not in FIELDS or not isinstance(field[TEXT], str):
        raise ValueError("Invalid task_spec name or text")
    return field[NAME]


def entries_for(spec):
    """A child keeps assigned identities; ordinary tasks derive obligations from fields."""
    assigned = spec.get(ASSIGNED, [])
    entries = list(assigned)
    for field in spec[FIELD_LIST]:
        obligated = field[NAME] in OBLIGATIONS
        if obligated and (not assigned or field[NAME] == "constraints"):
            entries.extend(field_entries(field))
    return distinct(entries)


def field_entries(field):
    """Bind every requirement to a precise character range in its original field."""
    text = field[TEXT]
    for start, end in spans(text):
        record = requirements.requirement(text[start:end], "task")
        source = dict(field=field[NAME], start=start, end=end)
        yield dict(record, source=source)


def prompt_text(spec):
    """Render user fields only; engine policy and typed transport stay outside the task."""
    if not spec[FIELD_LIST]:
        return requirements.HEADER.sub("", spec["raw_input"]).strip()
    populated = [field for field in spec[FIELD_LIST] if field[TEXT]]
    sections = ["## {name}\n{text}".format(**field) for field in populated]
    if spec.get(CONTEXT):
        sections.append("## Task split context\n{0}".format(spec[CONTEXT]))
    return "\n\n".join(sections)
