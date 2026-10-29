"""Run files a stage writes besides source: the plan, the progress and the review.

They live in the run directory and survive an interrupted session. Each turn of the
stage attaches its run file, so opencode reads it in every process of the session and
never rejects its overwrite as unread.
"""

from taskrail.application import plan_file, progress_file, review_file

PLANNER = "planner"
IMPLEMENTER = "implementer"
REVIEWS = frozenset(("plan-reviewer", "reviewer"))
STAGE = "stage"
ATTACHED = "attached_files"
REQUIREMENTS = "requirements"


def record_access(workflow, record):
    """Name the stage's run file among the record's writable and attached files."""
    target = None
    if record[STAGE] == PLANNER:
        read_only = bool(workflow.config.get("read_only"))
        target = plan_file.prepare(workflow.run, workflow.state[REQUIREMENTS], read_only)
    if record[STAGE] == IMPLEMENTER:
        target = progress_file.prepare(workflow.run)
    if record[STAGE] in REVIEWS:
        requirements = workflow.state[REQUIREMENTS]
        target = review_file.prepare(workflow.run, requirements, new(workflow))
    if target is not None:
        record["writable_files"].append(str(target))
        record[ATTACHED] = [str(target)]


def grant(access, workflow, record):
    """Let the stage's profile read and write its run file."""
    if record[STAGE] == PLANNER:
        plan_file.grant(access, workflow.run, workflow.state[REQUIREMENTS])
    if record[STAGE] == IMPLEMENTER:
        progress_file.grant(access, workflow.run)
    if record[STAGE] in REVIEWS:
        review_file.grant(access, workflow.run, workflow.state[REQUIREMENTS])


def new(workflow):
    """A review that starts after another stage writes a fresh review file."""
    recent = workflow.state["stages"][-2:]
    names = {entry[STAGE] for entry in recent}
    return len(recent) == 1 or len(names) == 2
