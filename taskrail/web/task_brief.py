"""What a task run of a split receives: its requirements and a compact brief.

Its requirements retain the parent's exact text and separate ownership scope,
followed by the task's own results. The brief includes the complete current
contract and a bounded prerequisite index; the full parent remains available
for specific lookups when needed.
"""

from taskrail.core import prompt_texts, task_graph, task_lineage

INDEX_BUDGET = 6000
BRIEF_BUDGET = 14000
CONTRACT_BUDGET = 8000
IDENTIFIER = "id"
REQUIREMENTS = "requirements"


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
    return prompt_texts.current("child.part", requirement=text, scope=scope) if scope else text


def brief(run, draft, entries, current):
    """A bounded index; the immutable artifact holds every full contract and outcome."""
    lines = [prompt_texts.current("child.scope")]
    lines.extend(
        [prompt_texts.current("child.position", parent=run.name, task=current[IDENTIFIER])]
    )
    lines.append(prompt_texts.current("child.reference"))
    lines.extend(["", current_contract(current), "", prompt_texts.current("child.prerequisites")])
    needed = task_graph.ancestors(entries, current[IDENTIFIER])
    remaining = min(INDEX_BUDGET, BRIEF_BUDGET - len("\n".join(lines)))
    for task in entries:
        if task[IDENTIFIER] in needed:
            line = task_line(task, current)
            if len(line) <= remaining:
                lines.append(line)
                remaining -= len(line)
    lines.append(prompt_texts.current("child.outside"))
    return "\n".join(lines)


def current_contract(task):
    """Checks and notes are essential input and cannot silently become a truncated pointer."""
    checks = "\n".join(task["checks"])
    notes = task.get("notes", "")
    text = prompt_texts.current(
        "child.contract",
        task=task_line(task, task),
        action=task["goal"],
        checks=checks,
        required="\n".join(task.get("required_checks", [])),
        excluded="\n".join(task.get("not_todo", [])),
        notes=notes,
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
