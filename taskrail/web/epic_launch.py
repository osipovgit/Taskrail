"""Start the next task of an epic as a new run with a short brief.

A task run is a new task, not a follow-up: it gets the overall goal, the task list
with outcomes so far and its own step, instead of every earlier conversation turn,
so long epics stay within the model context. It works in the epic's roots, which
are its worktrees when the epic was isolated.
"""

import json
from functools import partial

from taskrail.application import worktree_isolation
from taskrail.web import (
    epic_progress,
    epic_record,
    epic_tasks,
    history,
    parent_context,
    run_errors,
    split_approvals,
    task_brief,
)
from taskrail.web.run_activity import BusyError

TITLE_LIMIT = 160
IDENTIFIER = "id"


def start_next(launcher, run, automatic=False, retry=None):
    """Launch the next ready task; its run is linked to the epic before its worker starts.

    automatic: only while auto-continue still applies when the epic lock is held.
    """
    with launcher.lock, epic_record.changing(run) as epic:
        state = json.loads(history.read_artifact(run, "run.json"))
        if state.get(epic_tasks.STATUS) != epic_tasks.READY:
            raise ValueError("Only a task split can start its tasks")
        entries = epic_tasks.tasks(run, state)
        task = epic_progress.next_task(entries)
        # While a task runs or waits, auto-continue simply waits; that is not an error.
        if automatic and (task is None or not continues(epic, entries)):
            return None
        if task is None:
            raise ValueError(
                "No task is ready: one is running, failed or waits for its dependencies"
            )
        require_retry(task, retry)
        link = partial(epic_record.link, run, epic, ("tasks", task[IDENTIFIER]))
        epic.pop("launch_error", None)
        return launcher.submit(payload(run, state, entries, task), before_start=link)


def require_retry(task, retry):
    """Check the operator's exact target under the same lock as the new link."""
    current = (task[IDENTIFIER], task.get("run"))
    if retry is not None and current != retry:
        raise ValueError("Only the latest attempt of the next unfinished task can restart")


def payload(run, state, entries, task):
    """Task form fields of one task run."""
    draft = history.task_draft(run)
    title = "{} · {}: {}".format(draft["title"], task[IDENTIFIER], task["title"])
    done_when = "; ".join(task["done_when"])
    return dict(
        title=title[:TITLE_LIMIT],
        goal=done_when or task["goal"],
        criteria=task_brief.requirements(state, task),
        entry_points=parent_context.field("\n".join(task["files"]), "current task files"),
        constraints=draft["constraints"],
        split_context=task_brief.brief(run, draft, entries, task),
        parent_context=parent_context.snapshot(run, entries),
        task_scope=task["files"],
        assigned_contract=dict(parent_run=run.name, task_id=task[IDENTIFIER]),
        assigned_requirements=task_brief.assigned_requirements(state, task),
        roots=worktree_isolation.root_entries(state["roots"]),
        auto_approve=split_approvals.allows_all(run, draft),
        phase="task",
    )


def continue_quietly(launcher, run):
    """A failed or busy task waits for the operator; nothing is retried here."""
    try:
        start_next(launcher, run, automatic=True)
    except BusyError:
        return False
    except run_errors.ERRORS as error:
        run_errors.launch_failure(run, error)
        return False
    return True


def continues(epic, entries):
    """Auto-continue is on, every started task succeeded and the next is not paused."""
    if not epic.get("auto_continue"):
        return False
    return epic_progress.group(entries, True) == "running"
