"""Authenticated readable JSON views of approved sources with oversized lines."""

from pathlib import Path

from countersign.application import evidence, source_view_json, source_view_storage, source_windows
from countersign.core.files import atomic_json
from countersign.core.schema import require
from countersign.infrastructure.agent_sync import atomic_write

MAX_BYTES = 8 * 1024 * 1024
MAX_LINE = source_view_json.MAX_LINE
MANIFEST = source_view_storage.MANIFEST
ENCODING = "utf-8"


def directory(run):
    """Only the generated views are readable; their provenance ledger stays internal."""
    return source_view_storage.directory(run)


def prepare(run, path, roots):
    """Create a bounded view or return None; preparation never counts as an observation."""
    path = Path(path)
    if not approved_source(path, roots) or not source_view_storage.safe_storage(run):
        return None
    try:
        return create(run, path)
    except (OSError, ValueError, RecursionError):
        return None


def approved_source(path, roots):
    """Use only canonical regular sources within approved roots, excluding protected files."""
    regular = path.is_absolute() and path.is_file()
    return regular and source_windows.source_path(path, roots) == path


def create(run, path):
    """Bind an immutable view to both the source identity and its exact bytes."""
    documents = source_contents(path)
    if documents is None:
        return None
    entry = source_view_storage.metadata(run, path, *documents)
    target = Path(entry["path"])
    require(not target.is_symlink(), "Source view cannot replace a symlink")
    atomic_write(target, documents[1])
    entries = source_view_storage.manifest(run)
    entries[str(target)] = entry
    atomic_json(run / MANIFEST, entries)
    return entry


def source_contents(path):
    """Only oversized lines in bounded UTF-8 JSON sources need a derived view."""
    with path.open("rb") as stream:
        original = stream.read(MAX_BYTES + 1)
    if len(original) > MAX_BYTES:
        return None
    text = original.decode(ENCODING)
    if not any(len(line) > MAX_LINE for line in text.splitlines()):
        return None
    rendered = source_view_json.formatted(text).encode(ENCODING)
    return original, rendered


def validate(run, path, roots):
    """A cited view needs unchanged source and output bytes plus server-owned provenance."""
    path = Path(path)
    approved = source_view_storage.safe_storage(run) and path.parent == directory(run)
    require(approved and source_view_storage.canonical(path), "Invalid source view path")
    entry = source_view_storage.recorded(run, path)
    original = Path(entry["source_path"])
    require(approved_source(original, roots), "Source view source is outside approved roots")
    require(
        evidence.fingerprint(original) == entry["source_sha256"],
        f"Source view is stale; its source changed: {original}",
    )
    require(evidence.fingerprint(path) == entry["view_sha256"], "Source view content changed")
    return entry
