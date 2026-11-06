"""Detect provider context exhaustion and unexpected compaction."""

from taskrail.infrastructure.context_overflow import STATUS


def exceeded(telemetry, context_budget=None, completed=False):
    """Provider reporting may arrive after a token threshold has been crossed."""
    if completed:
        context_budget = None
    if context_reason(telemetry, context_budget):
        return STATUS
    return "OK"


def context_reason(telemetry, context_budget):
    """An explicit compaction marker or exhausted headroom ends the session."""
    if telemetry.timeline.compactions:
        return (
            "Unexpected compaction marker observed. Split the task before starting a new session."
        )
    incoming = telemetry.steps.inputs["last"]
    if context_budget is None or incoming is None or incoming < context_budget:
        return ""
    return (
        f"Session reached the reserved context boundary: {incoming} reported input tokens "
        f"including cache, {context_budget} available. Split the task or narrow its inputs; "
        "increase model_context_tokens only when the selected model supports that window."
    )


def explain(outcome, telemetry, context_budget):
    """Keep the actual observed boundary in the failed attempt's diagnostics."""
    reason = context_reason(telemetry, context_budget)
    if reason:
        outcome["errors"].append(reason)
