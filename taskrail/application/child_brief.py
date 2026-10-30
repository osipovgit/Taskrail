"""What a task of a split is told about its place in the split.

The brief names the task and the parent run and lists the earlier tasks, which are
already applied to the source, with their latest run's outcome and changed files, and
the later tasks, whose work is not to be done here. It comes from authenticated run
records and the reviewed plan, never from a sibling's own report.
"""

from taskrail.application import reviewed_artifacts
from taskrail.core import delivery_record, prompt_texts, task_graph

LISTED_FILES = 20
SUMMARY_LIMIT = 300
IDENTIFIER = "id"


def heading(step):
    """`T2: Title` of a task."""
    title = step.get("title") or step["action"]
    return f"{step[IDENTIFIER]}: {title}"


def context(parent, step):
    """Which task this is, what the earlier tasks changed and what the later ones own."""
    run = parent["run"].name
    lines = [prompt_texts.text("child.header", task=step[IDENTIFIER], parent=run)]
    earlier, later = around(parent["plan"]["steps"], step[IDENTIFIER])
    if earlier:
        lines.append(prompt_texts.text("child.earlier"))
        lines.extend(earlier_task(parent, entry) for entry in earlier)
    else:
        lines.append(prompt_texts.text("child.none"))
    if later:
        lines.append(prompt_texts.text("child.later"))
        lines.extend(map(later_task, later))
    return "\n".join(lines)


def around(steps, task):
    """The plan steps that run before a task and those that run after it."""
    order = task_graph.order(steps)
    position = order.index(task)
    before = set(order[:position])
    after = set(order[position + 1 :])
    earlier = [entry for entry in steps if entry[IDENTIFIER] in before]
    return earlier, [entry for entry in steps if entry[IDENTIFIER] in after]


def earlier_task(parent, step):
    """One earlier task: its latest run's outcome and the files it changed."""
    attempts = delivery_record.attempts(parent["epic"], step[IDENTIFIER])
    if not attempts:
        return f"- {heading(step)}"
    run = reviewed_artifacts.run_path(parent["run"].parent, attempts[-1])
    state = reviewed_artifacts.document(run, "run.json")
    summary = state.get("summary", "")[:SUMMARY_LIMIT]
    changed = listed(state.get("changed_files", []))
    return "- {} ({}): {} Changed files: {}".format(
        heading(step), state["status"], summary, changed
    )


def later_task(step):
    """A later task's behavior boundary, including work in a shared file."""
    files = listed(step["files"])
    outcomes = "; ".join(step.get("done_when", [])) or step["action"]
    return prompt_texts.text("child.excluded", task=heading(step), outcomes=outcomes, files=files)


def listed(files):
    """At most LISTED_FILES names and how many more there are."""
    shown = ", ".join(files[:LISTED_FILES]) or "none"
    more = len(files) - LISTED_FILES
    return f"{shown} and {more} more" if more > 0 else shown
