"""The exact text submitted for review, including the rationale when no commit is needed."""

import textwrap

from taskrail.core import schema
from taskrail.core.files import digest
from taskrail.infrastructure.agent_sync import atomic_write

KEY = "implementation_submission"
PATH = "path"
MESSAGE = "commit-message.txt"
NO_CHANGE = "no-change-note.txt"
SUBJECT_LIMIT = 72


def publish(directory, state, summary):
    """Each implementation revision creates its own read-only proposal before checks."""
    run = directory.parent
    if state["changed_files"]:
        body = message(run, summary)
        path = directory / MESSAGE
    else:
        body = f"{summary}\n"
        path = directory / NO_CHANGE
    encoded = body.encode()
    atomic_write(path, encoded)
    relative = str(path.relative_to(run))
    state[KEY] = dict(path=relative, sha256=digest(encoded))


def record(folder, state, verdict):
    """Publish before the stage inventory and checkpoint are written."""
    if isinstance(verdict, dict) and verdict.get("status") == "IMPLEMENTED":
        publish(folder, state, verdict["summary"])


def message(run, summary):
    """Retain the full rationale below the short subject and identify its run."""
    subject = textwrap.shorten(summary, SUBJECT_LIMIT, placeholder="...")
    return f"{subject}\n\n{summary}\n\nTaskrail-Run: {run.name}\n"


def read(run, submission):
    """Use the same reviewed bytes for citations, finalization and continuation."""
    path = run / submission[PATH]
    canonical = path.resolve() == path and run in path.parents
    schema.require(canonical and path.name in {MESSAGE, NO_CHANGE}, "Invalid submission path")
    encoded = path.read_bytes()
    schema.require(digest(encoded) == submission["sha256"], "Implementation submission changed")
    return encoded.decode()


def review_path(run, stage, state):
    """Only result review can cite the current submission for its wording."""
    submission = state.get(KEY)
    if stage == "reviewer" and submission:
        read(run, submission)
        return str(run / submission[PATH])
    return None
