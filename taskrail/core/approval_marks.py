"""Durable denials also cover linked workers whose run directory does not exist yet."""

import contextlib
import fcntl
import time

from taskrail.core.files import atomic_json

OFF = "auto-approve.off"
DIRECTORY = ".approval-policy"


def marker(run):
    """Keep revocation independent of the parent and of worker startup."""
    return run.parent / DIRECTORY / f"{run.name}.off"


def revoked(run):
    """A marker can only remove authority; it never grants anything."""
    return (run / OFF).exists() or marker(run).exists()


@contextlib.contextmanager
def changing(run):
    """Serialize operator grants and revocations, including workers not created yet."""
    path = marker(run)
    path.parent.mkdir(exist_ok=True)
    with path.with_suffix(".lock").open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def revoke(run):
    """Persist denial before touching an optional worker directory."""
    with changing(run):
        payload = dict(revoked_at=time.time())
        atomic_json(marker(run), payload)
        if run.is_dir() and not run.is_symlink():
            atomic_json(run / OFF, payload)


def grant(run):
    """Only the operator decision writer clears a denial, never a delayed worker."""
    with changing(run):
        marker(run).unlink(missing_ok=True)
        (run / OFF).unlink(missing_ok=True)
