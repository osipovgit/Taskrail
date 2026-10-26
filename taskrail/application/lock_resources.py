"""What the projects of a run lock: their directories, parents and Git repositories.

A run holds each root exclusively and the root's parent directories shared, so a run on
a directory and a run on one of its subdirectories exclude each other, while independent
directories share only their common parents. A root inside a Git work tree also holds
that repository exclusively: two roots of one repository share its index, and a linked
worktree and its source checkout share the refs the integrity guard watches. The
repository is found from the root itself, so a worktree passed to another run still
names its source repository.
"""

from pathlib import Path

from taskrail.application.git_state import linked_directory
from taskrail.application.result_context import git_reference

ROOT = "root"
GIT = "git"
SHARED = "shared"
EXCLUSIVE = "exclusive"
RUNNING = "Another task is running on {0}"


def resources(sources):
    """(kind, location) -> mode for every source, its parent directories and repository."""
    modes = {}
    for source in map(canonical, sources):
        for parent in source.parents:
            modes.setdefault((ROOT, str(parent)), SHARED)
        modes[ROOT, str(source)] = EXCLUSIVE
        repository = identity(source)
        if repository is not None:
            modes[GIT, str(repository)] = EXCLUSIVE
    return modes


def contested(held, wanted):
    """Why sources wanted would conflict with sources another run holds, or None."""
    claimed = resources(held)
    for key, mode in resources(wanted).items():
        if key in claimed and EXCLUSIVE in {mode, claimed[key]}:
            return RUNNING.format(describe(key))
    return None


def describe(key):
    """A lock resource as the operator knows it."""
    kind, location = key
    return location if kind == ROOT else f"the Git repository {location}"


def canonical(source):
    """The resolved directory, so aliases and symlinks name one project."""
    return Path(source).expanduser().resolve()


def identity(source):
    """The common Git directory of the work tree that contains source, or None."""
    reference = git_reference(source)
    if not reference.exists():
        return None
    directory = linked_directory(reference) if reference.is_file() else reference
    common = directory / "commondir"
    if common.is_file():
        directory = directory / common.read_text(encoding="utf-8").strip()
    return directory.resolve()
