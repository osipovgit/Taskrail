"""Validate a saved plan or independent review after context exhaustion."""

from taskrail.application import feedback_files
from taskrail.application.attempt_session import validated
from taskrail.core import prompt_texts
from taskrail.infrastructure.context_overflow import STATUS

ELIGIBLE = frozenset(("understanding", "planner", "plan-reviewer", "reviewer"))
STAGE = "stage"
RECOVERY = "plan_recovery"


def recover(workflow, record, outcome):
    """Recover only a verdict accepted by the original stage validator."""
    if record[STAGE] not in ELIGIBLE or outcome["status"] != STATUS:
        return None
    try:
        verdict = validated(workflow, record, outcome)
    except (ValueError, TypeError) as error:
        failure = dict(status="rejected", reason=str(error))
        record[RECOVERY] = dict(failure, stage=record[STAGE])
        outcome[RECOVERY] = record[RECOVERY]
        return None
    if record[STAGE] == "planner" and verdict["status"] != "PLAN_READY":
        return None
    record[RECOVERY] = dict(status="validated", interrupted_status=outcome["status"])
    return verdict


def feedback(outcome, folder):
    """Retry the saved proposal with exact validation failures, not another broad audit."""
    failure = outcome.get(RECOVERY)
    if not failure:
        return ""
    key = "recovery.plan" if failure[STAGE] == "planner" else "recovery.review"
    if failure[STAGE] == "understanding":
        key = "recovery.understanding"
    return "\n{}\n".format(
        prompt_texts.text(
            key,
            reason=feedback_files.validation(folder, failure["reason"]),
        )
    )
