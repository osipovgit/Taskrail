"""Whether a `.git` entry belongs to Git: a directory with HEAD, or a gitfile naming one.

An empty or unrelated `.git` (left behind by another tool) does not make its parent a
repository; Git itself would not treat it as one.
"""

from pathlib import Path

GITDIR = "gitdir:"


def control(path):
    """True for a Git directory with HEAD or a `gitdir:` file; any other entry is not Git."""
    path = Path(path)
    if path.is_dir():
        return path.joinpath("HEAD").is_file()
    if not path.is_file():
        return False
    try:
        with path.open(encoding="utf-8", errors="replace") as stream:
            return stream.read(len(GITDIR)) == GITDIR
    except OSError:
        return False
