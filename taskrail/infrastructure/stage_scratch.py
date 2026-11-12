"""Temporary files shared by a single model attempt and its local commands."""

import shutil
import stat
from contextlib import contextmanager

from taskrail.infrastructure import sandbox_cache

DIRECTORY = "scratch"
PRIVATE = 0o700


def prepare(folder):
    """Create a private directory in the newly allocated attempt, outside project roots."""
    path = folder / DIRECTORY
    path.mkdir(mode=PRIVATE)
    return path


def discard(run, folder):
    """Clean up even if a command replaced the scratch directory with a link."""
    if folder.parent != run or folder.resolve() != folder:
        return
    path = folder / DIRECTORY
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
    else:
        try:
            shutil.rmtree(path)
        except PermissionError:
            sanitize(path)
            shutil.rmtree(path)


@contextmanager
def command_files(path):
    """Before handing control back to native tools, keep only independent regular files."""
    if path is None:
        yield
        return
    if path.resolve() != path or not path.is_dir():
        raise RuntimeError("Stage scratch directory is missing or redirected")
    try:
        yield
    finally:
        secure(path)


def secure(path):
    """An incomplete inspection must end the session before native tools regain access."""
    try:
        sanitize(path)
    except OSError as error:
        raise RuntimeError("Could not secure stage scratch files for native tools") from error


def sanitize(path):
    """A command-created link or special file cannot become a native read/write grant."""
    if path.parent.resolve() != path.parent:
        raise RuntimeError("Stage directory redirected during local execution")
    if path.is_symlink() or not path.is_dir():
        path.unlink(missing_ok=True)
        path.mkdir(mode=PRIVATE)
        return
    pending = [path]
    while pending:
        pending.extend(clean_directory(pending.pop()))


def clean_directory(directory):
    """Remove special entries without following links or changing any linked file."""
    directory.chmod(PRIVATE)
    for entry in directory.iterdir():
        metadata = entry.lstat()
        if stat.S_ISDIR(metadata.st_mode):
            yield entry
        elif not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            entry.unlink()


def mount(scratch, protected):
    """Mount the current attempt's scratch space and apply its protected-file masks."""
    if scratch is None:
        return []
    return [
        "--bind",
        str(scratch),
        str(scratch),
        *sandbox_cache.masks([scratch], protected, project=True),
    ]
