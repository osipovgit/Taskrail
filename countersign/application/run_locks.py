"""Run locks: the installation lock (shared), one lock per run and the project locks.

Runs on independent projects proceed in parallel; lock_resources says what the projects
of a run lock. The installer takes the installation lock exclusively, so it waits for
every active run. No lock is waited for, so runs never deadlock.
"""

import contextlib
import fcntl
import hashlib
from pathlib import Path
from types import MappingProxyType

from countersign.application import lock_resources

STATE = Path(".local/state/countersign")
INSTALL_LOCK = "live.lock"
LOCKS = "locks"
EXCLUSIVE = fcntl.LOCK_EX | fcntl.LOCK_NB
SHARED = fcntl.LOCK_SH | fcntl.LOCK_NB
MODES = MappingProxyType(
    {lock_resources.EXCLUSIVE: EXCLUSIVE, lock_resources.SHARED: SHARED},
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
    install = stack.enter_context(lock_file(Path.home() / STATE / INSTALL_LOCK))
    if not locked(install, SHARED):
        return "An installation is in progress"
    if not locked(stack.enter_context(lock_file(lock_path(RUN, run))), EXCLUSIVE):
        return "This run is already active"
    return hold(stack, sources)


def hold(stack, sources):
    """Lock every project resource in a fixed order; why one is held elsewhere, else None."""
    for key, mode in sorted(lock_resources.resources(sources).items()):
        stream = stack.enter_context(lock_file(lock_path(*key)))
        if not locked(stream, MODES[mode]):
            return lock_resources.RUNNING.format(lock_resources.describe(key))
    return None


def conflict(sources):
    """Why a run on these sources could not start now, or None; nothing stays locked."""
    with contextlib.ExitStack() as stack:
        return hold(stack, sources)


def lock_path(kind, location):
    """A stable lock file name for a path, outside every project."""
    digest = hashlib.sha256(str(location).encode()).hexdigest()
    name = digest[:NAME_LENGTH]
    return Path.home() / STATE / LOCKS / f"{kind}-{name}.lock"


@contextlib.contextmanager
def lock_file(path):
    """Open (and create) a lock file; closing it releases the lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as stream:
        yield stream


def locked(stream, mode):
    """Try a lock without waiting."""
    try:
        fcntl.flock(stream, mode)
    except BlockingIOError:
        return False
    return True
