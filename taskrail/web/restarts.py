"""Explicit retries retain the reviewed assignment and the parent's attempt chain."""

import json

from taskrail.application import check_parents, reviewed_artifacts
from taskrail.core.schema import require
from taskrail.web import delivery_launch, epic_launch, history, run_family


def restart(launcher, run):
    """Offer standalone drafts; a split task or delivery phase restarts under its parent."""
    state = json.loads(history.read_artifact(run, "run.json"))
    phase = state.get(check_parents.PHASE)
    if phase in check_parents.PHASES:
        return restart_phase(launcher, run, phase)
    if phase != "task":
        return dict(id=run.name, draft=history.task_draft(run))
    metadata = history.TaskDraft(history.read_artifact(run, history.TASK_FILE)).metadata
    assignment = metadata.get("assigned_contract")
    require(isinstance(assignment, dict), "Missing child assignment; open the parent split")
    parent = reviewed_artifacts.parent(launcher.base, assignment.get("parent_run"))
    return epic_launch.start_next(
        launcher, parent["run"], retry=(assignment.get("task_id"), run.name)
    )


def restart_phase(launcher, run, phase):
    """A delivery phase runs again under the delivery that started it."""
    link = run_family.parent_link(run)
    require(link is not None and link[1] == phase, "Missing delivery parent of this phase")
    parent = history.checked_run(launcher.base, link[0])
    return delivery_launch.restart_phase(launcher, parent, phase, run.name)


def require_standalone(run, mode, state):
    """A task or phase run cannot become a detached planner or conversation.

    It restarts through its restart action and continues through Continue with a note;
    a follow-up belongs to its parent.
    """
    require(
        not state.get(check_parents.PHASE),
        f"Run {run.name} belongs to a split or delivery; use its restart action, Continue "
        "with a note, or a follow-up of the parent run",
    )
