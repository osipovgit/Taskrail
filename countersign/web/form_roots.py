"""Project roots submitted through the browser form."""

import re
from pathlib import Path

MAX_ROOTS = 8
ALIAS = re.compile("[A-Za-z0-9_-]+")
ALIAS_UNSAFE = re.compile("[^A-Za-z0-9_-]+")
UNSAFE_PATH = frozenset("*?\r\n\x00")


def checked_roots(entries, runs):
    """Alias -> absolute existing directory; roots and the run store never overlap."""
    if not isinstance(entries, list) or not 1 <= len(entries) <= MAX_ROOTS:
        raise ValueError("Provide between one and eight project roots")
    roots = {}
    for entry in entries:
        alias, root = checked_entry(entry, roots)
        if overlaps(root, runs):
            raise ValueError("Project roots and the run storage must not overlap")
        if any(overlaps(root, Path(other)) for other in roots.values()):
            raise ValueError("Project roots must not overlap")
        roots[alias] = str(root)
    return roots


def checked_entry(entry, roots):
    """(alias, resolved directory) of one submitted project."""
    if not isinstance(entry, dict):
        raise ValueError("Each project needs a path and an optional alias")
    root = checked_path(entry.get("path"))
    return checked_alias(entry, roots) or derived_alias(root, roots), root


def checked_alias(entry, roots):
    """A unique alias of letters, digits, underscores or hyphens; empty derives one."""
    if set(entry) not in ({"path"}, {"alias", "path"}):
        raise ValueError("Each project needs a path and an optional alias")
    alias = entry.get("alias", "")
    if alias == "":
        return None
    valid = isinstance(alias, str) and bool(ALIAS.fullmatch(alias))
    if not valid or alias in roots:
        raise ValueError("Project aliases must be unique letters, digits, underscores or hyphens")
    return alias


def derived_alias(root, roots):
    """The directory name as an alias, numbered when another project already uses it."""
    base = ALIAS_UNSAFE.sub("-", root.name).strip("-") or "project"
    alias = base
    number = 1
    while alias in roots:
        number += 1
        alias = f"{base}-{number}"
    return alias


def checked_path(raw):
    """An existing absolute directory that is not a filesystem root."""
    if not isinstance(raw, str) or UNSAFE_PATH.intersection(raw):
        raise ValueError("Invalid project path")
    if not Path(raw).expanduser().is_absolute():
        raise ValueError("Use absolute project paths or ~/...")
    root = Path(raw).expanduser().resolve(strict=True)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError("Project must be an existing directory, not a filesystem root")
    return root


def overlaps(first, second):
    """Identical or nested paths."""
    return first.is_relative_to(second) or second.is_relative_to(first)
