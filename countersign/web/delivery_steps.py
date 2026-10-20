"""The step a delivery is in: code, Jenkins validation, confirmation, then server checks."""

from types import MappingProxyType

from countersign.web.epic_tasks import FINISHED

RUNNING_STATUSES = frozenset(("STARTING", "RUNNING"))
WAITING = "WAITING_APPROVAL"
SKIPPED = "skipped"
SERVER = "server"
VALIDATION = "validation"
RUNNING = "running"
ATTENTION = "attention"
DONE = "done"
STATUS = "status"
CHECK_KEYS = MappingProxyType({VALIDATION: "jenkins", SERVER: SERVER})
# Phase -> (step while it is pending or running, step after it failed).
PHASE_STEPS = MappingProxyType(
    {VALIDATION: ("validating", "validation_failed"), SERVER: (SERVER, "server_failed")}
)
GROUPS = MappingProxyType(
    {
        "implementing": RUNNING,
        "needs_you": ATTENTION,
        "validating": RUNNING,
        "validation_failed": ATTENTION,
        "approval": ATTENTION,
        "confirm": "review",
        SERVER: RUNNING,
        "server_failed": ATTENTION,
        DONE: DONE,
    }
)


def step(delivery):
    """The current step of a delivery view; GROUPS maps it to the run list."""
    code = delivery["implementation"]
    if code != DONE:
        return "implementing" if code == RUNNING else "needs_you"
    validation = phase_step(delivery, VALIDATION)
    if validation:
        return validation
    if not delivery["confirmed"]:
        return "confirm" if needs_confirmation(delivery) else DONE
    return phase_step(delivery, SERVER) or DONE


def phase_step(delivery, name):
    """The step of a needed phase until it succeeded or was skipped; None after that."""
    if not delivery["checks"][CHECK_KEYS[name]]:
        return None
    pending, failed = PHASE_STEPS[name]
    record = delivery["phases"].get(name)
    if record is None or record[STATUS] in RUNNING_STATUSES:
        return pending
    if record[STATUS] == WAITING:
        return "approval"
    if record[STATUS] in FINISHED or record[STATUS] == SKIPPED:
        return None
    return failed


def needs_confirmation(delivery):
    """A change to confirm, or server checks that may only run after confirmation."""
    unchanged = delivery[STATUS] == "NO_CHANGES_REQUIRED"
    return not unchanged or bool(delivery["checks"][SERVER])
