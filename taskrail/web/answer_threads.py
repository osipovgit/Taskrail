"""Answer-only turns share a dashboard card. Each launch keeps its own audit trail."""

import contextlib
import fcntl

from taskrail.application import run_locks
from taskrail.core import delivery_record
from taskrail.web import history
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


def discussions(base):
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


def cards(base, entries):
    """Use the current turn's status and keep the original task title and permalink."""
    by_id = {entry["id"]: entry for entry in entries}
    for root, links in discussions(base).items():
        if root not in by_id:
            continue
        group_card(by_id, root, chain(root, links)[1:])
    return by_id.values()


def group_card(by_id, root, names):
    """A missing or removed member never hides a surviving run."""
    members = list(filter(by_id.__contains__, names))
    if members:
        latest = members[-1]
        current = by_id[latest]
        for name in members:
            by_id.pop(name)
        by_id[root] = dict(
            current,
            id=root,
            title=by_id[root]["title"],
            mode="answer",
            latest=latest,
            members=members,
        )


def discussion_for(submission, index):
    """Only an answer to a standalone research task continues its discussion."""
    if submission.mode != "answer" or submission.flags["design"] or submission.delivery["phase"]:
        return None
    metadata = history.TaskDraft.submitted(submission.previous).metadata
    if metadata.get("read_only") and not metadata.get("design"):
        if index.get("status") == "RUNNING":
            raise ValueError("Wait for the current answer before sending another question")
        run = submission.previous
        origin = link(run.parent / SUBMISSIONS / run.name)
        return origin[0] if origin else run.name
    return None


@contextlib.contextmanager
def posting(base, launch):
    """Serialize replies across the CLI and web so stale submissions cannot fork a thread."""
    root = launch.get(ROOT)
    if root is None:
        yield
        return
    with run_locks.resource("discussion", base / root, fcntl.LOCK_EX):
        links = discussions(base).get(root, {})
        if chain(root, links)[-1] != launch["restart_from"]:
            raise ValueError("The discussion has a newer turn. Open it before replying.")
        yield
