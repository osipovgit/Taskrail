"""Check a final response while its session can still correct it."""

from countersign.application import evidence
from countersign.application.attempt_session import validated
from countersign.core.files import changed


def preview(workflow, active, roots, outcome):
    """The validation error of a final response, or None when it would pass.

    Evidence is refreshed from the session's events first. A writer's changed files
    are the current ones, as the end of the stage would record them.
    """
    folder, record = active
    evidence.refresh(workflow.run, folder / "events.jsonl", roots)
    guard = workflow.guard
    if workflow.writable() and guard.before is not None:
        workflow.state["changed_files"] = changed(guard.before, guard.scan())
    try:
        validated(workflow, record, outcome)
    except (ValueError, TypeError) as error:
        return str(error)
    return None
