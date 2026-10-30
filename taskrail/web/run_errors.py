"""Report damaged run artifacts without depending on their JSON or losing other runs."""

import contextlib

from taskrail.core.files import atomic_json
from taskrail.web import delivery_state, epic_record, epic_tasks, run_family
from taskrail.web.run_files import contained, read_json

NAME = "recovery-required.json"
STATUS = "RECOVERY_REQUIRED"
ERRORS = (OSError, ValueError, KeyError, TypeError, AttributeError)
SUMMARY_LIMIT = 2000


def launch_failure(run, error):
    """Stop auto-launch when its index works; damaged indexes use a separate diagnostic."""
    try:
        with epic_record.changing(run) as epic:
            inspect(run, epic)
            epic.update(auto_continue=False, launch_error=str(error))
    except ERRORS:
        record(run, error)


def inspect(run, epic):
    """Exercise authority readers before a recovery handler can rewrite their inputs."""
    run_family.members(epic)
    state = read_json(contained(run, "run.json"))
    delivery_state.view(run, state)


def record(run, error):
    """Best-effort diagnostics never replace an unreadable authority record."""
    detail = dict(status=STATUS, summary=str(error)[:SUMMARY_LIMIT])
    with contextlib.suppress(*ERRORS):
        path = contained(run, NAME)
        if path.is_file() and read_json(path) == detail:
            return
        atomic_json(path, detail)


def clear(run):
    """A successful subsequent inspection clears only the separate diagnostic."""
    with contextlib.suppress(*ERRORS):
        inspect(run, epic_tasks.record(run))
        contained(run, NAME).unlink(missing_ok=True)


def summary(run, error):
    """Keep a damaged run discoverable in the task list."""
    return dict(
        id=run.name,
        title=run.name,
        status=STATUS,
        mode="develop",
        group="attention",
        summary=f"Saved task data needs recovery: {error}"[:SUMMARY_LIMIT],
    )


def view(run, error):
    """A safe diagnostic view offers no actions based on unreadable task authority."""
    return dict(
        summary(run, error),
        launch={},
        parent=None,
        roots={},
        stages=[],
        requirements=[],
        changed_files=[],
        unverified=[],
        conversation=[],
        draft=None,
        actions={},
        auto_approve=False,
        delivery=None,
        pending_approval=None,
        task="",
        console="",
        report="",
        diff="",
        design="",
    )
