"""Start the next task of an epic as a new run with a short brief.

A task run is a new task, not a follow-up: it gets the overall goal, the task list
with outcomes so far and its own step, instead of every earlier conversation turn,
so long epics stay within the model context. It works in the epic's roots, which
are its worktrees when the epic was isolated.
"""

import json
from functools import partial

from countersign.application import worktree_isolation
from countersign.interactions import approval_policy
from countersign.web import epic_progress, epic_record, epic_tasks, history

TITLE_LIMIT = 160
IDENTIFIER = "id"
SCOPE = "This run is one task of a larger goal that was split into tasks. Do only the current task below; every other task has its own run. Finished tasks are already in the source."


def start_next(launcher, run, automatic=False):
    """Launch the next ready task; its run is linked to the epic before its worker starts.

    automatic: only while auto-continue still applies when the epic lock is held.
    """
    with launcher.lock, epic_record.changing(run) as epic:
        state = json.loads(history.read_artifact(run, "run.json"))
        if state.get(epic_tasks.STATUS) != epic_tasks.READY:
            raise ValueError("Only a task split can start its tasks")
        entries = epic_tasks.tasks(run, state)
        if automatic and not continues(epic, entries):
            return None
        task = epic_progress.next_task(entries)
        if task is None:
            raise ValueError(
                "No task is ready: one is running, failed or waits for its dependencies"
            )
        link = partial(epic_record.link, run, epic, ("tasks", task[IDENTIFIER]))
        return launcher.submit(payload(run, state, entries, task), before_start=link)


def payload(run, state, entries, task):
    """Task form fields of one task run."""
    draft = history.task_draft(run)
    title = "{0} · {1}: {2}".format(draft["title"], task[IDENTIFIER], task["title"])
    return dict(
        title=title[:TITLE_LIMIT],
        goal=task["goal"],
        criteria="\n".join(task["checks"]),
        entry_points="\n".join(task["files"]),
        constraints=draft["constraints"],
        split_context=brief(run.name, draft, entries, task),
        roots=worktree_isolation.root_entries(state["roots"]),
        auto_approve=approval_policy.at_start(run, draft),
        phase="task",
    )


def brief(epic, draft, entries, current):
    """The scope rule, the overall goal and criteria, and every task with its outcome so far."""
    lines = [SCOPE, "", f"Overall goal (task split run {epic}):", draft["goal"], ""]
    lines.extend(["Overall acceptance criteria (apply to this task's part):", draft["criteria"]])
    lines.extend(["", "Tasks:"])
    lines.extend(task_line(task, current) for task in entries)
    return "\n".join(lines)


def task_line(task, current):
    """One task of the brief: current, later, or finished with its outcome."""
    label = "{0}: {1}".format(task[IDENTIFIER], task["title"])
    if task is current:
        return f"- {label} (current task)"
    if task["status"] is None:
        return f"- {label} (later; not part of this run)"
    state = "marked done" if task["done"] else task["status"]
    changed = ", ".join(task["changed_files"]) or "none"
    return f"- {label} ({state}): {task['summary']} Changed files: {changed}"


def continue_quietly(launcher, run):
    """A failed or busy task waits for the operator; nothing is retried here."""
    try:
        start_next(launcher, run, automatic=True)
    except (ValueError, OSError, KeyError):
        return


def continues(epic, entries):
    """Auto-continue is on, every started task succeeded and the next is not paused."""
    if not epic.get("auto_continue"):
        return False
    return epic_progress.group(entries, True) == "running"
