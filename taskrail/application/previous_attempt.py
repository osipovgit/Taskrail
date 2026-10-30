"""A retry of a split task continues from the edits of its earlier attempts."""

from taskrail.application import (
    inherited_preimages,
    outside_changes,
    prior_git,
    reviewed_artifacts,
    task_branch,
)
from taskrail.core import prompt_texts

FAILED = frozenset(("FAIL",))


def start(workflow, earlier, outside):
    """Continue from earlier attempts and name what changed outside the split's tasks."""
    if earlier:
        continue_from(workflow, earlier)
    if outside:
        outside_changes.announce(workflow, outside)


def continue_from(workflow, earlier):
    """Diff against the original bytes and tell the implementer what happened before."""
    allowed = set(workflow.state["preimages"])
    if task_branch.detect(workflow.config["roots"], workflow.config["worktrees"]):
        allowed = None
    inherited_preimages.inherit(workflow, earlier, allowed)
    prior_git.inherit(workflow, earlier)
    workflow.flow["feedback"] = feedback(earlier[-1])


def feedback(run):
    """The latest attempt's outcome, review findings and failed checks."""
    state = reviewed_artifacts.document(run, "run.json")
    note = prompt_texts.text("note.previous_attempt", run=run.name, status=state["status"])
    report = dict(instruction=note, summary=state.get("summary", ""))
    review = state.get("results", {}).get("review")
    if review:
        report["findings"] = reviewed_artifacts.document(run, review).get("findings", [])
    failed = list(filter(failed_check, state.get("checks", [])))
    if failed:
        report["checks"] = failed
    return report


def failed_check(check):
    """A built-in or configured check that did not pass."""
    return check.get("status") in FAILED
