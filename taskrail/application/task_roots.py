"""Resolve declared project roots from a task header."""

import re
from pathlib import Path

from taskrail.application import task_scope
from taskrail.core import protected_paths

ROOTS = "roots"
ALIAS = re.compile("[A-Za-z0-9_-]+")
WILDCARDS = frozenset("*?\n\r")


def declared_access(meta, task, options):
    """Declared roots, protected path entries and a child's writable task scope."""
    roots = declared_roots(meta, task)
    protected = protected_paths.configured(options)
    patterns = protected_paths.read_patterns(protected)
    scope = task_scope.configured(meta, roots, patterns)
    return {ROOTS: roots, protected_paths.KEY: protected, task_scope.KEY: scope}


def declared_roots(meta, task):
    """Return alias -> resolved root; without a declaration use the task's repository."""
    declared = meta.get(ROOTS)
    if ROOTS not in meta:
        declared = {"project": str(repository(task))}
    if not isinstance(declared, dict):
        raise ValueError("roots must be an alias-to-path object")
    roots = {}
    for alias, raw in declared.items():
        root = project_root(alias, raw, task.parent)
        if any(overlaps(root, existing) for existing in roots.values()):
            raise ValueError("Project roots must not overlap")
        roots[alias] = root
    if not roots:
        raise ValueError("At least one project root required")
    return roots


def repository(task):
    """The nearest parent folder with a `.git` entry."""
    for parent in task.parents:
        if parent.joinpath(".git").exists():
            return parent
    raise ValueError("Task outside a repository needs taskrail-task JSON with roots")


def project_root(alias, raw, base):
    """Relative roots are resolved from the task folder."""
    if not ALIAS.fullmatch(alias) or not isinstance(raw, str):
        raise ValueError("Invalid root alias/path")
    root = base.joinpath(Path(raw).expanduser()).resolve(strict=True)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError("Project must be an existing non-filesystem-root directory")
    if WILDCARDS.intersection(str(root)):
        raise ValueError("Wildcard/newline in root is not supported")
    return root


def overlaps(root, other):
    """Nested or identical roots would make ownership ambiguous."""
    return root.is_relative_to(other) or other.is_relative_to(root)
