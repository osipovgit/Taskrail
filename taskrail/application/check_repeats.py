"""Whether a repair left exactly the checks failing that sent the implementer to repair.

Another repair would only repeat it, so the run stops with the failure. A timed-out
check may still pass, and run-specific output (an evidence path, a duration) does not
make two failures different.
"""

import re

FAIL = "FAIL"
TIMED_OUT = "timed out"
VARYING = re.compile(r"evidence \S+|\b\d+(?:\.\d+)?\s?(?:ms|s|sec|seconds)\b")


def repeated(feedback, checks):
    """True when the failures equal those the last repair was asked to fix."""
    earlier = feedback.get("checks") if isinstance(feedback, dict) else None
    if not earlier:
        return False
    now = failures(checks)
    return bool(now) and now == failures(earlier)


def failures(checks):
    """Normalized failing checks, or None when one timed out."""
    found = set()
    for check in checks:
        if check.get("status") != FAIL:
            continue
        detail = str(check.get("detail", ""))
        if TIMED_OUT in detail.lower():
            return None
        found.add((check.get("file"), VARYING.sub("", detail)))
    return frozenset(found)
