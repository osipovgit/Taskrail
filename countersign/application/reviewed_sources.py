"""Check the ordered source lineage before reusing a parent's approved contract.

Tasks of a split run in plan order, so every task starts from the source the earlier
tasks left. Each run started for a task is an attempt; the chain passes through every
attempt that ran a stage, and only the last attempt of an earlier task must have an
independently approved result. A retry of the current task therefore continues from
its earlier attempts' edits, and an operator baseline accepts intended edits between
tasks.
"""

from countersign.application import reviewed_artifacts
from countersign.core import delivery_record, schema, task_graph

FINISHED = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED"))
ACTIVE = frozenset(("STARTING", "RUNNING"))
STATUS = "status"
CHECKPOINT = "checkpoint.json"
EXPECTED = "expected"
GIT = "git_before"


def verify(parent, task_id, workflow):
    """The current source must be where the chain of earlier attempts left it.

    Returns the earlier attempts of the current task that ran, oldest first.
    """
    roots = parent["state"]["roots"]
    schema.require(roots == workflow.state["roots"], "Parent roots changed")
    attempts = delivery_record.attempts(parent["epic"], task_id)
    earlier_attempts = [run for run in attempts if run != workflow.run.name]
    checkpoint, earlier = chain(
        parent, task_id, earlier_attempts, after_earlier_tasks(parent, task_id)
    )
    schema.require(
        checkpoint[EXPECTED] == workflow.guard.expected,
        "Sources changed since reviewed task prerequisites; accept the current files for "
        "this task or replan the parent",
    )
    schema.require(
        checkpoint[GIT] == workflow.guard.git_before,
        "Git changed since reviewed task prerequisites; parent replanning required",
    )
    return earlier


def after_earlier_tasks(parent, task_id):
    """The checkpoint where the tasks before this one in plan order left the source."""
    checkpoint = reviewed_artifacts.document(parent["run"], CHECKPOINT)
    order = task_graph.order(parent["plan"]["steps"])
    for name in order[: order.index(task_id)]:
        checkpoint = completed_task(parent, name, checkpoint)
    return checkpoint


def completed_task(parent, name, checkpoint):
    """An earlier task: its attempts in order, the last one independently approved."""
    names = delivery_record.attempts(parent["epic"], name)
    schema.require(bool(names), "Earlier task has not completed; parent replanning required")
    child = reviewed_artifacts.run_path(parent["run"].parent, names[-1])
    state = reviewed_artifacts.document(child, "run.json")
    schema.require(state[STATUS] in FINISHED, "Earlier task has no accepted result")
    verify_review(child, state["results"])
    return chain(parent, name, names, checkpoint)[0]


def chain(parent, task, names, checkpoint):
    """(checkpoint after the attempts, the attempts that ran), with any operator baseline.

    A baseline replaces the chain at the attempt count it was accepted at.
    """
    baseline = parent["epic"].get("baselines", {}).get(task)
    ran = []
    for index, name in enumerate(names):
        checkpoint = attempt(parent, name, rebased(baseline, index, checkpoint), ran)
    return rebased(baseline, len(names), checkpoint), ran


def rebased(baseline, index, checkpoint):
    """The operator's accepted source when the chain reaches its position."""
    if baseline and baseline["after"] == index:
        return baseline
    return checkpoint


def attempt(parent, name, checkpoint, ran):
    """The checkpoint after one attempt; an attempt that ran a stage is added to ran.

    An attempt that never ran a stage changed nothing. Any other attempt must have
    started exactly where the chain stood and must not be running.
    """
    child = reviewed_artifacts.run_path(parent["run"].parent, name)
    if not child.joinpath(CHECKPOINT).is_file():
        return checkpoint
    state = reviewed_artifacts.document(child, "run.json")
    schema.require(state[STATUS] not in ACTIVE, "An attempt of this task is still running")
    before = reviewed_artifacts.document(child, "00-input/manifest.json")
    schema.require(before == checkpoint[EXPECTED], "Prerequisite source lineage changed")
    ran.append(child)
    return reviewed_artifacts.document(child, CHECKPOINT)


def verify_review(child, references):
    """A previous implementation must have an independently accepted final result."""
    review_reference = references.get("review") or references.get("plan-review")
    schema.require(bool(review_reference), "Prerequisite needs independent review")
    review = reviewed_artifacts.document(child, review_reference)
    schema.require(review[STATUS] == "APPROVE", "Prerequisite review did not approve")
