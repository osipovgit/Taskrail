"""Independent acceptance of the combined result of all child tasks."""

import contextlib
import json
from pathlib import Path

from taskrail.application import outside_changes, run_locks, worktree_isolation
from taskrail.application.source_guard import SourceGuard
from taskrail.core.files import digest
from taskrail.interactions import approval_policy
from taskrail.web import epic_tasks, history, parent_context, task_form
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
        auto_approve=approval_policy.at_start(run, draft),
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
    """Hold the reviewed roots unchanged while the operator confirms a split."""
    if "tasks" not in delivery:
        yield
        return
    record = delivery["phases"][NAME]
    child = history.checked_run(run.parent, record["run"])
    guard = review_guard(child)
    with run_locks.run_locks(guard.roots.values(), run) as conflict:
        if conflict:
            raise BusyError(conflict)
        guard.verify("Source changed since integration review; repeat review before confirmation")
        yield


def review_guard(child):
    """Restore the final review's fingerprint boundary without trusting summaries."""
    state = json.loads(history.read_artifact(child, "run.json"))
    checkpoint = json.loads(history.read_artifact(child, "checkpoint.json"))
    roots = resolved_roots(state["roots"])
    guard = SourceGuard(roots)
    guard.adopt(checkpoint["expected"], checkpoint["git_before"])
    return guard


def resolved_roots(roots):
    """Convert stored roots for the shared integrity guard."""
    return {alias: Path(root) for alias, root in roots.items()}
