"""Independent acceptance of the combined result of all child tasks."""

import contextlib
import json
from pathlib import Path

from countersign.application import run_locks, worktree_isolation
from countersign.application.source_guard import SourceGuard
from countersign.core.files import digest
from countersign.interactions import approval_policy
from countersign.web import epic_tasks, history, parent_context, task_form
from countersign.web.run_activity import BusyError

NAME = "integration"
SEAL = "integration_inputs"
TITLE_LIMIT = 160


def signature(entries):
    """Bind acceptance to the exact child runs and their completion records."""
    selected = [
        {key: task[key] for key in ("id", "run", "status", "done", "changed_files")}
        for task in entries
    ]
    return digest(json.dumps(selected, sort_keys=True).encode())


def payload(run, state):
    """Review the original goal and every original criterion against combined source."""
    draft = history.task_draft(run)
    fields = {key: draft.get(key, "") for key in task_form.FIELDS}
    fields["title"] = "{0} · Integration review".format(draft["title"])[:TITLE_LIMIT]
    return dict(
        fields,
        roots=worktree_isolation.root_entries(state["roots"]),
        phase=NAME,
        read_only=True,
        auto_approve=approval_policy.at_start(run, draft),
        parent_context=parent_context.snapshot(run, epic_tasks.tasks(run, state)),
        check_specs=[spec for spec in state.get("check_specs", []) if spec["phase"] == "check"],
        assigned_requirements=state.get("requirements", []),
        check_parent=run.name if state.get("check_specs") else None,
    )


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
