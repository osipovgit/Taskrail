"""The plan file a planner writes: its template, its instructions and its result.

plan.md lives in the run directory, so an interrupted or overflowing session leaves
it behind and the next attempt continues it. The planner may write only this file;
the server reads it, derives the plan result and names every problem by line.
"""

from taskrail.application import plan_template, project_map
from taskrail.core import plan_document, prompt_texts, protected_paths
from taskrail.infrastructure.agent_sync import atomic_write

NAME = "plan.md"


def path(run):
    """Where the plan of a run is written."""
    return run / NAME


def prepare(run, requirements, read_only=False):
    """Write the template once; an existing plan is continued, never replaced."""
    target = path(run)
    if not target.exists():
        atomic_write(target, plan_template.text(requirements, read_only).encode())
    return target


def grant(access, run, requirements):
    """Let the planner's profile read and write plan.md, and only that file."""
    target = prepare(run, requirements)
    access["writable"] = [*access["writable"], target]
    access["readable"].append(target)


def instructions(run, roots, requirements, protected=protected_paths.DEFAULT_PATTERNS):
    """The format, the project map and the requirement labels in the planner's request.

    The map is written on the first request of the run.
    """
    project = project_map.prepare(run, roots, requirements, protected)
    return prompt_texts.text("plan.format", path=path(run), map=project)


def read_plan(run, requirements, roots):
    """The plan result of the written file; ValueError names its problems."""
    target = path(run)
    written = target.read_text(encoding="utf-8") if target.is_file() else ""
    return plan_document.payload(written, requirements, roots)


def labelled(message, requirements):
    """A validation message with requirement IDs replaced by their plan labels."""
    for number, entry in enumerate(requirements, 1):
        message = message.replace(entry["id"], f"R{number}")
    return message


def labelled_requirements(requirements):
    """Each requirement's label, kind and text, without server identities."""
    return {
        f"R{number}": dict(kind=entry["kind"], text=entry["text"])
        for number, entry in enumerate(requirements, 1)
    }
