"""Freeze complete parent context outside the bounded child prompt."""

from taskrail.core.files import digest
from taskrail.infrastructure.agent_sync import atomic_write

NAME = "parent-task.md"
HASH = "parent_context_sha256"
MAX_BYTES = 4 * 1024 * 1024


def checked(text):
    """Validate a complete parent artifact without trimming its snapshots."""
    if not isinstance(text, str) or len(text.encode()) > MAX_BYTES:
        raise ValueError("Parent context must be text of at most 4 MiB")
    return text


def capture(task, inputs, state):
    """Copy the launcher's optional parent snapshot and record its integrity seal."""
    source = task.parent / NAME
    if not source.exists():
        return
    regular = source.is_file() and not source.is_symlink()
    if not regular or source.stat().st_size > MAX_BYTES:
        raise ValueError("Invalid parent context artifact")
    snapshot = source.read_bytes()
    atomic_write(inputs / NAME, snapshot)
    state[HASH] = digest(snapshot)


def verify(run, state):
    """A resumed child must see exactly the original parent context."""
    expected = state.get(HASH)
    if expected is None:
        return
    target = run / "00-input" / NAME
    if target.is_symlink() or not target.is_file():
        raise ValueError("Missing parent context; continuation refused")
    if digest(target.read_bytes()) != expected:
        raise ValueError("Parent context changed; continuation refused")
