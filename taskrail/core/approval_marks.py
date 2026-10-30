"""Durable denials also cover linked workers whose run directory does not exist yet."""

import contextlib
import fcntl
import time

from taskrail.core import owned_paths
from taskrail.core.files import atomic_json

OFF = "auto-approve.off"
DIRECTORY = ".approval-policy"


def marker(run, suffix=".off"):
    """Keep revocation independent of the parent and of worker startup."""
    run = owned_paths.child(run.parent, run.name)
    return owned_paths.child(run.parent, f"{DIRECTORY}/{run.name}{suffix}")


def revoked(run):
    """A marker can only remove authority; it never grants anything."""
    try:
        return denied(run)
    except ValueError:
        return True


def denied(run):
    """Validate both denial locations before reading either existence flag."""
    local = owned_paths.child(run, OFF)
    policy = marker(run)
    return local.exists() or policy.exists()


def granted(run):
    """Only the personal decision writer creates durable grants outside source roots."""
    try:
        path = marker(run, ".grant.json")
    except ValueError:
        return False
    return path.is_file()


@contextlib.contextmanager
def changing(run):
    """Serialize operator grants and revocations, including workers not created yet."""
    path = marker(run, ".lock")
    path.parent.mkdir(exist_ok=True)
    with path.open("a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def revoke(run):
    """Persist denial before touching an optional worker directory."""
    with changing(run):
        payload = dict(revoked_at=time.time())
        atomic_json(marker(run), payload)
        local = owned_paths.child(run, OFF)
        if local.parent.is_dir():
            atomic_json(local, payload)


def grant(run):
    """Persist a personal grant before clearing denial; workers never call this."""
    with changing(run):
        path = marker(run, ".grant.json")
        atomic_json(path, dict(granted_at=time.time()))
        marker(run).unlink(missing_ok=True)
        owned_paths.child(run, OFF).unlink(missing_ok=True)
