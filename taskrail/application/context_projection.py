"""Role inputs contain approved decisions and exact source ranges, not copied reports."""

from taskrail.application import (
    check_catalog,
    history_file,
    instruction_sources,
    plan_projection,
    source_delivery,
    source_guidance,
    source_packet,
    source_windows,
)
from taskrail.application.check_outcomes import latest_summary
from taskrail.application.dependency_checks import index as dependency_index
from taskrail.application.implementation_context import writer
from taskrail.application.implementation_submission import review_path
from taskrail.application.original_checkout import status_path
from taskrail.application.workspace_paths import public_mapping
from taskrail.core import protected_paths, requirements, task_spec
from taskrail.core.paths import tool_paths

OPERATOR_NOTE = "operator_note"


def task_text(config, run, entries=()):
    """The task as the model reads it: fields once, requirement labels, bounded history."""
    text = task_spec.prompt_text(config["task_spec"], entries)
    if not config.get("reviewed_input"):
        _, marker, historical = config["task_text"].partition(requirements.HISTORY)
        text = f"{text}{marker}{historical}"
    return history_file.prompt_task(text, run)


def request_context(config, execution, state, run):
    """Resolve server-owned roots and inputs once for all role prompts."""
    roots = config["roots"]
    plan = execution[1]
    context = dict(
        stage=execution[0],
        implementation_submission=review_path(run, execution[0], state),
        roots=state["roots"],
        workspace_paths=public_mapping(config),
        task_file=str(run / "00-input/task.md"),
        plan=plan_projection.plan_context(execution, state, roots),
        plan_result=str(run / state["results"]["plan"])
        if state.get("results", {}).get("plan")
        else None,
        imported_draft=instruction_sources.imported_draft(run, execution[0]),
        feedback=feedback_context(execution[3], roots),
        check_summary=latest_summary(state),
        checks=tool_paths(state["checks"], roots),
        diff_file=str(run / "changes.diff") if (run / "changes.diff").exists() else None,
        preimages=preimage_context(state["preimages"], roots, run),
    )
    if execution[0] == "implementer":
        context.update(writer(config, execution, state))
    if context["stage"] in {"planner", "plan-reviewer", "reviewer"}:
        context["diagnostic_changes"] = plan_projection.diagnostic_changes(state, roots)
    context["original_status"] = status_path(run)
    context["source_packet"] = packet_context(config, run, context["stage"], plan)
    context["source_views"] = source_guidance.inputs(config, plan, run)
    if config.get("reviewed_input"):
        context["dependency_checks"] = dependency_index(run, config["task_spec"])
        context["task_file"] = str(run / "00-input/reviewed-task-spec.json")
    context.update(check_catalog.context(config, context["stage"], context["plan"]))
    return {key: entry for key, entry in context.items() if included(key, entry)}


def packet_context(config, run, stage, plan):
    """Explicit entry points and current reads, without protected files."""
    supplied = source_windows.observations(config, plan)
    protected = protected_paths.patterns(config)
    packet = source_packet.prepare(run, stage, config["roots"], supplied, protected)
    return source_delivery.public(packet)


def included(key, entry):
    """Empty optional projections do not consume model context."""
    return key in {"check_catalog", "scheduled_checks"} or entry not in (None, [], {})


def preimage_context(preimages, roots, run):
    """Name original source artifacts only when an edit has captured them."""
    return {
        tool_paths(name, roots): str(run / ref) if ref else "FILE DID NOT EXIST"
        for name, ref in preimages.items()
    }


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
        "strategy",
        "findings_file",
        "lines",
        "interrupted",
        "instruction",
        "outside_changes",
        "input_correction",
    )
    projected = {key: feedback[key] for key in needed if key in feedback}
    projected = tool_paths(projected, roots or {})
    note = feedback.get(OPERATOR_NOTE)
    if note is not None:
        projected[OPERATOR_NOTE] = note
    if feedback.get("previous_feedback"):
        projected["previous_feedback"] = feedback_context(feedback["previous_feedback"], roots)
    return projected
