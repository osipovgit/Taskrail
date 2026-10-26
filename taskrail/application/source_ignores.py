"""Files Git ignores in each declared root: build output and tool caches, not source.

The integrity guard, check evidence and the project map share this view, so a linter
cache or test report written by an approved command is never mistaken for a source edit.
Outside a Git work tree, or when Git cannot answer, nothing is ignored.
"""

import subprocess

from taskrail.application import source_tree
from taskrail.git import process

LISTING = ("ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z")
FAILURES = (OSError, ValueError, subprocess.SubprocessError)


def current(roots, cache=None):
    """The guarded source of the roots: every file except what Git ignores."""
    return source_tree.snapshot(roots, cache, ignored(roots))


def ignored(roots):
    """Alias-relative names Git ignores; a name ending in / is a whole directory."""
    names = set()
    for alias, root in roots.items():
        names.update(f"{alias}/{name}" for name in listed(root))
    return frozenset(names)


def listed(root):
    """Ignored untracked paths below one root, relative to it."""
    try:
        outcome = process.invoke(root, list(LISTING))
    except FAILURES:
        return []
    if outcome.returncode != 0:
        return []
    return [name for name in outcome.stdout.split("\x00") if name]
