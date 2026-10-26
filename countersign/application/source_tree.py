"""Fingerprint declared source trees without following links or copying files."""

import os
from pathlib import Path

from countersign.core.files import stream_digest

PERMISSIONS = 0o777
NOTHING = frozenset()
SKIP = frozenset(
    (
        ".git",
        ".hg",
        ".svn",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".cache",
    )
)


def snapshot(roots, cache=None, ignored=NOTHING):
    """Map alias paths to content fingerprints; links are recorded, never followed."""
    known = {} if cache is None else cache
    found = {}
    for alias, root in roots.items():
        for path in sources(Path(root), Path(root), alias, ignored):
            found[label(alias, root, path)] = fingerprint(path, known)
    return found


def sources(directory, root, alias, ignored):
    """Yield files and links below a directory, skipping generated, VCS and ignored ones."""
    for entry in listing(directory):
        name = label(alias, root, entry)
        nested = entry.is_dir() and not entry.is_symlink()
        if not nested and name not in ignored:
            yield entry
        if nested and entry.name not in SKIP and f"{name}/" not in ignored:
            yield from sources(entry, root, alias, ignored)


def listing(directory):
    """Skip a folder that cannot be listed, as a directory walk does."""
    try:
        return list(directory.iterdir())
    except OSError:
        return []


def label(alias, root, path):
    """Return the alias-relative name used by plans and integrity records."""
    relative = path.relative_to(root).as_posix()
    return f"{alias}/{relative}"


def fingerprint(path, cache):
    """Hash regular files; record link targets; reject special files."""
    if path.is_symlink():
        target = os.readlink(path)
        return f"link:{target}"
    if not path.is_file():
        raise ValueError(f"Unsupported special file: {path}")
    return cached_fingerprint(path, cache)


def cached_fingerprint(path, cache):
    """Reuse a content hash only while all source identity fields are unchanged."""
    stamp = source_stamp(path)
    previous = cache.get(str(path))
    if previous and previous[0] == stamp:
        return previous[1]
    mode = stamp[-2] & PERMISSIONS
    signature = ":".join((format(mode, "o"), stream_digest(path)))
    cache[str(path)] = (stamp, signature)
    return signature


def source_stamp(path):
    """Track bytes, permissions and identity when reusing an integrity hash."""
    metadata = path.stat()
    return [
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_mode,
        metadata.st_nlink,
    ]
