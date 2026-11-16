"""Closed action schema and safe bundle paths."""

import re
from pathlib import PurePosixPath

from taskrail.core.schema import require
from taskrail.executor import protocol

FIELDS = frozenset(("targets", "script", "files", "reason"))


def validate(payload):
    """Validate the requested destinations and exact remote payload."""
    require(isinstance(payload, dict), "Action must be an object")
    require(
        FIELDS <= payload.keys() <= FIELDS | {"timeout_seconds"},
        "Action requires targets, script, files and reason; timeout_seconds is optional",
    )
    validate_targets(payload["targets"])
    if "timeout_seconds" in payload:
        timeout(payload.get("timeout_seconds"))
    text(payload["reason"])
    text(payload["script"])
    bundle(payload["files"])
    return payload


def text(entry):
    require(
        isinstance(entry, str) and entry.strip() and "\x00" not in entry,
        "Expected nonempty text without NUL bytes",
    )


def timeout(seconds):
    """An explicit command deadline must be a positive integer."""
    require(
        isinstance(seconds, int) and not isinstance(seconds, bool), "Timeout must be an integer"
    )
    require(seconds > 0, "Timeout must be positive")


def bundle(files):
    """Accept UTF-8 regular files, never local symlinks or paths."""
    require(isinstance(files, dict), "Files must be an object")
    for name, body in files.items():
        bundle_path(name)
        require(isinstance(body, str), "Bundle body must be text")
        require("\x00" not in body, "Bundle body contains a NUL byte")


def bundle_path(name):
    """Reject traversal, absolute paths and reserved execution paths."""
    require(isinstance(name, str), "Bundle path must be text")
    path = PurePosixPath(name)
    require(not path.is_absolute() and ".." not in path.parts, "Bundle path escapes its directory")
    require(bool(path.parts) and str(path) == name, "Bundle path must be canonical")
    require(
        all(re.fullmatch(r"[A-Za-z0-9_.-]+", part) for part in path.parts), "Invalid bundle path"
    )
    require(not name.startswith("-") and name != "action.sh", "Reserved bundle path")


def validate_targets(targets):
    """Accept the whole selected inventory or distinct aliases."""
    if targets == "all":
        return
    require(isinstance(targets, list), "Targets must be a list or all")
    require(bool(targets), "Missing SSH targets")
    targets = [protocol.label(target) for target in targets]
    require(len(set(targets)) == len(targets), "Duplicate targets")
