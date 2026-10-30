""" "Allow all actions" for a whole split or delivery, not only the run where it was given.

The operator may allow all actions in the task form, on the parent's own decision or on
a decision of any task or phase run. Every run started for the parent afterwards gets
it; revoking it in any of these runs revokes it for the parent too.
"""

import json

from taskrail.core import approval_family, approval_marks
from taskrail.interactions import approval_policy, approvals
from taskrail.web import epic_record, history, run_family

KEY = approval_policy.AUTO_APPROVE


def allows_all(run, draft):
    """Whether a run started now for this parent allows all actions."""
    state = json.loads(history.read_artifact(run, "run.json"))
    return approval_policy.at_start(run, draft, state)


def shown(run, state):
    """What a run card shows: its own setting or, for a parent, the one given for its runs."""
    return approval_policy.active(run, state)


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
    """Only server-linked children can grant or revoke their parent's authority."""
    return approval_family.parent(run)
