"""What a task run of a split receives: its requirements and a compact brief.

Its requirements retain the parent's exact text and separate ownership scope,
followed by the task's own results. The brief includes the complete current
contract and a bounded prerequisite index; the full parent remains available
for specific lookups when needed.
"""

from taskrail.core import task_graph, task_lineage

INDEX_BUDGET = 6000
BRIEF_BUDGET = 14000
CONTRACT_BUDGET = 8000
IDENTIFIER = "id"
REQUIREMENTS = "requirements"
SCOPE = "This run is one task of a larger goal that was split into tasks. Do only the current task below; every other task has its own run. Finished tasks are already in the source."


def requirements(state, task):
    """Literal owned parent requirements, separate scopes and the task's own results."""
    parent = state.get(REQUIREMENTS, [])
    texts = {entry[IDENTIFIER]: entry["text"] for entry in parent}
    scopes = {entry[IDENTIFIER]: entry["scope"] for entry in task["scopes"]}
    owned = filter(texts.__contains__, task[REQUIREMENTS])
    lines = [part(texts[name], scopes.get(name)) for name in owned]
    lines.extend(task["done_when"])
    if not lines:
        return "\n".join(f"- {line}" for line in task["checks"])
    return "\n\n".join(lines)


def assigned_requirements(state, task):
    """Pass parent IDs and literal text through the child without Markdown re-parsing."""
    step = dict(task, criteria=task[REQUIREMENTS])
    return task_lineage.for_step(state.get(REQUIREMENTS, []), step)


def part(text, scope):
    """Preserve the requirement exactly; scope is separate server-owned metadata."""
    return f"{text}\nOnly this assigned part: {scope}" if scope else text


def brief(run, draft, entries, current):
    """A bounded index; the immutable artifact holds every full contract and outcome."""
    lines = [SCOPE, "", f"Parent run: {run.name}. Current task: {current['id']}."]
    lines.append(
        "This run carries its complete assigned requirements, global constraints and current "
        "contract. The sealed parent-task.md is reference data: consult only a specific missing "
        "parent section or prerequisite, within the read budget; never read the whole snapshot. "
        "If an essential dependency cannot be resolved within the budget, report the exact gap."
    )
    lines.extend(["", current_contract(current), "", "Prerequisites:"])
    needed = task_graph.ancestors(entries, current[IDENTIFIER])
    remaining = min(INDEX_BUDGET, BRIEF_BUDGET - len("\n".join(lines)))
    for task in entries:
        if task[IDENTIFIER] in needed:
            line = task_line(task, current)
            if len(line) <= remaining:
                lines.append(line)
                remaining -= len(line)
    lines.append("Other tasks are outside this run's scope; their full index is in parent-task.md.")
    return "\n".join(lines)


def current_contract(task):
    """Checks and notes are essential input and cannot silently become a truncated pointer."""
    checks = "\n".join(task["checks"])
    notes = task.get("notes", "")
    text = "Current task:\n{}\nAction: {}\nChecks:\n{}\nNotes:\n{}".format(
        task_line(task, task), task["goal"], checks, notes
    )
    if len(text) > CONTRACT_BUDGET:
        raise ValueError(
            "Child contract exceeds its input budget; narrow the parent task before launch"
        )
    return text


def task_line(task, current):
    """One task: current, later by title only, or finished with its outcome."""
    label = "{}: {}".format(task[IDENTIFIER], task["title"])
    if task is current:
        return f"- {label} (current task)"
    if task["status"] is None:
        return f"- {label} (later; not part of this run)"
    state = "marked done" if task["done"] else task["status"]
    changed = ", ".join(task["changed_files"]) or "none"
    return f"- {label} ({state}): {task['summary']} Changed files: {changed}"
