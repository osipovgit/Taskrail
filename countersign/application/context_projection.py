"""Role inputs contain approved decisions and exact source ranges, not copied reports."""

from countersign.application import (
    check_catalog,
    history_file,
    instruction_sources,
    session_budget,
    source_delivery,
    source_guidance,
    source_packet,
    source_windows,
)
from countersign.core import requirements, task_spec
from countersign.core.paths import tool_paths

OPERATOR_NOTE = "operator_note"


def task_text(config, run):
    """Project typed input once and retain historical data through its existing bound."""
    original = config["task_text"]
    spec = config.get("task_spec")
    if spec is None:
        return history_file.prompt_task(original, run)
    text = task_spec.prompt_text(spec)
    if spec["fields"] and not config.get("reviewed_input"):
        _, marker, historical = original.partition(requirements.HISTORY)
        text += marker + historical
    return history_file.prompt_task(text, run)


def request_context(config, execution, state, run):
    """Resolve server-owned roots and inputs once for all role prompts."""
    roots = config["roots"]
    plan = execution[1]
    context = dict(
        schema_version=state.get("contract_version"),
        context_limits=session_budget.settings(config),
        requirements=list(map(requirement_metadata, state.get("requirements", []))),
        stage=execution[0],
        roots=state["roots"],
        task_file=str(run / "00-input/task.md"),
        plan=plan_context(tool_paths(plan, roots)),
        imported_draft=instruction_sources.imported_draft(run, execution[0]),
        allowed_files=tool_paths(execution[2], roots) if execution[0] == "implementer" else [],
        feedback=feedback_context(execution[3], roots),
        checks=tool_paths(state["checks"], roots),
        no_changes_needed=bool(plan is not None and not plan["proposed_change_files"]),
        diff_file=str(run / "changes.diff") if (run / "changes.diff").exists() else None,
        preimages=preimage_context(state["preimages"], roots, run),
    )
    context["source_packet"] = source_delivery.public(
        source_packet.prepare(
            run, context["stage"], roots, source_windows.observations(config, plan)
        )
    )
    context["source_views"] = source_guidance.inputs(config, plan, run)
    if config.get("reviewed_input"):
        context["task_file"] = str(run / "00-input/reviewed-task-spec.json")
    context.update(check_catalog.context(config, context["stage"], context["plan"]))
    return {key: entry for key, entry in context.items() if included(entry)}


def included(entry):
    """Empty optional projections do not consume model context."""
    return entry not in (None, [], {})


def preimage_context(preimages, roots, run):
    """Name original source artifacts only when an edit has captured them."""
    return {
        tool_paths(name, roots): str(run / ref) if ref else "FILE DID NOT EXIST"
        for name, ref in preimages.items()
    }


def plan_context(plan):
    """Keep the approved decisions, not another role's coverage and copied facts."""
    if plan is None:
        return None
    return {
        key: plan[key]
        for key in ("decision", "summary", "steps", "proposed_change_files", "check_selections")
        if key in plan and (key != "check_selections" or plan[key])
    }


def requirement_metadata(entry):
    """Text is labelled in the task; context repeats only its stable identity."""
    return {key: entry[key] for key in ("id", "kind")}


def feedback_context(feedback, roots=None):
    """Repair gets concrete defects and check failures, not a repeated coverage ledger."""
    if not isinstance(feedback, dict):
        return feedback
    needed = (
        "summary",
        "findings",
        "evidence",
        "blocking_gaps",
        "checks",
        OPERATOR_NOTE,
        "note_rule",
        "interrupted",
        "instruction",
        "change_limit",
    )
    projected = {key: feedback[key] for key in needed if key in feedback}
    projected = tool_paths(projected, roots or {})
    note = feedback.get(OPERATOR_NOTE)
    if note is not None:
        projected[OPERATOR_NOTE] = note
    if feedback.get("previous_feedback"):
        projected["previous_feedback"] = feedback_context(feedback["previous_feedback"], roots)
    return projected
