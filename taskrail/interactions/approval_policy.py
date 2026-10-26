"""Per-run "allow all actions": approve operator decisions automatically, with a ledger.

The setting lives in the worker's run state only, so a command cannot turn it on
by writing a file. The operator turns it off with a marker file, which can only
remove the permission. It covers local commands and the change limit; SSH actions
and Jenkins builds keep their separate root-only approval.
"""

import time
import uuid

from taskrail.core.files import atomic_json
from taskrail.interactions import approvals, read_only

AUTO_APPROVE = "auto_approve"
ALLOW = "allow"
ALLOW_ALL = "allow_all"
READ_ONLY = "read_only"
OFF = "auto-approve.off"


def decision(run, request, state, scope=None, personal=False):
    """Approve read-only requests and, when allowed for this run, all others on record.

    The scope holds the declared roots and protected patterns of the read-only route;
    without one (the change limit) only the run's setting can approve automatically.
    A personal request, such as a push to a remote or inline shell or Python code,
    always waits for the operator.
    """
    if not personal and scope is not None and read_only.request(request, *scope):
        return automatic(run, request, READ_ONLY)
    if not personal and enabled(run, state):
        return automatic(run, request, ALLOW_ALL)
    answer = approvals.wait(run, request)
    if answer.get("allow_all") and answer["decision"] == ALLOW:
        state[AUTO_APPROVE] = True
        (run / OFF).unlink(missing_ok=True)
    return answer


def enabled(run, state):
    """The run's setting, switched off for good once the operator revoked it."""
    if (run / OFF).exists():
        state[AUTO_APPROVE] = False
    return state.get(AUTO_APPROVE) is True


def at_start(run, config):
    """The task header's setting, unless the operator revoked it for this run."""
    return config.get(AUTO_APPROVE) is True and not (run / OFF).exists()


def active(run, state):
    """What the UI shows: allowed and not revoked since the worker last saved its state."""
    return state.get(AUTO_APPROVE) is True and not (run / OFF).exists()


def revoke(run):
    """Ask the worker to stop approving automatically; it applies before the next decision."""
    atomic_json(run / OFF, dict(revoked_at=time.time()))
    return dict(id=run.name, status="AUTO_APPROVE_REVOKED")


def automatic(run, request, rule):
    """Record the automatic approval like an operator decision, with the rule that gave it."""
    identity = uuid.uuid4().hex
    ticket = dict(ticket=identity, request=request, created_at=time.time())
    answer = dict(decision=ALLOW, alternative="", automatic=True, rule=rule)
    atomic_json(run / f"approval-{identity}.json", dict(request=ticket, response=answer))
    return answer
