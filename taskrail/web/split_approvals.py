""" "Allow all actions" for a whole split or delivery, not only the run where it was given.

The operator may allow all actions in the task form, on the parent's own decision or on
a decision of any task or phase run. Every run started for the parent afterwards gets
it; revoking it in any of these runs revokes it for the parent too.
"""

import json

from taskrail.interactions import approval_policy
from taskrail.web import epic_record, epic_tasks, history, run_family

KEY = approval_policy.AUTO_APPROVE


def allows_all(run, draft):
    """Whether a run started now for this parent allows all actions."""
    if (run / approval_policy.OFF).exists():
        return False
    state = json.loads(history.read_artifact(run, "run.json"))
    granted = epic_tasks.record(run).get(KEY) is True
    return approval_policy.at_start(run, draft) or approval_policy.active(run, state) or granted


def shown(run, state):
    """What a run card shows: its own setting or, for a parent, the one given for its runs."""
    if approval_policy.active(run, state):
        return True
    split = epic_tasks.record(run).get(KEY) is True
    return split and not (run / approval_policy.OFF).exists()


def granted(run, payload):
    """An allow-all decision on a task or phase run applies to its parent from now on."""
    if not (payload.get(approval_policy.ALLOW_ALL) and payload.get("decision") == "allow"):
        return
    parent = parent_of(run)
    if parent is None:
        return
    with epic_record.changing(parent) as epic:
        epic[KEY] = True
    (parent / approval_policy.OFF).unlink(missing_ok=True)


def revoke(run):
    """Revoke it for the run and, for a task or phase run, for its parent."""
    parent = parent_of(run)
    if parent is not None:
        with epic_record.changing(parent) as epic:
            epic[KEY] = False
        approval_policy.revoke(parent)
    return approval_policy.revoke(run)


def parent_of(run):
    """The parent run of a task or phase run that still exists, or None."""
    if not run_family.shown_inside(run.parent, run):
        return None
    return run.parent / run_family.parent_link(run)[0]
