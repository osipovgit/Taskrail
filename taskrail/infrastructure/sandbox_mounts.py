"""The file system a sandboxed command sees, as bubblewrap mount options.

/tmp, /var/tmp and /run are private and empty. Home exposes only selected runtime
directories. Credential masks are applied after every mount, including project roots
and custom installations, so later binds cannot expose a masked configuration again.
"""

import os
from pathlib import Path

from taskrail.infrastructure import sandbox_paths, sandbox_secrets

GIT = ".git"
NULL = "/dev/null"
READ_ONLY = "--ro-bind"
TEMPORARY = "--tmpfs"
PRIVATE = ("/tmp", "/var/tmp", "/run")


def private():
    """Fresh temporary and runtime directories."""
    existing = filter(os.path.isdir, PRIVATE)
    return [option for path in existing for option in (TEMPORARY, path)]


def home():
    """An empty home with only existing runtime and cache components shown read-only."""
    return [TEMPORARY, str(Path.home()), *readonly(sandbox_paths.home())]


def installation(program):
    """Only the executable and conventional runtime components of a private prefix."""
    return readonly(sandbox_paths.installation(program))


def readonly(paths):
    """Read-only mounts for an explicit set of existing paths."""
    return [option for path in paths for option in (READ_ONLY, str(path), str(path))]


def project(roots, writable, protected, overlays):
    """The roots, writable, discarding writes or read-only; Git metadata never writable."""
    options = []
    for root in map(str, roots.values()):
        if writable:
            options.extend(("--bind", root, root))
        else:
            options.extend(discarded(root) if overlays else (READ_ONLY, root, root))
    for root in map(Path, roots.values()):
        metadata = str(root / GIT)
        if os.path.exists(metadata):
            options.extend((READ_ONLY, metadata, metadata))
    options.extend(sandbox_secrets.masks(roots.values(), protected, project=True))
    return options


def discarded(directory):
    """Mount options that keep a directory's writes in memory until the command ends."""
    return ["--overlay-src", directory, "--tmp-overlay", directory]


def credentials(program, protected):
    """Mask credentials exposed by runtime mounts after all project binds."""
    return sandbox_secrets.masks(
        (*sandbox_paths.home(), *sandbox_paths.installation(program)), protected
    )
