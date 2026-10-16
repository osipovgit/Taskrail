"""Single-use operator decisions, bound to the exact displayed request."""

import fcntl
import json
import sys
import time
import uuid

from countersign.core import control
from countersign.core.files import atomic_json
from countersign.core.schema import require

PENDING = "pending-approval.json"
DECISION = "approval-decision.json"
TICKET = "ticket"
ALTERNATIVE = "alternative"
TEXT_LIMIT = 16000
POLL_SECONDS = 0.2


def load(run):
    """A missing request is an idle approval channel."""
    path = run / PENDING
    return json.loads(path.read_text()) if path.is_file() else None


def decide(run, payload):
    """A browser decision cannot edit the command or approve another ticket."""
    validate_decision(payload)
    with (run / "approval.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        pending = load(run)
        require(pending is not None, "No approval pending")
        require(pending[TICKET] == payload[TICKET], "Stale approval")
        require(not (run / DECISION).exists(), "Decision already submitted")
        atomic_json(run / DECISION, payload)
    return dict(id=run.name, status="DECISION_RECORDED")


def wait(run, request):
    """No deadline while waiting; cooperative Stop still works."""
    identity = uuid.uuid4().hex
    ticket = dict(ticket=identity, request=request, created_at=time.time())
    (run / DECISION).unlink(missing_ok=True)
    atomic_json(run / PENDING, ticket)
    sys.stdout.write("Waiting for personal approval in the task UI (no timeout).\n")
    sys.stdout.flush()
    try:
        answer = receive(run, ticket)
    except BaseException:
        clear(run)
        raise
    atomic_json(run / f"approval-{identity}.json", dict(request=ticket, response=answer))
    clear(run)
    return answer


def clear(run):
    """Do not leave a stale decision for the next command."""
    (run / PENDING).unlink(missing_ok=True)
    (run / DECISION).unlink(missing_ok=True)


def receive(run, ticket):
    """Only the exact outstanding decision can unblock execution."""
    while True:
        control.check_stop(run)
        path = run / DECISION
        if path.is_file():
            decision = json.loads(path.read_text())
            require(decision[TICKET] == ticket[TICKET], "Approval ticket mismatch")
            return decision
        time.sleep(POLL_SECONDS)


def validate_decision(payload):
    """Reject unrecognized or incomplete operator responses."""
    require(isinstance(payload, dict), "Decision must be an object")
    require(set(payload) == {"id", TICKET, "decision", ALTERNATIVE}, "Invalid decision fields")
    require(payload["decision"] in {"allow", "deny", ALTERNATIVE}, "Invalid decision")
    text = payload[ALTERNATIVE]
    require(isinstance(text, str) and len(text) <= TEXT_LIMIT, "Invalid alternative")
    if payload["decision"] == ALTERNATIVE:
        require(bool(text.strip()), "Provide an alternative")
