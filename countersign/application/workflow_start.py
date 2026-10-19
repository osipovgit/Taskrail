"""Start a fresh run or continue from a validated checkpoint under the lock."""

import json

from countersign.application import instruction_sources, resume_inputs
from countersign.application.artifacts import save_run
from countersign.application.checkpoints import load_checkpoint
from countersign.application.workflow_state import FLOW_KEYS, STAGE
from countersign.core import control
from countersign.core.files import atomic_json, digest
from countersign.observability.progress import clock

INPUTS = "00-input"
OPERATOR_NOTE = "The operator wrote operator_note when continuing this run, for example after installing a missing tool. Use it to choose another way to finish; the task, approved scope and policy still apply."
INTERRUPTED_WRITER = (
    "An earlier implementation was interrupted. Inspect current files and preimages, "
    + "preserve applied changes, and finish only missing approved work. "
    + "Do not blindly replay edits."
)


def start(workflow, resume):
    """Prepare the guard and flow; a stop request is cleared only after validation."""
    if resume:
        restore(workflow, validated_checkpoint(workflow), resume)
    else:
        begin(workflow)
    control.clear_stop(workflow.run, resume)


def begin(workflow):
    """Freeze role sources and fingerprint untouched sources."""
    inputs = workflow.run / INPUTS
    instruction_sources.capture(workflow.run, workflow.state, workflow.config["source"])
    workflow.guard.capture()
    atomic_json(inputs / "manifest.json", workflow.guard.before)
    atomic_json(inputs / "git-metadata.json", workflow.guard.git_before)


def validated_checkpoint(workflow):
    """Sources, Git, task, instructions and preimages must match the checkpoint."""
    run = workflow.run
    checkpoint = load_checkpoint(run, workflow.state)
    workflow.guard.before = json.loads(run.joinpath(INPUTS, "manifest.json").read_text())
    workflow.guard.adopt(checkpoint["expected"], checkpoint["git_before"])
    workflow.guard.verify(
        "Source/Git changed since checkpoint; continuation refused. Use Restart for fresh planning."
    )
    task_hash = checkpoint.get("task_hash")
    if task_hash and digest(workflow.config["task_text"].encode()) != task_hash:
        raise ValueError("Task changed since checkpoint; continuation refused")
    instruction_sources.verify(run, workflow.state)
    resume_inputs.verify_preimages(run, workflow.state, workflow.guard.before)
    return checkpoint


def restore(workflow, checkpoint, mode):
    """Continue the recorded stage; an interrupted writer inspects before editing."""
    flow = workflow.flow
    flow.update((key, checkpoint[key]) for key in FLOW_KEYS)
    stage = flow[STAGE]
    note = workflow.runtime["note"]
    if stage == "implementer" or note:
        flow["feedback"] = continuation_feedback(checkpoint["feedback"], stage, note)
    workflow.runtime["recovery"] = resume_inputs.observations(
        workflow.run, workflow.state, stage, workflow.config["roots"]
    )
    if mode == "extend":
        resume_inputs.extend_budget(workflow.run, stage, workflow.config)
    reopen(workflow)


def continuation_feedback(previous, stage, note):
    """An interrupted writer inspects before editing; an operator note is passed verbatim."""
    feedback = dict(previous_feedback=previous)
    if stage == "implementer":
        feedback.update(interrupted=True, instruction=INTERRUPTED_WRITER)
    if note:
        feedback["operator_note"] = note
        feedback["note_rule"] = OPERATOR_NOTE
    return feedback


def reopen(workflow):
    """Close abandoned records and mark the run as running again."""
    state = workflow.state
    resume_inputs.interrupt_open_records(workflow.run, state)
    continuation = dict(started_at=clock(), stage=workflow.flow[STAGE])
    if workflow.runtime["note"]:
        continuation["operator_note"] = workflow.runtime["note"]
    state.setdefault("continuations", []).append(continuation)
    state.update(
        status="RUNNING",
        summary="Continuing from validated checkpoint",
        monitoring=dict(max_observed_tokens=workflow.config["max_observed_tokens"]),
    )
    state.pop("finished_at", None)
    save_run(workflow.run, state)
