"""Freeze trusted worktree provenance and permission bases independently of task input."""

import json
from pathlib import Path

from taskrail.application import original_checkout, reviewed_artifacts, run_state
from taskrail.core.files import atomic_json, digest
from taskrail.core.schema import require
from taskrail.git import reviewed_commit

REFERENCE = "00-input/execution-context.json"
SIGNATURE = "execution_context_sha256"
ROOTS = "roots"
WORKTREES = "worktrees"
BASE = "permission_worktree"
FOLLOWUPS = frozenset(("followup", "answer", "design"))


def capture(run, config, state):
    """Only server-created or authenticated inherited records establish ownership."""
    base = config.get(BASE)
    payload = dict(
        roots=run_state.stored_roots(config[ROOTS]),
        worktrees=config.get(WORKTREES, {}),
        permission_worktree=None if base is None else str(base),
    )
    atomic_json(run / REFERENCE, payload)
    state[SIGNATURE] = digest(reviewed_artifacts.read(run, REFERENCE))
    state[WORKTREES] = payload[WORKTREES]
    return state


def frozen(run, state):
    """Authenticate the sealed execution context of every current run."""
    expected = state.get(SIGNATURE)
    require(expected is not None, "Execution context seal is missing")
    encoded = reviewed_artifacts.read(run, REFERENCE)
    require(digest(encoded) == expected, "Frozen execution context changed")
    payload = json.loads(encoded)
    require(payload[ROOTS] == state[ROOTS], "Execution context roots changed")
    require(payload[WORKTREES] == state.get(WORKTREES, {}), "Worktree provenance changed")
    return payload


def restore(run, config, state):
    """Continue from this run's sealed context without reopening its parent."""
    apply(config, frozen(run, state))


def apply(config, payload):
    """Execution context cannot add roots or replace the submitted effective roots."""
    require(payload[ROOTS] == run_state.stored_roots(config[ROOTS]), "Inherited roots differ")
    config[WORKTREES] = payload[WORKTREES]
    base = payload[BASE]
    config[BASE] = None if base is None else Path(base)


def adopt(workflow, parent, state):
    """Call only after the parent assignment or delivery phase has been authenticated."""
    apply(workflow.config, frozen(parent, state))
    original_checkout.inherit(parent, workflow.run)
    capture(workflow.run, workflow.config, workflow.state)


def submitted_parent(task, base, name):
    """A follow-up relationship comes from the server's exact durable launch record."""
    folder = task.parent
    if folder.parent != base / ".submissions":
        return None
    launch = reviewed_artifacts.document(folder, "launch.json")
    parent = launch.get("execution_parent")
    if parent is None:
        return None
    identity = folder.name == launch["launch_id"] == launch["id"] == name
    require(task.name == "task.md" and identity, "Follow-up launch does not identify this run")
    require(
        not launch["resume"] and launch.get("submission_mode") in FOLLOWUPS,
        "Invalid follow-up execution relationship",
    )
    return reviewed_artifacts.run_path(base, parent)


def submission_source(config, run):
    """Authenticate a follow-up before creating its new branch from the parent checkout."""
    parent = submitted_parent(config["task"], run.parent, run.name)
    if parent is None:
        return None
    state = reviewed_artifacts.document(parent, "run.json")
    require(not state.get("phase"), "A child run cannot own a standalone follow-up")
    require(state["status"] not in {"RUNNING", "STARTING"}, "Follow-up parent is still running")
    reviewed_commit.require_settled(parent)
    payload = frozen(parent, state)
    require(payload[ROOTS] == run_state.stored_roots(config[ROOTS]), "Follow-up roots differ")
    return payload
