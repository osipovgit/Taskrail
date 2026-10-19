"""Tool failures that executed nothing stay visible as warnings, not transport failures."""

import os
import re

OFFSET_ERROR = re.compile(r"Error: Offset \d+ is out of range for this file \(\d+ lines\)")
INVALID_ARGUMENTS = re.compile(r"The \w+ tool was called with invalid arguments: ")
MISSING_RESOLUTION = "Unsuccessful exploratory read recorded as an observation, not source evidence. Discover existing paths or correct the source line offset; required missing evidence must remain a blocking gap in the final result."
ERROR = "error"
INVALID_RESOLUTION = "The tool rejected the call's arguments before running it; nothing executed. The final result is still validated."


def classify_missing_reads(outcome):
    """Keep absence and rejected arguments as observations; required evidence is still checked."""
    for failure in outcome["tool_errors"]:
        resolution = resolution_for(failure)
        if resolution is None or failure[ERROR] not in outcome["errors"]:
            continue
        failure["resolution"] = resolution
        outcome["warnings"].append(dict(failure))
        outcome["errors"].remove(failure[ERROR])
    return outcome


def resolution_for(failure):
    """Why a failed call is harmless, or None when it must stay an error."""
    if INVALID_ARGUMENTS.match(failure[ERROR]):
        return INVALID_RESOLUTION
    if is_missing_read(failure):
        return MISSING_RESOLUTION
    return None


def is_missing_read(failure):
    """Match a missing-file read against the actual tool input, not loose text."""
    source = failure.get("input", {}).get("filePath")
    if failure.get("tool") != "read" or not isinstance(source, str):
        return False
    first_line = failure[ERROR].split("\n", 1)[0]
    missing = first_line == f"Error: File not found: {source}"
    offset = bool(OFFSET_ERROR.fullmatch(first_line))
    return os.path.isabs(source) and (missing or offset)
