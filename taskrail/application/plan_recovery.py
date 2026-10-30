"""Validate a persisted planner proposal after context exhaustion, before spending a retry."""

from taskrail.application.attempt_session import validated
from taskrail.core import prompt_texts
from taskrail.infrastructure.context_overflow import STATUS

RECOVERY = "plan_recovery"


def recover(workflow, record, outcome):
    """Only a fully validated plan may proceed to the existing independent plan review."""
    if record["stage"] != "planner" or outcome["status"] != STATUS:
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
    return "\n{}\n".format(prompt_texts.text("recovery.plan", reason=failure["reason"]))
