"""The plan.md template: one line per requirement, with the usual outcome filled in.

A runtime requirement starts as `runtime` and, when the run may change code, a global
constraint starts as `all tasks`; every other line waits for the planner's outcome.
"""

from types import MappingProxyType

from taskrail.core import prompt_texts, task_labels

LINE = "- R{0} → {1}"
PLACEHOLDER = "<outcome>"
RUNTIME = "runtime"
CONSTRAINT = "constraint"
PREFILLED = MappingProxyType({RUNTIME: RUNTIME, CONSTRAINT: "all tasks"})


def text(requirements, read_only=False):
    """The template with the requirement lines of this run."""
    lines = [
        LINE.format(number, prefilled(entry, read_only))
        for number, entry in enumerate(requirements, 1)
    ]
    section_key = "plan.template_answer" if read_only else "plan.template_tasks"
    return prompt_texts.text(
        "plan.template", requirements="\n".join(lines), sections=prompt_texts.text(section_key)
    )


def prefilled(requirement, read_only):
    """The outcome a requirement line starts with; an answer has no tasks to keep it."""
    kind = line_kind(requirement)
    if read_only and kind == CONSTRAINT:
        return PLACEHOLDER
    return PREFILLED.get(kind, PLACEHOLDER)


def line_kind(requirement):
    """runtime, constraint or task: what the plan line of a requirement starts as."""
    return task_labels.kind_of(requirement)
