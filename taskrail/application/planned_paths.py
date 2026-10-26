"""Resolve planned alias paths to editable regular files inside declared roots.

Model-facing checks also pass the run's protected patterns; the server's own readers
of planned files rely on the fixed protected folders alone.
"""

from pathlib import Path

from taskrail.application.source_tree import SKIP
from taskrail.core import protected_paths

PROTECTED = SKIP | frozenset((".git", ".hg", ".svn", ".opencode", ".ssh", ".kube"))
WILDCARDS = frozenset("*?\r\n")
PARENT = ".."


def safe_file(name, roots, protected=()):
    """Reject protected, linked, special or hard-linked targets before any write."""
    parts = planned_parts(name, roots, protected)
    path = roots[parts[0]]
    for part in parts[1:]:
        path /= part
        if path.is_symlink():
            raise ValueError(f"Symlink in planned path: {name}")
    check_target(path, name)
    return path


def planned_parts(name, roots, protected=()):
    """Split a normalized alias/relative/file name."""
    if not isinstance(name, str) or not name or WILDCARDS.intersection(name):
        raise ValueError("Invalid planned file")
    if not normalized(name, roots):
        raise ValueError(f"Use normalized alias/relative/file: {name}")
    parts = Path(name).parts
    folders = any(map(protected_part, parts[1:]))
    relative = "/".join(parts[1:])
    if folders or protected_paths.matches(f"/{relative}", protected):
        raise ValueError(f"Protected path in plan: {name}")
    return parts


def normalized(name, roots):
    """The alias must be declared and the path must already be normal."""
    parts = Path(name).parts
    canonical = str(Path(name)) == name and PARENT not in parts
    return canonical and len(parts) > 1 and parts[0] in roots


def protected_part(part):
    """VCS, tool state, credentials, environment files and generated folders."""
    return part in PROTECTED or part.startswith(".env")


def check_target(path, name):
    """Only regular single-link files may be replaced in place."""
    if path.exists() and not path.is_file():
        raise ValueError(f"Planned path is not a regular file: {name}")
    if path.exists() and path.stat().st_nlink != 1:
        raise ValueError(f"Hard-linked files cannot be edited: {name}")
