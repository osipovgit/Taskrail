"""Prove a completed history write changed only the revision and tree it was allowed to."""

from pathlib import Path

from taskrail.core.schema import require
from taskrail.git import process

BEFORE = "head_before"
HISTORY_WRITES = frozenset(("commit", "revert", "cherry-pick", "merge"))
ERROR = "Git history changed outside the controlled write"


def head(repo, unborn=False):
    """An absent HEAD is valid only on a verified unborn branch before its first commit."""
    observed = process.invoke(repo, ["rev-parse", "--verify", "HEAD"])
    if observed.returncode == 0:
        return observed.stdout.strip()
    require(unborn, "Cannot resolve committed Git HEAD")
    branch = process.checked(repo, ["symbolic-ref", "--quiet", "HEAD"]).strip()
    missing = process.invoke(repo, ["show-ref", "--verify", "--quiet", branch])
    require(missing.returncode == 1, "Cannot verify an unborn Git branch")
    return None


def prepare(repo, entry):
    """Pin the starting revision before source/index preflight and the actual write."""
    if entry["request"]["argv"][0] in HISTORY_WRITES | {"add"}:
        entry[BEFORE] = head(repo, unborn=True)


def verify(repo, entry, revision):
    """Validate topology, complete changed-path set and the exact approved commit index."""
    before = entry[BEFORE]
    argv = entry["request"]["argv"]
    if argv[0] == "merge":
        require(revision == argv[-1], ERROR)
    else:
        parents = process.checked(repo, ["rev-list", "--parents", "-n", "1", revision]).split()
        expected = [before] if before else []
        require(parents[1:] == expected, ERROR)
        require(revision != before, ERROR)
    paths = set(entry["affected_paths"])
    require(changed_paths(repo, before, revision) == paths, ERROR)
    if argv[0] == "commit":
        verify_index(repo, entry["fingerprint"], revision)


def changed_paths(repo, before, revision):
    """Compare pinned trees, including the entire initial tree on an unborn branch."""
    if before:
        argv = ["diff", "--name-only", "--no-renames", "-z", before, revision]
    else:
        argv = [
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            "-z",
            revision,
        ]
    names = filter(None, process.checked(repo, argv).split("\x00"))
    return {str(repo / name) for name in names}


def verify_index(repo, expected, revision):
    """A concurrent index replacement must not be mistaken for this run's commit."""
    for name, identity in expected.items():
        relative = Path(name).relative_to(repo).as_posix()
        listing = process.checked(repo, ["ls-tree", "-z", revision, "--", relative])
        require(
            tree_entry(listing) == identity, "Committed content differs from the approved Git index"
        )


def tree_entry(listing):
    """Match a committed tree entry with the staged mode/blob/stage identity."""
    if not listing:
        return None
    mode, _, blob = listing.split("\t", 1)[0].split()
    return f"{mode}:{blob}:0"
