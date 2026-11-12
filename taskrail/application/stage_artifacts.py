"""Run files a stage writes besides source: the plan, the progress and the review.

They live in the run directory and survive an interrupted session. Each turn of the
stage attaches its run file, so opencode reads it in every process of the session and
never rejects its overwrite as unread.
"""

from taskrail.application import plan_file, progress_file, review_file, understanding_file
from taskrail.infrastructure import stage_scratch

PLANNER = "planner"
IMPLEMENTER = "implementer"
REVIEWS = frozenset(("plan-reviewer", "reviewer"))
STAGE = "stage"
ATTACHED = "attached_files"
REQUIREMENTS = "requirements"


def record_access(workflow, record):
    """Name the stage's run file among the record's writable and attached files."""
    target = None
    stage = record[STAGE]
    if stage == understanding_file.STAGE:
        target = understanding_file.prepare(workflow.run)
    else:
        scratch = stage_scratch.prepare(workflow.run / record["directory"])
        record["scratch_directory"] = str(scratch)
        record["writable_files"].append(str(scratch))
    if stage == PLANNER:
        read_only = bool(workflow.config.get("read_only"))
        target = plan_file.prepare(workflow.run, workflow.state[REQUIREMENTS], read_only)
    if stage == IMPLEMENTER:
        target = progress_file.prepare(workflow.run)
    if stage in REVIEWS:
        requirements = workflow.state[REQUIREMENTS]
        target = review_file.prepare(workflow.run, requirements, new(workflow))
    if target is not None:
        record["writable_files"].append(str(target))
        record[ATTACHED] = [str(target)]


def new(workflow):
    """A review that starts after another stage writes a fresh review file."""
    recent = workflow.state["stages"][-2:]
    names = {entry[STAGE] for entry in recent}
    return len(recent) == 1 or len(names) == 2
