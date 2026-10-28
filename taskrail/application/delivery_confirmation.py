"""Bind personal delivery confirmation to reviewed files, Git and completion evidence."""

import json
from pathlib import Path

from taskrail.application import reviewed_artifacts
from taskrail.application.source_guard import SourceGuard
from taskrail.core import delivery_record
from taskrail.core.files import digest
from taskrail.core.schema import require

INPUTS = "confirmed_inputs"
ROOTS = "roots"
ERROR = "Confirmed source/Git or review evidence changed; repeat review and confirmation"
ROOT_ERROR = "Reviewed delivery roots differ"


def review_guard(run):
    """Use the completed review's checkpoint, never a new baseline at confirmation."""
    state = reviewed_artifacts.document(run, "run.json")
    require(isinstance(state.get(ROOTS), dict), ROOT_ERROR)
    checkpoint = reviewed_artifacts.document(run, "checkpoint.json")
    return guard(dict(roots=state[ROOTS], **checkpoint))


def guard(snapshot):
    """Restore the exact source and Git boundary recorded by independent review."""
    stored = snapshot[ROOTS]
    roots = {alias: Path(root) for alias, root in stored.items()}
    boundary = SourceGuard(roots)
    boundary.adopt(snapshot["expected"], snapshot["git_before"])
    return boundary


def links(epic):
    """Server attempts may change; the accepted tasks and prior checks may not."""
    phases = epic.get("phases", {})
    return dict(
        tasks=epic.get("tasks", {}),
        phases={name: phases[name] for name in ("integration", "validation") if name in phases},
    )


def evidence(run, roots):
    """Bind completed state and the result artifacts it cites, not only its status."""
    state = reviewed_artifacts.document(run, "run.json")
    require(state.get(ROOTS) == roots, ROOT_ERROR)
    outcomes = {
        name: digest(reviewed_artifacts.read(run, reference))
        for name, reference in state.get("results", {}).items()
    }
    for reference in ("00-input/task.md", "checkpoint.json"):
        if (run / reference).exists():
            outcomes[reference] = digest(reviewed_artifacts.read(run, reference))
    encoded = json.dumps(dict(state=state, results=outcomes), sort_keys=True)
    return digest(encoded.encode())


def capture(run, reviewed, epic):
    """Freeze the reviewed checkpoint and every accepted completion used by this delivery."""
    boundary = review_guard(reviewed)
    roots = {alias: str(root) for alias, root in boundary.roots.items()}
    return dict(
        roots=roots,
        expected=boundary.expected,
        git_before=boundary.git_before,
        records=completed_records(run, links(epic), roots),
        links=links(epic),
    )


def completed_records(run, accepted, roots):
    """Include each linked successful task and prior check once."""
    names = {run.name, *accepted["tasks"].values()}
    names.update(
        name for name in accepted["phases"].values() if delivery_record.RUN_NAME.fullmatch(name)
    )
    runs = [reviewed_artifacts.run_path(run.parent, name) for name in sorted(names)]
    return {member.name: evidence(member, roots) for member in runs}


def verify(run, epic=None):
    """A missing legacy snapshot fails closed; every server action rechecks this boundary."""
    record = delivery_record.read(run) if epic is None else epic
    snapshot = record.get(INPUTS)
    require(bool(record.get("confirmed")), ERROR)
    require(isinstance(snapshot, dict), ERROR)
    require(snapshot["links"] == links(record), ERROR)
    for name, expected in snapshot["records"].items():
        member = reviewed_artifacts.run_path(run.parent, name)
        require(evidence(member, snapshot[ROOTS]) == expected, ERROR)
    guard(snapshot).verify(ERROR)
