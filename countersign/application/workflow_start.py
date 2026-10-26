"""Start a fresh run or continue from a validated checkpoint under the lock."""

import json

from countersign.application import (
    child_inputs,
    instruction_sources,
    resume_inputs,
    reviewed_input,
    reviewed_start,
)
from countersign.application.artifacts import save_run
from countersign.application.checkpoints import load_checkpoint
from countersign.application.workflow_state import FLOW_KEYS, STAGE
from countersign.core import control, prompt_texts
from countersign.core.files import atomic_json, digest
from countersign.interactions import approval_policy
from countersign.observability.progress import clock

INPUTS = "00-input"


def start(workflow, resume):
    """Prepare the guard and flow; a stop request is cleared only after validation.

    Allowing all actions comes from the task header unless the operator revoked it; a
    choice made on an approval card lasts until the worker exits.
    """
    instruction_sources.adopt_texts(workflow.run)
    if resume:
        restore(workflow, validated_checkpoint(workflow), resume)
    else:
        begin(workflow)
    workflow.state[approval_policy.AUTO_APPROVE] = approval_policy.at_start(
        workflow.run, workflow.config
    )
    workflow.state["decompose"] = workflow.config.get("decompose") is True
    workflow.state.setdefault("auto_continue", True)
    control.clear_stop(workflow.run, resume)


def begin(workflow):
    """Freeze role sources and fingerprint untouched sources."""
    inputs = workflow.run / INPUTS
    instruction_sources.capture(workflow.run, workflow.state, workflow.config["source"])
    workflow.guard.capture()
    workflow.state["phase"] = workflow.config.get("phase")
    atomic_json(inputs / "manifest.json", workflow.guard.before)
    atomic_json(inputs / "git-metadata.json", workflow.guard.git_before)
    reviewed_start.begin(workflow)


def validated_checkpoint(workflow):
    """Sources, Git, task, instructions and preimages must match the checkpoint."""
    run = workflow.run
    checkpoint = load_checkpoint(run, workflow.state)
    workflow.guard.before = json.loads(run.joinpath(INPUTS, "manifest.json").read_text())
    workflow.guard.adopt(checkpoint["expected"], checkpoint["git_before"])
    workflow.guard.verify(checkpoint_source_error(workflow.config))
    task_hash = checkpoint.get("task_hash")
    if task_hash and digest(workflow.config["task_text"].encode()) != task_hash:
        raise ValueError("Task changed since checkpoint; continuation refused")
    reviewed_input.restore(workflow)
    instruction_sources.verify(run, workflow.state)
    child_inputs.verify(run, workflow.state)
    resume_inputs.verify_preimages(run, workflow.state, workflow.guard.before)
    return checkpoint


def checkpoint_source_error(config):
    """A refused continuation must not send a split child into standalone planning."""
    if config.get("phase") == "task":
        return (
            "Source/Git changed since checkpoint; continuation refused. Open the parent split, "
            "inspect the current files and explicitly accept them for this task before retrying. "
            "Replan the parent if its scope or requirements changed."
        )
    return (
        "Source/Git changed since checkpoint; continuation refused. Use Restart for fresh planning."
    )


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
        feedback.update(interrupted=True, instruction=prompt_texts.text("note.interrupted_writer"))
    if note:
        feedback["operator_note"] = note
        feedback["note_rule"] = prompt_texts.text("note.operator")
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
