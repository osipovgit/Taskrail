"""Closed permission rules for managed profiles; opencode applies the last matching rule.

opencode names a file absolutely or relative to one base directory (the Git worktree
for 1.x, the run directory for 2.x). Every allowed path gets both forms, so the same
rules hold for each naming; everything else stays denied. Protected patterns come last,
so they deny reads and edits even inside allowed roots.
"""

import os
from pathlib import Path
from types import MappingProxyType

from taskrail.core import protected_paths

ALLOW = "allow"
DENY = "deny"
CLOSED = MappingProxyType({"*": DENY})
# A writable root never makes its Git metadata writable.
GIT_METADATA = (".git", ".git/*", "*/.git", "*/.git/*")
# Allowing the whole base keeps absolute and parent-relative names denied.
WHOLE_BASE = MappingProxyType({"*": ALLOW, "/*": DENY, "..": DENY, "../*": DENY})


def permissions(roots, readable, writable, base=None, protected=protected_paths.DEFAULT_PATTERNS):
    roots = list(roots)
    edit_denials = (*protected, *GIT_METADATA) if writable else ()
    return {
        "*": DENY,
        "read": denied_last(read_rules(roots, list(readable), base), protected),
        "list": ALLOW,
        "glob": ALLOW,
        "grep": ALLOW,
        "external_directory": directory_rules([*roots, *readable]),
        "edit": denied_last(edit_rules(roots, writable, base), edit_denials),
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
    return rules


def denied_last(rules, protected):
    """Protected patterns after every allowance; opencode applies the last match.

    An edit section without writable files stays closed and gets none.
    """
    for pattern in protected:
        rules.pop(pattern, None)
        rules[pattern] = DENY
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
    """Edits authorize exact files, absolutely and relative to ONE base.

    A writable directory, a whole root on a task branch, also covers what is below it.
    """
    rules = dict(CLOSED)
    if not writable:
        return rules
    anchor = permission_worktree(roots[0]) if base is None else Path(base)
    if anchor in set(map(Path, writable)):
        rules = dict(WHOLE_BASE)
    for path in map(Path, writable):
        names = [str(path), os.path.relpath(path, anchor)]
        if path.is_dir():
            names += [f"{name}/*" for name in names]
        rules.update(dict.fromkeys(names, ALLOW))
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
