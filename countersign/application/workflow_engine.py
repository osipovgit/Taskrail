"""The single execution path of CLI and web runs."""

import contextlib
import fcntl
import subprocess
from pathlib import Path

from countersign.application import attempt_context, run_setup, transitions, workflow_start
from countersign.application.changes import capture_preimages, write_diff
from countersign.application.check_stage import run_checks
from countersign.application.run_report import report
from countersign.application.stage_attempts import StageAttempts
from countersign.application.workflow_finish import close, interrupted
from countersign.application.workflow_state import STAGE, Workflow
from countersign.core import control

LOCK = Path(".local/state/countersign/live.lock")
FAILURES = (ValueError, OSError, KeyError, subprocess.TimeoutExpired)
RUNNING = "RUNNING"
STATUS = "status"
PREIMAGES = "preimages"


def execute(request):
    """Run or continue one task under the global single-writer lock."""
    config, run, state = run_setup.open_run(request)
    with execution_lock() as acquired:
        if acquired:
            supervise(Workflow(config, run, state, request), request["resume"])
        elif request["resume"]:
            raise ValueError("Another live run holds the lock; continuation was not started")
        else:
            state.update(status="BLOCKED", summary="Another live run holds the lock")
            report(run, state)
    return run, state[STATUS]


@contextlib.contextmanager
def execution_lock():
    """Yield whether this process holds the lock; it is released on exit."""
    path = Path.home() / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        yield locked(lock)


def locked(lock):
    """Try the exclusive lock without waiting."""
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        return False
    return True


def supervise(workflow, resume):
    """Every stop path ends with a report; no change is rolled back."""
    try:
        run_stages(workflow, resume)
    except KeyboardInterrupt:
        interrupted(workflow)
    except FAILURES as error:
        workflow.state.update(status=attempt_context.failure_status(error), summary=str(error))
    finally:
        close(workflow)


def run_stages(workflow, resume):
    """Advance stages until a terminal status; every stage starts from verified sources."""
    workflow_start.start(workflow, resume)
    while workflow.state[STATUS] == RUNNING:
        control.check_stop(workflow.run)
        control.check_stage(workflow.flow[STAGE], workflow.config)
        workflow.checkpoint()
        workflow.guard.verify("Source/Git changed outside the workflow; stopped without rollback")
        if workflow.flow[STAGE] == "check":
            run_checks(workflow)
        else:
            model_stage(workflow)


def model_stage(workflow):
    """Apply a valid verdict through the pure transitions and their write effects."""
    outcome = StageAttempts(workflow).run()
    if outcome is None:
        return
    verdict, record = outcome
    reference = "{0}/result.json".format(record["directory"])
    transitions.advance(
        workflow.flow, workflow.state, verdict, reference, workflow.config["max_repairs"]
    )
    effect = workflow.flow.pop("effect", None)
    if workflow.state[STATUS] == RUNNING:
        apply_effect(workflow, effect)


def apply_effect(workflow, effect):
    """Capture preimages before implementation; refresh the diff after it."""
    roots = workflow.config["roots"]
    preimages = workflow.state[PREIMAGES]
    if effect == "capture_preimages":
        capture_preimages(workflow.run, roots, workflow.flow["allowed"], preimages)
    elif effect == "write_diff":
        write_diff(workflow.run, roots, preimages)
