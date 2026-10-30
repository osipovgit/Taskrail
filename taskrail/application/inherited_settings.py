"""Resolve frozen delivery recipe IDs before parsing a generated phase task.

This read does not grant execution authority. The phase's durable parent link,
roots and requirements are authenticated again under the workflow lock.
"""

from pathlib import Path

from taskrail.application import (
    check_configuration,
    check_parents,
    execution_context,
    reviewed_artifacts,
)
from taskrail.core import input_header
from taskrail.core.runtime import run_storage
from taskrail.core.schema import require


def for_request(request):
    """Current settings cannot replace or remove the recipe catalog of a delivery."""
    task = Path(request["task"]).expanduser().resolve()
    location = request.get("run_dir")
    base = (
        run_storage(request["settings"])
        if location is None
        else Path(location).expanduser().resolve().parent
    )
    parent_name = parent_reference(input_header.parse(task.read_text(encoding="utf-8")))
    if parent_name is not None:
        return parent_settings(reviewed_artifacts.run_path(base, parent_name))
    parent = execution_context.submitted_parent(
        task, base, Path(location).name if location else None
    )
    return None if parent is None else parent_settings(parent)


def parent_settings(parent):
    """Read only authenticated commands; execution still requires the phase's parent link."""
    state = reviewed_artifacts.document(parent, "run.json")
    saved = check_configuration.parent_settings(parent, state)
    return dict(
        saved, permission_worktree=execution_context.frozen(parent, state)["permission_worktree"]
    )


def continued(run, state):
    """A continuation validates its frozen permission base before current settings."""
    saved = check_configuration.frozen(run, state)
    return dict(
        saved, permission_worktree=execution_context.frozen(run, state)["permission_worktree"]
    )


def parent_reference(metadata):
    """Child claims are syntax here; their actual assignment is checked under the lock."""
    if metadata.get("phase") != "task":
        return check_parents.reference(metadata)
    assignment = metadata.get("assigned_contract")
    require(
        isinstance(assignment, dict) and set(assignment) == {"parent_run", "task_id"},
        "A task of a split needs an authenticated parent contract",
    )
    return assignment["parent_run"]
