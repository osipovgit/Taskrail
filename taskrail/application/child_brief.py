"""What a task of a split is told about its place in the split.

The brief names the task and the parent run and lists the earlier tasks, which are
already applied to the source, with their latest run's outcome and changed files. It
comes from authenticated run records, never from a sibling's own report.
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
    """Which task this is and what the earlier tasks, already applied, changed."""
    run = parent["run"].name
    header = prompt_texts.text("child.header", task=step[IDENTIFIER], parent=run)
    earlier = earlier_steps(parent["plan"]["steps"], step[IDENTIFIER])
    if not earlier:
        return "{}\n{}".format(header, prompt_texts.text("child.none"))
    lines = [earlier_task(parent, entry) for entry in earlier]
    return "\n".join([header, prompt_texts.text("child.earlier"), *lines])


def earlier_steps(steps, task):
    """The plan steps that run before a task."""
    order = task_graph.order(steps)
    names = set(order[: order.index(task)])
    return [entry for entry in steps if entry[IDENTIFIER] in names]


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


def listed(files):
    """At most LISTED_FILES names and how many more there are."""
    shown = ", ".join(files[:LISTED_FILES]) or "none"
    more = len(files) - LISTED_FILES
    return f"{shown} and {more} more" if more > 0 else shown
