"""Check the ordered source lineage before reusing a parent's approved contract."""

from countersign.application import reviewed_artifacts
from countersign.core import schema, task_graph

FINISHED = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED"))
STATUS = "status"


def verify(parent, task_id, workflow):
    """All earlier child effects must form an unchanged, independently reviewed chain."""
    parent_roots = parent["state"]["roots"]
    schema.require(parent_roots == workflow.state["roots"], "Parent roots changed")
    checkpoint = reviewed_artifacts.document(parent["run"], "checkpoint.json")
    for name in task_graph.order(parent["plan"]["steps"]):
        if name == task_id:
            break
        checkpoint = child_checkpoint(parent, name, checkpoint)
    schema.require(
        checkpoint["expected"] == workflow.guard.expected,
        "Sources changed since reviewed task prerequisites; parent replanning required",
    )
    schema.require(
        checkpoint["git_before"] == workflow.guard.git_before,
        "Git changed since reviewed task prerequisites; parent replanning required",
    )


def child_checkpoint(parent, name, checkpoint):
    """A manually marked task cannot supply an unreviewed implementation contract."""
    child_id = parent["epic"].get("tasks", {}).get(name)
    schema.require(bool(child_id), "Earlier task has not completed; parent replanning required")
    child = reviewed_artifacts.run_path(parent["run"].parent, child_id)
    state = reviewed_artifacts.document(child, "run.json")
    schema.require(state[STATUS] in FINISHED, "Earlier task has no accepted result")
    before = reviewed_artifacts.document(child, "00-input/manifest.json")
    schema.require(before == checkpoint["expected"], "Prerequisite source lineage changed")
    verify_review(child, state["results"])
    return reviewed_artifacts.document(child, "checkpoint.json")


def verify_review(child, references):
    """A previous implementation must have an independently accepted final result."""
    review_reference = references.get("review") or references.get("plan-review")
    schema.require(bool(review_reference), "Prerequisite needs independent review")
    review = reviewed_artifacts.document(child, review_reference)
    schema.require(review[STATUS] == "APPROVE", "Prerequisite review did not approve")
