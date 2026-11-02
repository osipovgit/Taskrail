"""Why model results and requests were sent back, summed across runs for analytics.

Each stage record keeps the kind and first feedback line of its corrections. Paths and
numbers vary between runs, so they are blanked; what remains names the rule a model
broke, and the most frequent rules are the ones worth fixing first.
"""

import re
from collections import Counter

REJECTIONS = "rejections"
TOP_REASONS = 5
VARYING = re.compile(r"/\S+|\d+")


def counted(record):
    """The normalized reasons of one stage record."""
    return Counter(map(reason, record.get(REJECTIONS) or []))


def reason(rejection):
    """What was rejected and why, without the paths and numbers of one run."""
    kind = rejection.get("kind", "result")
    stated = VARYING.sub("…", str(rejection.get("reason", "")))
    return f"{kind}: {stated}"


def top(reasons):
    """The most frequent reasons with their counts."""
    common = reasons.most_common(TOP_REASONS)
    return [dict(reason=name, count=count) for name, count in common]
