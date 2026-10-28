"""Independent acceptance of the combined result of all child tasks."""

import contextlib
import json

from taskrail.application import (
    delivery_confirmation,
    outside_changes,
    run_locks,
    worktree_isolation,
)
from taskrail.core import delivery_record
from taskrail.core.files import digest
from taskrail.web import epic_tasks, history, parent_context, split_approvals, task_form
from taskrail.web.run_activity import BusyError

NAME = "integration"
SEAL = "integration_inputs"
TITLE_LIMIT = 160
LISTED_FILES = 20


def signature(entries):
    """Bind acceptance to the exact child runs and their completion records."""
    selected = [
        {key: task[key] for key in ("id", "run", "status", "done", "changed_files")}
        for task in entries
    ]
    return digest(json.dumps(selected, sort_keys=True).encode())


def payload(run, state):
    """Review the original goal and every original criterion against combined source.

    The parent link is authenticated by the integration run, which then shows the
    combined diff of all task runs against the files before the split.
    """
    draft = history.task_draft(run)
    entries = epic_tasks.tasks(run, state)
    fields = {key: draft.get(key, "") for key in task_form.FIELDS}
    fields["title"] = "{} · Integration review".format(draft["title"])[:TITLE_LIMIT]
    return dict(
        fields,
        roots=worktree_isolation.root_entries(state["roots"]),
        phase=NAME,
        read_only=True,
        auto_approve=split_approvals.allows_all(run, draft),
        split_context=changes_by_task(entries),
        parent_context=parent_context.snapshot(run, entries),
        check_specs=[spec for spec in state.get("check_specs", []) if spec["phase"] == "check"],
        assigned_requirements=state.get("requirements", []),
        check_parent=run.name,
    )


def changes_by_task(entries):
    """One line per task: its title, run outcome, changed files and outside changes."""
    lines = ["Tasks of the split, in the order they ran:"]
    for task in entries:
        files = list(task["changed_files"])
        changed = ", ".join(files[:LISTED_FILES]) or "none"
        more = len(files) - LISTED_FILES
        if more > 0:
            changed = f"{changed} and {more} more (see changes.diff)"
        lines.append(
            "- {id}: {title} ({status}, run {run}); changed files: {0}".format(changed, **task)
            + outside_changes.integration_note(task.get("outside_files"))
        )
    return "\n".join(lines)


def invalidate(delivery, epic):
    """A changed child completion record cannot retain an earlier overall approval."""
    recorded = delivery["phases"].get(NAME)
    current = signature(delivery.get("tasks", []))
    if recorded and epic.get(SEAL) != current:
        recorded.update(status="STALE", summary="Child results changed; repeat integration review.")


@contextlib.contextmanager
def confirmation_lock(run, delivery):
    """Hold the reviewed roots unchanged for standalone and split confirmation alike."""
    child = run
    if "tasks" in delivery:
        child = history.checked_run(run.parent, delivery["phases"][NAME]["run"])
    snapshot = delivery_confirmation.capture(run, child, delivery_record.read(run))
    guard = delivery_confirmation.guard(snapshot)
    with run_locks.run_locks(guard.roots.values(), run) as conflict:
        if conflict:
            raise BusyError(conflict)
        review = "review" if child == run else "integration review"
        guard.verify(f"Source changed since {review}; repeat review before confirmation")
        yield snapshot
