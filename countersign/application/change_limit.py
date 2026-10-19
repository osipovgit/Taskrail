"""A change larger than the configured limit waits for the operator before checks."""

from countersign.interactions import approval_policy

IMPLEMENTER = "implementer"
SIZE_KEYS = ("lines", "files")
HEADERS = ("+++", "---")
MARKERS = ("+", "-")
NOTICE = "The implementation is larger than the configured change limit. Allow to continue to checks and review, Deny to stop with the changes preserved, or send an alternative to return it to the implementer."


def approved(workflow):
    """True when the change may proceed; otherwise the flow or the state says why not."""
    size = change_size(workflow)
    if not exceeds(size, workflow.config):
        return True
    if covered(size, workflow.state.get("approved_change")):
        return True
    request = dict(stage="check", status="CHANGE_LIMIT", notice=NOTICE, **size)
    request["limits"] = dict(
        lines=workflow.config["max_change_lines"], files=workflow.config["max_change_files"]
    )
    decision = approval_policy.decision(workflow.run, request, workflow.state)
    if decision["decision"] == "allow":
        workflow.state["approved_change"] = size
        return True
    refuse(workflow, size, decision)
    return False


def change_size(workflow):
    """Changed diff lines and changed files since the run started."""
    diff = workflow.run / "changes.diff"
    lines = diff.read_text(encoding="utf-8").splitlines() if diff.is_file() else []
    edits = [line for line in lines if is_edit(line)]
    return dict(lines=len(edits), files=len(workflow.state["changed_files"]))


def is_edit(line):
    """An added or removed diff line, not a file header."""
    if line.startswith(HEADERS):
        return False
    return line.startswith(MARKERS)


def exceeds(size, config):
    """A zero limit is disabled."""
    over_lines = 0 < config["max_change_lines"] < size["lines"]
    return over_lines or 0 < config["max_change_files"] < size["files"]


def covered(size, accepted):
    """The operator already allowed a change at least this large."""
    if not accepted:
        return False
    return all(size[key] <= accepted[key] for key in SIZE_KEYS)


def refuse(workflow, size, decision):
    """An alternative returns the change to the implementer; a denial stops the run."""
    if decision["decision"] == "alternative":
        feedback = dict(change_limit=size, operator_note=decision.get("alternative", ""))
        workflow.flow.update(stage=IMPLEMENTER, feedback=feedback)
        return
    summary = "Change of {lines} lines in {files} files exceeds the limit; stopped by the operator"
    workflow.state.update(status="CHANGE_LIMIT_EXCEEDED", summary=summary.format(**size))
