"""Native opencode tool diagnostics, independent of whether the turn can finish."""


def failure(part):
    """1.x reports unavailable calls through its completed `invalid` sentinel tool."""
    state = part.get("state") or {}
    if state.get("status") == "error":
        message = str(state.get("error") or "Unknown tool error")
        if message.startswith("PermissionDeniedError(") and '"ruleset"' in message:
            return "Permission denied: this tool call is outside the stage access rules."
        return message
    if part.get("tool") == "invalid" and state.get("status") == "completed":
        return str(state.get("output") or "Invalid tool call")
    return ""
