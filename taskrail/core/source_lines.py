"""Exact source positions from read envelopes and bounded missing-range feedback."""

import re

from taskrail.core import source_read_windows

LINE_PREFIX = re.compile(r"^(\d+)(?:: ?|\| )(.*)$")
READ_HEADER = re.compile(r"(?:<path>[^\r\n]*</path>\r?\n<type>file</type>\r?\n)?<(content|file)>")
READ_WINDOW = 200
FEEDBACK_WINDOWS = 3


def returned_lines(record):
    """Read tools carry source line numbers; executor snapshots carry exact raw text."""
    output = record["output"]
    rows = output.splitlines()
    if record.get("output_clipped") and not output.endswith("\n"):
        rows = rows[:-1]
    if record.get("tool") == "executor":
        return dict(enumerate(rows, record["input"].get("offset", 1)))
    return numbered_lines(read_body("\n".join(rows)).splitlines())


def read_body(output):
    """Strip only the outer envelope: numbered source lines may contain literal tags."""
    opening = READ_HEADER.match(output)
    if opening is None:
        return output
    body = output[opening.end() :]
    return body.rsplit(f"</{opening[1]}>", 1)[0]


def numbered_lines(rows):
    """Reject duplicate or reordered source positions instead of guessing their meaning."""
    numbered = []
    for row in rows:
        match = LINE_PREFIX.fullmatch(row)
        if match:
            numbered.append((int(match[1]), match[2]))
    numbers = [number for number, _ in numbered]
    if numbers != sorted(set(numbers)):
        return {}
    return dict(numbered)


def shown(output, excerpt):
    """Compare the whole observed line; repeated substrings are not source evidence."""
    if output is None:
        return False
    return " ".join(output.split()) == " ".join(excerpt.split())


def windows(positions):
    """Group adjacent source positions into bounded, explicit read windows."""
    ranges = []
    for number in sorted(positions):
        adjacent = ranges and number == ranges[-1][1] + 1
        if adjacent and number - ranges[-1][0] < READ_WINDOW:
            ranges[-1][1] = number
        else:
            ranges.append([number, number])
    return ranges


def missing_feedback(positions):
    """Name a few actual gaps without asking a model to reread the full citation."""
    ranges = source_read_windows.windows(positions)
    reads = [read_instruction(window) for window in ranges[:FEEDBACK_WINDOWS]]
    remaining = max(0, len(ranges) - FEEDBACK_WINDOWS)
    return (
        "Missing complete current source lines; read only these windows: "
        + "; ".join(reads)
        + f". Further missing windows: {remaining}. Reuse already observed lines. "
        "If a line is truncated, use a supplied readable source view or report the specific "
        "unavailable evidence; repeating the same truncated read cannot reveal its suffix."
    )


def read_instruction(window):
    """A source offset and bounded size, without displaying the source text again."""
    start, end = window
    count = end - start + 1
    return f"offset={start}, limit={count}"
