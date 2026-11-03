"""Native opencode tool diagnostics, independent of whether the turn can finish."""


def failure(part):
    """1.x reports unavailable calls through its completed `invalid` sentinel tool."""
    state = part.get("state") or {}
    if state.get("status") == "error":
        return str(state.get("error") or "Unknown tool error")
    if part.get("tool") == "invalid" and state.get("status") == "completed":
        return str(state.get("output") or "Invalid tool call")
    return ""
