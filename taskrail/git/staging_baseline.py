"""Trusted committed content for later staging, separate from immutable original preimages."""

import json
import subprocess
from pathlib import Path

from taskrail.core.schema import require
from taskrail.git import history_outcome, process

KEY = "source_baseline"
HISTORY_WRITES = history_outcome.HISTORY_WRITES
SUCCEEDED = "SUCCEEDED"
EXECUTABLE_BIT = 0o100


def originals(environment):
    """Read immutable preimages separately from the run's later controlled commits."""
    found = {}
    for name, signature in json.loads(
        (environment["run"] / "00-input/manifest.json").read_text()
    ).items():
        parts = name.split("/", 1)
        path = environment["roots"][parts[0]] / parts[1]
        found[str(path)] = signature
    return found


def updated(originals, previous, repo):
    """Adopt only successful controlled history writes in this same repository."""
    found = dict(originals)
    revision = None
    for record in previous:
        belongs = record.get("repository") == str(repo)
        if belongs and record.get("status") == SUCCEEDED and KEY in record:
            require(record["request"]["argv"][0] in HISTORY_WRITES, "Invalid Git source baseline")
            saved = record[KEY]
            revision = saved["head"]
            found.update(saved["files"])
    if revision is not None:
        require(
            history_outcome.head(repo) == revision,
            "Git HEAD changed after the run's controlled commit",
        )
    return found


def record(entry):
    """A successful history write advances only the paths it was allowed to affect."""
    command = entry["request"]["argv"][0]
    if entry["status"] != SUCCEEDED or command not in HISTORY_WRITES:
        return
    repo = Path(entry["repository"])
    try:
        entry[KEY] = snapshot(repo, entry)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        entry.update(status="UNKNOWN", stderr=f"Cannot record committed source identity: {error}")


def snapshot(repo, entry):
    """Validate and read one pinned outcome; a concurrent HEAD change leaves it unknown."""
    revision = history_outcome.head(repo)
    history_outcome.verify(repo, entry, revision)
    paths = entry["affected_paths"]
    files = {name: committed(repo, Path(name), revision) for name in paths}
    require(history_outcome.head(repo) == revision, history_outcome.ERROR)
    return dict(head=revision, files=files)


def committed(repo, path, revision):
    """Committed mode and content digest, or None for a path removed by this write."""
    relative = path.relative_to(repo).as_posix()
    listing = process.checked(repo, ["ls-tree", "-z", revision, "--", relative])
    if not listing:
        return None
    outcome = process.invoke(repo, ["show", f"{revision}:{relative}"])
    require(outcome.returncode == 0, "Cannot read the committed Git source baseline")
    mode = listing.split(" ", 1)[0]
    return f"{mode}:{outcome.stdout_sha256}"


def source_identity(signature):
    """Git tracks only the owner's executable bit, not other filesystem permissions."""
    mode, checksum = signature.split(":", 1)
    return bool(int(mode, 8) & EXECUTABLE_BIT), checksum
