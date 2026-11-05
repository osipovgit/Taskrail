"""Explicit continuation checkpoints. Never infer a completed write from a timeout."""

import json

from taskrail.application import run_store

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
        "BLOCKED",
        "INVALID_RESULT",
        "TURN_ERROR",
        "CONTEXT_EXCEEDED",
        "NO_PROGRESS",
    )
)


def load_checkpoint(run, state):
    run_store.continuing(state)
    path = run / "checkpoint.json"
    if path.is_file():
        checkpoint = json.loads(path.read_text())
        run_store.validate(checkpoint)
        return checkpoint
    raise ValueError("No safe checkpoint. Restart creates a fresh run against current source.")


def resume_available(run, state):
    """Whether Continue is offered, with the reason shown to the operator."""
    if state.get(STATUS) not in RESUMABLE:
        return False, "This status does not support continuation."
    try:
        load_checkpoint(run, state)
    except (OSError, ValueError, KeyError) as error:
        return False, str(error)
    return True, "Source and Git integrity will be checked before continuing."
