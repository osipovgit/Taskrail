"""Recognize a provider refusing a turn because the session outgrew the model context.

opencode compacts a session only when the model's context limit is configured; with
an unknown limit the session grows until the provider rejects the next call.
"""

import re

STATUS = "CONTEXT_EXCEEDED"
MARKERS = re.compile(
    r"context[ _]?window[ _]?exceeded|context_length_exceeded|maximum context length"
    + r"|prompt is too long|context ?overflow|input is too long",
    re.IGNORECASE,
)


def exceeded(errors):
    """True when any recorded error reports an exceeded context window."""
    return any(MARKERS.search(str(error)) for error in errors)
