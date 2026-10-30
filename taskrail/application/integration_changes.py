"""The combined change of a finished split, shown to its integration review."""

from taskrail.application import correction_history, inherited_preimages, reviewed_artifacts
from taskrail.application.changes import write_diff
from taskrail.core import corrections, delivery_record, task_graph


def capture(workflow, parent):
    """changes.diff of every task run against the files before the split.

    The parent link is authenticated by check_parents before this runs.
    """
    correction_history.completed(parent)
    runs = task_runs(parent)
    if runs:
        inherited_preimages.inherit(workflow, runs)
        write_diff(workflow.run, workflow.config["roots"], workflow.state["preimages"])


def task_runs(parent):
    """Every attempt of every task of a split, in plan order."""
    state = reviewed_artifacts.document(parent, "run.json")
    reference = state.get("results", {}).get("plan")
    if reference is None:
        return []
    plan = reviewed_artifacts.document(parent, reference)
    epic = delivery_record.read(parent)
    children = [
        reviewed_artifacts.run_path(parent.parent, attempt)
        for task in task_graph.order(plan["steps"])
        for attempt in delivery_record.attempts(epic, task)
    ]
    return [
        *children,
        *[
            reviewed_artifacts.run_path(parent.parent, entry["run"])
            for entry in corrections.records(epic)
        ],
    ]
