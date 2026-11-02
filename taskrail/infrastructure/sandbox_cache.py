"""Reuse the credential masks of unchanged trees, so a sandboxed command starts at once.

Finding credential names walks every mounted runtime tree and project root, which takes
seconds in large toolchain caches. A name can only appear by adding or renaming an
entry, which changes its directory's modification time, so the masks of a tree whose
directories all keep their times are still exact.
"""

import functools
import os

from taskrail.infrastructure import sandbox_secrets

CACHED = 16


def masks(roots, protected, project=False):
    """sandbox_secrets.masks, recomputed only when a directory of the roots changed."""
    named = tuple(dict.fromkeys(map(str, roots)))
    return list(computed(named, tuple(protected), project, signature(named)))


@functools.lru_cache(maxsize=CACHED)
def computed(roots, protected, project, stamp):
    """The masks of the roots in the state the stamp describes."""
    return tuple(sandbox_secrets.masks(roots, protected, project))


def signature(roots):
    """Every directory below the roots with its modification time; unreadable ones too."""
    stamps = []
    for root in roots:
        for directory, _, _ in os.walk(root):
            try:
                stamps.append((directory, os.stat(directory).st_mtime_ns))
            except OSError:
                stamps.append((directory, None))
        if not os.path.isdir(root):
            stamps.append((root, os.path.exists(root)))
    return tuple(stamps)
