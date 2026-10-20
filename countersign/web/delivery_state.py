"""Where a code change stands: its implementation, Jenkins validation, confirmation and
server checks.

A delivery run changes code and is not itself a task, validation or server-check run.
Its plan is implemented in the same run or split into task runs (TASKS_READY); the
later phases are recorded in epic.json beside it.
"""

from countersign.web import (
    delivery_checks,
    delivery_steps,
    epic_progress,
    epic_tasks,
    history,
    lifecycle,
)

NOT_DELIVERY = ("read_only", "design", "phase")
STEP = "step"


def view(run, state):
    """The delivery of a code-changing run, or None for answers, designs and phase runs."""
    if not container(run):
        return None
    epic = epic_tasks.record(run)
    split = epic_progress.view(run, state)
    delivery = dict(split or {}, status=lifecycle.display_status(run, state))
    delivery["phases"] = phases(run, epic)
    delivery["checks"] = delivery_checks.checks(run, state)
    delivery["confirmed"] = bool(epic.get("confirmed"))
    delivery["implementation"] = implementation(delivery["status"], split)
    delivery[STEP] = delivery_steps.step(delivery)
    return delivery


def container(run):
    """A started run whose task changes code and is not a phase of another run."""
    if not run.joinpath(history.TASK_FILE).is_file():
        return False
    metadata = history.TaskDraft(history.read_artifact(run, history.TASK_FILE)).metadata
    return not any(metadata.get(flag) for flag in NOT_DELIVERY)


def phases(run, epic):
    """Each recorded phase: its run, status and summary, or why it was skipped."""
    recorded = epic.get("phases", {})
    return {name: phase(run, entry) for name, entry in recorded.items()}


def phase(run, entry):
    """One phase record: a run ID, or "skipped: <reason>" when the executor lacks it."""
    if entry.startswith(delivery_steps.SKIPPED):
        reason = entry.split(": ", 1)[-1]
        return dict(run=None, status=delivery_steps.SKIPPED, summary=reason)
    outcome = epic_tasks.outcome(run.parent / entry)
    summary = outcome.get("summary", "")
    return dict(run=entry, status=outcome[delivery_steps.STATUS], summary=summary)


def implementation(status, split):
    """running, attention or done for the code change itself; a waiting approval needs you."""
    if split is not None:
        grouped = epic_progress.group(split["tasks"], split["auto_continue"])
        return "done" if grouped == "review" else grouped
    if status in epic_tasks.FINISHED:
        return "done"
    return "running" if status in epic_tasks.ACTIVE else "attention"


def list_fields(run, state, current):
    """Group, step and task progress of a delivery in the run list; a done mark wins."""
    delivery = view(run, state)
    if delivery is None:
        return {}
    fields = {key: delivery[key] for key in ("progress",) if key in delivery}
    fields[STEP] = delivery[STEP]
    if current != delivery_steps.DONE:
        current = delivery_steps.GROUPS[delivery[STEP]]
    fields["group"] = current
    return fields
