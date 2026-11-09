"""The approved plan as the next stage reads it: decisions and tasks, no copied facts."""

from taskrail.core.paths import tool_paths

PLAN_FIELDS = ("decision", "summary", "proposed_change_files", "unverified")
# The plan line is for problem messages; the action repeats the title and results.
HIDDEN_STEP_FIELDS = frozenset(("line", "action"))
EMPTY = (None, "", [], {})


def plan_context(plan, requirements=()):
    """Keep the approved decisions, not another role's coverage and copied facts."""
    if plan is None:
        return None
    context = {key: plan[key] for key in PLAN_FIELDS if key in plan}
    if plan.get("blocking_gaps"):
        context["blocking_gaps"] = plan["blocking_gaps"]
    named = labels(requirements)
    if plan.get("check_selections"):
        context["check_selections"] = [
            labelled_criteria(selection, named) for selection in plan["check_selections"]
        ]
    steps = plan.get("steps", [])
    context["steps"] = [step_context(step, named) for step in steps]
    return context


def labelled_criteria(entry, named):
    """Show check bindings with the same labels as the task, without changing stored IDs."""
    criteria = [named.get(name, name) for name in entry["criteria"]]
    return dict(entry, criteria=criteria)


def step_context(step, named):
    """A task as its implementer reads it: requirement labels, no plan line or empty fields."""
    shown = {key: entry for key, entry in step.items() if key not in HIDDEN_STEP_FIELDS}
    criteria = step.get("criteria", [])
    shown["criteria"] = [named.get(name, name) for name in criteria]
    scopes = step.get("scopes", [])
    shown["scopes"] = [labelled_scope(scope, named) for scope in scopes]
    return {key: entry for key, entry in shown.items() if entry not in EMPTY}


def labelled_scope(scope, named):
    """A scoped part of a requirement, named by its label."""
    return dict(scope, id=named.get(scope["id"], scope["id"]))


def labels(requirements):
    """Requirement ID -> the R<n> label the task shows."""
    return {entry["id"]: f"R{number}" for number, entry in enumerate(requirements, 1)}


def diagnostic_changes(state, roots):
    """Changed source from read-only roles must remain visible to independent review."""
    readers = {
        stage["directory"]
        for stage in state.get("stages", [])
        if stage.get("role") in {"planner", "reviewer"}
    }
    effects = state.get("command_effects", [])
    receipts = [entry for entry in effects if entry["stage"] in readers]
    return tool_paths(receipts, roots)
