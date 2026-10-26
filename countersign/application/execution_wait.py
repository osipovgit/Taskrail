"""Persist executor tickets and return results to the same workflow."""

import json
import time

from countersign.application.artifacts import save_run
from countersign.core import control
from countersign.core.files import atomic_json
from countersign.executor import client, protocol
from countersign.interactions import output_preview

LEDGER = "execution.json"
STATUS = "status"
IDENTIFIER = "id"
TERMINAL = frozenset(("SUCCEEDED", "FAILED", "UNKNOWN", "REJECTED"))


def read(run):
    """Use a durable ledger independently of worker lifecycle metadata."""
    path = run / LEDGER
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


def submit(run, folder, action, kind="action", binding=None):
    """Persist the idempotency key before contacting the executor.

    The key includes the request's position in the run, so a repeated identical
    check is a new ticket rather than the earlier result; retries reuse the stored key.
    """
    entries = read(run)
    identity = dict(run=str(run), stage=folder.name, action=action)
    identity.update(sequence=len(entries), kind=kind)
    key = protocol.fingerprint(identity)
    entry = {"operation": "submit", "key": key, kind: action}
    pending = dict(request=entry, stage=folder.name, status="SUBMITTING", binding=binding)
    entries.append(pending)
    atomic_json(run / LEDGER, entries)


def resume(run, state):
    """Continue observing the existing ticket; never resubmit completed work."""
    entries = read(run)
    if not entries:
        return ""
    pending = entries[-1]
    while pending[STATUS] not in TERMINAL:
        control.check_stop(run)
        summary = observe(pending)
        atomic_json(run / LEDGER, entries)
        state["execution_jobs"] = entries
        state["summary"] = summary.format(pending[STATUS])
        save_run(run, state)
        if pending[STATUS] not in TERMINAL:
            time.sleep(2)
    state["execution_jobs"] = entries
    save_run(run, state)
    terminal_status = pending[STATUS]
    if terminal_status == "REJECTED":
        return "Remote action rejected by the operator. Nothing executed. Skip this action and continue feasible work; do not repeat the request unchanged."
    if terminal_status == "UNKNOWN":
        raise ValueError(
            "Remote outcome UNKNOWN. Inspect the target before submitting another action; no automatic replay."
        )
    evidence_path = save_snapshot(run, pending)
    return output_preview.ticket_preview(evidence_path, pending)


def observe(pending):
    """Update the ticket and return a summary; an unreachable executor is asked again.

    Repeating a submission with its stored key or a status query never executes twice.
    """
    query = pending["request"]
    if pending.get(IDENTIFIER):
        query = dict(operation=STATUS, id=pending[IDENTIFIER])
    try:
        pending.update(client.request(query))
    except OSError:
        return "Executor unreachable; retrying. Last status: {0}"
    return "Executor action: {0}"


def report_lines(state):
    """Separate observed server execution from deferred task verification."""
    jobs = state.get("execution_jobs", [])
    if not jobs:
        return []
    lines = [
        "",
        "## SSH and Jenkins execution",
        "",
        "Exact requests and outputs: [execution.json](execution.json)",
        "",
    ]
    for job in jobs:
        identifier = job.get("id", "pending")
        lines.append(f"- {identifier}: {job[STATUS]}")
    return lines


def save_snapshot(run, pending):
    """Keep completed ticket evidence at a stable, model-readable path."""
    filename = f"{protocol.label(pending[IDENTIFIER])}.json"
    destination = run / "00-input" / "ssh" / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        snapshot = json.loads(destination.read_text())
        if destination.is_symlink() or not snapshot or snapshot[-1] != pending:
            raise ValueError("Executor evidence snapshot changed")
    else:
        atomic_json(destination, [pending])
    output_preview.save_ticket_outputs(destination, pending)
    return destination
