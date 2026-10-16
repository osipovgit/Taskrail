"""Bind model quotations to current source and independently observed reads."""

import re
from pathlib import Path

from countersign.core.schema import require

DEFAULT_READ_LIMIT = 2000


def validate_claim(claim, records):
    """A quotation needs both current bytes and an attributed tool observation."""
    start, end = claim["line_start"], claim["line_end"]
    require(start <= end, "Reversed evidence range")
    lines = Path(claim["path"]).read_text().splitlines()
    require(end <= len(lines), "Evidence range outside source")
    excerpt = "\n".join(lines[start - 1 : end])
    require(claim["quote"] in excerpt, "Quotation differs from source")
    matches = [record for record in records if supports(record, claim)]
    require(bool(matches), "Evidence has no matching observed source read")
    return {
        "claim_id": claim["id"],
        "source_sha256": matches[-1]["source_sha256"],
        "source_event": matches[-1]["source_event"],
        "event_line": matches[-1]["event_line"],
    }


def supports(record, claim):
    """Quoted text must have reached the model, not merely exist on disk."""
    if record["input"]["filePath"] != claim["path"]:
        return False
    start = record["input"].get("offset", 1)
    end = start + record["input"].get("limit", DEFAULT_READ_LIMIT) - 1
    output = re.sub(r"(?m)^\d+: ?|^\d+\| ", "", record["output"])
    covered = start <= claim["line_start"] and claim["line_end"] <= end
    return covered and claim["quote"] in output
