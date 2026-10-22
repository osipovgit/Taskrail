"""One lossless typed task transport header, independent of display headings."""

import json
import re

HEADER = re.compile(r"(?ms)^```countersign-task\s*\n(.*?)^```\s*$")


def typed_metadata(text):
    """Return typed metadata only; ordinary Markdown continues through the legacy importer."""
    header = HEADER.search(text)
    if header is None:
        return None
    meta = json.loads(header[1])
    return meta if isinstance(meta, dict) and "task_spec" in meta else None
