"""Runs that belong to another run: the tasks of a split and the phases of a delivery.

A task run names its split in its assigned contract; a phase run (integration review,
Jenkins validation, server checks) names its delivery as its check parent. Such a run
is shown inside its parent's card, not as a separate task.
"""

from taskrail.application import check_parents, run_store
from taskrail.core import delivery_record
from taskrail.web import epic_tasks, history
from taskrail.web.run_files import contained, optional_json

TASK = "task"
PHASE_ATTEMPTS = "phase_attempts"


def task_metadata(folder, filename):
    """Use the task location belonging to this run or launch."""
    path = contained(folder, filename)
    if not path.is_file():
        return {}
    return history.TaskDraft(path.read_text(encoding="utf-8")).metadata


def parent_link(metadata):
    """(parent run, task ID or phase name) encoded by a task header, or None."""
    phase = metadata.get(check_parents.PHASE)
    if phase == TASK:
        contract = metadata.get("assigned_contract")
        if isinstance(contract, dict):
            return valid(contract.get("parent_run"), contract.get("task_id"))
        return None
    if phase in check_parents.PHASES:
        return valid(metadata.get(check_parents.PARENT), phase)
    return None


def valid(parent, slot):
    """Only a well-formed run name and slot form a link."""
    if not isinstance(parent, str) or not delivery_record.RUN_NAME.fullmatch(parent):
        return None
    if not isinstance(slot, str) or not slot:
        return None
    return parent, slot


def visible_parent(base, metadata):
    """A child belongs in a parent's card only if the parent is in current storage."""
    link = parent_link(metadata)
    if link is None:
        return None
    parent = base / link[0]
    if parent.is_symlink() or not run_store.supported(optional_json(parent, "run.json")):
        return None
    return link


def members(epic):
    """Every run started for a split or delivery, for search in the run list."""
    names = set(epic.get("tasks", {}).values())
    for runs in epic.get("attempts", {}).values():
        names.update(runs)
    for runs in epic.get(PHASE_ATTEMPTS, {}).values():
        names.update(runs)
    for phases in (epic.get("phases", {}), *epic.get("phase_history", [])):
        names.update(phases.values())
    return sorted(name for name in names if delivery_record.RUN_NAME.fullmatch(name))


def member_fields(run):
    """The task and phase runs of a split or delivery, so search finds their parent."""
    children = members(epic_tasks.record(run))
    return dict(members=children) if children else {}


def can_follow_up(run, state):
    """A stopped standalone run; a task or phase run continues through its parent."""
    if state.get("status") == "RUNNING" or state.get(check_parents.PHASE):
        return False
    return run.joinpath("run.json").is_file()
