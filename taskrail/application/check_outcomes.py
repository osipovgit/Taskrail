"""Gate outcomes shared by stage routing, repair feedback and retry detection."""

from collections import Counter
from types import MappingProxyType

from taskrail.core import prompt_texts

STATUS_BY_ASSESSMENT = MappingProxyType(dict(passed="PASS", failed="FAIL", unknown="UNVERIFIED"))
BLOCKING = frozenset(("FAIL", "UNVERIFIED"))


def blocks(check):
    """An inconclusive mandatory check needs resolution before review."""
    return check.get("status") in BLOCKING


def summary(syntax, commands):
    """Count actual file validations and observed command starts independently."""
    files = Counter(row["status"] for row in syntax)
    starts = Counter(row.get("started") for row in commands)
    return prompt_texts.text(
        "checks.summary",
        passed=files["PASS"],
        failed=files["FAIL"],
        skipped=files["SKIPPED"],
        selected=len(commands),
        started=starts[True],
        not_started=starts[False],
        uncertain=starts[None],
    )


def latest_summary(state):
    """Only the latest check stage can describe the current checks."""
    for stage in reversed(state.get("stages", [])):
        if stage.get("stage") == "check":
            return stage.get("summary") if stage.get("mode") == "builtin" else None
    return None


def observed_start(outcome):
    """Only an observed exit or executor evidence establishes whether a process ran."""
    if outcome.get("exit_code") is not None:
        return True
    if outcome["status"] in {"DECLINED", "REJECTED"}:
        return False
    return outcome.get("process_started")
