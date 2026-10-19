"""Explicit continuation checkpoints. Never infer a completed write from a timeout."""

import json

from countersign.core.schema import contract_version

STATUS = "status"

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
        "INVALID_RESULT",
        "TOOL_ERROR",
    )
)


def load_checkpoint(run, state):
    contract_version(state.get("contract_version"))
    path = run / "checkpoint.json"
    if path.is_file():
        checkpoint = json.loads(path.read_text())
        if state.get(STATUS) == "BLOCKED_PERMISSION" and checkpoint.get("stage") not in (
            "planner",
            "plan-reviewer",
            "reviewer",
        ):
            raise ValueError("Permission-denied writes cannot be automatically continued")
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
