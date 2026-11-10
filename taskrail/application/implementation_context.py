"""Effective task scope and scheduled local checks for the implementation stage."""

from taskrail.application import check_selection, followup_selection
from taskrail.application.planned_paths import writable_roots
from taskrail.core.paths import tool_paths


def writer(config, execution, state):
    """Keep planned targets, actual write grants and scheduled checks distinct."""
    plan = execution[1] or {}
    roots = config["roots"]
    grants = writable_roots(config, execution[2])
    checks = check_selection.applicable(config, state.get("requirements", []))
    scheduled = [check["spec"] for check in checks]
    return dict(
        planned_files=tool_paths(plan.get("proposed_change_files", []), roots),
        writable_roots=list(map(str, grants)),
        writable_files=[] if grants else tool_paths(execution[2], roots),
        preserved_files=tool_paths(state.get(followup_selection.PRESERVED, []), roots),
        scheduled_checks=[spec.get("recipe_id", spec["id"]) for spec in scheduled],
    )
