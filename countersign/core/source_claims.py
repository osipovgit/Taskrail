"""Bind model citations to current source and independently observed reads.

A citation names a file and a line range; the server takes the text from the file.
Every cited line must be current and must have reached the model in full.
"""

import hashlib
from pathlib import Path

from countersign.core import source_lines
from countersign.core.schema import require
from countersign.core.source_lines import returned_lines as returned_lines

SHOWN_SOURCE = 600
MISSING = "missing"


def validate_claim(claim, records):
    """A citation needs current bytes and an attributed tool observation of its lines."""
    label = "Evidence {id} ({path} lines {line_start}-{line_end})".format(**claim)
    excerpt, source_hash = cited_lines(claim, label)
    current = dict(
        source_sha256=source_hash,
        missing=dict(enumerate(excerpt.split("\n"), claim["line_start"])),
    )
    proofs = observed_ranges(claim, records, current)
    require(
        not current[MISSING],
        f"{label}: no matching observed read returned these lines; "
        + source_lines.missing_feedback(current[MISSING]),
    )
    return {
        "claim_id": claim["id"],
        "excerpt": excerpt[:SHOWN_SOURCE],
        "source_sha256": source_hash,
        "source_event": proofs[0]["source_event"],
        "event_line": proofs[0]["event_line"],
        "observations": proofs,
    }


def cited_lines(claim, label):
    """The current text of the cited line range."""
    start, end = claim["line_start"], claim["line_end"]
    require(start <= end, f"{label}: reversed line range")
    source_bytes = Path(claim["path"]).read_bytes()
    lines = source_bytes.decode("utf-8").splitlines()
    require(end <= len(lines), f"{label}: range outside source of {len(lines)} lines")
    excerpt = "\n".join(lines[start - 1 : end])
    return excerpt, hashlib.sha256(source_bytes).hexdigest()


def supports(record, claim, excerpt):
    """Every cited position must be in the returned output, with the current text."""
    if record["input"]["filePath"] != claim["path"]:
        return False
    expected = dict(enumerate(excerpt.split("\n"), claim["line_start"]))
    return len(matching_positions(record, expected)) == len(expected)


def observed_ranges(claim, records, current):
    """Union exact current lines, recording the provenance of every contributing window."""
    proofs = []
    for record in matching_records(claim, records, current["source_sha256"]):
        positions = matching_positions(record, current[MISSING])
        if not positions:
            continue
        proofs.append(
            dict(
                source_event=record["source_event"],
                event_line=record["event_line"],
                line_ranges=source_lines.windows(positions),
            )
        )
        for number in positions:
            current[MISSING].pop(number)
    return proofs


def matching_positions(record, expected):
    """Return only positions whose complete observed line equals current source text."""
    lines = returned_lines(record)
    positioned = expected.items()
    compare = source_lines.shown
    return [number for number, line in positioned if compare(lines.get(number), line)]


def matching_records(claim, records, source_hash):
    """Current observations of exactly this source, newest first."""
    for record in reversed(records):
        same_path = record["input"]["filePath"] == claim["path"]
        if same_path and record["source_sha256"] == source_hash:
            yield record
