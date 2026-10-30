"""Per-run "allow all actions": approve operator decisions automatically, with a ledger.

The initial setting lives in trusted task input. Personal card grants are durable
outside project roots and inherited only through authenticated family links. The
operator can revoke them; ancestor denials override copied flags. It covers local
commands and the change limit; SSH actions
and Jenkins builds keep their separate root-only approval. A command that runs in
the sandbox needs no decision; its automatic approval is recorded the same way.
"""

import time
import uuid

from taskrail.core import approval_family, approval_marks
from taskrail.core.files import atomic_json
from taskrail.interactions import approvals, read_only

AUTO_APPROVE = "auto_approve"
ALLOW = "allow"
ALLOW_ALL = "allow_all"
READ_ONLY = "read_only"
SANDBOX = "sandbox"
OFF = approval_marks.OFF


def decision(run, request, state, scope=None, personal=False):
    """Approve read-only requests and, when allowed for this run, all others on record.

    The scope holds the declared roots and protected patterns of the read-only route;
    without one (the change limit) only the run's setting can approve automatically.
    A personal request, such as a push to a remote or a manual installation step,
    always waits for the operator.
    """
    if not personal and scope is not None and read_only.request(request, *scope):
        return automatic(run, request, READ_ONLY)
    if not personal and enabled(run, state):
        return automatic(run, request, ALLOW_ALL)
    answer = approvals.wait(run, request)
    if answer.get("allow_all") and answer["decision"] == ALLOW:
        state[AUTO_APPROVE] = not approval_marks.revoked(run)
    return answer


def enabled(run, state):
    """Refresh live family grants; a denial always wins over persisted run state."""
    granted, denied = approval_family.status(run, state.get("phase"))
    if denied:
        state[AUTO_APPROVE] = False
    elif granted:
        state[AUTO_APPROVE] = True
    return state.get(AUTO_APPROVE) is True


def at_start(run, config, state=None):
    """Continue preserves a card grant; task input cannot override later revocation."""
    saved = state or {}
    allowed = config.get(AUTO_APPROVE) is True
    allowed = allowed or saved.get(AUTO_APPROVE) is True
    effective = dict(saved, auto_approve=allowed)
    effective.setdefault("phase", config.get("phase"))
    return enabled(run, effective)


def active(run, state):
    """What the UI shows: allowed and not revoked since the worker last saved its state."""
    return enabled(run, dict(state))


def revoke(run):
    """Ask the worker to stop approving automatically; it applies before the next decision."""
    approval_marks.revoke(run)
    return dict(id=run.name, status="AUTO_APPROVE_REVOKED")


def automatic(run, request, rule):
    """Record the automatic approval like an operator decision, with the rule that gave it."""
    identity = uuid.uuid4().hex
    ticket = dict(ticket=identity, request=request, created_at=time.time())
    answer = dict(decision=ALLOW, alternative="", automatic=True, rule=rule)
    atomic_json(run / f"approval-{identity}.json", dict(request=ticket, response=answer))
    return answer
