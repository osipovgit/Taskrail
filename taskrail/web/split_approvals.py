""" "Allow all actions" for a whole split or delivery, not only the run where it was given.

The operator may allow all actions in the task form, on the parent's own decision or on
a decision of any task or phase run. Every run started for the parent afterwards gets
it; revoking it in any of these runs revokes it for the parent too.
"""

import json

from taskrail.core import approval_marks
from taskrail.interactions import approval_policy, approvals
from taskrail.web import epic_record, epic_tasks, history, run_family

KEY = approval_policy.AUTO_APPROVE


def allows_all(run, draft):
    """Whether a run started now for this parent allows all actions."""
    if approval_marks.revoked(run):
        return False
    state = json.loads(history.read_artifact(run, "run.json"))
    granted = epic_tasks.record(run).get(KEY) is True
    return approval_policy.at_start(run, draft) or approval_policy.active(run, state) or granted


def shown(run, state):
    """What a run card shows: its own setting or, for a parent, the one given for its runs."""
    if approval_policy.active(run, state):
        return True
    split = epic_tasks.record(run).get(KEY) is True
    return split and not approval_marks.revoked(run)


def decide(run, payload):
    """Serialize a personal decision and its family grant against family revocation."""
    if not (payload.get(approval_policy.ALLOW_ALL) and payload.get("decision") == "allow"):
        return approvals.decide(run, payload)
    parent = parent_of(run) or run
    with epic_record.changing(parent) as epic:
        recorded = approvals.decide(run, payload)
        epic[KEY] = True
        approval_marks.grant(parent)
    return recorded


def revoke(run):
    """Revoke the parent and every recorded task/phase attempt before another can start."""
    parent = parent_of(run) or run
    with epic_record.changing(parent) as epic:
        epic[KEY] = False
        members = {parent.name, run.name, *run_family.members(epic)}
        for name in sorted(members):
            approval_policy.revoke(parent.parent / name)
    return dict(id=run.name, status="AUTO_APPROVE_REVOKED")


def parent_of(run):
    """The parent run of a task or phase run that still exists, or None."""
    if not run_family.shown_inside(run.parent, run):
        return None
    return run.parent / run_family.parent_link(run)[0]
