"""What each run needs from the operator: running, attention, review or done.

A run counts as done when it ended without changes or when the operator marked it
done. The mark records the outcome it was given for, so a later continuation that
ends differently shows up again.
"""

import json

from countersign.core.files import atomic_json
from countersign.web.history import read_artifact

MARKER = "done.json"
STATUS = "status"
ACTIVE = frozenset(("STARTING", "RUNNING"))
REVIEW = "READY_FOR_REVIEW"
FINISHED = "NO_CHANGES_REQUIRED"


def group(run, state, status):
    """The list group of a run with its display status."""
    if status in ACTIVE:
        return "running"
    if status == FINISHED or marked(run, state):
        return "done"
    return "review" if status == REVIEW else "attention"


def marked(run, state):
    """A done mark given for exactly the current outcome."""
    path = run / MARKER
    if not path.is_file() or path.is_symlink():
        return False
    return json.loads(path.read_text()) == outcome(state)


def mark(run, done):
    """Mark a stopped run done, or move it back to its computed group."""
    state = json.loads(read_artifact(run, "run.json"))
    if state.get(STATUS) in ACTIVE:
        raise ValueError("Only a stopped task can be marked done")
    if done:
        atomic_json(run / MARKER, outcome(state))
        return dict(id=run.name, status="DONE")
    (run / MARKER).unlink(missing_ok=True)
    return dict(id=run.name, status="REOPENED")


def awaiting_ticket(state):
    """A running stage that waits for root approval of an SSH or Jenkins ticket."""
    if state.get(STATUS) != "RUNNING":
        return False
    jobs = state.get("execution_jobs") or [{}]
    return jobs[-1].get(STATUS) == "PENDING_APPROVAL"


def outcome(state):
    """The part of the run index that a done mark is bound to."""
    return dict(status=state.get(STATUS), finished_at=state.get("finished_at"))
