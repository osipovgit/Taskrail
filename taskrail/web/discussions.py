"""Conversation turns share a dashboard card. Each launch keeps its own audit trail."""

import contextlib
import fcntl

from taskrail.application import run_locks
from taskrail.core import delivery_record
from taskrail.web.run_sources import launch_record

ROOT = "discussion_root"
SUBMISSIONS = ".submissions"


def link(folder):
    """The server-recorded discussion and predecessor of an original reply launch."""
    launch = launch_record(folder)
    if not isinstance(launch, dict) or launch.get("id") != folder.name:
        return None
    names = (launch.get(ROOT), launch.get("restart_from"))
    if all(isinstance(name, str) for name in names) and all(
        map(delivery_record.RUN_NAME.fullmatch, names)
    ):
        return names
    return None


def replies_by_root(base):
    """Group original reply launches, including those waiting for their worker."""
    folders = base / SUBMISSIONS
    groups = {}
    if folders.is_dir() and not folders.is_symlink():
        for folder in folders.iterdir():
            origin = link(folder)
            if origin:
                groups.setdefault(origin[0], {})[origin[1]] = folder.name
    return groups


def chain(root, links):
    """Order turns by predecessor even when two IDs have the same timestamp."""
    ordered = [root]
    pending = dict(links)
    while ordered[-1] in pending:
        ordered.append(pending.pop(ordered[-1]))
    return ordered


def root_of(run):
    """A follow-up keeps the first turn's permanent task ID."""
    origin = link(run.parent / SUBMISSIONS / run.name)
    return origin[0] if origin else run.name


def current_turn(base, name):
    """A CLI discussion ID addresses the latest turn; an explicit turn stays pinned."""
    links = replies_by_root(base).get(name, {})
    current = chain(name, links)[-1]
    if links and not (base / current / "run.json").is_file():
        raise ValueError(
            f"The latest turn {current} has not started. Check its launch before replying."
        )
    return current


@contextlib.contextmanager
def posting(base, launch):
    """Serialize replies across the CLI and web so stale submissions cannot fork a thread."""
    root = launch.get(ROOT)
    if root is None:
        yield
        return
    with run_locks.resource("discussion", base / root, fcntl.LOCK_EX):
        links = replies_by_root(base).get(root, {})
        if chain(root, links)[-1] != launch["restart_from"]:
            raise ValueError("The discussion has a newer turn. Open it before replying.")
        yield
