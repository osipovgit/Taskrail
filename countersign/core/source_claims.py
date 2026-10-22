"""Bind model citations to current source and independently observed reads.

A citation names a file and a line range; the server takes the text from the file.
The cited lines must be current and must have reached the model through one read.
"""

import re
from pathlib import Path

from countersign.core.schema import require

LINE_PREFIX = re.compile(r"^(\d+)(?:: ?|\| )(.*)$")
READ_HEADER = re.compile(r"(?:<path>[^\r\n]*</path>\r?\n<type>file</type>\r?\n)?<(content|file)>")
SHOWN_SOURCE = 600


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
    """Every cited position must be in the returned output, with the current text."""
    if record["input"]["filePath"] != claim["path"]:
        return False
    lines = returned_lines(record)
    expected = enumerate(excerpt.split("\n"), claim["line_start"])
    matches = [shown(lines.get(number), line) for number, line in expected]
    return all(matches)


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
    """Remove only the outer read envelope, including a tag adjacent to line one.

    Source text is not XML: numbered lines can themselves contain literal tags.
    The last closing envelope separates the body from any tool footer.
    """
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
