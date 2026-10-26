"""Runs that belong to another run: the tasks of a split and the phases of a delivery.

A task run names its split in its assigned contract; a phase run (integration review,
Jenkins validation, server checks) names its delivery as its check parent. Such a run
is shown inside its parent's card, not as a separate task.
"""

from countersign.application import check_parents
from countersign.core import delivery_record
from countersign.web import epic_tasks, history

TASK = "task"
# A started run keeps its task in 00-input; a launch folder keeps it at its top.
TASK_FILES = (history.TASK_FILE, "task.md")
PHASE_ATTEMPTS = "phase_attempts"


def parent_link(folder):
    """(parent run, task ID or phase name) of a run or launch folder, or None."""
    tasks = [folder / name for name in TASK_FILES]
    readable = [path for path in tasks if path.is_file() and not path.is_symlink()]
    if not readable:
        return None
    metadata = history.TaskDraft(readable[0].read_text(encoding="utf-8")).metadata
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


def shown_inside(base, folder):
    """A child run whose parent still exists is shown in that parent's card."""
    link = parent_link(folder)
    return link is not None and base.joinpath(link[0], "run.json").is_file()


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
