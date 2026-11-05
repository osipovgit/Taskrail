"""Read bounded regular-file versions from a source checkout without following links."""

import os
import stat
from contextlib import ExitStack
from pathlib import Path

from taskrail.core.schema import require
from taskrail.git import process

FILE_LIMIT = 8 * 1024 * 1024
TOTAL_MIB = 128
TOTAL_LIMIT = TOTAL_MIB * 1024 * 1024
DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
REGULAR = os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW
MODES = frozenset(("100644", "100755"))


def working(root, relative, limit):
    """Pin every directory descriptor, even if the source checkout changes concurrently."""
    with ExitStack() as stack:
        directory = os.open(root, DIRECTORY)
        stack.callback(os.close, directory)
        for component in relative.parts[:-1]:
            directory = os.open(component, DIRECTORY, dir_fd=directory)
            stack.callback(os.close, directory)
        stream = stack.enter_context(open_regular(directory, relative.name))
        return read_regular(stream, limit)


def open_regular(directory, name):
    mode = os.stat(name, dir_fd=directory, follow_symlinks=False).st_mode
    require(stat.S_ISREG(mode), "not a regular file")
    descriptor = os.open(name, REGULAR, dir_fd=directory)
    return os.fdopen(descriptor, "rb")


def read_regular(stream, limit):
    """Reject special, oversized or concurrently modified files."""
    before = os.fstat(stream.fileno())
    require(stat.S_ISREG(before.st_mode), "not a regular file")
    require(before.st_size <= limit, "snapshot size limit")
    source_bytes = stream.read(limit + 1)
    after = os.fstat(stream.fileno())
    require(
        len(source_bytes) == before.st_size and before.st_ctime_ns == after.st_ctime_ns,
        "file changed during capture",
    )
    return source_bytes, bool(before.st_mode & stat.S_IXUSR)


def indexed(root, relative, limit):
    """Read the stage-zero blob by its immutable ID, including staged-only edits."""
    listing = process.checked(root, ["ls-files", "--stage", "-z", "--", str(relative)])
    metadata, _, name = listing.partition("\t")
    require(name == f"{relative}\x00", "index entry unavailable")
    return read_blob(root, metadata, limit)


def read_blob(root, metadata, limit):
    """Size-check the immutable Git object before loading a regular stage-zero blob."""
    mode, blob, stage = metadata.split()
    require(mode in MODES and stage == "0", "not a regular stage-zero blob")
    size = int(process.checked(root, ["cat-file", "-s", blob]))
    require(size <= limit, "snapshot size limit")
    source_bytes = process.blob(root, blob)
    require(source_bytes is not None and len(source_bytes) == size, "index blob unavailable")
    return source_bytes, mode == "100755"


def save(target, version):
    """Snapshot modes allow an explicit copy to preserve the executable bit."""
    source_bytes, executable = version
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source_bytes)
    target.chmod(stat.S_IRWXU if executable else stat.S_IRUSR | stat.S_IWUSR)
    return len(source_bytes)


def safe_name(name):
    """NUL-delimited Git paths must identify one canonical project entry."""
    relative = Path(name)
    if "\ufffd" in name:
        return False
    return (
        not relative.is_absolute()
        and relative.as_posix() == name
        and not {".git", "..", "."}.intersection(relative.parts)
        and name not in {"", "."}
    )
