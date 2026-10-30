"""Authenticate a fresh corrective writer without inheriting approval to write."""

import json

from taskrail.application import (
    check_parents,
    delivery_confirmation,
    integration_changes,
    reviewed_artifacts,
    reviewed_input,
)
from taskrail.core import corrections, prompt_texts
from taskrail.core.files import digest
from taskrail.core.schema import require
from taskrail.git import reviewed_commit

RUN = "run"


def begin(workflow):
    """The rejected integration and exact server link authorize fresh planning only."""
    parent = reviewed_artifacts.parent(workflow.run.parent, workflow.config["check_parent"])
    review = rejected_review(workflow, parent)
    check_parents.adopt(workflow)
    workflow.state["check_parent"] = parent[RUN].name
    require(not workflow.config.get("read_only"), "A correction must allow its reviewed writer")
    require(not workflow.config.get("decompose"), "A correction cannot create another split")
    freeze_input(workflow, parent["state"], review)


def rejected_review(workflow, parent):
    """No stale source, unresolved writer or arbitrary rejected run can seed a correction."""
    run = linked_review(workflow, parent)
    state = reviewed_artifacts.document(run, "run.json")
    require(state["status"] == "CHANGES_REQUESTED", "Correction requires rejected integration")
    require(state.get("phase") == "integration", "Correction needs an integration review")
    require(state["roots"] == parent["state"]["roots"], "Correction review roots changed")
    settled(parent[RUN], workflow.run.name)
    delivery_confirmation.review_guard(run).verify(
        "Source changed since rejected integration; repeat review"
    )
    return reviewed_artifacts.document(run, state["results"]["review"])


def linked_review(workflow, parent):
    """The server's current rejected review and bounded correction slot are immutable."""
    entries = corrections.records(parent["epic"])
    current = entries[-1][RUN] if entries else None
    require(current == workflow.run.name, "Correction is not linked")
    settings = reviewed_artifacts.document(parent[RUN], "00-input/settings.json")
    require(len(entries) <= corrections.limit(settings), "Integration correction budget exhausted")
    selected = entries[-1]["review"]
    require(
        parent["epic"].get("phases", {}).get("integration") == selected, "Correction review changed"
    )
    return reviewed_artifacts.run_path(workflow.run.parent, selected)


def settled(parent, current):
    """Only completed prior corrective writers can be followed automatically."""
    for run in integration_changes.task_runs(parent):
        if run.name != current:
            reviewed_commit.require_settled(run)
    entries = corrections.records(reviewed_artifacts.document(parent, "epic.json"))
    for entry in entries:
        if entry[RUN] != current:
            state = reviewed_artifacts.document(parent.parent / entry[RUN], "run.json")
            require(
                state["status"] in {"READY_FOR_REVIEW", "NO_CHANGES_REQUIRED"},
                "Previous correction needs operator attention",
            )


def freeze_input(workflow, state, review):
    """Only original task input and authenticated findings enter the corrective brief."""
    spec = dict(state["task_spec"])
    context = prompt_texts.text(
        "correction.findings", findings=json.dumps(review, ensure_ascii=False)
    )
    spec.update(
        requirements=state["requirements"],
        assigned_requirements=state["requirements"],
        context="\n\n".join(filter(None, (spec.get("context"), context))),
        task_sha256=digest(workflow.config["task_text"].encode()),
    )
    reviewed_input.install(workflow, spec)


def refresh(workflow):
    """A reviewed corrective plan may add gates; seal the resulting continuation inputs."""
    corrective = workflow.config.get("phase") == corrections.PHASE
    if corrective and check_parents.SEAL in workflow.state:
        workflow.state[check_parents.SEAL] = check_parents.receipt(workflow)
