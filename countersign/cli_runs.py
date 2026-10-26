"""One run from the CLI: found by ID or directory, controlled, answered and read."""

import json
from pathlib import Path

from countersign.core.runtime import run_storage
from countersign.interactions import approvals
from countersign.web import delivery_state, history, run_activity
from countersign.web.submissions import TaskLauncher

STATUS_FIELDS = ("status", "summary", "answer", "changed_files")
DELIVERY_FIELDS = ("step", "progress", "next")


def launcher(args):
    """The browser's launcher on the configured run store.

    The service recovers launches its last process left behind; a CLI command does
    not, because the service may be starting a worker meanwhile.
    """
    return TaskLauncher(run_storage(args.settings, args.runs_dir), args.settings, recover=False)


def run_path(args):
    """A run of the configured store, by ID or by its directory."""
    base = run_storage(args.settings, args.runs_dir)
    candidate = Path(args.run).expanduser()
    if not candidate.is_dir():
        return history.checked_run(base, args.run)
    if candidate.resolve().parent != base:
        raise ValueError(f"The run is not in the run store {base}")
    return candidate.resolve()


def action_payload(args):
    """The fields of POST /api/actions; a note or task only when given."""
    payload = dict(id=run_path(args).name, action=args.action)
    if args.note is not None:
        payload["note"] = args.note
    if args.task is not None:
        payload["task"] = args.task
    return payload


def decide(args):
    """Bind the decision to the ticket the run waits for right now."""
    run = run_path(args)
    pending = approvals.load(run)
    if pending is None:
        raise ValueError("The run is not waiting for an approval")
    payload = dict(id=run.name, ticket=pending["ticket"], decision=args.decision)
    payload["alternative"] = args.text
    if args.allow_all:
        payload["allow_all"] = True
    return launcher(args).route("/api/decision", payload)


def status(args):
    """Run status, pending approval request and delivery step.

    `active` tells whether a worker holds the run: a RUNNING run without one was
    left behind by a stopped process and continues only through `action resume`.
    """
    run = run_path(args)
    state = json.loads(history.read_artifact(run, "run.json"))
    report = {key: state.get(key) for key in STATUS_FIELDS}
    report.update(id=run.name, report=str(run / "report.md"))
    report["active"] = run_activity.run_held(run)
    pending = approvals.load(run)
    if pending is not None:
        report["approval"] = pending["request"]
    delivery = delivery_state.view(run, state)
    if delivery is not None:
        report["delivery"] = {key: delivery.get(key) for key in DELIVERY_FIELDS}
    return report
