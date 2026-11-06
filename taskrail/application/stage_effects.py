"""Apply durable effects only after a validated stage transition."""

from taskrail.application import planned_checks, reviewed_artifacts, understanding_file
from taskrail.application.artifacts import save_run
from taskrail.application.changes import capture_preimages, write_diff
from taskrail.application.correction_start import refresh as refresh_correction
from taskrail.application.task_commit import commit


def apply(workflow, record, verdict):
    """Bind an interpretation or reviewed plan before any next stage can start."""
    if record["stage"] == "plan-reviewer" and verdict["status"] != "REINTERPRET_TASK":
        planned_checks.activate(workflow)
        reviewed_artifacts.seal(workflow)
        refresh_correction(workflow)
    effect = workflow.flow.pop("effect", None)
    if effect == "understood":
        understanding_file.install(workflow, verdict)
    elif effect == "commit":
        commit(workflow)
    elif workflow.state["status"] == "RUNNING":
        source_effect(workflow, effect)
    save_run(workflow.run, workflow.state)
    if workflow.state["status"] == "RUNNING":
        workflow.checkpoint()


def source_effect(workflow, effect):
    """Capture preimages before implementation; refresh the diff after it."""
    roots = workflow.config["roots"]
    preimages = workflow.state["preimages"]
    if effect == "capture_preimages":
        capture_preimages(workflow.run, roots, workflow.flow["allowed"], preimages)
    elif effect == "write_diff":
        write_diff(workflow.run, roots, preimages)
