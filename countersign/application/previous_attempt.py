"""A retry of a split task continues from the edits of its earlier attempts."""

from countersign.application import inherited_preimages, reviewed_artifacts
from countersign.core import prompt_texts

FAILED = frozenset(("FAIL",))


def continue_from(workflow, earlier):
    """Diff against the original bytes and tell the implementer what happened before."""
    allowed = set(workflow.state["preimages"])
    inherited_preimages.inherit(workflow, earlier, allowed)
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
