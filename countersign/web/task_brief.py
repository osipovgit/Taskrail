"""What a task run of a split receives: its requirements and a compact brief.

Its requirements are the parent requirements its plan task owns, without their
section headings and with the scope of a shared one, followed by the task's own
results. The brief tells it what earlier tasks delivered and names later tasks by
title only, so a long split stays within the model context.
"""

import re

HEADING = re.compile(r"(?m)^#+\s.*$")
BULLET = re.compile(r"^[-*+]\s+")
CONTEXT_LIMIT = 600
SCOPE = "This run is one task of a larger goal that was split into tasks. Do only the current task below; every other task has its own run. Finished tasks are already in the source."


def requirements(state, task):
    """One bullet per owned parent requirement, then one per result of the task."""
    parent = state.get("requirements", [])
    texts = {entry["id"]: entry["text"] for entry in parent}
    scopes = {entry["id"]: entry["scope"] for entry in task["scopes"]}
    owned = filter(texts.__contains__, task["requirements"])
    lines = [part(texts[name], scopes.get(name)) for name in owned]
    lines.extend(task["done_when"])
    return "\n".join(f"- {line}" for line in lines or task["checks"])


def part(text, scope):
    """A parent requirement on one line, limited to its scope when it is shared."""
    flat = " ".join(HEADING.sub("", text).split())
    plain = BULLET.sub("", flat)
    return f"{plain} (only this part: {scope})" if scope else plain


def brief(run, draft, entries, current):
    """The scope rule, the overall goal, the other tasks and this task's checks."""
    lines = [SCOPE, "", f"Overall goal (task split run {run.name}):", clipped(draft["goal"])]
    lines.extend(["Overall acceptance criteria:", clipped(draft["criteria"])])
    parent = run / "00-input/task.md"
    listed = [task_line(task, current) for task in entries]
    lines.extend([f"The complete parent task is {parent}.", "", "Tasks:", *listed])
    lines.extend(
        ["", "Checks to run for this task:", *(f"- {check}" for check in current["checks"])]
    )
    if current["notes"]:
        lines.extend(["", "Planner notes: {0}".format(current["notes"])])
    return "\n".join(lines)


def task_line(task, current):
    """One task: current, later by title only, or finished with its outcome."""
    label = "{0}: {1}".format(task["id"], task["title"])
    if task is current:
        return f"- {label} (current task)"
    if task["status"] is None:
        return f"- {label} (later; not part of this run)"
    state = "marked done" if task["done"] else task["status"]
    changed = ", ".join(task["changed_files"]) or "none"
    return f"- {label} ({state}): {task['summary']} Changed files: {changed}"


def clipped(text):
    """Context text bounded to CONTEXT_LIMIT characters."""
    if len(text) <= CONTEXT_LIMIT:
        return text
    return "{0}…".format(text[:CONTEXT_LIMIT].rstrip())
