"""Advance deliveries: next tasks, then Jenkins validation, then server checks once confirmed.

The service calls advance() every few seconds. A phase starts at most once; when the
executor does not offer Jenkins or SSH targets, the phase is recorded as skipped.
"""

import json
import time
from pathlib import Path
from types import MappingProxyType

from countersign.core.files import atomic_json
from countersign.executor import client, protocol
from countersign.web import (
    delivery_checks,
    delivery_payload,
    delivery_state,
    epic_launch,
    epic_tasks,
    history,
)
from countersign.web.delivery_steps import SERVER, VALIDATION

PENDING = MappingProxyType({"validating": VALIDATION, SERVER: SERVER})
OFFERS = MappingProxyType({VALIDATION: "jenkins", SERVER: "hosts"})
UNAVAILABLE = MappingProxyType(
    {
        VALIDATION: "skipped: Jenkins is not configured in the executor",
        SERVER: "skipped: the SSH executor has no targets",
    }
)
INDEX = "run.json"


def advance(launcher):
    """Move every delivery to its next automatic step."""
    for run in launcher.base.iterdir():
        if run.joinpath(INDEX).is_file():
            proceed_quietly(launcher, run)


def proceed_quietly(launcher, run):
    """A busy project or an unreadable run waits for the next round."""
    try:
        proceed(launcher, run)
    except (ValueError, OSError, KeyError):
        return


def proceed(launcher, run):
    """Start the next task of a split, a pending validation or confirmed server checks."""
    state = json.loads(history.read_artifact(run, INDEX))
    delivery = delivery_state.view(run, state)
    if delivery is None:
        return
    if delivery["step"] == "implementing" and "tasks" in delivery:
        epic_launch.continue_quietly(launcher, run)
        return
    name = PENDING.get(delivery["step"])
    if name and name not in delivery["phases"]:
        start_phase(launcher, run, name)


def start_phase(launcher, run, name):
    """Start one phase run, or record that the executor cannot run it."""
    with launcher.lock:
        if name in epic_tasks.record(run).get("phases", {}):
            return None
        offers = executor_offers()
        if offers is None:
            return None
        if not offers.get(OFFERS[name]):
            return record_phase(run, name, UNAVAILABLE[name])
        state = json.loads(history.read_artifact(run, INDEX))
        checks = delivery_checks.checks(run, state)
        started = launcher.submit(delivery_payload.payload(run, state, name, checks))
        record_phase(run, name, started["id"])
        return started


def confirm(launcher, run):
    """The operator accepts the finished change; server checks may run after this."""
    state = json.loads(history.read_artifact(run, INDEX))
    delivery = delivery_state.view(run, state)
    if delivery is None or delivery["step"] != "confirm":
        raise ValueError("Only a finished change that waits for confirmation can be confirmed")
    epic = epic_tasks.record(run)
    epic["confirmed"] = time.time()
    atomic_json(run / epic_tasks.EPIC, epic)
    proceed_quietly(launcher, run)
    return dict(id=run.name, status="CONFIRMED")


def record_phase(run, name, entry):
    """Remember the phase run, or why it was skipped."""
    epic = epic_tasks.record(run)
    epic.setdefault("phases", {})[name] = entry
    atomic_json(run / epic_tasks.EPIC, epic)
    return dict(id=run.name, status="PHASE_RECORDED")


def executor_offers():
    """The executor catalog, {} when no executor is installed, None when it is unreachable."""
    if not Path(protocol.SOCKET).exists():
        return {}
    try:
        return client.request({"operation": "catalog"})
    except (OSError, ValueError):
        return None
