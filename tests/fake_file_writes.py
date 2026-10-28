"""Native rejected writes and content-matched recovery for subprocess workflow tests."""

import json
import time


def implement(target, mode, emit):
    """A rejected write changes nothing; recovery reads and matches the current text.

    After a context handoff the fresh session finds the edit done and only finishes.
    """
    if mode == "write-context" and "return 2" in target.read_text():
        return
    error = f"You must read file {target} before overwriting it. Use the Read tool first"
    tool = "write"
    if mode.startswith("write-mismatch"):
        tool = "edit"
        error = (
            "Error: Could not find oldString in the file. It must match exactly, "
            "including whitespace, indentation, and line endings."
        )
    event(emit, target, tool, "error", error)
    if mode in {"write-unresolved", "write-mismatch-unresolved"}:
        return
    current = target.read_text()
    numbered = "\n".join(f"{number}:{line}" for number, line in enumerate(current.splitlines(), 1))
    event(emit, target, "read", "completed", numbered)
    assert current.count("return 1") == 1
    updated = current.replace("return 1", "return 2")
    target.write_text(updated)
    event(emit, target, "edit", "completed", "File edited successfully")
    if mode == "write-scope":
        target.with_name("unrelated.txt").write_text("forbidden change\n")
    if mode == "write-context":
        emit(
            json.dumps(
                dict(type="step_finish", part=dict(id="overflow", tokens=dict(input=100000)))
            ),
            flush=True,
        )
        time.sleep(1)


def event(emit, target, tool, status, output):
    """One completed or failed native operation with a stable session-local identity."""
    state = dict(status=status, input=dict(filePath=str(target)))
    state["error" if status == "error" else "output"] = output
    identity = "source-" + tool + "-" + status
    part = dict(id=identity, callID=identity, tool=tool, state=state)
    emit(json.dumps(dict(type="tool_use", part=part)))
