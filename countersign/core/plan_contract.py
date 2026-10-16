"""Check structured plan ownership before any file is authorized for editing."""

from countersign.core.coverage import unique
from countersign.core.schema import require
from countersign.core.work_packages import validate as validate_packages

IDENTIFIER = "id"
STEPS = "steps"


def validate_plan_steps(payload, requirements):
    """Require exact edit scope and an owning step for every planned criterion."""
    steps = payload[STEPS]
    unique(steps, "step ID")
    validate_sequence(steps, {entry[IDENTIFIER] for entry in requirements})
    validate_packages(steps)
    paths = {path for step in steps for path in step["files"]}
    require(
        paths == set(payload["proposed_change_files"]), "Step files differ from authorized scope"
    )
    owned = {criterion for step in steps for criterion in step["criteria"]}
    for entry in payload["coverage"]:
        if entry["outcome"] == "planned":
            require(entry[IDENTIFIER] in owned, "Planned requirement has no owning step")
    if payload["status"] == "BLOCKED":
        require(not paths, "Blocked plan cannot authorize edits")
    elif not paths:
        require(not steps, "No-change plan cannot contain implementation steps")


def validate_sequence(steps, criteria):
    """Dependencies must precede consumers; every step owns actual work."""
    previous = set()
    for step in steps:
        require(bool(step["files"]), "Step needs concrete files")
        require(bool(step["criteria"]), "Step needs criteria")
        require(set(step["criteria"]) <= criteria, "Invalid step criteria")
        require(set(step["depends_on"]) <= previous, "Unknown or forward dependency")
        require(bool(step["checks"]), "Step needs verification instructions")
        previous.add(step[IDENTIFIER])


def validate_completion(payload, plan, changed):
    """Compare implementation claims with approved steps and observed changes."""
    approved = {step[IDENTIFIER] for step in plan[STEPS]}
    require(set(payload["completed_steps"]) <= approved, "Unknown completed step")
    require(
        set(payload["changed_files"]) == set(changed), "Changed files disagree with source scan"
    )
    if payload["status"] == "IMPLEMENTED":
        require(set(payload["completed_steps"]) == approved, "Incomplete implementation")
