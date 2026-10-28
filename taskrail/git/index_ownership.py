"""Which staged changes belong to the run, separately for each repository.

A run owns exactly the index entries its own successful `add` produced in a repository,
until a commit or another history write there. Staged changes of the user, in that or
any other repository, and an entry the run staged that changed since, are not the run's
to stage over or commit, even inside an approved file.
"""

import subprocess
from pathlib import Path

from taskrail.core.files import digest
from taskrail.core.schema import require
from taskrail.git import process, staging_receipt

ADD = "add"
SUCCEEDED = "SUCCEEDED"
UNOWNED = "not staged by this run"
EXECUTABLE_BIT = 0o100


def entries(repo, paths):
    """Path -> staged mode/blob/stage identity, or None when the entry is absent."""
    names = [path.relative_to(repo).as_posix() for path in paths]
    outcome = process.invoke(repo, ["ls-files", "--stage", "-z", "--", *names])
    require(outcome.returncode == 0, outcome.stderr or "Cannot read the Git index")
    found = index_blobs(repo, outcome.stdout)
    return {str(path): found.get(str(path)) for path in paths}


def index_blobs(repo, listing):
    """Keep executable modes and conflict stages as well as content identity."""
    found = {}
    for record in filter(None, listing.split("\x00")):
        description, name = record.split("\t", 1)
        found[str(repo / name)] = ":".join(description.split())
    return found


def owned(previous, repo):
    """Path -> blob of each entry the run staged in repo and has not committed yet."""
    staged = {}
    for record in previous:
        succeeded = record.get("status") == SUCCEEDED
        if not succeeded or record.get("repository") != str(repo):
            continue
        if record["request"]["argv"][0] == ADD:
            staged.update(record.get("staged", {}))
        else:
            staged = {}
    return staged


def belongs(repo, staged, recorded):
    """Every staged path holds exactly the entry the run staged for it."""
    found = entries(repo, staged)
    return {name: recorded.get(name, UNOWNED) for name in found} == found


def fingerprint(repo, root, argv):
    """What an add or commit would act on now; None for other writes.

    Repeating the same request is a replay only while this is unchanged.
    """
    if argv[0] == ADD:
        paths = [root / name for name in argv[2:]]
        return {str(path): file_digest(path) for path in paths}
    if argv[0] == "commit":
        staged = process.checked(repo, ["diff", "--cached", "--name-only", "--no-renames", "-z"])
        names = filter(None, staged.split("\x00"))
        return entries(repo, [repo / name for name in names])
    return None


def file_digest(path):
    """Working content and executable bit; a mode-only edit permits a fresh add."""
    if not path.is_file():
        return None
    executable = bool(path.stat().st_mode & EXECUTABLE_BIT)
    return f"{executable}:{digest(path.read_bytes())}"


def record(root, entry):
    """After a successful add, keep the exact entries it staged as the run's own."""
    argv = entry["request"]["argv"]
    if entry["status"] != SUCCEEDED or argv[0] != ADD:
        return
    paths = [root / name for name in argv[2:]]
    repo = Path(entry["repository"])
    try:
        entry["staged"] = staging_receipt.capture(repo, entry, paths, entries)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        entry.update(status="UNKNOWN", stderr=f"Cannot record staged source identity: {error}")
