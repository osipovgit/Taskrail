"""Match native file spellings to exact approved targets without granting access."""

import os
import re
from pathlib import Path

UNREAD = re.compile(
    r"(?:Error: )?You must read file (.+) before overwriting it\. Use the Read tool first"
)


def approved(name, targets):
    """Collapse dot segments only within exact approved paths and matching filesystem resolution."""
    if not isinstance(name, str):
        return None
    if not os.path.isabs(name) or "\0" in name:
        return None
    normalized = os.path.normpath(name)
    if normalized not in targets:
        return None
    try:
        resolved = unlinked(name)
    except (OSError, RuntimeError, ValueError):
        return None
    return normalized if resolved == normalized else None


def unlinked(name):
    """A symlink, including a loop hidden before '..', cannot establish file identity."""
    path = Path(name)
    if any(part.is_symlink() for part in (path, *path.parents)):
        return None
    return str(path.resolve())


def from_call(record, targets):
    """Resolve the recorded input without changing the diagnostic's original spelling."""
    arguments = record.get("input", {})
    return approved(arguments.get("filePath"), targets)


def unread(failure, target):
    """The exact native rejection and its input must identify the same approved file."""
    matched = UNREAD.fullmatch(failure.get("error", ""))
    if not matched or target is None:
        return False
    if failure.get("tool") not in {"edit", "write"}:
        return False
    supplied = from_call(failure, (target,))
    reported = approved(matched[1], (target,))
    return supplied == target and reported == target
