"""Follow the source lineage of a split before reusing a parent's approved contract.

Tasks of a split run in plan order, so every task starts from the source the earlier
tasks left. Each run started for a task is an attempt; the chain passes through every
attempt that ran a stage, and only the last attempt of an earlier task must have an
independently approved result. A retry of the current task continues from its earlier
attempts' edits.

Files or Git state that changed between two links of the chain were changed outside
the split's tasks, by the operator or another tool. They do not stop a task: its
implementer and its report name them, because a later task may find its work already
done there or may need to change those files too.
"""

from taskrail.application import outside_changes, reviewed_artifacts
from taskrail.core import delivery_record, schema, task_graph

FINISHED = frozenset(("READY_FOR_REVIEW", "NO_CHANGES_REQUIRED"))
ACTIVE = frozenset(("STARTING", "RUNNING"))
STATUS = "status"
CHECKPOINT = "checkpoint.json"
EXPECTED = outside_changes.EXPECTED
GIT = outside_changes.GIT


def verify(parent, task_id, workflow):
    """(earlier attempts of this task that ran, changes made outside the split's tasks).

    The changes are None when the source is exactly where the chain left it.
    """
    roots = parent["state"]["roots"]
    schema.require(roots == workflow.state["roots"], "Parent roots changed")
    drift = outside_changes.Drift()
    start = after_earlier_tasks(parent, task_id, drift)
    checkpoint, earlier = chain(parent, own_attempts(parent, task_id, workflow), start, drift)
    drift.between(checkpoint, {EXPECTED: workflow.guard.expected, GIT: workflow.guard.git_before})
    return earlier, drift.summary(roots)


def own_attempts(parent, task_id, workflow):
    """The earlier runs started for this task, oldest first."""
    attempts = delivery_record.attempts(parent["epic"], task_id)
    return [run for run in attempts if run != workflow.run.name]


def after_earlier_tasks(parent, task_id, outside):
    """The checkpoint where the tasks before this one in plan order left the source."""
    checkpoint = reviewed_artifacts.document(parent["run"], CHECKPOINT)
    order = task_graph.order(parent["plan"]["steps"])
    for name in order[: order.index(task_id)]:
        checkpoint = completed_task(parent, name, checkpoint, outside)
    return checkpoint


def completed_task(parent, name, checkpoint, outside):
    """An earlier task: its attempts in order, the last one independently approved."""
    names = delivery_record.attempts(parent["epic"], name)
    schema.require(bool(names), "Earlier task has not completed; parent replanning required")
    child = reviewed_artifacts.run_path(parent["run"].parent, names[-1])
    state = reviewed_artifacts.document(child, "run.json")
    schema.require(state[STATUS] in FINISHED, "Earlier task has no accepted result")
    verify_review(child, state["results"])
    return chain(parent, names, checkpoint, outside)[0]


def chain(parent, names, checkpoint, outside):
    """(checkpoint after the attempts, the attempts that ran)."""
    ran = []
    for name in names:
        checkpoint = attempt(parent, name, checkpoint, ran, outside)
    return checkpoint, ran


def attempt(parent, name, checkpoint, ran, outside):
    """The checkpoint after one attempt; an attempt that ran a stage is added to ran.

    An attempt that never ran a stage changed nothing. Any other attempt must not be
    running; what changed between the chain and its start was changed outside the tasks.
    """
    child = reviewed_artifacts.run_path(parent["run"].parent, name)
    if not child.joinpath(CHECKPOINT).is_file():
        return checkpoint
    state = reviewed_artifacts.document(child, "run.json")
    schema.require(state[STATUS] not in ACTIVE, "An attempt of this task is still running")
    started = {
        EXPECTED: reviewed_artifacts.document(child, "00-input/manifest.json"),
        GIT: reviewed_artifacts.document(child, "00-input/git-metadata.json"),
    }
    outside.between(checkpoint, started)
    ran.append(child)
    return reviewed_artifacts.document(child, CHECKPOINT)


def verify_review(child, references):
    """A previous implementation must have an independently accepted final result."""
    review_reference = references.get("review") or references.get("plan-review")
    schema.require(bool(review_reference), "Prerequisite needs independent review")
    review = reviewed_artifacts.document(child, review_reference)
    schema.require(review[STATUS] == "APPROVE", "Prerequisite review did not approve")
