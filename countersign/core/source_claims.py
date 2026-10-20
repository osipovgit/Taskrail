"""Bind model quotations to current source and independently observed reads.

A quotation is exact text from the cited lines. Whitespace is not significant, and a
long quotation may be shortened with "..." between exact fragments in source order.
"""

import re
from pathlib import Path

from countersign.core.schema import require

DEFAULT_READ_LIMIT = 2000
ELLIPSIS = re.compile(r"\.\.\.|…")
LINE_PREFIX = re.compile(r"(?m)^\d+: ?|^\d+\| ")
SHOWN_SOURCE = 600


def validate_claim(claim, records):
    """A quotation needs both current bytes and an attributed tool observation."""
    label = "Evidence {id} ({path} lines {line_start}-{line_end})".format(**claim)
    excerpt = cited_lines(claim, label)
    require(quoted(excerpt, claim["quote"]), mismatch(label, excerpt))
    matches = [record for record in records if supports(record, claim)]
    require(
        bool(matches), f"{label}: no matching observed read returned these lines; read them first"
    )
    return {
        "claim_id": claim["id"],
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


def mismatch(label, excerpt):
    """Name the evidence and show what the cited lines actually say."""
    shown = excerpt[:SHOWN_SOURCE]
    clipped = " [clipped]" if len(shown) < len(excerpt) else ""
    return f"Quotation differs from source: {label}. Those lines read{clipped}:\n{shown}"


def supports(record, claim):
    """Quoted text must have reached the model, not merely exist on disk."""
    if record["input"]["filePath"] != claim["path"]:
        return False
    start = record["input"].get("offset", 1)
    end = start + record["input"].get("limit", DEFAULT_READ_LIMIT) - 1
    output = LINE_PREFIX.sub("", record["output"])
    covered = start <= claim["line_start"] and claim["line_end"] <= end
    return covered and quoted(output, claim["quote"])


def quoted(text, quote):
    """Every exact fragment of the quote appears in the text, in order."""
    haystack = " ".join(text.split())
    fragments = [" ".join(part.split()) for part in ELLIPSIS.split(quote)]
    fragments = [fragment for fragment in fragments if fragment]
    position = 0
    for fragment in fragments:
        position = haystack.find(fragment, position)
        if position < 0:
            return False
        position += len(fragment)
    return bool(fragments)
