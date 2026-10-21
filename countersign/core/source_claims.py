"""Bind model citations to current source and independently observed reads.

A citation names a file and a line range; the server takes the text from the file.
The cited lines must be current and must have reached the model through one read.
"""

import re
from pathlib import Path

from countersign.core.schema import require

DEFAULT_READ_LIMIT = 2000
LINE_PREFIX = re.compile(r"(?m)^\d+: ?|^\d+\| ")
SHOWN_SOURCE = 600
# Read tools cut long lines, so only the start of each cited line is compared.
COMPARED_CHARACTERS = 200


def validate_claim(claim, records):
    """A citation needs current bytes and an attributed tool observation of its lines."""
    label = "Evidence {id} ({path} lines {line_start}-{line_end})".format(**claim)
    excerpt = cited_lines(claim, label)
    matches = [record for record in records if supports(record, claim, excerpt)]
    require(
        bool(matches), f"{label}: no matching observed read returned these lines; read them first"
    )
    return {
        "claim_id": claim["id"],
        "excerpt": excerpt[:SHOWN_SOURCE],
        "source_sha256": matches[-1]["source_sha256"],
        "source_event": matches[-1]["source_event"],
        "event_line": matches[-1]["event_line"],
    }


def cited_lines(claim, label):
    """The current text of the cited line range."""
    start, end = claim["line_start"], claim["line_end"]
    require(start <= end, f"{label}: reversed line range")
    lines = Path(claim["path"]).read_text().splitlines()
    require(end <= len(lines), f"{label}: range outside source of {len(lines)} lines")
    return "\n".join(lines[start - 1 : end])


def supports(record, claim, excerpt):
    """The read covered the cited range and actually returned its lines."""
    if record["input"]["filePath"] != claim["path"]:
        return False
    start = record["input"].get("offset", 1)
    end = start + record["input"].get("limit", DEFAULT_READ_LIMIT) - 1
    covered = start <= claim["line_start"] and claim["line_end"] <= end
    return covered and shown(LINE_PREFIX.sub("", record["output"]), excerpt)


def shown(output, excerpt):
    """Each cited line appears in the output, in order; whitespace is not significant."""
    haystack = " ".join(output.split())
    position = 0
    for line in excerpt.splitlines():
        fragment = " ".join(line.split())[:COMPARED_CHARACTERS]
        position = haystack.find(fragment, position)
        if position < 0:
            return False
        position += len(fragment)
    return True
