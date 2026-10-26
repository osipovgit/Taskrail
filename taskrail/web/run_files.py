"""Bounded, contained reads of run artifacts for the dashboard."""

import json
from functools import lru_cache
from pathlib import Path

from taskrail.observability.telemetry import inspect_events

JSON_LIMIT = 8 * 1024 * 1024
TEXT_LIMIT = 200000
TEXT = "text"
TRUNCATED = "truncated"
CACHED_FILES = 128


def contained(base, relative):
    """A path inside base; symlinks and escapes are refused."""
    root = Path(base).resolve()
    candidate = root / relative
    if candidate.is_symlink():
        raise ValueError("Symlinks are not served")
    resolved = candidate.resolve()
    if root not in resolved.parents:
        raise ValueError("Path outside runs directory")
    return resolved


def read_json(path, limit=JSON_LIMIT):
    """A JSON artifact of bounded size."""
    if path.stat().st_size > limit:
        raise ValueError("JSON artifact is too large")
    return json.loads(path.read_text(encoding="utf-8"))


def text_tail(path, limit=TEXT_LIMIT):
    """The last `limit` bytes of a text artifact, decoded leniently."""
    if not path.is_file():
        return {TEXT: "", TRUNCATED: False}
    size = path.stat().st_size
    with path.open("rb") as stream:
        stream.seek(max(0, size - limit))
        tail = stream.read(limit).decode("utf-8", "replace")
    return {TEXT: tail, TRUNCATED: size > limit}


def optional_json(run, relative):
    """A contained JSON artifact, or None while it is missing or being written."""
    try:
        return read_json(contained(run, relative))
    except (OSError, ValueError):
        return None


@lru_cache(maxsize=CACHED_FILES)
def historical_telemetry(path, size, mtime):
    """Telemetry of an unchanged event file is computed once."""
    return inspect_events(Path(path))


def stage_telemetry(run, directory):
    """JSONL is authoritative after interruption; telemetry.json may lag its last event."""
    path = contained(run, f"{directory}/events.jsonl")
    try:
        stat = path.stat()
    except OSError:
        return inspect_events(path)
    return historical_telemetry(str(path), stat.st_size, stat.st_mtime_ns)
