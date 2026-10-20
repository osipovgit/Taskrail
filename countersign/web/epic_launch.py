"""Start the next task of an epic as a new run with a short brief.

A task run is a new task, not a follow-up: it gets the overall goal, the task list
with outcomes so far and its own step, instead of every earlier conversation turn,
so long epics stay within the model context. It works in the epic's roots, which
are its worktrees when the epic was isolated.
"""

import json

from countersign.application import worktree_isolation
from countersign.core.files import atomic_json
from countersign.web import epic_progress, epic_tasks, history

TITLE_LIMIT = 160
IDENTIFIER = "id"
SCOPE = "\n\nThis is one task of a larger goal that was split into tasks. Do only this task; the other tasks have their own runs."


def start_next(launcher, run):
    """Launch the next ready task and link its run to the epic."""
    with launcher.lock:
        state = json.loads(history.read_artifact(run, "run.json"))
        if state.get(epic_tasks.STATUS) != epic_tasks.READY:
            raise ValueError("Only a task split can start its tasks")
        entries = epic_tasks.tasks(run, state)
        task = epic_progress.next_task(entries)
        if task is None:
            raise ValueError(
                "No task is ready: one is running, failed or waits for its dependencies"
            )
        started = launcher.submit(payload(run, state, entries, task))
        epic = epic_tasks.record(run)
        epic["tasks"][task[IDENTIFIER]] = started[IDENTIFIER]
        atomic_json(run / epic_tasks.EPIC, epic)
        return started


def payload(run, state, entries, task):
    """Task form fields of one task run."""
    draft = history.task_draft(run)
    title = "{0} · {1}: {2}".format(draft["title"], task[IDENTIFIER], task["title"])
    return dict(
        title=title[:TITLE_LIMIT],
        goal=task["goal"] + SCOPE,
        criteria="\n".join(task["checks"]),
        entry_points="\n".join(task["files"]),
        constraints=brief(run.name, draft, entries, task),
        roots=worktree_isolation.root_entries(state["roots"]),
        auto_approve=draft["auto_approve"],
    )


def brief(epic, draft, entries, current):
    """The overall goal, every task with its outcome so far and the original constraints."""
    lines = [f"Overall goal (task split run {epic}):", draft["goal"], "", "Tasks:"]
    for task in entries:
        lines.append(task_line(task, current))
    if draft["constraints"]:
        lines.extend(["", draft["constraints"]])
    return "\n".join(lines)


def task_line(task, current):
    """One task of the brief: current, later, or finished with its outcome."""
    label = "{0}: {1}".format(task[IDENTIFIER], task["title"])
    if task is current:
        return f"- {label} (current task)"
    if task["status"] is None:
        return f"- {label} (later; not part of this run)"
    changed = ", ".join(task["changed_files"]) or "none"
    return f"- {label} ({task['status']}): {task['summary']} Changed files: {changed}"


def advance(launcher):
    """Start the next task of every epic that continues automatically after successes."""
    for run in launcher.base.iterdir():
        if (run / epic_tasks.EPIC).is_file():
            continue_quietly(launcher, run)


def continue_quietly(launcher, run):
    """A failed or busy task waits for the operator; nothing is retried here."""
    try:
        if continues(run):
            start_next(launcher, run)
    except (ValueError, OSError, KeyError):
        return


def continues(run):
    """Auto-continue is on and every started task succeeded."""
    if not epic_tasks.record(run).get("auto_continue"):
        return False
    state = json.loads(history.read_artifact(run, "run.json"))
    return epic_progress.group(epic_tasks.tasks(run, state), True) == "running"
