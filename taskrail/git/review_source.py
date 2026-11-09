"""Read complete Git sources for independent review of selected Follow-up files."""

import os
import stat

from taskrail.core.files import digest
from taskrail.core.schema import require
from taskrail.git import original_files, process


def status_names(listing):
    """Working or staged paths from NUL-separated porcelain status with renames disabled."""
    return {entry[3:] for entry in listing.split("\0") if entry}


def head_file(root, relative):
    """Read bytes by immutable object ID and distinguish an absent path from a Git failure."""
    listing = process.checked(root, ["ls-tree", "-z", "HEAD", "--", relative])
    if not listing:
        return None
    mode, kind, oid = listing.split("\t", 1)[0].split()
    require(kind == "blob" and mode in original_files.MODES, "Unsupported Follow-up preimage")
    source_bytes = process.blob(root, oid)
    require(source_bytes is not None, "Cannot read Follow-up preimage")
    return int(mode, 8) & stat.S_IXUSR, source_bytes


def full_patch(root, original, path):
    """Include creations, deletions, executable bits and Git binary patches."""
    if original is None and not path.exists():
        return ""
    before = str(original or os.devnull)
    after = str(path) if path.exists() else os.devnull
    outcome = process.raw(
        root,
        ["diff", "--no-ext-diff", "--no-textconv", "--binary", "--no-index", "--", before, after],
        process.filter_settings(root),
    )
    require(
        outcome.returncode in {0, 1},
        outcome.stderr.decode(errors="replace") or "Cannot build the Follow-up diff",
    )
    return outcome.stdout.decode(errors="replace")


def blob_digest(root, oid):
    """Verify the entire staged or committed blob independently of transcript limits."""
    raw_bytes = process.blob(root, oid)
    require(raw_bytes is not None, "Cannot read Git source blob")
    return digest(raw_bytes)
