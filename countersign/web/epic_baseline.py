"""Accept the current files as the starting point of the next task of a split.

When the operator edited the projects between two tasks on purpose, the next task's
lineage check would otherwise refuse to start. The accepted fingerprints are recorded
in epic.json with the number of attempts the task had, and only that task's chain
uses them.
"""

import json
import time
from pathlib import Path

from countersign.application import run_locks, source_ignores
from countersign.application.git_state import git_metadata
from countersign.core import delivery_record
from countersign.web import epic_progress, epic_record, epic_tasks, history
from countersign.web.run_activity import BusyError, run_sources


def accept(launcher, run, task):
    """Record the current files for the next task; nothing may run on its projects."""
    with launcher.lock, epic_record.changing(run) as epic:
        state = json.loads(history.read_artifact(run, "run.json"))
        require_next(run, state, task)
        conflict = run_locks.conflict(run_sources(run))
        if conflict:
            raise BusyError(f"{conflict}. Wait until it stops.")
        baseline = current_files(state["roots"])
        attempts = delivery_record.attempts(epic, task)
        baseline.update(after=len(attempts), accepted_at=time.time())
        epic.setdefault("baselines", {})[task] = baseline
    return dict(id=run.name, status="SOURCES_ACCEPTED", task=task)


def require_next(run, state, task):
    """Only the next task of an approved split can start from the current files."""
    if state.get("status") != epic_tasks.READY:
        raise ValueError("Only a task split can accept the current files for a task")
    ready = epic_progress.next_task(epic_tasks.tasks(run, state))
    if ready is None or ready["id"] != task:
        raise ValueError("Only the next task of the split can start from the current files")


def current_files(stored):
    """The guarded fingerprints and Git state of the split's roots now."""
    roots = {alias: Path(location) for alias, location in stored.items()}
    return dict(expected=source_ignores.current(roots), git_before=git_metadata(roots))
