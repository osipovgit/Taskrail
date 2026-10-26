"""Read authenticated parent plans without extending model artifact permissions."""

import json

from taskrail.core import delivery_record, schema, task_spec
from taskrail.core.files import digest

SEAL = "reviewed_plan_sha256"
STATUS = "status"


def run_path(base, name):
    """A parent or child reference always names a direct, non-symlink storage child."""
    schema.require(
        isinstance(name, str) and delivery_record.RUN_NAME.fullmatch(name), "Invalid run ID"
    )
    path = base / name
    schema.require(
        not path.is_symlink() and path.resolve().parent == base.resolve(), "Invalid run path"
    )
    return path


def read(run, reference):
    """Internal references cannot follow symlinks or leave their own run."""
    path = run / reference
    schema.require(
        not path.is_symlink() and run.resolve() in path.resolve().parents, "Invalid artifact path"
    )
    return path.read_bytes()


def document(run, reference):
    """Decode one server-owned JSON artifact."""
    return json.loads(read(run, reference))


def seal(workflow):
    """Bind independent plan approval to the exact result artifact used for dispatch."""
    state = workflow.state
    if state.get("plan_review", {}).get(STATUS) == "APPROVE":
        reference = state["results"].get("plan")
        if reference:
            state[SEAL] = digest(read(workflow.run, reference))


def parent(base, name):
    """The sealed, independently approved split a child was started for."""
    run = run_path(base, name)
    state = document(run, "run.json")
    schema.require(state[STATUS] == "TASKS_READY", "Parent task is not an approved split")
    schema.require(
        SEAL in state and typed_requirements(state),
        "Parent split was planned by an older release; restart the parent task",
    )
    encoded = read(run, state["results"]["plan"])
    schema.require(digest(encoded) == state[SEAL], "Reviewed parent plan changed; replan required")
    review = document(run, state["results"]["plan-review"])
    schema.require(review[STATUS] == "APPROVE", "Parent plan has no independent approval")
    plan = json.loads(encoded)
    schema.validate(plan, schema.SCHEMAS["planner"])
    return dict(run=run, state=state, plan=plan, epic=delivery_record.read(run))


def typed_requirements(state):
    """Every task requirement names its field, so global constraints can be inherited."""
    entries = [entry for entry in state["requirements"] if entry["kind"] == "task"]
    fields = [entry.get("source", {}).get("field") for entry in entries]
    return all(field in task_spec.OBLIGATIONS for field in fields)
