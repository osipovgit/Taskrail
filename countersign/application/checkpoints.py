"""Explicit continuation checkpoints. Never infer a completed write from a timeout."""

import json

from countersign.core.schema import contract_version

STATUS = "status"
# A blocked read-only stage may continue with the operator's note; a blocked writer may not.
READ_ONLY_STAGES = frozenset(("planner", "plan-reviewer", "reviewer"))

RESUMABLE = frozenset(
    (
        "TIMEOUT",
        "INCOMPLETE",
        "PROCESS_ERROR",
        "INTERRUPTED",
        "LAUNCH_ERROR",
        "SESSION_ERROR",
        "RUNNING",
        "TOKEN_BUDGET_EXCEEDED",
        "STAGE_BUDGET_EXCEEDED",
        "BLOCKED_PERMISSION",
        "BLOCKED",
        "INVALID_RESULT",
        "TOOL_ERROR",
        "CONTEXT_EXCEEDED",
        "CHANGE_LIMIT_EXCEEDED",
    )
)


def load_checkpoint(run, state):
    contract_version(state.get("contract_version"))
    path = run / "checkpoint.json"
    if path.is_file():
        checkpoint = json.loads(path.read_text())
        blocked = state.get(STATUS) in {"BLOCKED_PERMISSION", "BLOCKED"}
        if blocked and checkpoint.get("stage") not in READ_ONLY_STAGES:
            raise ValueError("A blocked writer cannot be continued; restart after inspecting edits")
        return checkpoint
    raise ValueError("No safe checkpoint. Restart creates a fresh run against current source.")


def resume_available(run, state):
    """Whether Continue is offered, with the reason shown to the operator."""
    if state.get(STATUS) not in RESUMABLE and not budget_paused(state):
        return False, "This status does not support continuation."
    try:
        load_checkpoint(run, state)
    except (OSError, ValueError, KeyError) as error:
        return False, str(error)
    return True, "Source and Git integrity will be checked before continuing."


def budget_paused(state):
    """Identify engine budget stops, for time, attempts or tokens."""
    if state.get(STATUS) in {
        "TOKEN_BUDGET_EXCEEDED",
        "STAGE_BUDGET_EXCEEDED",
    }:
        return True
    return False
