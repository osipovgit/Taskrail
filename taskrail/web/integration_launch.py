"""Start or explicitly repeat the independent review after a task split."""

import json
from functools import partial

from taskrail.application import correction_history, delivery_confirmation
from taskrail.web import (
    delivery_state,
    epic_record,
    history,
    integration_review,
    run_attempts,
)
from taskrail.web.delivery_steps import INTEGRATION
from taskrail.web.run_activity import BusyError

PHASES = "phases"
INDEX = "run.json"


def start(launcher, run):
    """The combined review is mandatory and does not depend on a remote executor."""
    with launcher.lock, epic_record.changing(run) as epic:
        if INTEGRATION in epic.get(PHASES, {}):
            return None
        state = json.loads(history.read_artifact(run, INDEX))
        delivery = delivery_state.view(run, state)
        if delivery is None or delivery["step"] != "integrating":
            raise ValueError("Integration review requires all child tasks to finish")
        epic[integration_review.SEAL] = integration_review.signature(
            [*delivery["tasks"], *delivery.get("corrections", [])]
        )
        link = partial(epic_record.link, run, epic, (PHASES, INTEGRATION))
        return launcher.submit(integration_review.payload(run, state), before_start=link)


def repeat(launcher, run):
    """An operator can replace a stopped read-only review, never an active writer."""
    with epic_record.changing(run) as epic:
        correction_history.completed(run)
        state = json.loads(history.read_artifact(run, INDEX))
        delivery = delivery_state.view(run, state)
        if delivery is None or delivery["implementation"] != "done" or "tasks" not in delivery:
            raise ValueError("Integration review requires finished child tasks")
        previous = delivery_state.phases(run, epic).values()
        if any(active_phase(phase) for phase in previous):
            raise BusyError("Stop active delivery phases before repeating integration review")
        run_attempts.remember_phases(epic)
        epic.setdefault("phase_history", []).append(epic.get(PHASES, {}))
        epic[PHASES] = {}
        epic.pop("confirmed", None)
        epic.pop(delivery_confirmation.INPUTS, None)
        epic.pop("launch_error", None)
    return start(launcher, run)


def active_phase(phase):
    """A repeated review cannot abandon a running validation or server phase."""
    return phase.get("status") in {"STARTING", "RUNNING", "WAITING_APPROVAL"}
