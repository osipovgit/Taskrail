"""Serialized changes of epic.json: task and phase links, choices and the confirmation.

Each change reads, edits and writes the record under one lock, so auto-continue, Pause,
Confirm and phase starts never lose each other's updates. A child run is linked, and
the link written, before its worker starts (see TaskLauncher.submit), so a restart
between the two steps can never start the same task twice.
"""

import contextlib
import fcntl

from countersign.application import run_locks
from countersign.core.files import atomic_json
from countersign.web import epic_tasks

PAUSE = epic_tasks.PAUSE


@contextlib.contextmanager
def changing(run):
    """Yield the record to edit; it is written when the block ends without an error."""
    with run_locks.lock_file(run_locks.lock_path("epic", run)) as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        epic = epic_tasks.record(run)
        yield epic
        save(run, epic)


def save(run, epic):
    """Write the record now; inside changing(), before an action that relies on it."""
    atomic_json(run / epic_tasks.EPIC, epic)


def link(run, epic, place, child):
    """Link a child run under epic[section][name] and write it before the child starts.

    A task keeps the list of every run started for it, so a retry can continue from
    an earlier attempt's edits through an authenticated chain.
    """
    section, name = place
    links = epic.setdefault(section, {})
    if section == "tasks":
        earlier = [links[name]] if name in links else []
        epic.setdefault("attempts", {}).setdefault(name, earlier).append(child)
    links[name] = child
    save(run, epic)


def set_auto(run, enabled):
    """Turn automatic continuation after each successful task on or off."""
    with changing(run) as epic:
        epic["auto_continue"] = enabled
    return dict(id=run.name, status="AUTO_CONTINUE_ON" if enabled else "AUTO_CONTINUE_OFF")


def set_pause(run, task, paused):
    """Make auto-continue wait for the operator before one task, or stop waiting."""
    with changing(run) as epic:
        waiting = set(epic.get(PAUSE, [])) - {task}
        epic[PAUSE] = sorted(waiting | {task} if paused else waiting)
    return dict(id=run.name, status="PAUSE_SET" if paused else "PAUSE_CLEARED")
