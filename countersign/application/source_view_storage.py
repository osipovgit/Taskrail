"""Internal provenance and content addressing for generated source views."""

import json

from countersign.core.files import digest
from countersign.core.schema import require

MANIFEST = "source-views.json"
ENCODING = "utf-8"


def directory(run):
    """Only the generated views are readable; their provenance ledger stays internal."""
    return run / "00-input/source-views"


def safe_storage(run):
    """Neither the output directory nor the internal ledger may traverse symlinks."""
    locations = [run, directory(run), run / MANIFEST]
    return all(canonical(path) for path in locations)


def canonical(path):
    """An internal artifact never traverses or replaces a symlink."""
    return path.resolve() == path and not path.is_symlink()


def manifest(run):
    """Missing provenance means no view is trusted, including on older runs."""
    index = run / MANIFEST
    if not index.is_file():
        return {}
    entries = json.loads(index.read_text(encoding=ENCODING))
    require(isinstance(entries, dict), "Invalid source view manifest")
    return entries


def recorded(run, path):
    """Malformed internal provenance fails as a contract error rather than a crash."""
    entry = manifest(run).get(str(path))
    require(isinstance(entry, dict), "Unknown source view")
    require(entry.get("path") == str(path), "Unknown source view")
    fields = ("source_path", "source_sha256", "view_sha256")
    require(
        all(isinstance(entry.get(key), str) for key in fields), "Invalid source view provenance"
    )
    return entry


def metadata(run, path, original, rendered):
    """Content addressing separates equal bytes from distinct source identities."""
    identity_bytes = b"\x00".join((str(path).encode(ENCODING), original))
    identity = digest(identity_bytes)
    target = directory(run) / f"{identity}.json"
    return dict(
        path=str(target),
        source_path=str(path),
        source_sha256=digest(original),
        view_sha256=digest(rendered),
        lines=len(rendered.splitlines()),
    )
