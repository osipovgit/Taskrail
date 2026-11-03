"""Native rejected writes and content-matched recovery for subprocess workflow tests."""

import json
import time

EDIT_MISMATCH = "Error: Could not find oldString in the file. It must match exactly, including whitespace, indentation, and line endings."


def plan_mismatches(target, content, emit):
    """One actual read survives repeated no-op edits before the completed plan write."""
    event(emit, target, "read", "completed", target.read_text())
    for number in range(3):
        state = dict(status="error", input=dict(filePath=str(target)), error=EDIT_MISMATCH)
        identity = f"plan-mismatch-{number}"
        part = dict(id=identity, callID=identity, tool="edit", state=state)
        emit(json.dumps(dict(type="tool_use", part=part)))
    target.write_text(content)
    event(emit, target, "write", "completed", "File written successfully")


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
        error = EDIT_MISMATCH
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


def review_abort(target, content, emit):
    """A partial result write is read and replaced before the reviewer finishes."""
    target.write_text("Summary: interrupted\n")
    event(emit, target, "write", "error", "Tool execution aborted")
    event(emit, target, "read", "completed", target.read_text())
    target.write_text(content)
    event(emit, target, "write", "completed", "File written successfully")


def empty_abort(emit):
    """The reported provider event: an aborted edit without a target or arguments."""
    state = dict(status="error", input={}, error="Tool execution aborted")
    part = dict(id="empty-abort", callID="empty-abort", tool="edit", state=state)
    emit(json.dumps(dict(type="tool_use", part=part)))


def identical_edit(target, emit):
    """A redundant native edit changes nothing, followed by a read and final result."""
    arguments = dict(filePath=str(target), oldString="same", newString="same", replaceAll=False)
    state = dict(
        status="error",
        input=arguments,
        error="Error: No changes to apply: oldString and newString are identical.",
    )
    part = dict(id="identical-edit", callID="identical-edit", tool="edit", state=state)
    emit(json.dumps(dict(type="tool_use", part=part)))
    event(emit, target, "read", "completed", target.read_text())


def plan_alias(target, content, emit):
    """A rejected dot-segment edit is repaired through the canonical plan path."""
    target.write_text("Summary: draft\n")
    alias = str(target.parent / "00-input" / ".." / target.name)
    error = f"Error: You must read file {alias} before overwriting it. Use the Read tool first"
    event(emit, alias, "edit", "error", error)
    event(emit, target, "read", "completed", target.read_text())
    target.write_text(content)
    event(emit, target, "edit", "completed", "File edited successfully")
