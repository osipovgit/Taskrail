"""Per-run "allow all actions": approve operator decisions automatically, with a ledger.

The setting lives in the worker's run state only, so a command cannot turn it on
by writing a file. It covers local commands, read access and the change limit;
SSH actions keep their separate root-only approval.
"""

import time
import uuid

from countersign.core.files import atomic_json
from countersign.interactions import approvals

AUTO_APPROVE = "auto_approve"
ALLOW = "allow"


def decision(run, request, state):
    """Approve automatically when allowed for this run; otherwise ask the operator."""
    if state.get(AUTO_APPROVE):
        return automatic(run, request)
    answer = approvals.wait(run, request)
    if answer.get("allow_all") and answer["decision"] == ALLOW:
        state[AUTO_APPROVE] = True
    return answer


def automatic(run, request):
    """Record the automatic approval like an operator decision."""
    identity = uuid.uuid4().hex
    ticket = dict(ticket=identity, request=request, created_at=time.time())
    answer = dict(decision=ALLOW, alternative="", automatic=True)
    atomic_json(run / f"approval-{identity}.json", dict(request=ticket, response=answer))
    return answer
