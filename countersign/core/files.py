"""Explicit file selection and post-stage integrity checks; NOT a sandbox."""

import functools
import hashlib
import json
import os
from pathlib import Path

CHUNK_BYTES = 1024 * 1024


def atomic_json(path, document):
    """Replace a JSON file atomically."""
    path = Path(path)
    pending = path.with_suffix(f"{path.suffix}.tmp")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(path)


def changed(before, after):
    """Sorted names whose fingerprint (a string) differs or exists on one side only."""
    differences = before.items() ^ after.items()
    return sorted({entry[0] for entry in differences})


def digest(source_bytes):
    """Return the SHA-256 hex digest of bytes."""
    return hashlib.sha256(source_bytes).hexdigest()


def stream_digest(path):
    """Hash large source files without reading the complete file into memory."""
    digestor = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(functools.partial(stream.read, CHUNK_BYTES), b""):
            digestor.update(chunk)
    return digestor.hexdigest()
