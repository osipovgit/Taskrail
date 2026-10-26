"""Ownership evidence retained by run and launcher records."""

import json
from pathlib import Path

from taskrail.application.task_config import HEADER

RUN_INDEX = "run.json"
LAUNCH_INDEX = "launch.json"


def document(path):
    """Fail closed on malformed or redirected ownership evidence."""
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Unsafe history record: {path}")
    record = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(record, dict):
        raise ValueError(f"Invalid history record: {path}")
    return record


def declared_roots(record):
    """Use recorded absolute roots without requiring deleted projects to exist."""
    for raw in root_paths(record):
        if not isinstance(raw, str) or not Path(raw).is_absolute():
            raise ValueError("History roots must be absolute paths")
        yield Path(raw).resolve()


def root_paths(record):
    """An isolated run protects both its worktrees and its original projects."""
    roots = record.get("roots", {})
    worktrees = record.get("worktrees") or {}
    if not isinstance(roots, dict) or not isinstance(worktrees, dict):
        raise ValueError("Invalid roots in history record")
    paths = list(roots.values())
    for entry in worktrees.values():
        if not isinstance(entry, dict) or "source" not in entry:
            raise ValueError("Invalid worktree in history record")
        paths.append(entry["source"])
    return paths


def launch_roots(folder):
    """A failed launch still records its declared roots in task.md."""
    document(folder / LAUNCH_INDEX)
    task = folder / "task.md"
    if task.is_symlink() or not task.is_file():
        raise ValueError(f"Missing task in launcher record: {folder}")
    headers = HEADER.findall(task.read_text(encoding="utf-8"))
    if len(headers) != 1:
        raise ValueError(f"Invalid task in launcher record: {folder}")
    record = json.loads(headers[0])
    if not isinstance(record, dict):
        raise ValueError(f"Invalid task header: {task}")
    return declared_roots(record)
