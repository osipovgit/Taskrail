"""Recognize only application-owned approval sidecars during a fresh reset."""

import math

from taskrail.core import delivery_record
from taskrail.deployment.reset_records import document


def validate(directory):
    """Unknown files, redirected records and nonempty lock files forbid deletion."""
    for path in directory.iterdir():
        if not owned(path):
            raise ValueError(f"Unrecognized approval policy record: {path}")


def owned(path):
    """A normal run name followed by the exact marker or lock suffix."""
    if path.is_symlink() or not path.is_file():
        return False
    if not delivery_record.RUN_NAME.fullmatch(path.stem):
        return False
    if path.suffix == ".off":
        return valid_marker(document(path))
    return path.suffix == ".lock" and path.stat().st_size == 0


def valid_marker(marker):
    """A revocation contains only its finite, positive creation timestamp."""
    timestamp = marker.get("revoked_at")
    if set(marker) != {"revoked_at"} or isinstance(timestamp, bool):
        return False
    if not isinstance(timestamp, (int, float)):
        return False
    return timestamp > 0 and math.isfinite(timestamp)
