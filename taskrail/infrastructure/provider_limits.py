"""Recognize a provider refusing every call until its quota or billing limit is raised.

Such an error is not a broken transport: a new session fails the same way at once, so
the stage stops instead of retrying, and the operator continues the run after the limit
resets. A short rate limit is not matched and keeps the usual bounded retry.
"""

import re

MARKERS = re.compile(
    r"quota|usage limit|billing|payment required|insufficient[ _]?(credit|balance|funds)",
    re.IGNORECASE,
)


def reached(errors):
    """True when any recorded error reports an exhausted quota or billing limit."""
    return any(MARKERS.search(str(error)) for error in errors)
