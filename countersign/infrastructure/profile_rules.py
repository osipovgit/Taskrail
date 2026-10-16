"""Closed permission rules for managed profiles; opencode applies the last matching rule.

opencode names a file absolutely or relative to one base directory (the Git worktree
for 1.x, the run directory for 2.x). Every allowed path gets both forms, so the same
rules hold for each naming; everything else stays denied.
"""

import os
from pathlib import Path
from types import MappingProxyType

from countersign.infrastructure.artifact_access import PROTECTED_READ_PATTERNS

ALLOW = "allow"
DENY = "deny"
CLOSED = MappingProxyType({"*": DENY})
# Allowing the whole base keeps absolute and parent-relative names denied.
WHOLE_BASE = MappingProxyType({"*": ALLOW, "/*": DENY, "..": DENY, "../*": DENY})


def permissions(roots, readable, writable, base=None):
    roots = list(roots)
    return {
        "*": DENY,
        "read": read_rules(roots, list(readable), base),
        "list": ALLOW,
        "glob": ALLOW,
        "grep": ALLOW,
        "external_directory": directory_rules([*roots, *readable]),
        "edit": edit_rules(roots, writable, base),
        "bash": DENY,
        "task": DENY,
        "skill": DENY,
    }


def read_rules(roots, readable, base):
    covered = set(map(Path, roots))
    whole = base is not None and Path(base) in covered
    rules = dict(WHOLE_BASE if whole else CLOSED)
    for path in map(Path, [*roots, *readable]):
        rules.update(dict.fromkeys(read_patterns(path, base), ALLOW))
    rules.update(dict.fromkeys(PROTECTED_READ_PATTERNS, DENY))
    return rules


def read_patterns(path, base):
    names = [str(path)]
    if base is not None:
        relative = os.path.relpath(str(path), str(base))
        names.extend([] if relative == os.curdir else [relative])
    if path.is_file():
        return names
    return [pattern for name in names for pattern in (name, f"{name}/*")]


def directory_rules(paths):
    """opencode checks external_directory against dirname(file) + '/*', apart from read rules."""
    rules = dict(CLOSED)
    for path in map(Path, paths):
        directory = path.parent if path.is_file() else path
        rules.update({str(directory): ALLOW, f"{directory}/*": ALLOW})
    return rules


def edit_rules(roots, writable, base):
    """Edits authorize exact files, absolutely and relative to ONE base; never wildcards."""
    rules = dict(CLOSED)
    for path in map(str, writable):
        anchor = permission_worktree(roots[0]) if base is None else Path(base)
        relative = os.path.relpath(path, str(anchor))
        rules.update({path: ALLOW, relative: ALLOW})
    return rules


def permission_worktree(directory):
    """Infer the normal opencode worktree without executing Git. Fail closed on gitfiles."""
    directory = Path(directory).resolve()
    for parent in (directory, *directory.parents):
        marker = parent / ".git"
        if marker.is_symlink() or marker.is_file():
            raise ValueError(
                "Gitfile/symlink worktree requires settings.permission_worktree from opencode logs"
            )
        if marker.is_dir():
            return parent
    return Path(directory.anchor)
