"""Run locks: the installation lock (shared), one lock per run and the project locks.

Runs on independent projects proceed in parallel; lock_resources says what the projects
of a run lock. The installer takes the installation lock exclusively, so it waits for
every active run. No lock is waited for, so runs never deadlock.
"""

import contextlib
import hashlib
from pathlib import Path
from types import MappingProxyType

from taskrail.application import lock_resources
from taskrail.core import file_lock

STATE = Path(".local/state/taskrail")
INSTALL_LOCK = "live.lock"
LOCKS = "locks"
MODES = MappingProxyType(
    {lock_resources.EXCLUSIVE: file_lock.EXCLUSIVE, lock_resources.SHARED: file_lock.SHARED},
)
NAME_LENGTH = 32
RUN = "run"
ROOT = lock_resources.ROOT


@contextlib.contextmanager
def run_locks(sources, run):
    """Yield None while every lock is held, or why the run cannot start now."""
    with contextlib.ExitStack() as stack:
        yield acquire(stack, sources, run)


def acquire(stack, sources, run):
    """Take the installation and run locks, then the project locks."""
    path = Path.home() / STATE / INSTALL_LOCK
    install = stack.enter_context(file_lock.open_lock(path))
    if not file_lock.locked(install, file_lock.SHARED):
        return "An installation is in progress"
    if not stack.enter_context(resource(RUN, run, file_lock.EXCLUSIVE)):
        return "This run is already active"
    return hold(stack, sources)


def hold(stack, sources, probe=False):
    """Lock every project resource in a fixed order; why one is held elsewhere, else None."""
    for key, mode in sorted(lock_resources.resources(sources).items()):
        if not stack.enter_context(resource(*key, MODES[mode], probe=probe)):
            return lock_resources.RUNNING.format(lock_resources.describe(key))
    return None


def conflict(sources):
    """Why a run on these sources could not start now, or None; nothing stays locked."""
    with contextlib.ExitStack() as stack:
        return hold(stack, sources, probe=True)


def lock_path(kind, location):
    """A stable lock file name for a path, outside every project."""
    digest = hashlib.sha256(str(location).encode()).hexdigest()
    name = digest[:NAME_LENGTH]
    return Path.home() / STATE / LOCKS / f"{kind}-{name}.lock"


def resource(kind, location, mode, *, probe=False):
    """Use a removable lock keyed by the shared resource's canonical path."""
    return file_lock.scoped(lock_path(kind, location), mode, probe=probe)
