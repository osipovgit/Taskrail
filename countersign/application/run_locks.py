"""Run locks: the installation lock (shared), one lock per source root and one per run.

Runs on different projects proceed in parallel. The installer takes the installation
lock exclusively, so it waits for every active run.
"""

import contextlib
import fcntl
import hashlib
from pathlib import Path

STATE = Path(".local/state/countersign")
INSTALL_LOCK = "live.lock"
LOCKS = "locks"
EXCLUSIVE = fcntl.LOCK_EX | fcntl.LOCK_NB
NAME_LENGTH = 32
RUN = "run"
ROOT = "root"


@contextlib.contextmanager
def run_locks(sources, run):
    """Yield None while every lock is held, or why the run cannot start now."""
    with contextlib.ExitStack() as stack:
        yield acquire(stack, sources, run)


def acquire(stack, sources, run):
    """Take the locks in a fixed order and stop at the first one that is held."""
    install = stack.enter_context(lock_file(Path.home() / STATE / INSTALL_LOCK))
    if not locked(install, fcntl.LOCK_SH | fcntl.LOCK_NB):
        return "An installation is in progress"
    if not locked(stack.enter_context(lock_file(lock_path(RUN, run))), EXCLUSIVE):
        return "This run is already active"
    for source in sorted(map(str, sources)):
        if not locked(stack.enter_context(lock_file(lock_path(ROOT, source))), EXCLUSIVE):
            return f"Another task is running on {source}"
    return None


def busy(path):
    """True while another process holds the lock at path."""
    with lock_file(path) as stream:
        return not locked(stream, EXCLUSIVE)


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
