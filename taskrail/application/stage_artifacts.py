"""Run files a stage writes besides source: the planner's plan, the implementer's progress.

Both live in the run directory and survive an interrupted session. Each turn of the
stage attaches its run file, so opencode reads it in every process of the session and
never rejects its overwrite as unread. Format repair writes neither.
"""

from taskrail.application import plan_file, progress_file

PLANNER = "planner"
IMPLEMENTER = "implementer"
STAGE = "stage"
ATTACHED = "attached_files"


def record_access(workflow, record):
    """Name the stage's run file among the record's writable and attached files."""
    target = None
    if record[STAGE] == PLANNER:
        read_only = bool(workflow.config.get("read_only"))
        target = plan_file.prepare(workflow.run, workflow.state["requirements"], read_only)
    if record[STAGE] == IMPLEMENTER:
        target = progress_file.prepare(workflow.run)
    if target is not None:
        record["writable_files"].append(str(target))
        record[ATTACHED] = [str(target)]


def grant(access, workflow, record, format_only):
    """Let the stage's profile read and write its run file."""
    if format_only:
        return
    if record[STAGE] == PLANNER:
        plan_file.grant(access, workflow.run, workflow.state["requirements"])
    if record[STAGE] == IMPLEMENTER:
        progress_file.grant(access, workflow.run)
