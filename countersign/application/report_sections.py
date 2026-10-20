"""Report sections for stage errors and the limits of what was verified."""

import json

BULLET = "- {0}"
CHECK = "- {file}: {status} — {detail}"
WORKTREE = "- {0}: `{worktree}` on branch `{branch}`, created from `{source}` at {base}"
STATUS = "status"


def stage_errors(state):
    """Tool errors with their resolution, or plain stage errors."""
    lines = []
    for stage in state["stages"]:
        tool_errors = stage.get("tool_errors", [])
        if tool_errors or stage.get("errors"):
            lines += ["", "## Stage errors: {0}".format(stage["directory"]), ""]
            lines += error_lines(stage, tool_errors)
    return lines


def error_lines(stage, tool_errors):
    """Tool errors carry more detail than the summary errors they produced."""
    if tool_errors:
        return [line for error in tool_errors for line in tool_error(error)]
    return [BULLET.format(error) for error in stage["errors"]]


def tool_error(error):
    """One denied or failed tool call."""
    arguments = json.dumps(error.get("input"), ensure_ascii=False)
    lines = [
        "- Tool: {0}".format(error.get("tool")),
        f"  Input: `{arguments}`",
        "  Error: {0}".format(error["error"]),
    ]
    if error.get("resolution"):
        lines.append("  Resolution: {0}".format(error["resolution"]))
    if error.get("recovered_by"):
        event = error["recovered_by"]["event_line"]
        lines.append(f"  Recovered by a later full read; event: {event}")
    return lines


def not_verified(state):
    """Unverified criteria and review limitations stay visible in every report."""
    lines = [
        "",
        "## Not verified",
        "",
        "- Only explicitly recorded checks/actions were executed; other runtime criteria remain unverified.",
    ]
    lines += [BULLET.format(text) for text in dict.fromkeys(state["unverified"])]
    for limit in state.get("review_limits", []):
        lines += ["", "### Review limitations: {0}".format(limit["stage"]), ""]
        lines += [BULLET.format(text) for text in limit["unverified"]]
        lines += [f"- Blocking gap: {text}" for text in limit["blocking_gaps"]]
    return lines


def check_lines(state):
    """Recorded checks or why none ran."""
    checks = [CHECK.format(**check) for check in state["checks"]]
    if checks:
        return checks
    if state[STATUS] == "NO_CHANGES_REQUIRED":
        return ["Built-in checks were skipped: no changes are required."]
    if state[STATUS] == "TASKS_READY":
        return ["Built-in checks run in each task's own run."]
    return ["Checks have not run yet."]


def worktree_lines(state):
    """Where an isolated run left its uncommitted changes."""
    worktrees = state.get("worktrees") or {}
    if not worktrees:
        return []
    entries = []
    for alias, entry in worktrees.items():
        entries.append(WORKTREE.format(alias, **entry))
    return [
        "",
        "## Isolated worktrees",
        "",
        "Changes are uncommitted in these worktrees; the source checkouts are unchanged. Review, commit and merge each branch yourself, then remove the worktree with `git worktree remove`.",
        "",
        *entries,
    ]
