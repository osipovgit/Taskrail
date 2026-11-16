"""Pass an ordinary account's read-only project file over the local executor socket."""

import fcntl
import os
import re
import stat
from contextlib import ExitStack, contextmanager
from pathlib import Path

from taskrail.core.files import digest
from taskrail.core.schema import require
from taskrail.executor import inventory_groups

FILENAME = "file"
NAME_PATTERN = re.compile(r"[\w-][\w.-]*\.ya?ml")
DIRECTORY_FLAGS = os.O_PATH | os.O_DIRECTORY | os.O_NOFOLLOW
FILE_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
MAX_BYTES = 8 * 1024 * 1024


@contextmanager
def opened(path):
    """Open a canonical regular file without following links in any path component."""
    path = Path(path)
    require(path.is_absolute() and ".." not in path.parts, "Expected an absolute inventory path")
    with ExitStack() as stack:
        parent = None
        for part in path.parts[:-1]:
            parent = os.open(part, DIRECTORY_FLAGS, dir_fd=parent)
            stack.callback(os.close, parent)
        fd = os.open(path.name, FILE_FLAGS, dir_fd=parent)
        stack.callback(os.close, fd)
        validate(fd)
        yield fd


def validate(fd):
    attributes = os.fstat(fd)
    if not stat.S_ISREG(attributes.st_mode) or attributes.st_size > MAX_BYTES:
        raise inventory_groups.InventoryError("Expected a regular inventory of at most 8 MiB.")
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    if flags & os.O_ACCMODE != os.O_RDONLY or flags & os.O_PATH:
        raise inventory_groups.InventoryError("Expected a readable, read-only inventory file.")


def read_descriptor(fd):
    if fd is None:
        raise inventory_groups.InventoryError(
            "The project inventory is unavailable. Repeat the lookup."
        )
    validate(fd)
    raw = os.pread(fd, MAX_BYTES + 1, 0)
    if len(raw) > MAX_BYTES:
        raise inventory_groups.InventoryError("Inventory exceeds the size limit.")
    return raw


def valid_name(filename):
    path = Path(filename)
    if path.is_absolute() and ".." not in path.parts:
        return str(path) == filename and bool(NAME_PATTERN.fullmatch(path.name))
    return bool(NAME_PATTERN.fullmatch(filename))


def project(selection):
    return bool(selection and Path(selection[FILENAME]).is_absolute())


def pin(selection):
    if project(selection):
        with opened(selection[FILENAME]) as descriptor:
            return dict(selection, sha256=digest(read_descriptor(descriptor)))
    return selection
