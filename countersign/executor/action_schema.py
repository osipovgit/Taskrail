"""Closed action schema and safe bundle paths."""

import re
from pathlib import PurePosixPath

from countersign.core.schema import require
from countersign.executor import protocol

FIELDS = frozenset(("targets", "script", "files", "reason", "timeout_seconds"))
MAX_TARGETS = 16
MAX_TIMEOUT = 3600
MAX_FILES = 200


def validate(payload):
    """Reject ambiguous targets and executable payloads that were not reviewed."""
    require(isinstance(payload, dict), "Action must be an object")
    require(
        set(payload) == FIELDS, "Action requires targets, script, files, reason, timeout_seconds"
    )
    validate_targets(payload["targets"])
    timeout(payload["timeout_seconds"])
    protocol.text(payload["reason"])
    protocol.text(payload["script"])
    bundle(payload["files"])
    require(len(protocol.encode(payload)) <= protocol.MAX_SCRIPT, "Action bundle exceeds 512 KiB")
    return payload


def timeout(seconds):
    """Booleans and unbounded SSH runtimes are not accepted."""
    require(
        isinstance(seconds, int) and not isinstance(seconds, bool), "Timeout must be an integer"
    )
    require(1 <= seconds <= MAX_TIMEOUT, "Timeout must be between 1 and 3600 seconds")


def bundle(files):
    """Accept only bounded UTF-8 regular files, never local symlinks or paths."""
    require(isinstance(files, dict), "Files must be an object")
    require(len(files) <= MAX_FILES, "Too many bundle files")
    for name, body in files.items():
        bundle_path(name)
        require(isinstance(body, str), "Bundle body must be text")
        if body:
            protocol.text(body)


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
    """Require a nonempty distinct bounded target list."""
    require(isinstance(targets, list), "Targets must be a list")
    require(1 <= len(targets) <= MAX_TARGETS, "Invalid target count")
    targets = [protocol.label(target) for target in targets]
    require(len(set(targets)) == len(targets), "Duplicate targets")
