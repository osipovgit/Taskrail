"""Recover only known plan-artifact read-before-write rejections."""

from taskrail.core import prompt_texts
from taskrail.infrastructure import write_targets


def read_before_write(outcome, run):
    """Only a rejected edit of this run's plan can request a same-session read."""
    failures = [
        failure for failure in outcome.get("tool_errors", []) if not failure.get("resolution")
    ]
    if not failures or outcome.get("status") != "TOOL_ERROR":
        return None
    if outcome.get("permission") or outcome.get("exit_code", 0):
        return None
    if outcome.get("errors") != [failure.get("error") for failure in failures]:
        return None
    target = str(run / "plan.md")
    if not all(write_targets.unread(failure, target) for failure in failures):
        return None
    return prompt_texts.text("feedback.plan_unread", path=target)
