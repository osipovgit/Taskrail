"""Bounded same-session repair for native rejections that did not change a run artifact."""

from taskrail.core import prompt_texts
from taskrail.infrastructure import write_targets, write_warnings


def feedback(outcome, targets):
    """Only exact no-op rejections of approved artifacts request a read and correction."""
    failures = [
        failure for failure in outcome.get("tool_errors", []) if not failure.get("resolution")
    ]
    if not failures or outcome.get("status") != "TOOL_ERROR":
        return None
    if outcome.get("permission") or outcome.get("exit_code", 0):
        return None
    if outcome.get("errors") != [failure.get("error") for failure in failures]:
        return None
    paths = [repair_target(failure, targets) for failure in failures]
    if not all(paths):
        return None
    return prompt_texts.text("feedback.artifact_edit", paths=", ".join(dict.fromkeys(paths)))


def repair_target(failure, targets):
    """A known mismatch or unread-file rejection proves no write; an abort does not."""
    target = write_targets.from_call(failure, targets)
    known = write_targets.unread(failure, target) or write_warnings.edit_mismatch(failure)
    return target if known else None
