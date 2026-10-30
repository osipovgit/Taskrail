"""Create bounded fresh corrections only for authenticated rejected integration reviews."""

import json
from functools import partial

from taskrail.core import corrections
from taskrail.core.schema import require
from taskrail.web import (
    delivery_state,
    epic_record,
    history,
    integration_launch,
    integration_review,
)


def start(launcher, run, automatic=False):
    """Record one new writer before launching; an existing failed writer is never replayed."""
    with launcher.lock, epic_record.changing(run) as epic:
        if automatic and not epic.get("auto_continue"):
            return None
        state = json.loads(history.read_artifact(run, "run.json"))
        delivery = delivery_state.view(run, state)
        require(
            delivery is not None and delivery.get("correction_available"),
            "No integration correction is available; inspect the prior attempt or repair budget",
        )
        review = delivery["phases"]["integration"]["run"]
        link = partial(linked, run, epic, review)
        epic.pop("launch_error", None)
        return launcher.submit(payload(run, state), before_start=link)


def payload(run, state):
    """The application replaces submitted prose with the frozen original goal and findings."""
    fields = integration_review.payload(run, state)
    fields.update(phase=corrections.PHASE, read_only=False, title="Integration correction")
    return fields


def linked(run, epic, review, child):
    """Keep the rejected review attached even after later integration replaces its phase."""
    record = dict(run=child, review=review)
    epic.setdefault(corrections.KEY, []).append(record)
    epic_record.link(run, epic, ("phases", corrections.PHASE), child)


def advance(launcher, run, delivery):
    """Auto-continue covers new corrections and their fresh overall acceptance review."""
    if not delivery.get("auto_continue"):
        return
    if delivery["step"] == "integration_failed" and delivery.get("correction_available"):
        start(launcher, run, automatic=True)
    elif delivery["step"] == "corrected":
        integration_launch.repeat(launcher, run)
