"""An add owns only index entries matching the worktree input pinned before execution."""

import stat

from taskrail.core.schema import require
from taskrail.git import history_outcome, process

ERROR = "Git index changed outside the controlled add"


def capture(repo, entry, paths, reader):
    """Read, verify and recheck before publishing any owned staged identity."""
    staged = reader(repo, paths)
    verify(repo, entry, staged)
    require(reader(repo, paths) == staged, ERROR)
    same_head(repo, entry)
    return staged


def verify(repo, entry, staged):
    """Hash immutable staged blobs, including mode, instead of trusting the current index."""
    expected = entry["fingerprint"]
    require(staged.keys() == expected.keys(), ERROR)
    for name, identity in staged.items():
        require(working_identity(repo, identity) == expected[name], ERROR)
    same_head(repo, entry)


def working_identity(repo, identity):
    """Compare index content with the exact raw bytes and owner x-bit authorized for add."""
    if identity is None:
        return None
    mode, blob, stage = identity.split(":")
    require(stage == "0", ERROR)
    outcome = process.invoke(repo, ["cat-file", "blob", blob])
    require(outcome.returncode == 0, "Cannot verify staged Git content")
    executable = bool(int(mode, 8) & stat.S_IXUSR)
    return f"{executable}:{outcome.stdout_sha256}"


def same_head(repo, entry):
    """Index writes may never advance HEAD, including creating a previously unborn branch."""
    expected = entry[history_outcome.BEFORE]
    require(history_outcome.head(repo, unborn=True) == expected, ERROR)
