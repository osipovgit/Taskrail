"""Project durable corrective attempts into delivery progress without granting approval."""

from taskrail.application import reviewed_artifacts
from taskrail.core import corrections, owned_paths
from taskrail.web import epic_tasks
from taskrail.web.run_files import read_json

STATUS = "status"


def budget(run):
    """Use the original run's frozen repair budget, never newly edited settings."""
    reference = "00-input/settings.json"
    try:
        settings = read_json(owned_paths.child(run, reference))
    except FileNotFoundError:
        settings = {}
    return corrections.limit(settings)


def entries(run, epic):
    """A corrective writer is a visible node with its rejected review and actual outcome."""
    numbered = enumerate(corrections.records(epic), 1)
    return [entry(run, record, number) for number, record in numbered]


def entry(run, record, number):
    """Use status, not an operator's Done marker, to advance another writer."""
    child = reviewed_artifacts.run_path(run.parent, record["run"])
    outcome = epic_tasks.outcome(child)
    return dict(
        outcome,
        id=f"C{number}",
        title=f"Integration correction {number}",
        run=record["run"],
        review=record["review"],
        done=False,
        changed_files=outcome.get("changed_files", []),
    )


def attach(delivery, run, epic):
    """An unresolved corrective writer blocks new corrections but remains resumable."""
    completed = delivery[corrections.KEY]
    remaining = max(0, budget(run) - len(completed))
    delivery["corrections_remaining"] = remaining
    review = delivery["phases"].get("integration", {})
    settled = all(entry[STATUS] in epic_tasks.FINISHED for entry in completed)
    handled = {entry["review"] for entry in completed}
    delivery["correction_available"] = bool(
        remaining
        and settled
        and review.get(STATUS) == "CHANGES_REQUESTED"
        and review.get("run") not in handled
    )


def step(delivery):
    """The current correction must finish before integration is repeated."""
    current = delivery["phases"].get(corrections.PHASE)
    if current is None:
        return None
    if current[STATUS] in epic_tasks.ACTIVE:
        return "correcting"
    if current[STATUS] == "WAITING_APPROVAL":
        return "approval"
    if current[STATUS] in epic_tasks.FINISHED:
        return "corrected"
    return "correction_failed"
