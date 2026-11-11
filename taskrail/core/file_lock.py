"""POSIX file locks shared by workers, probes and the installer."""

import contextlib
import fcntl
import os

EXCLUSIVE = fcntl.LOCK_EX | fcntl.LOCK_NB
SHARED = fcntl.LOCK_SH | fcntl.LOCK_NB


@contextlib.contextmanager
def scoped(path, mode, *, probe=False):
    """Retire unused lock files. A waiter must hold the inode still at this path."""
    if probe and not path.exists():
        yield True
        return
    while True:
        with open_lock(path) as stream:
            if not locked(stream, mode):
                yield False
                return
            if not same_lock(path, stream):
                continue
            try:
                yield True
            finally:
                retire(path, stream)
            return


def retire(path, stream):
    """The last holder can remove its name while holding an exclusive lock."""
    if locked(stream, EXCLUSIVE) and same_lock(path, stream):
        path.unlink()


def same_lock(path, stream):
    """Another holder may have removed the name while this descriptor waited."""
    try:
        return os.path.samestat(path.stat(), os.fstat(stream.fileno()))
    except FileNotFoundError:
        return False


@contextlib.contextmanager
def open_lock(path):
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
