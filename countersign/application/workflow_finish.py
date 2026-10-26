"""Interruption checkpoints and the final report; nothing is rolled back."""

import json

from countersign.application.changes import write_diff
from countersign.application.run_report import report
from countersign.core.files import changed
from countersign.observability.progress import clock, say

PREIMAGES = "preimages"
DESIGN_FILE = "design.md"
STATUS = "status"


def interrupted(workflow):
    """Checkpoint only when every pending change is an approved write."""
    guard = workflow.guard
    current = guard.scan()
    pending = set(changed(guard.expected, current))
    if guard.git_unchanged() and pending.issubset(workflow.writable()):
        workflow.checkpoint(expected=current)
    workflow.state.update(
        status="INTERRUPTED", summary="Interrupted; changes preserved, no automatic replay"
    )


def close(workflow):
    """Finish the open record, refresh changes, write the report and remove profiles."""
    state = workflow.state
    if workflow.runtime["active"]:
        errors = [state.get("summary", "")]
        workflow.finish_active(state[STATUS], diagnostics={"errors": errors})
    try:
        refresh_changes(workflow)
    except (ValueError, OSError) as error:
        state["report_error"] = str(error)
    state["finished_at"] = clock()
    design_document(workflow)
    record_answer(workflow)
    report(workflow.run, state)
    for profile in workflow.runtime["profiles"]:
        profile.unlink(missing_ok=True)
    say("Status: {}\nReport: {}".format(state[STATUS], workflow.run / "report.md"))


def refresh_changes(workflow):
    """Record every file changed since the run started and the current diff."""
    state = workflow.state
    if workflow.guard.before is not None:
        state["changed_files"] = changed(workflow.guard.before, workflow.guard.scan())
    if state[PREIMAGES]:
        write_diff(workflow.run, workflow.config["roots"], state[PREIMAGES])


def design_document(workflow):
    """A finished design discussion leaves its reviewed document as design.md."""
    summary = reviewed_summary(workflow, "design")
    if summary is not None:
        workflow.run.joinpath(DESIGN_FILE).write_text(f"{summary}\n", encoding="utf-8")


def record_answer(workflow):
    """A finished question keeps its reviewed answer in the run index and report."""
    summary = reviewed_summary(workflow, "read_only")
    if summary is not None:
        workflow.state["answer"] = summary


def reviewed_summary(workflow, flag):
    """The approved plan's summary when a run of this mode finished without edits."""
    plan = workflow.state["results"].get("plan")
    finished = workflow.state[STATUS] == "NO_CHANGES_REQUIRED"
    if not workflow.config.get(flag) or not finished or not plan:
        return None
    plan_json = workflow.run.joinpath(plan).read_text(encoding="utf-8")
    return json.loads(plan_json)["summary"]
