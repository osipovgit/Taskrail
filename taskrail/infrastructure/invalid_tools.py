"""An explicitly unexecuted unavailable-tool request cannot invalidate later valid work."""

import re

UNAVAILABLE = re.compile(r"\b(?:unavailable|unknown) tool\b", re.IGNORECASE)
ERROR = "error"


def rejected(failure):
    """Only opencode's invalid sentinel establishes that no source tool executed."""
    missing = bool(UNAVAILABLE.search(failure.get(ERROR, "")))
    return failure.get("tool") == "invalid" and missing


def recover(outcome, final_line):
    """A completed final DONE permits normal artifact validation, never approval by itself."""
    lines = outcome["final_text"].rstrip().splitlines()
    done = bool(lines) and lines[-1].strip() == "DONE"
    if not outcome["completed"] or not done or outcome.get("permission"):
        return outcome
    for failure in outcome["tool_errors"]:
        if rejected(failure) and failure["event_line"] < final_line:
            warning = dict(
                failure, resolution="Unavailable tool never executed; later DONE is validated"
            )
            outcome["warnings"].append(warning)
            if failure[ERROR] in outcome["errors"]:
                outcome["errors"].remove(failure[ERROR])
    return outcome


def correction(outcome):
    """Only isolated unavailable-tool failures allow bounded same-session guidance."""
    errors = outcome.get("errors", [])
    failures = outcome.get("tool_errors", [])
    rejected_errors = [failure[ERROR] for failure in filter(rejected, failures)]
    eligible = outcome["status"] == "TOOL_ERROR"
    eligible = eligible and outcome.get("exit_code", 0) == 0
    eligible = eligible and not outcome.get("permission") and bool(errors)
    return errors if eligible and errors == rejected_errors else []
