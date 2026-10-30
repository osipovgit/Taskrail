"""Advance deliveries: next tasks, then Jenkins validation, then server checks once confirmed.

The service calls advance() every few seconds. A phase starts at most once; when the
executor does not offer Jenkins or SSH targets, the phase is recorded as skipped.
"""

import json
import time
from functools import partial
from pathlib import Path
from types import MappingProxyType

from taskrail.application import delivery_confirmation
from taskrail.executor import client, protocol
from taskrail.web import (
    delivery_payload,
    delivery_state,
    epic_launch,
    epic_record,
    history,
    integration_launch,
    integration_review,
    run_attempts,
)
from taskrail.web.correction_launch import advance as advance_correction
from taskrail.web.delivery_steps import INTEGRATION, SERVER, VALIDATION
from taskrail.web.run_activity import BusyError
from taskrail.web.run_errors import ERRORS, clear, launch_failure

PENDING = MappingProxyType({"integrating": INTEGRATION, "validating": VALIDATION, SERVER: SERVER})
OFFERS = MappingProxyType({VALIDATION: "jenkins", SERVER: "hosts"})
UNAVAILABLE = MappingProxyType(
    {
        VALIDATION: "skipped: Jenkins is not configured in the executor",
        SERVER: "skipped: the SSH executor has no targets",
    }
)
INDEX = "run.json"
PHASES = "phases"
STEP = "step"


def advance(launcher):
    """Move every delivery to its next automatic step."""
    for run in launcher.base.iterdir():
        if not run.is_symlink() and run.joinpath(INDEX).is_file():
            proceed_quietly(launcher, run)


def proceed_quietly(launcher, run):
    """A busy project or an unreadable run waits for the next round."""
    try:
        if proceed(launcher, run) is not False:
            clear(run)
    except BusyError:
        return
    except ERRORS as error:
        launch_failure(run, error)


def proceed(launcher, run):
    """Start the next task of a split, a pending validation or confirmed server checks."""
    state = json.loads(history.read_artifact(run, INDEX))
    delivery = delivery_state.view(run, state)
    if delivery is None:
        return None
    if delivery[STEP] in {"integration_failed", "corrected"}:
        advance_correction(launcher, run, delivery)
        return None
    if delivery[STEP] == "implementing" and "tasks" in delivery:
        return epic_launch.continue_quietly(launcher, run)
    name = PENDING.get(delivery[STEP])
    if name and name not in delivery["phases"]:
        start_phase(launcher, run, name)
    return None


def start_phase(launcher, run, name):
    """Start one phase run, linked before its worker starts, or record why it cannot run."""
    if name == INTEGRATION:
        return integration_launch.start(launcher, run)
    offers = executor_offers()
    if offers is None:
        return None
    with launcher.lock, epic_record.changing(run) as epic:
        if name in epic.get(PHASES, {}):
            return None
        if name == SERVER:
            delivery_confirmation.verify(run, epic)
        if not offers.get(OFFERS[name]):
            epic.setdefault(PHASES, {})[name] = UNAVAILABLE[name]
            return dict(id=run.name, status="PHASE_RECORDED")
        state = json.loads(history.read_artifact(run, INDEX))
        link = partial(epic_record.link, run, epic, (PHASES, name))
        return launcher.submit(delivery_payload.payload(run, state, name), before_start=link)


def restart_phase(launcher, run, name, attempt):
    """Run the latest attempt of a stopped phase again under the same delivery."""
    if name == "correction":
        raise ValueError(
            "Continue an interrupted correction after inspecting its edits; corrective writers are not restarted automatically"
        )
    with epic_record.changing(run) as epic:
        if epic.get(PHASES, {}).get(name) != attempt:
            raise ValueError("Only the latest attempt of a delivery phase can restart")
        if integration_launch.active_phase(delivery_state.phase(run, attempt)):
            raise BusyError("Stop the phase before restarting it")
        run_attempts.remember_phases(epic)
        if name != INTEGRATION:
            epic[PHASES].pop(name)
            epic.pop("launch_error", None)
    if name == INTEGRATION:
        return integration_launch.repeat(launcher, run)
    return start_phase(launcher, run, name)


def confirm(launcher, run):
    """The operator accepts the finished change; server checks may run after this."""
    with epic_record.changing(run) as epic:
        state = json.loads(history.read_artifact(run, INDEX))
        delivery = delivery_state.view(run, state)
        if delivery is None or delivery[STEP] != "confirm":
            raise ValueError("Only a finished change that waits for confirmation can be confirmed")
        with integration_review.confirmation_lock(run, delivery) as snapshot:
            epic["confirmed"] = time.time()
            epic[delivery_confirmation.INPUTS] = snapshot
    proceed_quietly(launcher, run)
    return dict(id=run.name, status="CONFIRMED")


def executor_offers():
    """The executor catalog, {} when no executor is installed, None when it is unreachable."""
    if not Path(protocol.SOCKET).exists():
        return {}
    try:
        return client.request({"operation": "catalog"})
    except (OSError, ValueError):
        return None
