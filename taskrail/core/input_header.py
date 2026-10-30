"""One lossless typed task transport header, independent of display headings."""

import json
import re

NAME = r"taskrail-task"
HEADER = re.compile(rf"(?ms)^```{NAME}\s*\n(.*?)^```\s*$")
FENCE = re.compile(rf"^```{NAME}\s*$", re.MULTILINE)


def parse(text):
    """Decode exactly one optional metadata object before applying task semantics."""
    headers = HEADER.findall(text)
    if len(headers) > 1:
        raise ValueError("Only one taskrail-task header is supported")
    metadata = json.loads(headers[0]) if headers else {}
    if not isinstance(metadata, dict):
        raise ValueError("Task header and settings must be JSON objects")
    return metadata
