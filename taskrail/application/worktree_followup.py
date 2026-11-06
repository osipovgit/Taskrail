"""Carry a parent's index and working changes into a new linked worktree only."""

import os
import shutil
import stat
from pathlib import Path
from tempfile import TemporaryDirectory

from taskrail.application.original_checkout import COMMAND
from taskrail.core.schema import require
from taskrail.git import original_files, process

INDEX = ("ls-files", "--stage", "-z")
CHUNK_BYTES = 65536


def transfer(config, parent):
    """The parent is authenticated and locked; its checkout and index remain untouched."""
    for alias, record in config["worktrees"].items():
        with TemporaryDirectory() as scratch:
            snapshot = Snapshot(Path(parent["roots"][alias]), Path(scratch))
            snapshot.capture()
            snapshot.apply(Path(record["worktree"]))
        previous = parent["worktrees"][alias]
        record["original_source"] = previous.get("original_source", previous["source"])


class Snapshot:
    """Capture changed paths and staged blobs, retaining deletions, modes and symlinks."""

    def __init__(self, root, scratch):
        self.root = root
        self.scratch = scratch
        self.index = process.checked(root, list(INDEX))
        self.status = process.checked(root, list(COMMAND))
        self.head = process.checked(root, ["rev-parse", "HEAD"])
        self.paths = {}
        for entry in filter(None, self.index.split("\x00")):
            require(
                original_files.safe_name(entry.partition("\t")[2]),
                "Unsupported follow-up index path",
            )

    def capture(self):
        """Never follow a symlink into host files or silently omit an unsupported entry."""
        for entry in filter(None, self.status.split("\x00")):
            name = entry[3:]
            require(original_files.safe_name(name), "Unsupported follow-up Git path")
            saved = self.scratch / str(len(self.paths))
            copied = copy_path(self.root, Path(name), saved)
            self.paths[name] = saved if copied else None
        self.verify()

    def verify(self):
        """Concurrent checkout/index changes are an explicit failure, never a partial success."""
        current_index = process.checked(self.root, list(INDEX))
        require(current_index == self.index, "Follow-up index changed")
        require(
            process.checked(self.root, list(COMMAND)) == self.status, "Follow-up status changed"
        )
        require(
            process.checked(self.root, ["rev-parse", "HEAD"]) == self.head, "Follow-up HEAD moved"
        )
        for name, saved in self.paths.items():
            current = self.scratch / "current"
            if current.exists() or current.is_symlink():
                current.unlink()
            exists = copy_path(self.root, Path(name), current)
            require(
                same_path(current if exists else None, saved), f"Follow-up file changed: {name}"
            )

    def apply(self, target):
        """Git reconstructs the new index; copied working files retain unstaged differences."""
        require(
            process.checked(target, ["rev-parse", "HEAD"]) == self.head, "Follow-up base differs"
        )
        self.install_files(target)
        process.checked(target, ["read-tree", "--empty"])
        outcome = process.invoke(
            target, ["update-index", "-z", "--index-info"], input_data=self.index.encode()
        )
        require(outcome.returncode == 0, outcome.stderr or "Cannot copy follow-up index")
        self.verify()

    def install_files(self, target):
        """Replace only captured paths in the fresh checkout."""
        for name in self.paths:
            path = target / name
            if path.is_symlink() or path.is_file():
                path.unlink()
                prune_empty_parents(path.parent, target)
        for name, saved in self.paths.items():
            if saved is not None:
                path = target / name
                require(
                    not any(part.is_symlink() for part in path.parents), "Unsafe follow-up target"
                )
                if path.is_dir():
                    path.rmdir()
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(saved, path, follow_symlinks=False)


def prune_empty_parents(path, root):
    """A deleted tracked directory may be replaced with a file in the parent checkout."""
    while path != root:
        try:
            path.rmdir()
        except OSError:
            return
        path = path.parent


def copy_path(root, relative, target):
    """Pin each parent directory; copy ordinary files or the link itself, never its target."""
    with original_files.opened(root, original_files.DIRECTORY) as directory:
        for component in relative.parts[:-1]:
            try:
                with original_files.opened(component, original_files.DIRECTORY, directory) as child:
                    os.dup2(child, directory, inheritable=False)
            except (FileNotFoundError, NotADirectoryError):
                return False
        try:
            metadata = os.stat(relative.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return False
        if stat.S_ISDIR(metadata.st_mode):
            return False
        if stat.S_ISLNK(metadata.st_mode):
            target.symlink_to(os.readlink(relative.name, dir_fd=directory))
        else:
            require(stat.S_ISREG(metadata.st_mode), f"Unsupported follow-up file: {relative}")
            copy_regular(directory, relative.name, target)
    return True


def copy_regular(directory, name, target):
    """Stream binary files without executing filters or allocating their entire contents."""
    with (
        original_files.opened(name, original_files.REGULAR, directory) as descriptor,
        os.fdopen(descriptor, "rb", closefd=False) as source,
        target.open("wb") as destination,
    ):
        before = os.fstat(descriptor)
        shutil.copyfileobj(source, destination)
        require(before.st_ctime_ns == os.fstat(descriptor).st_ctime_ns, "Follow-up file changed")
        target.chmod(stat.S_IMODE(before.st_mode))


def same_path(source, saved):
    """Compare exact captured contents without following links."""
    if saved is None or source is None:
        return saved is None and source is None
    if saved.is_symlink():
        return source.is_symlink() and os.readlink(source) == os.readlink(saved)
    if source.is_symlink() or not source.is_file():
        return False
    with source.open("rb") as left, saved.open("rb") as right:
        while chunk := left.read(CHUNK_BYTES):
            if chunk != right.read(len(chunk)):
                return False
        source_mode = stat.S_IMODE(source.stat().st_mode)
        same_mode = source_mode == stat.S_IMODE(saved.stat().st_mode)
        return not right.read(1) and same_mode
