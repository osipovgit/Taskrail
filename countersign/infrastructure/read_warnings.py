"""Keep missing exploratory reads visible without declaring transport failure."""

import os
import re


def is_missing_read(failure):
    """Match a missing-file read against the actual tool input, not loose text."""
    source = failure.get("input", {}).get("filePath")
    if failure.get("tool") != "read" or not isinstance(source, str):
        return False
    first_line = failure["error"].split("\n", 1)[0]
    missing = first_line == f"Error: File not found: {source}"
    offset = re.fullmatch(
        r"Error: Offset \d+ is out of range for this file \(\d+ lines\)", first_line
    )
    return os.path.isabs(source) and (missing or bool(offset))


def classify_missing_reads(outcome):
    """Keep absence as an observation; required evidence still needs validation."""
    for failure in outcome["tool_errors"]:
        if not is_missing_read(failure) or failure["error"] not in outcome["errors"]:
            continue
        failure["resolution"] = (
            "Unsuccessful exploratory read recorded as an observation, not source evidence. "
            "Discover existing paths or correct the source line offset; "
            "required missing evidence must remain a blocking gap in the final result."
        )
        outcome["warnings"].append(dict(failure))
        outcome["errors"].remove(failure["error"])
    return outcome
