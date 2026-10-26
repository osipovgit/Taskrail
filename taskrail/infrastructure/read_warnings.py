"""Failures that changed nothing stay visible as warnings, not stage failures.

Permission denials and failed writes remain errors.
"""

import os
import re

from taskrail.infrastructure import opencode_cli

OFFSET_ERROR = re.compile(r"Error: Offset \d+ is out of range for this file \(\d+ lines\)")
INVALID_ARGUMENTS = re.compile(r"The \w+ tool was called with invalid arguments: ")
MISSING_RESOLUTION = "Unsuccessful exploratory read recorded as an observation, not source evidence. Discover existing paths or correct the source line offset; required missing evidence must remain a blocking gap in the final result."
ERROR = "error"
ERRORS = "errors"
READ_ONLY_TOOLS = frozenset(("read", "glob", "grep", "list"))
SESSION_RESOLUTION = "opencode reported an error during the turn and the model continued to a final answer; the answer is still validated."
READ_RESOLUTION = "A read-only tool call failed and changed nothing; its output is an observation, not evidence. The final result is still validated."
INVALID_RESOLUTION = "The tool rejected the call's arguments before running it; nothing executed. The final result is still validated."


def classify_missing_reads(outcome):
    """Keep absence and rejected arguments as observations; required evidence is still checked."""
    for failure in outcome["tool_errors"]:
        resolution = resolution_for(failure)
        if resolution is None or failure[ERROR] not in outcome[ERRORS]:
            continue
        failure["resolution"] = resolution
        outcome["warnings"].append(dict(failure))
        outcome[ERRORS].remove(failure[ERROR])
    return outcome


def recover_session_errors(outcome, session_errors, final_line):
    """An opencode or provider error followed by a final answer was recovered from.

    Errors after the final answer, without one, or denying permission stay errors.
    """
    if final_line is None or not outcome["final_text"].strip():
        return
    for entry in session_errors:
        if entry["event_line"] > final_line or entry[ERROR] not in outcome[ERRORS]:
            continue
        if not opencode_cli.permission_error(entry[ERROR]):
            outcome[ERRORS].remove(entry[ERROR])
            outcome["warnings"].append(dict(entry, resolution=SESSION_RESOLUTION))


def resolution_for(failure):
    """Why a failed call is harmless, or None when it must stay an error."""
    if INVALID_ARGUMENTS.match(failure[ERROR]):
        return INVALID_RESOLUTION
    if is_missing_read(failure):
        return MISSING_RESOLUTION
    if failure.get("tool") not in READ_ONLY_TOOLS:
        return None
    return None if opencode_cli.permission_error(failure[ERROR]) else READ_RESOLUTION


def is_missing_read(failure):
    """Match a missing-file read against the actual tool input, not loose text."""
    source = failure.get("input", {}).get("filePath")
    if failure.get("tool") != "read" or not isinstance(source, str):
        return False
    first_line = failure[ERROR].split("\n", 1)[0]
    missing = first_line == f"Error: File not found: {source}"
    offset = bool(OFFSET_ERROR.fullmatch(first_line))
    return os.path.isabs(source) and (missing or offset)
