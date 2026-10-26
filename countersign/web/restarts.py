"""Explicit retries retain the reviewed assignment and the parent's attempt chain."""

import json

from countersign.application import reviewed_artifacts
from countersign.core.schema import require
from countersign.web import epic_launch, history


def restart(launcher, run):
    """Offer standalone drafts, but relaunch a split child from its approved parent."""
    state = json.loads(history.read_artifact(run, "run.json"))
    if state.get("phase") != "task":
        return dict(id=run.name, draft=history.task_draft(run))
    metadata = history.TaskDraft(history.read_artifact(run, history.TASK_FILE)).metadata
    assignment = metadata.get("assigned_contract")
    require(isinstance(assignment, dict), "Missing child assignment; open the parent split")
    parent = reviewed_artifacts.parent(launcher.base, assignment.get("parent_run"))
    return epic_launch.start_next(
        launcher, parent["run"], retry=(assignment.get("task_id"), run.name)
    )


def require_standalone(run, mode, state):
    """An old UI or API caller cannot turn an assigned retry into a detached planner."""
    require(
        mode != "restart" or state.get("phase") != "task",
        f"Run {run.name} is an assigned task; use its restart action or the parent split",
    )
