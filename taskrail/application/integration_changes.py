"""The combined change of a finished split, shown to its integration review."""

import json

from taskrail.application import (
    correction_history,
    feedback_files,
    inherited_preimages,
    reviewed_artifacts,
    reviewed_input,
)
from taskrail.application.changes import write_diff
from taskrail.core import corrections, delivery_record, task_graph
from taskrail.core.files import digest
from taskrail.core.schema import require


def capture(workflow, parent):
    """changes.diff of every task run against the files before the split.

    The parent link is authenticated by check_parents before this runs.
    """
    completed = correction_history.completed(parent)
    if completed:
        reports = [resolved_findings(run, state) for run, state in completed]
        workflow.flow["feedback"] = feedback_files.findings(workflow.run / "00-input", reports)
    runs = task_runs(parent)
    if runs:
        inherited_preimages.inherit(workflow, runs)
        write_diff(workflow)


def resolved_findings(run, state):
    """Bring disputed and accepted fixes back to combined review with their original findings."""
    spec = reviewed_artifacts.read(run, reviewed_input.REFERENCE)
    require(digest(spec) == state[reviewed_input.SIGNATURE], "Reviewed correction input changed")
    original = reviewed_artifacts.read(run, reviewed_input.FINDINGS)
    expected = json.loads(spec)["findings_sha256"]
    require(digest(original) == expected, "Correction findings changed")
    plan = reviewed_artifacts.document(run, state["results"]["plan"])
    findings = json.loads(original)
    return dict(run=run.name, findings=findings, reviewed_steps=plan["steps"])


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
