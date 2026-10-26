"""The single execution path of CLI and web runs."""

import subprocess

from countersign.application import (
    attempt_context,
    check_batches,
    check_parents,
    planned_checks,
    reviewed_artifacts,
    run_setup,
    transitions,
    workflow_start,
)
from countersign.application.changes import capture_preimages, write_diff
from countersign.application.check_stage import run_checks
from countersign.application.run_locks import run_locks
from countersign.application.run_report import report
from countersign.application.stage_attempts import StageAttempts
from countersign.application.workflow_finish import close, interrupted
from countersign.application.workflow_state import STAGE, Workflow
from countersign.core import control

FAILURES = (ValueError, OSError, KeyError, subprocess.TimeoutExpired)
RUNNING = "RUNNING"
STATUS = "status"
PREIMAGES = "preimages"


def execute(request):
    """Run or continue one task while its project roots and run directory are locked."""
    config, run = run_setup.configure(request)
    sources = run_setup.source_roots(config, request)
    with run_locks(sources, run) as reason:
        if reason and request["resume"]:
            raise ValueError(f"{reason}; continuation was not started")
        state = run_setup.open_state(config, run, request, ready=reason is None)
        if reason is None:
            supervise(Workflow(config, run, state, request), request["resume"])
        else:
            state.update(status="BLOCKED", summary=reason)
            report(run, state)
    return run, state[STATUS]


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
    prepare_stages(workflow, resume)
    while workflow.state[STATUS] == RUNNING:
        control.check_stop(workflow.run)
        control.check_stage(workflow.flow[STAGE], workflow.config)
        workflow.checkpoint()
        workflow.guard.verify("Source/Git changed outside the workflow; stopped without rollback")
        if workflow.flow[STAGE] == "check":
            run_checks(workflow)
        else:
            model_stage(workflow)


def prepare_stages(workflow, resume):
    """Authenticate inherited inputs before executing a fixed batch or launching models."""
    workflow_start.start(workflow, resume)
    check_parents.adopt(workflow, resume)
    check_batches.run_configured(workflow)


def model_stage(workflow):
    """Apply a valid verdict through the pure transitions and their write effects."""
    outcome = StageAttempts(workflow).run()
    if outcome is None:
        return
    verdict, record = outcome
    reference = "{}/result.json".format(record["directory"])
    transitions.advance(
        workflow.flow, workflow.state, verdict, reference, workflow.config["max_repairs"]
    )
    if record["stage"] == "plan-reviewer":
        planned_checks.activate(workflow)
        reviewed_artifacts.seal(workflow)
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
