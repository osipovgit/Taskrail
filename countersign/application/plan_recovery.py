"""Validate a persisted planner proposal after context exhaustion, before spending a retry."""

from countersign.application.attempt_session import validated
from countersign.infrastructure.context_overflow import STATUS

RECOVERY = "plan_recovery"


def recover(workflow, record, outcome):
    """Only a fully validated plan may proceed to the existing independent plan review."""
    if record["stage"] != "planner" or outcome["status"] != STATUS:
        return None
    if outcome.get("admission_blocked"):
        return None
    try:
        verdict = validated(workflow, record, outcome)
    except (ValueError, TypeError) as error:
        record[RECOVERY] = dict(status="rejected", reason=str(error))
        outcome[RECOVERY] = record[RECOVERY]
        return None
    if verdict["status"] != "PLAN_READY":
        return None
    record[RECOVERY] = dict(status="validated", interrupted_status=outcome["status"])
    return verdict


def feedback(outcome):
    """Retry the saved proposal with exact validation failures, not another broad audit."""
    failure = outcome.get(RECOVERY)
    if not failure:
        return ""
    return (
        "\nThe saved plan.md failed server validation: {0}\n"
        "Read the current plan file in this session before editing it. Correct these "
        "defects using recorded evidence; read only missing source ranges. Do not repeat "
        "completed discovery. Finish the plan and end with DONE.\n"
    ).format(failure["reason"])
