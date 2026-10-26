"""Which task of an epic can start next, and what the epic needs from the operator."""

from taskrail.web import epic_tasks

ACTIVE = epic_tasks.ACTIVE
# A task whose run waits for your decision is still in progress: nothing else starts.
BUSY = ACTIVE | {"WAITING_APPROVAL"}
FINISHED = epic_tasks.FINISHED
STATUS = epic_tasks.STATUS


def finished(task):
    """A task whose run succeeded, or that the operator marked done."""
    return task[STATUS] in FINISHED or task["done"]


def next_task(entries):
    """The first unfinished task once its dependencies finished, unless a task is active.

    A task whose run failed may be started again by the operator; auto-continue never
    does, because the epic then needs the operator (see group).
    """
    if any(task[STATUS] in BUSY for task in entries):
        return None
    done = {task["id"] for task in entries if finished(task)}
    for task in entries:
        if task["id"] not in done:
            return task if set(task["depends_on"]) <= done else None
    return None


def group(entries, auto_continue):
    """running, attention or review, like any run in the list."""
    statuses = [task[STATUS] for task in entries]
    if any(status in ACTIVE for status in statuses):
        return "running"
    if any(task[STATUS] and not finished(task) for task in entries):
        return "attention"
    ready = next_task(entries)
    if ready is None:
        return "review"
    return "running" if auto_continue and not ready["pause_before"] else "attention"


def view(run, state):
    """Tasks, progress and controls of an epic run; None for any other run."""
    if state.get(STATUS) != epic_tasks.READY:
        return None
    entries = epic_tasks.tasks(run, state)
    ready = next_task(entries)
    return dict(
        tasks=entries,
        progress=progress(entries),
        auto_continue=bool(epic_tasks.record(run).get("auto_continue")),
        next=ready["id"] if ready else None,
    )


def progress(entries):
    """Finished tasks out of all tasks, as shown in the run list."""
    count = sum(finished(task) for task in entries)
    return f"{count}/{len(entries)}"
