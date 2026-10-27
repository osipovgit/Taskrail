"""Run files a stage writes besides source: the planner's plan, the implementer's progress.

Both live in the run directory and survive an interrupted session. Format repair
writes neither.
"""

from taskrail.application import plan_file, progress_file

PLANNER = "planner"
IMPLEMENTER = "implementer"
STAGE = "stage"


def record_access(workflow, record):
    """Name the stage's run file among the record's writable files."""
    if record[STAGE] == PLANNER:
        read_only = bool(workflow.config.get("read_only"))
        target = plan_file.prepare(workflow.run, workflow.state["requirements"], read_only)
        record["writable_files"].append(str(target))
    if record[STAGE] == IMPLEMENTER:
        record["writable_files"].append(str(progress_file.prepare(workflow.run)))


def grant(access, workflow, record, format_only):
    """Let the stage's profile read and write its run file."""
    if format_only:
        return
    if record[STAGE] == PLANNER:
        plan_file.grant(access, workflow.run, workflow.state["requirements"])
    if record[STAGE] == IMPLEMENTER:
        progress_file.grant(access, workflow.run)
