"""Which staged changes belong to the run, separately for each repository.

A run owns exactly the index entries its own successful `add` produced in a repository,
until a commit or another history write there. Staged changes of the user, in that or
any other repository, and an entry the run staged that changed since, are not the run's
to stage over or commit, even inside an approved file.
"""

from pathlib import Path

from countersign.core.files import digest
from countersign.core.schema import require
from countersign.git import process

ADD = "add"
SUCCEEDED = "SUCCEEDED"
UNOWNED = "not staged by this run"


def entries(repo, paths):
    """Path -> staged blob ID, or None when the index has no entry for the path."""
    names = [path.relative_to(repo).as_posix() for path in paths]
    outcome = process.invoke(repo, ["ls-files", "--stage", "-z", "--", *names])
    require(outcome.returncode == 0, outcome.stderr or "Cannot read the Git index")
    found = index_blobs(repo, outcome.stdout)
    return {str(path): found.get(str(path)) for path in paths}


def index_blobs(repo, listing):
    """Path -> blob ID from the output of `git ls-files --stage -z`."""
    found = {}
    for record in filter(None, listing.split("\x00")):
        description, name = record.split("\t", 1)
        found[str(repo / name)] = description.split()[1]
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
    """The digest of a working-tree file, or None when it is absent."""
    return digest(path.read_bytes()) if path.is_file() else None


def record(root, entry):
    """After a successful add, keep the exact entries it staged as the run's own."""
    argv = entry["request"]["argv"]
    if entry["status"] != SUCCEEDED or argv[0] != ADD:
        return
    paths = [root / name for name in argv[2:]]
    try:
        entry["staged"] = entries(Path(entry["repository"]), paths)
    except ValueError:
        entry["staged"] = {}
