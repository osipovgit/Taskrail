"""The step a delivery is in: code, Jenkins validation, confirmation, then server checks."""

from types import MappingProxyType

from taskrail.web.epic_tasks import FINISHED

RUNNING_STATUSES = frozenset(("STARTING", "RUNNING"))
WAITING = "WAITING_APPROVAL"
SKIPPED = "skipped"
SERVER = "server"
VALIDATION = "validation"
INTEGRATION = "integration"
RUNNING = "running"
ATTENTION = "attention"
DONE = "done"
REVIEW = "review"
STATUS = "status"
CHECK_KEYS = MappingProxyType({INTEGRATION: INTEGRATION, VALIDATION: "jenkins", SERVER: SERVER})
# Phase -> (step while it is pending or running, step after it failed).
PHASE_STEPS = MappingProxyType(
    {
        INTEGRATION: ("integrating", "integration_failed"),
        VALIDATION: ("validating", "validation_failed"),
        SERVER: (SERVER, "server_failed"),
    }
)
GROUPS = MappingProxyType(
    {
        "implementing": RUNNING,
        "needs_you": ATTENTION,
        "integrating": RUNNING,
        "integration_failed": ATTENTION,
        "validating": RUNNING,
        "validation_failed": ATTENTION,
        "approval": ATTENTION,
        "confirm": REVIEW,
        REVIEW: REVIEW,
        SERVER: RUNNING,
        "server_failed": ATTENTION,
        DONE: DONE,
    }
)


def step(delivery):
    """The current step of a delivery view; GROUPS maps it to the run list."""
    if delivery.get("launch_error"):
        return "needs_you"
    code = delivery["implementation"]
    if code != DONE:
        return "implementing" if code == RUNNING else "needs_you"
    validation = phase_step(delivery, INTEGRATION) or phase_step(delivery, VALIDATION)
    if validation:
        return validation
    if not delivery["confirmed"]:
        return final_step(delivery)
    return phase_step(delivery, SERVER) or DONE


def phase_step(delivery, name):
    """The step of a needed phase until it succeeded or was skipped; None after that."""
    if not required(delivery, name):
        return None
    pending, failed = PHASE_STEPS[name]
    record = delivery["phases"].get(name)
    if record is None or record[STATUS] in RUNNING_STATUSES:
        return pending
    if record[STATUS] == WAITING:
        return "approval"
    accepted = {"NO_CHANGES_REQUIRED"} if name == INTEGRATION else FINISHED | {SKIPPED}
    if record[STATUS] in accepted:
        return None
    return failed


def final_step(delivery):
    """Confirmation only before server checks; a finished change waits for your review.

    Server checks may change servers, so they start only after you confirm. Without
    them nothing waits for you: a change is ready for your review, no change is done.
    """
    if delivery["checks"][SERVER]:
        return "confirm"
    return DONE if delivery[STATUS] == "NO_CHANGES_REQUIRED" else REVIEW


def required(delivery, name):
    """Every split needs an integration review; remote phases need explicit checks."""
    if name == INTEGRATION:
        return bool(delivery.get("tasks"))
    return bool(delivery["checks"][CHECK_KEYS[name]])
