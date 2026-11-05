"""Freeze the submitting checkout separately from the clean, writable task branch."""

import json
import shutil
import stat
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from taskrail.core import prompt_texts, protected_paths
from taskrail.core.schema import require
from taskrail.git import original_files, process
from taskrail.infrastructure import sandbox_secrets

DIRECTORY = "00-input/original"
STATUS = "status.jsonl"
FAILURES = (OSError, ValueError, subprocess.SubprocessError)
COMMAND = (
    "status",
    "--porcelain=v1",
    "-z",
    "--no-renames",
    "--untracked-files=all",
    "--ignore-submodules=none",
)


def capture(run, config):
    """Once per isolated launch, before planning; a failed listing never means clean."""
    if not config.get("worktrees"):
        return
    directory = run / DIRECTORY
    directory.mkdir(mode=stat.S_IRWXU)
    remaining = original_files.TOTAL_LIMIT
    with (directory / STATUS).open("x", encoding="utf-8") as stream:
        for alias in config["worktrees"]:
            record = config["worktrees"][alias]
            remaining = Snapshot(directory / alias, record, config, remaining).capture(stream)


class Snapshot:
    """One JSON line per path; names and errors cannot inject additional status records."""

    def __init__(self, destination, record, config, remaining):
        self.destination = destination
        self.root = Path(record["source"])
        self.base = record["base"]
        self.worktree = record["worktree"]
        self.protected = (*protected_paths.patterns(config), *sandbox_secrets.MANDATORY)
        self.remaining = remaining

    def capture(self, stream):
        header = dict(alias=self.destination.name, base=self.base, worktree=self.worktree)
        header["root"] = str(self.root)
        try:
            entries = self.listing()
        except FAILURES as error:
            header["error"] = str(error)
            write_row(stream, header)
            return self.remaining
        header["changed_entries"] = len(entries)
        write_row(stream, header)
        for entry in entries:
            row = self.entry(entry[:2], entry[3:])
            write_row(stream, row)
        return self.remaining

    def listing(self):
        head = process.checked(self.root, ["rev-parse", "HEAD"]).strip()
        require(head == self.base, "HEAD moved during isolation")
        settings = process.filter_settings(self.root)
        listing = process.invoke(self.root, list(COMMAND), settings)
        require(listing.returncode == 0, listing.stderr or "Git status failed")
        return list(filter(None, listing.stdout.split("\x00")))

    def entry(self, status, name):
        row = dict(xy=status, path=name, alias=self.destination.name)
        if not original_files.safe_name(name):
            return dict(row, unavailable="unsupported Git path")
        if self.private(name):
            return dict(row, unavailable="protected path")
        if "U" in status or status in {"AA", "DD"}:
            return dict(row, unavailable="unmerged index")
        if status[0] not in " ?D":
            row["index"] = self.copy("index", name, original_files.indexed)
        if status[1] not in " D":
            row["working"] = self.copy("working", name, original_files.working)
        return row

    def private(self, name):
        path = self.root / name
        return sandbox_secrets.private(path, path, project=True) or protected_paths.matches(
            path, self.protected
        )

    def copy(self, layer, name, reader):
        path = self.destination / layer / name
        limit = min(original_files.FILE_LIMIT, self.remaining)
        try:
            version = reader(self.root, Path(name), limit)
        except FAILURES as error:
            return dict(unavailable=str(error))
        self.remaining -= original_files.save(path, version)
        return str(path.relative_to(self.destination.parent))


def write_row(stream, row):
    encoded = json.dumps(row, ensure_ascii=False)
    stream.write(f"{encoded}\n")


def inherit(parent, run):
    """A reviewed child sees the launch snapshot, even if the original checkout changed."""
    source = parent / DIRECTORY
    if source.is_dir():
        require(source.resolve() == source, "Unsafe original snapshot directory")
        target = run / DIRECTORY
        if target.exists():
            require(target.resolve() == target, "Unsafe inherited snapshot directory")
            require(
                (target / STATUS).read_bytes() == (source / STATUS).read_bytes(),
                "Conflicting launch snapshots",
            )
            return
        with TemporaryDirectory(dir=target.parent) as scratch:
            staged = Path(scratch) / "snapshot"
            shutil.copytree(source, staged, symlinks=True, ignore=checked_entries)
            staged.rename(target)


def checked_entries(directory, names):
    """A parent artifact cannot introduce links, devices or named pipes into a child."""
    for name in names:
        path = Path(directory) / name
        require(not path.is_symlink(), "Unexpected link in original snapshot")
        require(path.is_dir() or path.is_file(), "Unexpected special file in original snapshot")
    return []


def status_path(run):
    status = run / DIRECTORY / STATUS
    return str(status) if status.is_file() else None


def status_note(run, request):
    """Keep isolated status output distinct from launch evidence in the Git transcript."""
    path = run / DIRECTORY / STATUS
    if not path.is_file() or not isinstance(request["argv"], list):
        return ""
    if request["argv"][:1] != ["status"]:
        return ""
    with path.open(encoding="utf-8") as stream:
        for row in map(json.loads, stream):
            if row.get("worktree") == request["root"]:
                return prompt_texts.text(
                    "git.original_status", count=row.get("changed_entries", "unknown"), path=path
                )
    return ""
